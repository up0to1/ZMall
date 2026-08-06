"""
ai-models FastAPI 入口（AI 模特图服务）

启动时：注册 Nacos → 初始化 Redis/连接池 → 启动 MQ 消费者
关闭时：停止 MQ 消费者 → 注销 Nacos → 释放连接池
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.config import settings
from app.core.security import AuthMiddleware
from app.api.v1 import model, ws, search
from app.models.schemas import HealthResponse
from shared.nacos_register import NacosRegistrar
from app.mq.model_consumer import ModelMqConsumer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Nacos 注册器
_registrar = NacosRegistrar(
    server_addr=settings.nacos_server,
    service_name="ai-models",
    port=settings.port,
    username=settings.nacos_username,
    password=settings.nacos_password,
)

# MQ 消费者（在 lifespan 中启动/停止）
_model_mq_consumer: ModelMqConsumer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时注册 Nacos + 启动 MQ 消费者，关闭时反向释放"""
    global _model_mq_consumer
    # ===== 启动 =====
    logger.info("ai-models 启动中...")

    # 注册到 Nacos（失败不阻塞启动，Gateway 轮询重试）
    await _registrar.register()

    # 启动 AI 模特图 MQ 消费者（独立线程，订阅 ai.model.generate 队列）
    try:
        _model_mq_consumer = ModelMqConsumer(asyncio.get_running_loop())
        _model_mq_consumer.start()
        logger.info("AI 模特图 MQ 消费者已启动")
    except Exception as e:
        logger.error("MQ 消费者启动失败（业务接口仍可服务）: %s", e, exc_info=True)
        _model_mq_consumer = None

    logger.info("ai-models 启动完成，端口=%s", settings.port)
    yield

    # ===== 关闭 =====
    logger.info("ai-models 关闭中...")
    if _model_mq_consumer is not None:
        try:
            _model_mq_consumer.stop()
        except Exception as e:
            logger.warning("MQ 消费者停止异常: %s", e)
        _model_mq_consumer = None
    # 释放 deps.py 中的单例客户端（VtonClient/GenClient/Redis/Qdrant/Java/Nacos 持有的连接）
    try:
        from app.api.deps import close_all_clients
        await close_all_clients()
    except Exception as e:
        logger.warning("关闭单例客户端异常: %s", e)
    # 补全 _llm.py 模块级 httpx.AsyncClient 资源释放
    # close_all_clients 只释放 deps.py 中的单例，_llm.py 的 _text_client/_vision_client 不在其中
    try:
        from app.subgraphs._llm import close_llm_clients
        await close_llm_clients()
    except Exception as e:
        logger.warning("关闭 LLM httpx client 异常: %s", e)
    await _registrar.deregister()
    logger.info("ai-models 已关闭")


app = FastAPI(
    title="ZMall AI Models",
    description="AI 模特图生成 + WebSocket 推送 + 向量搜索",
    version="1.0.0",
    lifespan=lifespan,
)

# 中间件
app.add_middleware(AuthMiddleware)

# 路由（AI 模特图/WS/搜索）
app.include_router(model.router)
app.include_router(ws.router)
app.include_router(search.router)


@app.get("/health", response_model=HealthResponse, summary="健康检查")
async def health():
    """Nacos 心跳 + K8s 探针"""
    return HealthResponse(status="UP", service="ai-models")


@app.get("/metrics", summary="Prometheus 监控指标")
async def metrics():
    """Prometheus 拉取监控指标（后端架构方案 §7.5）"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
