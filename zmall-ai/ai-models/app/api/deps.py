"""
依赖注入

所有客户端单例均使用 asyncio.Lock 保护延迟初始化，避免并发请求下创建多个实例
（连接池泄漏）。同步客户端（Qdrant）的初始化通过 asyncio.to_thread 放到线程池执行，
避免阻塞事件循环。
"""
import asyncio
import logging

import redis.asyncio as aioredis

from app.core.config import settings
from shared.nacos_discovery import NacosDiscovery
from shared.java_client import JavaClient
from shared.qdrant_client.client import QdrantClientWrapper
from shared.qdrant_client.searcher import QdrantSearcher
from shared.model_client.embed_client import EmbedClient
from shared.model_client.vton_client import VtonClient
from shared.model_client.gen_client import GenClient
from shared.model_client.refiner_client import RefinerClient
from shared.oss_client.client import OssClientWrapper
from shared.oss_client.uploader import OssUploader

logger = logging.getLogger(__name__)

# ===== Redis 连接（单例）=====
_redis_pool: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        async with _redis_lock:
            # 二次检查，避免锁等待期间已被其他协程初始化
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


# ===== Embed 客户端（单例，用于 /api/v1/search/similar 向量检索）=====
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


# ===== VTON 客户端（多 Agent 决策链式 VTON 用，单例）=====
# 千问 aitryon-plus，复用 qwen_api_url + llm_api_key + OssUploader
_vton_client: VtonClient | None = None
_vton_lock = asyncio.Lock()


async def get_vton_client() -> VtonClient:
    """获取 VtonClient 单例（多 Agent 工作流的 vton_execute_node 用，千问 aitryon-plus）

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


# ===== 图生图客户端（多 Agent 决策后处理节点用，单例）=====
# 千问 wan2.7-image
_gen_client: GenClient | None = None
_gen_lock = asyncio.Lock()


async def get_gen_client() -> GenClient:
    """获取 GenClient 单例（多 Agent 工作流的 post_process_node 用，千问 wan2.7-image）

    用途：
    1. 后处理图生图（导演评估不通过时，对 VTON 输出图做精准细节修改）
    2. 人物姿势微调（基于 VTON 基准图生成 N 个姿势变体）
    3. 文生图兜底（系统模特图池为空时生成模特白底图）

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


# ===== VTON 精修客户端（千问 aitryon-refiner：保留接口，ai-models 主流程不调用）=====
# ai-models 的多 Agent 决策流程暂不使用 refiner（仅 ai-outfit 反馈轮使用），
# 但保留单例便于后续扩展（如多换装模式的独立后处理精修）。
_refiner_client: RefinerClient | None = None
_refiner_lock = asyncio.Lock()


async def get_refiner_client() -> RefinerClient:
    """获取 RefinerClient 单例（千问 aitryon-refiner）

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


# ===== OSS 上传器（多 Agent 决策结果图上传用，单例）=====
_oss_wrapper: OssClientWrapper | None = None
_oss_uploader: OssUploader | None = None
_oss_lock = asyncio.Lock()


async def get_oss_uploader() -> OssUploader:
    """获取 OssUploader 单例（多 Agent 工作流的 oss_upload_node 用）"""
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
                _oss_uploader = OssUploader(_oss_wrapper)
    return _oss_uploader


# ===== 资源释放（应用关闭时调用）=====
async def close_all_clients():
    """关闭所有单例客户端持有的连接资源（在 FastAPI lifespan 关闭阶段调用）

    释放：
    - VtonClient / GenClient / RefinerClient 持有的 httpx.AsyncClient
    - Redis 连接池
    - QdrantClientWrapper（持有 gRPC 连接，需显式 close）
    - JavaClient / NacosDiscovery（如有 close 方法）
    未释放：
    - OssUploader（OSS SDK 内部管理连接，进程退出时自动清理）
    - EmbedClient（无状态 httpx 调用，每次新建 client）
    """
    global _vton_client, _gen_client, _refiner_client, _redis_pool
    global _qdrant_wrapper, _qdrant_searcher, _java_client, _nacos_discovery, _embed_client
    for client_attr in ("_vton_client", "_gen_client", "_refiner_client"):
        client = globals().get(client_attr)
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning("关闭 %s 异常: %s", client_attr, e)
            globals()[client_attr] = None
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
        except Exception as e:
            logger.warning("关闭 Redis 异常: %s", e)
        _redis_pool = None
    # 补全 Qdrant / Java / Nacos / Embed 连接释放
    # QdrantClientWrapper 持有 qdrant_client.QdrantClient（gRPC 连接），需显式 close
    if _qdrant_wrapper is not None:
        try:
            close_fn = getattr(_qdrant_wrapper, "close", None)
            if close_fn is not None:
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.warning("关闭 Qdrant 异常: %s", e)
        _qdrant_wrapper = None
        _qdrant_searcher = None
    # JavaClient / NacosDiscovery / EmbedClient：检查是否有 close/aclose 方法
    for attr in ("_java_client", "_nacos_discovery", "_embed_client"):
        client = globals().get(attr)
        if client is not None:
            try:
                close_fn = getattr(client, "close", None) or getattr(client, "aclose", None)
                if close_fn is not None:
                    result = close_fn()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as e:
                logger.warning("关闭 %s 异常: %s", attr, e)
            globals()[attr] = None
