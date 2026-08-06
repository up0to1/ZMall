"""
ai-outfit FastAPI 入口（AI 随心搭服务）

U1 统一架构后承载两种模式：
  - 商品驱动模式：POST /api/v1/outfit/generate + /photo + /result/{taskId}
  - 风格驱动模式：POST /api/v1/outfit/agent/recommend + /feedback + /result/{taskId}

启动时：注册 Nacos → 启动 MQ 商品同步消费者
关闭时：停止 MQ 消费者 → 注销 Nacos
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.core.security import AuthMiddleware
from app.api.outfit_product import router as outfit_product_router
from app.api.outfit_agent import router as outfit_agent_router
from app.api.ws import router as ws_router
from app.mq.item_sync_consumer import ItemSyncMqConsumer
from app.mq.item_sync_dlq_consumer import ItemSyncDlqConsumer
from app.mq.user_behavior_consumer import UserBehaviorMqConsumer
from shared.nacos_register import NacosRegistrar

# 日志输出到文件 + 控制台（测试可观测性：测试后可查看 logs/ai-outfit.log 定位问题）
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            "logs/ai-outfit.log",
            maxBytes=1024 * 1024 * 50,  # 50MB
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

_registrar = NacosRegistrar(
    server_addr=settings.nacos_server,
    service_name="ai-outfit",
    port=settings.port,
    username=settings.nacos_username,
    password=settings.nacos_password,
)

# 商品库同步 MQ 消费者（在 lifespan 中启动/停止）
_item_sync_consumer: ItemSyncMqConsumer | None = None
# 商品库同步 DLQ 消费者（消费死信队列做最后一次重试，失败 ack 丢弃由对账兜底）
_item_sync_dlq_consumer: ItemSyncDlqConsumer | None = None
# 用户行为事件 MQ 消费者（个性化推荐画像，消费 ITEM_VIEW/CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT）
_user_behavior_consumer: UserBehaviorMqConsumer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时注册 Nacos + 启动 MQ 消费者，关闭时反向释放"""
    global _item_sync_consumer, _item_sync_dlq_consumer
    logger.info("ai-outfit 启动中...")
    await _registrar.register()

    # 主线程预先确保 Qdrant Collection 存在（单线程，避免 consumer 线程并发
    # 通过代理建 TLS 连接导致握手失败）。失败不阻塞启动，upsert 失败会进 DLQ。
    try:
        from shared.qdrant_client.client import QdrantClientWrapper
        from shared.qdrant_client.user_preference import UserPreferenceUpdater
        from shared.qdrant_client.user_episode import UserEpisodeStore
        from app.core.config import settings as _s
        _wrapper = QdrantClientWrapper(
            host=_s.qdrant_host, port=_s.qdrant_port,
            api_key=_s.qdrant_api_key, prefix=_s.qdrant_prefix,
            proxy_url=_s.proxy_url,
        )
        _wrapper.ensure_collections()
        # 补建 user_preference / user_episode collection 及索引（Qdrant Cloud 过滤必需）
        UserPreferenceUpdater(_wrapper).ensure_collection()
        UserEpisodeStore(_wrapper).ensure_collection()
        logger.info("Qdrant Collection 检查完成（主线程）")
    except Exception as e:
        logger.warning("Qdrant ensure_collections 失败（不阻塞启动，DLQ 兜底）: %s", e)

    # 启动商品库同步 MQ 消费者（独立线程，订阅 item.sync.upsert/delete 队列）
    try:
        _item_sync_consumer = ItemSyncMqConsumer(asyncio.get_running_loop())
        _item_sync_consumer.start()
        logger.info("商品库同步 MQ 消费者已启动")
    except Exception as e:
        logger.error("商品库同步 MQ 消费者启动失败（业务接口仍可服务）: %s", e, exc_info=True)
        _item_sync_consumer = None

    # 启动 DLQ 消费者（独立线程，消费 item.sync.dlq 做最后重试）
    try:
        _item_sync_dlq_consumer = ItemSyncDlqConsumer(asyncio.get_running_loop())
        _item_sync_dlq_consumer.start()
        logger.info("商品库同步 DLQ 消费者已启动")
    except Exception as e:
        logger.error("商品库同步 DLQ 消费者启动失败（主消费者仍可服务）: %s", e, exc_info=True)
        _item_sync_dlq_consumer = None

    # 启动用户行为事件 MQ 消费者（个性化推荐画像）
    # 消费 item/cart/trade + ai-outfit accept 发送的 ITEM_VIEW/CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT 事件
    # → CLIP 编码商品图 → Qdrant zmall_user_behavior collection，供 ProfileService 聚合画像
    try:
        _user_behavior_consumer = UserBehaviorMqConsumer(asyncio.get_running_loop())
        _user_behavior_consumer.start()
        logger.info("用户行为事件 MQ 消费者已启动")
    except Exception as e:
        logger.error("用户行为事件 MQ 消费者启动失败（不影响主流程）: %s", e, exc_info=True)
        _user_behavior_consumer = None

    # v6 工具拓展：注册外部工具（天气/库存/趋势/价格平衡）
    try:
        from app.tools.tool_registry_setup import register_outfit_tools
        register_outfit_tools()
    except Exception as e:
        logger.warning("外部工具注册失败（不影响主流程）: %s", e)

    logger.info("ai-outfit 启动完成，端口=%s", settings.port)
    yield

    # ===== 关闭 =====
    logger.info("ai-outfit 关闭中...")
    if _user_behavior_consumer is not None:
        try:
            _user_behavior_consumer.stop()
        except Exception as e:
            logger.warning("用户行为事件 MQ 消费者停止异常: %s", e)
        _user_behavior_consumer = None
    if _item_sync_dlq_consumer is not None:
        try:
            _item_sync_dlq_consumer.stop()
        except Exception as e:
            logger.warning("商品库同步 DLQ 消费者停止异常: %s", e)
        _item_sync_dlq_consumer = None
    if _item_sync_consumer is not None:
        try:
            _item_sync_consumer.stop()
        except Exception as e:
            logger.warning("商品库同步 MQ 消费者停止异常: %s", e)
        _item_sync_consumer = None
    # 释放 deps.py 中的单例客户端（VtonClient/GenClient/LlmClient/EmbedClient/
    # JavaClient/NacosDiscovery/Redis/MqProducer 持有的连接）
    try:
        from app.api.deps import close_all_clients
        await close_all_clients()
    except Exception as e:
        logger.warning("关闭单例客户端异常: %s", e)
    await _registrar.deregister()
    logger.info("ai-outfit 已关闭")


app = FastAPI(
    title="ZMall AI Outfit",
    description="AI 随心搭统一架构（商品驱动 + 风格驱动，LangGraph Agent 编排）",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)
# 商品驱动模式路由（/api/v1/outfit/*）+ 风格驱动模式路由（/api/v1/outfit/agent/*）
app.include_router(outfit_product_router)
app.include_router(outfit_agent_router)
app.include_router(ws_router)


@app.get("/health", summary="健康检查")
async def health():
    return {"status": "UP", "service": "ai-outfit"}


@app.get("/metrics", summary="Prometheus 监控指标")
async def metrics():
    """Prometheus 拉取监控指标（后端架构方案 §7.5）"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
