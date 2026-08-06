"""
商品库同步 MQ 消费者（核心功能设计 §3.8）

订阅 item.sync.exchange，消费 Java item-service 发来的商品上下架/更新消息，
调用 Indexer 更新 Qdrant 向量库，保证推荐不命中下架商品，且 color/season 字段实时生效。

pika 的 BlockingConnection 是同步的，在独立线程中运行，
通过 asyncio.run_coroutine_threadsafe 调用 async 业务代码（EmbedClient.encode_text）。

纯文本向量模式：拼接商品文本属性（name+category+color+season+style_tags）后编码为向量
（encode_text），商品文本属性已足够支撑语义检索。

消息格式（Java 侧 ItemSyncMessage 发送，camelCase 命名两端一致）：
  Exchange: item.sync.exchange
  Routing Key: item.upsert / item.delete
  Payload: {
    itemId, shopId, name(商品名称), category(中文), color, season,
    price, isActive, imageUrl, styleTags[],
    stock,            # 库存，节点2 filter stock>0
    fieldsChanged[],  # 本次变更字段列表，文本字段变更时才重新 encode
    targetGender      # 性别过滤扩展：male/female/unisex
  }

失败处理：
- 单条消息处理失败重试 3 次（间隔 2s/4s/8s）
- 超过重试次数后 nack（requeue=False），消息进入死信队列 item.sync.dlq 人工处理
"""
import asyncio
import json
import logging
import threading
import time
from typing import Any

from shared.mq_client.consumer import MqConsumer
from shared.qdrant_client.category_mapping import to_en, CN_TO_EN
from shared.qdrant_client.indexer import QdrantIndexer
from shared.qdrant_client.client import QdrantClientWrapper
from shared.model_client.embed_client import EmbedClient
from app.core.config import settings

logger = logging.getLogger(__name__)

# MQ 常量（与 Java 侧 MqConstants 对应）
ITEM_SYNC_EXCHANGE = "item.sync.exchange"
ITEM_SYNC_UPSERT_QUEUE = "item.sync.upsert.queue"
ITEM_SYNC_UPSERT_KEY = "item.upsert"
ITEM_SYNC_DELETE_QUEUE = "item.sync.delete.queue"
ITEM_SYNC_DELETE_KEY = "item.delete"

# 死信队列（处理失败的消息进入此处人工排查）
ITEM_SYNC_DLQ = "item.sync.dlq"
# DLQ 路由 key（upsert 队列的 x-dead-letter-routing-key 指向此值）
# main queue nack(requeue=False) 后，消息会被自动路由到 DLX(=item.sync.exchange) + 此 routing key
ITEM_SYNC_DLQ_KEY = "item.dlq"

# 单条消息重试参数
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

# 纯文本向量模式下，影响检索文本的字段（任一变更需重新 encode）
# 与 Java 侧 ItemServiceImpl.VECTOR_AFFECTING_FIELDS 对齐（image 保留兼容但实际不触发图片编码）
VECTOR_AFFECTING_FIELDS = {"name", "category", "color", "season", "style_tags", "image"}


