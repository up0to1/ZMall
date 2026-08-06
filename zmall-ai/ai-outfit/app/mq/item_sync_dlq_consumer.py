"""
商品库同步死信队列消费者

消费 item.sync.dlq 队列中失败的商品同步消息：
  - 重试 1 次（可能因临时故障如 EmbedClient 网络抖动失败，再次重试有机会成功）
  - 重试仍失败则记录详情到日志（含 itemId/category/error/raw_payload）
  - ack 丢弃（避免 DLQ 无限堆积，对账任务会兜底修复）

启动方式：与 ItemSyncMqConsumer 一样，在 main.py 中通过 start() 启动独立线程。

注意：本消费者不做"无限重试"——主消费者已重试 3 次，再无限重试只会堆积。
     失败的消息 ack 后丢弃，依赖定时对账脚本（reconcile_mysql_qdrant.py）兜底。
"""
import asyncio
import json
import logging
import threading
from typing import Any

from shared.mq_client.consumer import MqConsumer
from shared.qdrant_client.indexer import QdrantIndexer
from shared.qdrant_client.client import QdrantClientWrapper
from shared.qdrant_client.category_mapping import CN_TO_EN, to_en
from shared.model_client.embed_client import EmbedClient
from app.core.config import settings
from app.mq.item_sync_consumer import (
    ITEM_SYNC_EXCHANGE,
    ITEM_SYNC_DLQ,
    ITEM_SYNC_DLQ_KEY,
    ITEM_SYNC_UPSERT_KEY,
    ITEM_SYNC_DELETE_KEY,
    _build_item_text,
)

logger = logging.getLogger(__name__)


