"""
依赖注入（单例客户端，asyncio.Lock 保护延迟初始化）

U1 统一架构后：ai-outfit 承载商品驱动 + 风格驱动两种模式，
照片会话服务（PhotoSessionService）也迁移到 ai-outfit（app/services/photo_session.py），
Redis Key ai:photo:session:{userId} 与原 ai-models 保持一致，前端无感知。
"""
import asyncio
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from shared.nacos_discovery import NacosDiscovery
from shared.java_client import JavaClient
from shared.qdrant_client.client import QdrantClientWrapper
from shared.qdrant_client.searcher import QdrantSearcher
from shared.qdrant_client.user_preference import (
    UserPreferenceReader,
    UserPreferenceUpdater,
)
from shared.qdrant_client.user_episode import UserEpisodeStore
from shared.qdrant_client.user_behavior import UserBehaviorIndexer
from shared.model_client.vton_client import VtonClient
from shared.model_client.gen_client import GenClient
from shared.model_client.refiner_client import RefinerClient
from shared.model_client.embed_client import EmbedClient
from shared.model_client.llm_client import LlmClient
from shared.oss_client.client import OssClientWrapper
from shared.oss_client.uploader import OssUploader
from shared.mq_client import MqProducer

logger = logging.getLogger(__name__)

# ===== Redis 连接（单例）=====
_redis_pool: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        async with _redis_lock:
            if _redis_pool is None:
                _redis_pool = aioredis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    db=settings.redis_db,
                    password=settings.redis_password or None,
                    decode_responses=True,
                )
    return _redis_pool


# ===== Nacos 服务发现（单例）=====
_nacos_discovery: NacosDiscovery | None = None
_nacos_lock = asyncio.Lock()


async def get_nacos_discovery() -> NacosDiscovery:
    global _nacos_discovery
    if _nacos_discovery is None:
        async with _nacos_lock:
            if _nacos_discovery is None:
                _nacos_discovery = NacosDiscovery(
                    server_addr=settings.nacos_server,
                    username=settings.nacos_username,
                    password=settings.nacos_password,
                )
    return _nacos_discovery


# ===== Java 服务客户端（单例）=====
_java_client: JavaClient | None = None
_java_client_lock = asyncio.Lock()


async def get_java_client() -> JavaClient:
    global _java_client
    if _java_client is None:
        async with _java_client_lock:
            if _java_client is None:
                discovery = await get_nacos_discovery()
                _java_client = JavaClient(discovery)
    return _java_client


# ===== Qdrant 检索器（单例）=====
_qdrant_wrapper: QdrantClientWrapper | None = None
_qdrant_searcher: QdrantSearcher | None = None
_qdrant_lock = asyncio.Lock()


async def get_qdrant_searcher() -> QdrantSearcher:
    global _qdrant_wrapper, _qdrant_searcher
    if _qdrant_searcher is None:
        async with _qdrant_lock:
            if _qdrant_searcher is None:
                _qdrant_wrapper = QdrantClientWrapper(
                    host=settings.qdrant_host,
                    port=settings.qdrant_port,
                    api_key=settings.qdrant_api_key,
                    prefix=settings.qdrant_prefix,
                    proxy_url=settings.proxy_url,
                )
                _qdrant_searcher = QdrantSearcher(_qdrant_wrapper)
    return _qdrant_searcher


# 用户偏好读写器（复用同一个 QdrantClientWrapper）
_user_pref_reader: UserPreferenceReader | None = None
_user_pref_updater: UserPreferenceUpdater | None = None


async def get_user_preference_reader() -> UserPreferenceReader:
    """获取用户偏好读取器（首轮推荐时调用，注入 state）

    避免在 `async with _qdrant_lock` 内部调用 `get_qdrant_searcher()`，
    后者又尝试获取同一把锁，asyncio.Lock 不可重入 → 永久挂起。
    策略：先不持锁调 `get_qdrant_searcher()` 确保 wrapper 就绪，再持锁保护赋值。
    """
    global _user_pref_reader
    if _user_pref_reader is None:
        # 先确保 wrapper 已初始化（不持锁，避免与 get_qdrant_searcher 死锁）
        if _qdrant_wrapper is None:
            await get_qdrant_searcher()
        async with _qdrant_lock:
            if _user_pref_reader is None:
                _user_pref_reader = UserPreferenceReader(_qdrant_wrapper)
    return _user_pref_reader