def _build_item_text(payload: dict) -> str:
    """从 MQ payload 拼接商品文本用于向量编码

    纯文本向量模式：拼接 name + category + color + season + style_tags，
    用 text-embedding-v4 编码为向量。

    与 scripts/index_items.py 的 build_item_text 逻辑保持一致。
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

    if not parts:
        return f"商品{payload.get('itemId', '')}"
    return " ".join(parts)


class ItemSyncMqConsumer:
    """商品库同步 MQ 消费者（独立线程运行）

    同时订阅 item.upsert 和 item.delete 两个 routing key。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread: threading.Thread | None = None
        self._consumer: MqConsumer | None = None
        self._running = False
        # Qdrant 索引器（同步客户端，线程内创建避免跨线程共享）
        self._indexer: QdrantIndexer | None = None
        # Embed 客户端（用于商品文本向量化，线程内创建）
        self._embed_client: EmbedClient | None = None

    def start(self):
        """在独立线程中启动 MQ 消费者"""
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="item-sync-mq-consumer"
        )
        self._thread.start()
        logger.info("商品库同步 MQ 消费者线程已启动")

    def stop(self):
        """停止 MQ 消费者"""
        self._running = False
        if self._consumer:
            try:
                self._consumer.stop()
            except Exception as e:
                logger.warning("关闭商品库同步 MQ 消费者连接异常: %s", e)
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
        logger.info("商品库同步 MQ 消费者已停止")

    def _run(self):
        """消费者线程主逻辑"""
        try:
            # 初始化 Qdrant 索引器（同步客户端，线程内独占）
            qdrant_wrapper = QdrantClientWrapper(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                api_key=settings.qdrant_api_key,
                prefix=settings.qdrant_prefix,
                proxy_url=settings.proxy_url,
            )
            # 启动时确保 collection 存在，否则首条 upsert 消息会
            # 因 "collection not found" 失败 → 进 DLQ → DLQ 也失败 → 商品永远不入 Qdrant
            # 主线程 lifespan 已预先调用过 ensure_collections，这里失败不退出线程，
            # upsert 失败会进 DLQ 重试。
            try:
                qdrant_wrapper.ensure_collections()
            except Exception as e:
                logger.warning("ensure_collections 失败（不退出，DLQ 兜底）: %s", e)
            self._indexer = QdrantIndexer(qdrant_wrapper)

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
            # 统一用 UPSERT 队列绑定 upsert + delete 两个 routing_key，
            # 在 _on_message 中按 routing_key 分发到对应处理逻辑。
            #
            # UPSERT 队列加 x-dead-letter-exchange 参数，nack(requeue=False)
            # 后消息自动路由到 DLX(=本 exchange) + DLQ_KEY → 进 item.sync.dlq 队列
            # （由独立的 ItemSyncDlqConsumer 消费做重试 / 人工排查）
            self._consumer.declare_exchange(ITEM_SYNC_EXCHANGE, exchange_type="topic")
            # 主队列：声明 DLX 参数，失败消息自动路由到 item.sync.exchange + "item.dlq"
            self._consumer.declare_queue(
                ITEM_SYNC_UPSERT_QUEUE,
                arguments={
                    "x-dead-letter-exchange": ITEM_SYNC_EXCHANGE,
                    "x-dead-letter-routing-key": ITEM_SYNC_DLQ_KEY,
                },
            )
            # 死信队列：普通队列，无 DLX 参数
            self._consumer.declare_queue(ITEM_SYNC_DLQ)
            # 单队列绑定两个 routing_key，由 _on_message 内分发
            self._consumer.bind(ITEM_SYNC_EXCHANGE, ITEM_SYNC_UPSERT_QUEUE, ITEM_SYNC_UPSERT_KEY)
            self._consumer.bind(ITEM_SYNC_EXCHANGE, ITEM_SYNC_UPSERT_QUEUE, ITEM_SYNC_DELETE_KEY)
            # DLQ 绑定到 exchange 的 item.dlq routing key
            # 主队列 nack(requeue=False) → DLX → DLQ_KEY → DLQ
            self._consumer.bind(ITEM_SYNC_EXCHANGE, ITEM_SYNC_DLQ, ITEM_SYNC_DLQ_KEY)

            # 启动消费（auto_ack=False，处理成功后手动 ack）
            self._consumer.start_consuming(
                queue=ITEM_SYNC_UPSERT_QUEUE,
                callback=self._on_message,
                auto_ack=False,
            )
        except Exception as e:
            logger.error("商品库同步 MQ 消费者启动失败: %s", e, exc_info=True)

    def _on_message(self, channel, method, properties, body: bytes):
        """消息处理回调（同步，在 pika 线程中执行）

        根据 routing_key 分发到 upsert/delete 处理逻辑。
        失败重试 3 次，超过后 nack 进死信队列。
        """
        routing_key = method.routing_key
        try:
            payload: dict[str, Any] = json.loads(body.decode("utf-8"))
        except Exception as e:
            # 毒丸消息 nack 进死信队列保留排查
            logger.error("商品同步消息 JSON 解析失败，nack 进死信队列: %s, body=%s", e, body[:200])
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        logger.info("收到商品同步消息: routingKey=%s, itemId=%s",
                     routing_key, payload.get("itemId"))

        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                if routing_key == ITEM_SYNC_UPSERT_KEY:
                    self._handle_upsert(payload)
                elif routing_key == ITEM_SYNC_DELETE_KEY:
                    self._handle_delete(payload)
                else:
                    logger.warning("未知 routingKey=%s，直接 ack 丢弃", routing_key)
                # 处理成功 → ack
                channel.basic_ack(delivery_tag=method.delivery_tag)
                logger.info("商品同步消息处理成功: routingKey=%s, itemId=%s",
                             routing_key, payload.get("itemId"))
                return
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    logger.warning("商品同步消息处理失败（第 %d 次），%ds 后重试: %s",
                                    attempt + 1, wait, e)
                    time.sleep(wait)

        # 重试耗尽 → nack（requeue=False），消息进入死信队列
        logger.error("商品同步消息重试 %d 次仍失败，nack 进死信队列: itemId=%s, error=%s",
                      MAX_RETRIES, payload.get("itemId"), last_exc, exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _handle_upsert(self, payload: dict):
        """处理商品 upsert 消息（上下架/更新）

        流程（纯文本向量模式）：
        0. 穿搭类目过滤：非穿搭类目直接跳过（不写 Qdrant）
        1. fields_changed 优化：仅文本字段变更时才调 encode_text（省 API 调用）
        2. 品类中文→英文转码
        3. 调 Indexer.upsert_item 写入 Qdrant（含 color/season/stock）
        4. 若 isActive=false，则调 set_item_inactive 软删除
        """
        item_id = payload.get("itemId")
        if not item_id:
            raise ValueError("消息缺少 itemId 字段")

        # 0. 穿搭类目过滤：Java 侧已过滤，这里二次校验（防 MQ 历史消息/并发竞态）
        category_cn = payload.get("category")
        if not category_cn:
            raise ValueError(f"商品 {item_id} 缺少 category 字段")
        if category_cn not in CN_TO_EN:
            logger.info("非穿搭类目，跳过 Qdrant 同步: itemId=%s, category=%s", item_id, category_cn)
            return

        # 1. fields_changed 优化：判断是否需要重新 encode 文本向量
        # 文本字段（name/category/color/season/style_tags）变更时才调 encode API
        fields_changed = payload.get("fieldsChanged") or []
        need_reencode = self._should_reencode(fields_changed)

        vector = None
        if need_reencode:
            # 拼接商品文本（name + category + color + season + style_tags）
            item_text = _build_item_text(payload)
            if not item_text:
                raise ValueError(f"商品 {item_id} 文本拼接为空，无法生成向量")

            if self._embed_client is None:
                raise RuntimeError("EmbedClient 未初始化")
            future = asyncio.run_coroutine_threadsafe(
                self._embed_client.encode_text(item_text), self._loop
            )
            vector = future.result(timeout=30)
            if vector is None or len(vector) != 1024:
                raise ValueError(f"商品 {item_id} 向量生成失败或维度不符 (text={item_text[:80]})")
            logger.info("商品文本变更，已重新 encode: itemId=%s, fieldsChanged=%s, text=%s",
                         item_id, fields_changed, item_text[:80])
        else:
            logger.info("商品文本未变更，跳过 encode 仅更新 payload: itemId=%s, fieldsChanged=%s",
                         item_id, fields_changed)

        # 2. 品类中文→英文
        category_en = to_en(category_cn)

        # 3. 写入 Qdrant
        is_active = payload.get("isActive", True)
        if self._indexer is None:
            raise RuntimeError("Indexer 未初始化")

        if is_active:
            # stock 优化：从 MQ 消息取 stock（默认 0）
            stock = int(payload.get("stock") or 0)
            # 性别过滤扩展：从 MQ 消息取 targetGender（male/female/unisex）
            raw_gender = payload.get("targetGender")
            target_gender = raw_gender if raw_gender in ("male", "female", "unisex") else None

            if vector is not None:
                # 文本变更：完整 upsert（向量 + payload）
                self._indexer.upsert_item(
                    item_id=int(item_id),
                    vector=vector,
                    shop_id=int(payload.get("shopId", 0)),
                    category=category_en,
                    style_tags=payload.get("styleTags", []),
                    price=float(payload.get("price", 0)),
                    color=payload.get("color"),
                    season=payload.get("season"),
                    stock=stock,
                    is_active=True,
                    target_gender=target_gender,
                )
            else:
                # 文本未变更：仅更新 payload（set_payload），保留原向量
                self._indexer.update_payload(
                    item_id=int(item_id),
                    shop_id=int(payload.get("shopId", 0)),
                    category=category_en,
                    style_tags=payload.get("styleTags", []),
                    price=float(payload.get("price", 0)),
                    color=payload.get("color"),
                    season=payload.get("season"),
                    stock=stock,
                    is_active=True,
                    target_gender=target_gender,
                )
            logger.info("商品已 upsert 到 Qdrant: itemId=%s, category=%s, color=%s, season=%s, stock=%s, target_gender=%s, reencoded=%s",
                         item_id, category_en, payload.get("color"), payload.get("season"),
                         stock, target_gender, need_reencode)
        else:
            # 商品下架：软删除（置 is_active=false，保留向量供重新上架）
            self._indexer.set_item_inactive(int(item_id))
            logger.info("商品已下架（is_active=false）: itemId=%s", item_id)

    def _should_reencode(self, fields_changed: list) -> bool:
        """判断是否需要重新 encode 文本向量

        纯文本向量模式下，以下字段变更会影响检索文本，需重新 encode：
        name / category / color / season / style_tags
        （image 保留兼容标记，实际不触发图片编码，但也触发重新 encode 以保持一致性）

        - fields_changed 为空（老版本消息兼容）：默认重新 encode
        - fields_changed 包含任一文本字段：重新 encode
        - fields_changed 仅含 price/stock/status：跳过 encode
        """
        if not fields_changed:
            return True
        return any(f in VECTOR_AFFECTING_FIELDS for f in fields_changed)

    def _handle_delete(self, payload: dict):
        """处理商品 delete 消息（物理删除）

        调 Indexer.delete_item 从 Qdrant 删除向量。
        """
        item_id = payload.get("itemId")
        if not item_id:
            raise ValueError("消息缺少 itemId 字段")
        if self._indexer is None:
            raise RuntimeError("Indexer 未初始化")
        self._indexer.delete_item(int(item_id))
        logger.info("商品已从 Qdrant 删除: itemId=%s", item_id)
