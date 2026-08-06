"""
用户行为事件 MQ 消费者（§2.10 / §9.5 Step 51）

订阅 user.behavior.exchange，消费 Java 微服务（item/cart/trade）和 Python ai-outfit
发送的用户行为事件，调 EmbedClient 编码商品文本后写入 Qdrant user_behavior collection。

纯文本向量模式：拼接商品文本属性（name+category+color+season+styleTags）后编码为向量
（encode_text），与商品入库向量模式一致，确保行为向量与商品向量在同一向量空间。

消息格式（与 Java 侧 UserBehaviorMessage 对齐）：
  Exchange: user.behavior.exchange
  Routing Key: user.behavior.{type}（如 user.behavior.ITEM_VIEW）
  Payload: {
    userId, itemId, shopId, name, category(中文), color, season, price,
    type, timestamp, imageUrl, styleTags[],
    itemGender, userGender,  # 性别对齐检查用
    extra  # OUTFIT_ACCEPT 时含 outfitTaskId/outfitIndex
  }

失败处理：
  - 单条消息处理失败重试 3 次（间隔 2s/4s/8s）
  - 超过重试次数后 nack（requeue=False），消息进入死信队列 user.behavior.dlq
"""
import asyncio
import json
import logging
import threading
import time
from typing import Any

from shared.mq_client.consumer import MqConsumer
from shared.qdrant_client.client import QdrantClientWrapper
from shared.qdrant_client.user_behavior import UserBehaviorIndexer
from shared.model_client.embed_client import EmbedClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# MQ 常量（与 Java 侧 MqConstants 对齐）
USER_BEHAVIOR_EXCHANGE = "user.behavior.exchange"
USER_BEHAVIOR_QUEUE = "user.behavior.event.queue"
USER_BEHAVIOR_ROUTING_KEY = "user.behavior.*"  # 通配符匹配所有行为类型
USER_BEHAVIOR_DLQ = "user.behavior.dlq"
USER_BEHAVIOR_DLQ_KEY = "user.behavior.dlq"

# 单条消息重试参数
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]


def _build_behavior_item_text(payload: dict) -> str:
    """从用户行为消息 payload 拼接商品文本用于向量编码

    纯文本向量模式：拼接 name + category + color + season + styleTags，
    与商品入库（index_items.py）和商品同步（item_sync_consumer.py）的文本拼接逻辑一致，
    确保行为向量与商品向量在同一向量空间。
    """
    parts = []

    name = payload.get("name")
    if name:
        parts.append(str(name).strip())

    category = payload.get("category")
    if category:
        parts.append(str(category).strip())

    color = payload.get("color")
    if color:
        parts.append(str(color).strip())

    season = payload.get("season")
    if season:
        parts.append(str(season).strip())

    raw_style = payload.get("styleTags")
    if raw_style:
        try:
            if isinstance(raw_style, str):
                parsed = json.loads(raw_style)
                if isinstance(parsed, list):
                    style_tags = [str(s) for s in parsed if s]
                else:
                    style_tags = [str(parsed)]
            elif isinstance(raw_style, list):
                style_tags = [str(s) for s in raw_style if s]
            else:
                style_tags = []
            if style_tags:
                parts.extend(style_tags)
        except (ValueError, TypeError):
            pass

    return " ".join(parts) if parts else ""