class ItemSyncDlqConsumer:
    """商品库同步死信队列消费者

    设计取舍：
    - 主消费者已重试 3 次，DLQ 消费者再重试 1 次即丢弃（避免无限堆积）
    - 重试成功：罕见场景（如 EmbedClient 长时间故障后恢复，刚好 DLQ 有积压）
    - 重试失败：ack 丢弃，依赖对账脚本兜底（reconcile_mysql_qdrant.py --fix-missing）
    - 人工介入：通过日志查询 "DLQ 消息处理失败" 关键字排查
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread: threading.Thread | None = None
        self._consumer: MqConsumer | None = None
        self._running = False
        self._indexer: QdrantIndexer | None = None
        self._embed_client: EmbedClient | None = None

    def start(self):
        """在独立线程中启动 DLQ 消费者"""
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="item-sync-dlq-consumer"
        )
        self._thread.start()
        logger.info("商品库同步 DLQ 消费者线程已启动")

    def stop(self):
        """停止 DLQ 消费者"""
        self._running = False
        if self._consumer:
            try:
                self._consumer.stop()
            except Exception as e:
                logger.warning("关闭 DLQ 消费者连接异常: %s", e)
        if self._thread:
            self._thread.join(timeout=5)
        if self._embed_client:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._embed_client.close(), self._loop
                )
                future.result(timeout=3)
            except Exception as e:
                logger.warning("关闭 EmbedClient 异常: %s", e)
        logger.info("商品库同步 DLQ 消费者已停止")

    def _run(self):
        """DLQ 消费者线程主逻辑"""
        try:
            qdrant_wrapper = QdrantClientWrapper(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                api_key=settings.qdrant_api_key,
                prefix=settings.qdrant_prefix,
                proxy_url=settings.proxy_url,
            )
            # DLQ 重试也需要 collection 存在
            # 主线程 lifespan 已预先调用过 ensure_collections，这里失败不退出线程。
            try:
                qdrant_wrapper.ensure_collections()
            except Exception as e:
                logger.warning("DLQ ensure_collections 失败（不退出）: %s", e)
            self._indexer = QdrantIndexer(qdrant_wrapper)

            # DLQ 消费者仅在重试时需要 encode（图片变更场景），
            # 不配置 embed_api_url 时跳过 encode，仅记日志
            self._embed_client = EmbedClient(
                api_url=settings.embed_api_url,
                api_key=settings.embed_api_key,
                timeout=20,
                vector_dim=1024,
            )

            self._consumer = MqConsumer(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                username=settings.rabbitmq_username,
                password=settings.rabbitmq_password,
                virtual_host=settings.rabbitmq_vhost,
            )
            self._consumer.connect()

            # 声明 DLQ（与主消费者一致，确保队列存在）
            # 注意：DLQ 本身不需要 x-dead-letter-exchange（避免死循环）
            self._consumer.declare_exchange(ITEM_SYNC_EXCHANGE, exchange_type="topic")
            self._consumer.declare_queue(ITEM_SYNC_DLQ)
            self._consumer.bind(ITEM_SYNC_EXCHANGE, ITEM_SYNC_DLQ, ITEM_SYNC_DLQ_KEY)

            self._consumer.start_consuming(
                queue=ITEM_SYNC_DLQ,
                callback=self._on_message,
                auto_ack=False,
            )
        except Exception as e:
            logger.error("DLQ 消费者启动失败: %s", e, exc_info=True)

    def _on_message(self, channel, method, properties, body: bytes):
        """DLQ 消息处理回调

        主消费者已重试 3 次仍失败，这里再试 1 次；仍失败则 ack 丢弃。
        """
        try:
            payload: dict[str, Any] = json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.error("DLQ 消息 JSON 解析失败，直接 ack 丢弃: %s, body=%s",
                          e, body[:200])
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        item_id = payload.get("itemId")
        routing_key = method.routing_key  # 这里是 item.dlq，但原 routing_key 在 x-death header 里

        # 提取原 routing_key（来自 x-death header，用于区分 upsert/delete）
        original_routing_key = self._extract_original_routing_key(properties)

        logger.warning("收到 DLQ 消息: itemId=%s, originalRoutingKey=%s, payload=%s",
                        item_id, original_routing_key, json.dumps(payload, ensure_ascii=False)[:500])

        # 重试 1 次
        try:
            if original_routing_key == ITEM_SYNC_UPSERT_KEY:
                self._retry_upsert(payload)
            elif original_routing_key == ITEM_SYNC_DELETE_KEY:
                self._retry_delete(payload)
            else:
                logger.warning("DLQ 消息原 routing_key 未知，ack 丢弃: routingKey=%s",
                                original_routing_key)
                channel.basic_ack(delivery_tag=method.delivery_tag)
                return

            # 重试成功
            logger.info("DLQ 消息重试成功: itemId=%s, routingKey=%s",
                         item_id, original_routing_key)
            channel.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            # 重试仍失败 → ack 丢弃，依赖对账脚本兜底
            logger.error("DLQ 消息重试仍失败，ack 丢弃（依赖对账脚本兜底）: "
                          "itemId=%s, routingKey=%s, error=%s, payload=%s",
                          item_id, original_routing_key, e,
                          json.dumps(payload, ensure_ascii=False)[:500], exc_info=True)
            channel.basic_ack(delivery_tag=method.delivery_tag)

    def _extract_original_routing_key(self, properties) -> str | None:
        """从 RabbitMQ properties 的 x-death header 中提取原始 routing_key

        DLQ 消息会带 x-death header：[{queue, reason, time, routing-keys, exchange, ...}]
        """
        try:
            headers = properties.headers or {}
            x_death = headers.get("x-death") or []
            if x_death:
                # x-death 是 list[dict]
                first = x_death[0] if isinstance(x_death, list) else None
                if first:
                    routing_keys = first.get("routing-keys") or []
                    if routing_keys:
                        return routing_keys[0]
            return None
        except Exception:
            return None

    def _retry_upsert(self, payload: dict):
        """重试 upsert 处理（与 ItemSyncMqConsumer._handle_upsert 逻辑一致）

        DLQ 重试不再做穿搭类目过滤（已在主消费者做过），
        也不做 fields_changed 优化（重试必然要重新 encode）。
        纯文本向量模式：拼接商品文本属性后用 encode_text 编码。
        """
        item_id = payload.get("itemId")
        if not item_id:
            raise ValueError("DLQ 消息缺少 itemId 字段")

        category_cn = payload.get("category")
        if not category_cn:
            raise ValueError(f"DLQ 商品 {item_id} 缺少 category 字段")

        # 防御性穿搭类目过滤
        if category_cn not in CN_TO_EN:
            logger.info("DLQ 商品非穿搭类目，跳过: itemId=%s, category=%s",
                         item_id, category_cn)
            return

        is_active = payload.get("isActive", True)
        if self._indexer is None:
            raise RuntimeError("DLQ Indexer 未初始化")

        if not is_active:
            self._indexer.set_item_inactive(int(item_id))
            return

        # 强制重新 encode（DLQ 消息可能是因 encode 失败进来的）
        if self._embed_client is None or not self._embed_client.api_url:
            raise RuntimeError("DLQ 重试需要 encode 但 EmbedClient 未配置")

        # 纯文本向量模式：拼接商品文本后编码
        item_text = _build_item_text(payload)
        if not item_text:
            raise ValueError(f"DLQ 商品 {item_id} 文本拼接为空，无法生成向量")

        future = asyncio.run_coroutine_threadsafe(
            self._embed_client.encode_text(item_text), self._loop
        )
        vector = future.result(timeout=60)
        if vector is None or len(vector) != 1024:
            raise ValueError(f"DLQ 商品 {item_id} 向量生成失败或维度不符 (text={item_text[:80]})")

        category_en = to_en(category_cn)
        stock = int(payload.get("stock") or 0)
        raw_gender = payload.get("targetGender")
        target_gender = raw_gender if raw_gender in ("male", "female", "unisex") else None

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

    def _retry_delete(self, payload: dict):
        """重试 delete 处理"""
        item_id = payload.get("itemId")
        if not item_id:
            raise ValueError("DLQ delete 消息缺少 itemId 字段")
        if self._indexer is None:
            raise RuntimeError("DLQ Indexer 未初始化")
        self._indexer.delete_item(int(item_id))
