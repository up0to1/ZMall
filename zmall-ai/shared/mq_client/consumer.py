"""
RabbitMQ 消费者

用于消费 Java 侧发送的 AI 模特图生成任务消息。

修复说明：
- 增加自动重连机制，RabbitMQ 重启或网络抖动后自动恢复消费，
  避免消费链路永久下线必须重启进程。
- 禁用 heartbeat（heartbeat=0），避免 model_consumer 的
  future.result(timeout=300) 阻塞 5 分钟期间，pika BlockingConnection
  无法处理心跳而被 RabbitMQ 60s 心跳阈值强制断开。
"""
import logging
import time

import pika

logger = logging.getLogger(__name__)


class MqConsumer:
    """RabbitMQ 消费者封装（带自动重连）"""

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
        # 重连支持：记录所有声明/绑定操作和消费配置，重连后重放
        self._declarations: list[tuple] = []
        self._consume_config: dict | None = None
        self._running = False

    def connect(self):
        """建立 RabbitMQ 连接"""
        credentials = pika.PlainCredentials(self.username, self.password)
        params = pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            credentials=credentials,
            # 禁用心跳。model_consumer 的 _on_message 中
            # future.result(timeout=300) 会阻塞 pika 线程 5 分钟，
            # 若启用心跳（默认 60s）期间无法发送心跳，broker 会强制断开。
            heartbeat=0,
            blocked_connection_timeout=300,
            virtual_host=self.virtual_host,
        )
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        logger.info("RabbitMQ 消费者已连接: %s:%s vhost=%s", self.host, self.port, self.virtual_host)

    def declare_exchange(self, exchange: str, exchange_type: str = "topic", durable: bool = True):
        """声明 Exchange（幂等，重连后会重放）"""
        self._channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=durable)
        self._declarations.append(("exchange", exchange, exchange_type, durable))

    def declare_queue(self, queue: str, durable: bool = True, arguments: dict | None = None):
        """声明 Queue（幂等，重连后会重放）

        Args:
            queue: 队列名
            durable: 是否持久化
            arguments: 额外参数（如 x-dead-letter-exchange / x-dead-letter-routing-key / x-message-ttl）
                       注意：若队列已存在但参数不同，RabbitMQ 会抛 PRECONDITION_FAILED，
                       需先在 RabbitMQ 管理后台删除旧队列后重新声明。
        """
        self._channel.queue_declare(queue=queue, durable=durable, arguments=arguments or {})
        self._declarations.append(("queue", queue, durable, arguments))

    def bind(self, exchange: str, queue: str, routing_key: str):
        """绑定 Queue 到 Exchange（重连后会重放）"""
        self._channel.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)
        self._declarations.append(("bind", exchange, queue, routing_key))

    def _replay_declarations(self):
        """重连后重放所有 exchange/queue/binding 声明（声明操作本身是幂等的）"""
        for op in self._declarations:
            if op[0] == "exchange":
                self._channel.exchange_declare(exchange=op[1], exchange_type=op[2], durable=op[3])
            elif op[0] == "queue":
                # op = ("queue", name, durable, arguments)
                _, q_name, q_durable, q_args = op
                self._channel.queue_declare(queue=q_name, durable=q_durable, arguments=q_args or {})
            elif op[0] == "bind":
                self._channel.queue_bind(exchange=op[1], queue=op[2], routing_key=op[3])

    def _register_consumer(self):
        """注册消费者（首次和重连后均调用）"""
        cfg = self._consume_config
        # 设置 prefetch_count，允许消费者预取多条消息
        # 默认 1（保守），model_consumer 传 5 实现并行预取
        prefetch = cfg.get("prefetch_count", 1)
        self._channel.basic_qos(prefetch_count=prefetch)
        if cfg["auto_ack"]:
            self._channel.basic_consume(
                queue=cfg["queue"], on_message_callback=cfg["callback"], auto_ack=True
            )
        else:
            # 由 callback 自行处理 ack/nack；callback 抛异常时
            # 由 wrapped 兜底 nack(requeue=False) 进 DLQ，避免消息卡死。
            def wrapped(ch, method, properties, body):
                try:
                    cfg["callback"](ch, method, properties, body)
                except Exception as e:
                    # callback 未捕获异常兜底：nack 进 DLQ，避免消息卡死
                    logger.error("MQ callback 未捕获异常，nack 进 DLQ: %s", e, exc_info=True)
                    try:
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    except Exception as nack_err:
                        logger.error("MQ nack 兜底失败: %s", nack_err)
            self._channel.basic_consume(
                queue=cfg["queue"], on_message_callback=wrapped, auto_ack=False
            )

    def start_consuming(self, queue: str, callback, auto_ack: bool = False, prefetch_count: int = 1):
        """开始消费（带自动重连）

        RabbitMQ 重启或网络抖动导致连接断开后，自动重连并恢复
        exchange/queue/binding 声明和消费注册，无需重启进程。

        退出条件：
        - 调用 stop() 主动停止
        - 未知异常重试 5s 间隔仍失败（仅日志，不退出，继续重试）

        增加 prefetch_count 参数，允许消费者预取多条消息并行处理。
        默认 prefetch_count=1（保守，单线程顺序消费），
        model_consumer 设置 prefetch_count=5 实现 5 倍吞吐提升。
        注意：prefetch_count 仅控制预取数量，真正的并行需上层用线程池处理。
        """
        self._consume_config = {
            "queue": queue,
            "callback": callback,
            "auto_ack": auto_ack,
            "prefetch_count": prefetch_count,
        }
        self._register_consumer()
        logger.info("开始消费队列: %s, prefetch_count=%s", queue, prefetch_count)
        self._running = True
        self._consume_loop()

    def _consume_loop(self):
        """外层重连循环"""
        retry_backoff = [5, 10, 30, 60]  # 重试间隔（秒），最大 60s
        attempt = 0
        while self._running:
            try:
                self._channel.start_consuming()
                # start_consuming 正常返回（被 stop 中断）
                break
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.AMQPChannelError,
                    ConnectionError) as e:
                if not self._running:
                    break
                wait = retry_backoff[min(attempt, len(retry_backoff) - 1)]
                logger.error("MQ 消费者连接异常，%ds 后重连: %s", wait, e)
                attempt += 1
                time.sleep(wait)
                try:
                    self.connect()
                    self._replay_declarations()
                    self._register_consumer()
                    logger.info("MQ 消费者重连成功，恢复消费: queue=%s",
                                self._consume_config["queue"])
                    attempt = 0  # 重置退避计数
                except Exception as e2:
                    logger.error("MQ 消费者重连失败: %s", e2)
            except Exception as e:
                logger.error("MQ 消费者未知异常: %s", e, exc_info=True)
                if not self._running:
                    break
                time.sleep(5)

    def stop(self):
        """停止消费（设置 _running=False 让重连循环退出，并关闭连接）"""
        self._running = False
        if self._connection and self._connection.is_open:
            try:
                self._connection.close()
            except Exception as e:
                logger.warning("关闭 MQ 消费者连接异常: %s", e)

    def close(self):
        """兼容旧 API（等价于 stop）"""
        self.stop()