class UserBehaviorMqConsumer:
    """用户行为事件 MQ 消费者（独立线程运行）

    消费 4 类行为事件：ITEM_VIEW / CART_ADD / ORDER_PLACE / OUTFIT_ACCEPT
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread: threading.Thread | None = None
        self._consumer: MqConsumer | None = None
        self._running = False
        # Qdrant 索引器（同步客户端，线程内创建避免跨线程共享）
        self._indexer: UserBehaviorIndexer | None = None
        # Embed 客户端（用于商品文本向量化）
        self._embed_client: EmbedClient | None = None

    def start(self):
        """在独立线程中启动 MQ 消费者"""
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="user-behavior-mq-consumer"
        )
        self._thread.start()
        logger.info("用户行为事件 MQ 消费者线程已启动")

    def stop(self):
        """停止 MQ 消费者"""
        self._running = False
        if self._consumer:
            try:
                self._consumer.stop()
            except Exception as e:
                logger.warning("关闭用户行为 MQ 消费者连接异常: %s", e)
        if self._thread:
            self._thread.join(timeout=5)
        # 关闭 embed 客户端
        if self._embed_client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._embed_client.close(), self._loop
                )
                future.result(timeout=3)
            except Exception as e:
                logger.warning("关闭 EmbedClient 异常: %s", e)
        logger.info("用户行为事件 MQ 消费者已停止")

    def _run(self):
        """消费者线程主逻辑"""
        try:
            # 初始化 Qdrant 客户端（同步，线程内独占）
            qdrant_wrapper = QdrantClientWrapper(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                api_key=settings.qdrant_api_key,
                prefix=settings.qdrant_prefix,
                proxy_url=settings.proxy_url,
            )
            self._indexer = UserBehaviorIndexer(qdrant_wrapper)
            try:
                self._indexer.ensure_collection()
            except Exception as e:
                logger.warning("ensure_collection 失败（不退出，DLQ 兜底）: %s", e)

            # 初始化 Embed 客户端（用于商品文本向量化）
            self._embed_client = EmbedClient(
                api_url=settings.embed_api_url,
                api_key=settings.embed_api_key,
                timeout=20,
                vector_dim=1024,
            )

            # 创建消费者
            self._consumer = MqConsumer(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                username=settings.rabbitmq_username,
                password=settings.rabbitmq_password,
                virtual_host=settings.rabbitmq_vhost,
            )
            self._consumer.connect()

            # 声明 Exchange + Queues + Bindings
            self._consumer.declare_exchange(USER_BEHAVIOR_EXCHANGE, exchange_type="topic")
            # 主队列：声明 DLX 参数，失败消息自动路由到 DLQ
            self._consumer.declare_queue(
                USER_BEHAVIOR_QUEUE,
                arguments={
                    "x-dead-letter-exchange": USER_BEHAVIOR_EXCHANGE,
                    "x-dead-letter-routing-key": USER_BEHAVIOR_DLQ_KEY,
                },
            )
            # 死信队列：普通队列，无 DLX 参数
            self._consumer.declare_queue(USER_BEHAVIOR_DLQ)
            # 通配符绑定：匹配所有 user.behavior.* 的消息
            self._consumer.bind(USER_BEHAVIOR_EXCHANGE, USER_BEHAVIOR_QUEUE, USER_BEHAVIOR_ROUTING_KEY)
            self._consumer.bind(USER_BEHAVIOR_EXCHANGE, USER_BEHAVIOR_DLQ, USER_BEHAVIOR_DLQ_KEY)

            # 启动消费（auto_ack=False，处理成功后手动 ack）
            self._consumer.start_consuming(
                queue=USER_BEHAVIOR_QUEUE,
                callback=self._on_message,
                auto_ack=False,
                prefetch_count=5,  # 预取 5 条并行处理
            )
        except Exception as e:
            logger.error("用户行为 MQ 消费者启动失败: %s", e, exc_info=True)

    def _on_message(self, channel, method, properties, body: bytes):
        """消息处理回调（同步，在 pika 线程中执行）

        流程：
          1. 解析消息体
          2. 调 EmbedClient 编码商品文本（拼接 name+category+color+season+styleTags）
          3. 调 UserBehaviorIndexer 写入 Qdrant
        失败重试 3 次，超过后 nack 进死信队列。
        """
        try:
            payload: dict[str, Any] = json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.error("用户行为消息 JSON 解析失败，nack 进死信队列: %s, body=%s", e, body[:200])
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        routing_key = method.routing_key
        logger.info(
            "收到用户行为消息: routingKey=%s, userId=%s, itemId=%s, type=%s",
            routing_key, payload.get("userId"), payload.get("itemId"), payload.get("type"),
        )

        # 重试逻辑
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._process_message(payload)
                channel.basic_ack(delivery_tag=method.delivery_tag)
                return
            except Exception as e:
                logger.warning(
                    "处理用户行为消息失败(第%d次): userId=%s, itemId=%s, error=%s",
                    attempt, payload.get("userId"), payload.get("itemId"), e,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF[attempt - 1])

        # 重试耗尽，nack 进死信队列
        logger.error(
            "用户行为消息处理失败（重试 %d 次耗尽），nack 进死信队列: userId=%s, itemId=%s",
            MAX_RETRIES, payload.get("userId"), payload.get("itemId"),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _process_message(self, payload: dict):
        """处理单条用户行为消息

        1. 编码商品文本（拼接 name+category+color+season+styleTags）
        2. 写入 Qdrant user_behavior collection
        """
        user_id = int(payload.get("userId", 0))
        item_id = int(payload.get("itemId", 0))
        behavior_type = payload.get("type", "ITEM_VIEW")
        timestamp = payload.get("timestamp", "")
        category = payload.get("category")
        color = payload.get("color")
        price = payload.get("price")
        shop_id = payload.get("shopId")
        style_tags = payload.get("styleTags", [])
        item_gender = payload.get("itemGender")
        user_gender = payload.get("userGender")
        # OUTFIT_ACCEPT 事件的附加信息（outfitTaskId/outfitIndex，审计追溯用）
        extra = payload.get("extra")

        if not user_id or not item_id:
            logger.warning("用户行为消息缺少 userId/itemId，跳过: %s", payload)
            return

        # OUTFIT_ACCEPT 审计日志（extra 不写入 Qdrant payload，仅日志追溯搭配任务来源）
        if behavior_type == "OUTFIT_ACCEPT" and extra:
            logger.info(
                "[OUTFIT_ACCEPT] 用户采纳搭配: userId=%s, itemId=%s, extra=%s",
                user_id, item_id, extra,
            )

        # 1. 编码商品文本（纯文本向量模式，与商品入库向量模式一致）
        vector = None
        if self._embed_client:
            item_text = _build_behavior_item_text(payload)
            if item_text:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._embed_client.encode_text(item_text),
                        self._loop,
                    )
                    vector = future.result(timeout=30)
                except Exception as e:
                    logger.warning(
                        "编码商品文本失败（继续写入，vector=None）: itemId=%s, error=%s, text=%s",
                        item_id, e, item_text[:80],
                    )
            else:
                logger.debug("商品文本为空，跳过编码: itemId=%s", item_id)

        # 2. 写入 Qdrant
        if self._indexer:
            self._indexer.index_behavior(
                user_id=user_id,
                item_id=item_id,
                behavior_type=behavior_type,
                timestamp=timestamp,
                category=category,
                color=color,
                price=float(price) if price else None,
                shop_id=int(shop_id) if shop_id else None,
                style_tags=style_tags,
                item_gender=item_gender,
                user_gender=user_gender,
                vector=vector,
            )
        else:
            logger.warning("UserBehaviorIndexer 未初始化，跳过写入: userId=%s, itemId=%s", user_id, item_id)