async def get_user_preference_updater() -> UserPreferenceUpdater:
    """获取用户偏好写入器（feedback 接口异步调用）

    同 get_user_preference_reader，避免死锁。
    """
    global _user_pref_updater
    if _user_pref_updater is None:
        # 先确保 wrapper 已初始化（不持锁）
        if _qdrant_wrapper is None:
            await get_qdrant_searcher()
        async with _qdrant_lock:
            if _user_pref_updater is None:
                # 注入 Redis 用于分布式锁保证 upsert 原子性
                redis = await get_redis()
                _user_pref_updater = UserPreferenceUpdater(_qdrant_wrapper, redis=redis)
                # ensure_collection 是同步阻塞 Qdrant HTTP 调用，
                # 必须放到线程池避免阻塞事件循环（与 get_mq_producer 的 connect 一致）
                await asyncio.to_thread(_user_pref_updater.ensure_collection)
    return _user_pref_updater


# 用户搭配事件存储器（O3 优化：EpisodicMemory，跨会话记忆用户采纳的搭配）
_user_episode_store: UserEpisodeStore | None = None
_user_behavior_indexer: UserBehaviorIndexer | None = None


async def get_user_episode_store() -> UserEpisodeStore:
    """获取用户搭配事件存储器（accept 时写入，首轮推荐时读取）

    复用 QdrantClientWrapper 单例，避免死锁策略同 get_user_preference_updater。
    """
    global _user_episode_store
    if _user_episode_store is None:
        # 先确保 wrapper 已初始化（不持锁）
        if _qdrant_wrapper is None:
            await get_qdrant_searcher()
        async with _qdrant_lock:
            if _user_episode_store is None:
                _user_episode_store = UserEpisodeStore(_qdrant_wrapper)
                await asyncio.to_thread(_user_episode_store.ensure_collection)
    return _user_episode_store


async def get_user_behavior_indexer() -> UserBehaviorIndexer:
    """获取行为记忆纠错器，复用 Qdrant 单例。"""
    global _user_behavior_indexer
    if _user_behavior_indexer is None:
        if _qdrant_wrapper is None:
            await get_qdrant_searcher()
        async with _qdrant_lock:
            if _user_behavior_indexer is None:
                _user_behavior_indexer = UserBehaviorIndexer(_qdrant_wrapper)
                await asyncio.to_thread(_user_behavior_indexer.ensure_collection)
    return _user_behavior_indexer


# ===== 模型客户端（单例）=====
# VtonClient/GenClient/RefinerClient 均切换为千问实现
# - 共用 qwen_api_url + llm_api_key（同一阿里百炼账号）
# - 内部通过 OssUploader 把 bytes 转 URL（千问 API 不接受 Base64）
_vton_client: VtonClient | None = None
_vton_lock = asyncio.Lock()


async def get_vton_client() -> VtonClient:
    """获取 VtonClient 单例（千问 aitryon-plus）

    复用 qwen_api_url + llm_api_key + OssUploader。
    OssUploader 单例独立加锁，调用 get_oss_uploader() 不会与本锁死锁。
    """
    global _vton_client
    if _vton_client is None:
        async with _vton_lock:
            if _vton_client is None:
                oss_uploader = await get_oss_uploader()
                _vton_client = VtonClient(
                    api_url=settings.qwen_api_url,
                    api_key=settings.llm_api_key,
                    model=settings.qwen_vton_model,
                    oss_uploader=oss_uploader,
                )
    return _vton_client


