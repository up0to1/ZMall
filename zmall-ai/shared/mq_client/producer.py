"""
RabbitMQ 生产者

用于向 Java 侧发送 AI 任务结果消息（配额确认/回滚）。

特性：
- 连接断开自动重连（含 channel 重建）
- publish 失败时重试，避免 Java 侧永远收不到配额确认/回滚
- 线程安全（同一实例可被多个线程调用，但 pika BlockingConnection 不是线程安全的，
  实际使用时应通过 asyncio.to_thread 在固定线程池中调用，或每个调用方各自同步）
"""
import logging
import json
import threading

import pika
import pika.exceptions  # 用于捕获 UnroutableError 等 publisher confirm 异常

logger = logging.getLogger(__name__)

# 重连参数
MAX_RECONNECT_RETRIES = 3
RECONNECT_DELAY = 2  # 秒


class MqProducer:
    """RabbitMQ 生产者封装（带自动重连）"""

    def __init__(
        self,
        host: str = "192.168.59.128",
        port: int = 5672,
        username: str = "hmall",
        password: str = "",
        virtual_host: str = "/",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.virtual_host = virtual_host
        self._connection: pika.BlockingConnection | None = None
        self._channel = None
        self._lock = threading.Lock()
        # 缓存已声明的 exchange，避免每次 publish 都 exchange_declare
        self._declared_exchanges: set[str] = set()

    def connect(self):
        """建立 RabbitMQ 连接（线程安全）"""
        with self._lock:
            self._do_connect_locked()

    def _do_connect_locked(self):
        """实际建立连接（调用方需持有 _lock）"""
        # 先关闭旧连接（可能已断开）
        try:
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception:
            pass

        credentials = pika.PlainCredentials(self.username, self.password)
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=self.host,
                port=self.port,
                credentials=credentials,
                # 心跳 60s，避免被 RabbitMQ 空闲断开
                heartbeat=60,
                # 连接阻塞超时 30s
                blocked_connection_timeout=30,
                virtual_host=self.virtual_host,
            )
        )
        self._channel = self._connection.channel()
        # 启用 publisher confirm 机制，使 basic_publish 同步等待 broker ack/nack
        # 若 pika 版本差异导致调用失败，降级为不启用 confirm（保持原有行为）
        try:
            self._channel.confirm_delivery()
            logger.info("RabbitMQ 已启用 publisher confirm (confirm_delivery)")
        except Exception as confirm_err:
            logger.warning(
                "RabbitMQ 启用 confirm_delivery 失败，降级为不启用 confirm: %s", confirm_err
            )
        # 重连后清空已声明 exchange 缓存（新 channel 需要重新声明）
        self._declared_exchanges.clear()
        logger.info("RabbitMQ 生产者已连接: %s:%s vhost=%s", self.host, self.port, self.virtual_host)

    def _ensure_connected(self):
        """确保连接可用，断开则重连（调用方需持有 _lock）"""
        if self._connection is None or self._channel is None or not self._connection.is_open:
            logger.warning("RabbitMQ 连接不可用，尝试重连...")
            self._do_connect_locked()
            return
        # 检查 channel 是否仍然 open
        if not self._channel.is_open:
            logger.warning("RabbitMQ channel 已关闭，尝试重连...")
            self._do_connect_locked()

    def publish(
        self,
        exchange: str,
        routing_key: str,
        message: dict,
        exchange_type: str = "topic",
    ):
        """发送消息到指定 Exchange

        失败时最多重试 MAX_RECONNECT_RETRIES 次（含一次重连）。
        所有重试均失败则抛出异常，由调用方记录日志（不影响主流程）。
        """
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        properties = pika.BasicProperties(
            delivery_mode=2,  # 持久化
            content_type="application/json",
        )

        last_error: Exception | None = None
        for attempt in range(1, MAX_RECONNECT_RETRIES + 1):
            with self._lock:
                try:
                    self._ensure_connected()
                    # 幂等声明 exchange（同一 channel 内已声明则跳过）
                    if exchange not in self._declared_exchanges:
                        self._channel.exchange_declare(
                            exchange=exchange, exchange_type=exchange_type, durable=True
                        )
                        self._declared_exchanges.add(exchange)
                    # mandatory=True 使消息路由不到队列时触发 Basic.Return，
                    # 配合 confirm_delivery 模式下 basic_publish 同步阻塞等待 broker ack/nack，
                    # broker nack 或路由失败时抛出 UnroutableError
                    try:
                        self._channel.basic_publish(
                            exchange=exchange,
                            routing_key=routing_key,
                            body=body,
                            properties=properties,
                            mandatory=True,
                        )
                    except pika.exceptions.UnroutableError as nack_err:
                        # broker nack（消息未被确认/无法路由），
                        # 记录 warning 后 re-raise，交由外层重试逻辑处理
                        logger.warning(
                            "MQ 消息被 broker nack (UnroutableError): "
                            "exchange=%s, routingKey=%s, error=%s",
                            exchange, routing_key, nack_err,
                        )
                        raise
                    logger.info(
                        "MQ 消息已发送: exchange=%s, routingKey=%s", exchange, routing_key
                    )
                    return
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "MQ 发送失败(第%d次): exchange=%s, error=%s",
                        attempt, exchange, e,
                    )
                    # 标记连接需要重建
                    self._connection = None
                    self._channel = None
                    self._declared_exchanges.clear()

            # 重试前等待（最后一次不等待）
            if attempt < MAX_RECONNECT_RETRIES:
                import time
                time.sleep(RECONNECT_DELAY)

        # 所有重试均失败
        logger.error(
            "MQ 发送最终失败(重试 %d 次): exchange=%s, routingKey=%s, error=%s",
            MAX_RECONNECT_RETRIES, exchange, routing_key, last_error,
        )
        raise last_error if last_error else RuntimeError("MQ 发送失败")

    def close(self):
        with self._lock:
            if self._connection and self._connection.is_open:
                try:
                    self._connection.close()
                    logger.info("RabbitMQ 生产者连接已关闭")
                except Exception:
                    pass
            self._connection = None
            self._channel = None
            self._declared_exchanges.clear()