# ===== VTON 输入图预处理与结果一致性审核（best-effort 单例）=====
_vton_quality_service: Any | None = None
_vton_quality_lock = asyncio.Lock()


async def get_vton_quality_service() -> Any:
    """获取商品单品图裁剪 / VTON 结果审核服务。"""
    global _vton_quality_service
    if _vton_quality_service is None:
        async with _vton_quality_lock:
            if _vton_quality_service is None:
                # services 包当前会 eager-import AgentService；延迟导入避免与 deps 循环依赖。
                from app.services.vton_quality_service import VtonQualityService

                _vton_quality_service = VtonQualityService(
                    api_url=settings.llm_api_url,
                    api_key=settings.llm_api_key,
                    vision_model=settings.llm_vision_model,
                    proxy_url=settings.proxy_url,
                )
    return _vton_quality_service


_embed_client: EmbedClient | None = None
_embed_lock = asyncio.Lock()


async def get_embed_client() -> EmbedClient:
    global _embed_client
    if _embed_client is None:
        async with _embed_lock:
            if _embed_client is None:
                _embed_client = EmbedClient(
                    api_url=settings.embed_api_url,
                    api_key=settings.embed_api_key,
                    proxy_url=settings.proxy_url,
                )
    return _embed_client


# ===== 图像生成客户端（千问 wan2.7-image：随心搭文生图兜底 / 后处理图生图）=====
_gen_client: GenClient | None = None
_gen_lock = asyncio.Lock()


async def get_gen_client() -> GenClient:
    """获取 GenClient 单例（千问 wan2.7-image）

    用途：
    1. 随心搭场景 A 兜底文生图（系统模特图池为空时生成模特白底图）
    2. 反馈轮 / 后处理图生图（保留接口兼容，随心搭主流程暂不调用）

    复用 qwen_api_url + llm_api_key + OssUploader。
    """
    global _gen_client
    if _gen_client is None:
        async with _gen_lock:
            if _gen_client is None:
                oss_uploader = await get_oss_uploader()
                _gen_client = GenClient(
                    api_url=settings.qwen_api_url,
                    api_key=settings.llm_api_key,
                    model=settings.qwen_wan_model,
                    oss_uploader=oss_uploader,
                )
    return _gen_client


# ===== VTON 精修客户端（千问 aitryon-refiner：用户反馈不喜欢时二次精修）=====
_refiner_client: RefinerClient | None = None
_refiner_lock = asyncio.Lock()


async def get_refiner_client() -> RefinerClient:
    """获取 RefinerClient 单例（千问 aitryon-refiner）

    用途：VTON 生成后，用户对整体效果不满意但喜欢那套衣服单品时触发精修，
    用 person_image + coarse_image + 服饰图生成还原度更高的精修图。

    复用 qwen_api_url + llm_api_key + OssUploader。
    """
    global _refiner_client
    if _refiner_client is None:
        async with _refiner_lock:
            if _refiner_client is None:
                oss_uploader = await get_oss_uploader()
                _refiner_client = RefinerClient(
                    api_url=settings.qwen_api_url,
                    api_key=settings.llm_api_key,
                    model=settings.qwen_refiner_model,
                    oss_uploader=oss_uploader,
                )
    return _refiner_client


# ===== LLM 客户端（多轮反馈解析用，单例）=====
_llm_client: LlmClient | None = None
_llm_lock = asyncio.Lock()


async def get_llm_client() -> LlmClient:
    global _llm_client
    if _llm_client is None:
        async with _llm_lock:
            if _llm_client is None:
                # 双模型路由：text_model 用于纯文本任务，vision_model 用于图像理解
                # 场景 A（无自拍照）用 text_model 做搭配决策
                # 场景 B（有自拍照）用 vision_model 分析用户照片 + 搭配决策
                _llm_client = LlmClient(
                    api_url=settings.llm_api_url,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,                      # 向后兼容
                    text_model=settings.llm_text_model,            # 场景 A：qwen-flash
                    vision_model=settings.llm_vision_model,        # 场景 B：qwen3.5-flash
                    proxy_url=settings.proxy_url,
                )
    return _llm_client


# ===== OSS 上传器（单例）=====
_oss_wrapper: OssClientWrapper | None = None
_oss_uploader: OssUploader | None = None
_oss_lock = asyncio.Lock()


async def get_oss_uploader() -> OssUploader:
    global _oss_wrapper, _oss_uploader
    if _oss_uploader is None:
        async with _oss_lock:
            if _oss_uploader is None:
                _oss_wrapper = OssClientWrapper(
                    endpoint=settings.oss_endpoint,
                    access_key_id=settings.oss_access_key_id,
                    access_key_secret=settings.oss_access_key_secret,
                    bucket_name=settings.oss_bucket_name,
                )
                _oss_uploader = OssUploader(
                    _oss_wrapper,
                    local_root=settings.nginx_uploads_root,
                    local_url_prefix=settings.nginx_uploads_url_prefix,
                )
    return _oss_uploader


# ===== MQ 生产者（单例，带自动重连，详见 shared/mq_client/producer.py）=====
_mq_producer: MqProducer | None = None
_mq_producer_lock = asyncio.Lock()


async def get_mq_producer() -> MqProducer:
    """获取 MQ 生产者单例

    MqProducer.publish 是同步阻塞调用（pika BlockingConnection），
    调用方应通过 await asyncio.to_thread(producer.publish, ...) 放到线程池。
    """
    global _mq_producer
    if _mq_producer is None:
        async with _mq_producer_lock:
            if _mq_producer is None:
                producer = MqProducer(
                    host=settings.rabbitmq_host,
                    port=settings.rabbitmq_port,
                    username=settings.rabbitmq_username,
                    password=settings.rabbitmq_password,
                    virtual_host=settings.rabbitmq_vhost,
                )
                # connect 是同步阻塞，放到线程池
                await asyncio.to_thread(producer.connect)
                _mq_producer = producer
    return _mq_producer


# ===== 资源释放（应用关闭时调用）=====
async def close_all_clients():
    """关闭所有单例客户端持有的连接资源（在 FastAPI lifespan 关闭阶段调用）

    释放：
    - VtonClient / GenClient / RefinerClient / LlmClient / EmbedClient 持有的 httpx.AsyncClient
    - JavaClient / NacosDiscovery 持有的连接
    - Redis 连接池
    - MqProducer 的 pika BlockingConnection（同步 close，放线程池）
    未释放：
    - OssUploader（OSS SDK 内部管理连接，进程退出时自动清理）
    - QdrantClientWrapper（无 close 方法，Qdrant HTTP 由 requests 管理，进程退出自动清理）
    - UserPreferenceReader/Updater/EpisodeStore（复用 QdrantClientWrapper，无需单独释放）
    """
    global _vton_client, _gen_client, _refiner_client, _llm_client, _embed_client
    global _vton_quality_service
    global _java_client, _nacos_discovery, _redis_pool, _mq_producer

    # 异步客户端（httpx.AsyncClient 等）
    for client_attr in ("_vton_client", "_gen_client", "_refiner_client",
                         "_llm_client", "_embed_client", "_java_client", "_nacos_discovery"):
        client = globals().get(client_attr)
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning("关闭 %s 异常: %s", client_attr, e)
            globals()[client_attr] = None

    if _vton_quality_service is not None:
        try:
            await _vton_quality_service.close()
        except Exception as e:
            logger.warning("关闭 VTON 质量服务异常: %s", e)
        _vton_quality_service = None

    # Redis 连接池
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
        except Exception as e:
            logger.warning("关闭 Redis 异常: %s", e)
        _redis_pool = None

    # MqProducer（同步 close，放线程池避免阻塞事件循环）
    if _mq_producer is not None:
        try:
            await asyncio.to_thread(_mq_producer.close)
        except Exception as e:
            logger.warning("关闭 MqProducer 异常: %s", e)
        _mq_producer = None
