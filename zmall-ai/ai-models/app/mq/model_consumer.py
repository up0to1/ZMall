"""
AI 模特图生成 MQ 消费者

订阅 ai.model.generate 队列，消费 Java item-service 发来的任务消息。
pika 的 BlockingConnection 是同步的，在独立线程中运行，
通过 asyncio.run_coroutine_threadsafe 调用 async 业务代码。
"""
import asyncio
import concurrent.futures
import json
import logging
import threading
import time

from shared.mq_client.consumer import MqConsumer
from shared.mq_client.producer import MqProducer
from shared.metrics import record_model_generate, record_mq_consume
from app.core.config import settings

logger = logging.getLogger(__name__)

# MQ 常量（与 Java 侧 MqConstants 对应）
AI_MODEL_EXCHANGE = "ai.model.exchange"
AI_MODEL_GENERATE_QUEUE = "ai.model.generate.queue"
AI_MODEL_GENERATE_KEY = "ai.model.generate"
AI_MODEL_RESULT_KEY = "ai.model.result"


class ModelMqConsumer:
    """AI 模特图生成 MQ 消费者（独立线程运行）"""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread: threading.Thread | None = None
        self._consumer: MqConsumer | None = None
        self._producer: MqProducer | None = None
        self._running = False
        # 非阻塞消费 - 跟踪 in-flight 任务（delivery_tag → future）
        # future.add_done_callback 可能在不同线程触发，访问需加锁
        self._inflight: dict[int, concurrent.futures.Future] = {}
        self._inflight_lock = threading.Lock()
        self._prefetch_count = 5

    def start(self):
        """在独立线程中启动 MQ 消费者"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="model-mq-consumer")
        self._thread.start()
        logger.info("AI 模特图 MQ 消费者线程已启动")

    def stop(self):
        """停止 MQ 消费者

        - 立即关闭消费者连接（停止接收新消息，消费者线程可退出）
        - 后台线程等待 in-flight 任务完成后关闭生产者连接
        - 不在事件循环线程中阻塞等待（in-flight 协程在事件循环中执行，
          阻塞事件循环会导致协程无法完成 → 死锁）

        in-flight 任务的 ack 会因消费者连接已关闭而失败，消息由 RabbitMQ
        重投递，幂等校验（Redis SETNX）防止重复处理。

        关闭 producer 连接，避免 pika 连接泄漏。
        """
        self._running = False
        # 立即关闭消费者连接（停止接收新消息，让消费者线程退出）
        if self._consumer:
            try:
                self._consumer.stop()
            except Exception as e:
                logger.warning("关闭 MQ 消费者连接异常: %s", e)
        # 后台等待 in-flight 任务完成 → 关闭 producer
        # 不在事件循环线程阻塞等待（in-flight 协程需要事件循环持续运行）
        with self._inflight_lock:
            pending = list(self._inflight.values())
        if pending:
            threading.Thread(
                target=self._drain_and_close_producer,
                args=(pending,),
                daemon=True,
                name="model-mq-drain",
            ).start()
        else:
            # 无 in-flight 任务，直接关闭 producer
            if self._producer:
                try:
                    self._producer.close()
                except Exception as e:
                    logger.warning("关闭 MQ 生产者连接异常: %s", e)
        # 等待消费者线程退出（连接关闭后 start_consuming 返回）
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("AI 模特图 MQ 消费者停止信号已发送")

    def _drain_and_close_producer(self, pending: list[concurrent.futures.Future]):
        """后台等待 in-flight 任务完成并关闭 producer

        在独立 daemon 线程中运行，避免阻塞事件循环。
        in-flight 协程在事件循环中执行，需要事件循环持续运行才能完成。
        最多等待 600s（与单任务超时一致），超时后强制取消。
        """
        logger.info("等待 %d 个 in-flight 任务完成（最多 600s）...", len(pending))
        done, not_done = concurrent.futures.wait(pending, timeout=600)
        if not_done:
            logger.warning("%d 个 in-flight 任务超时未完成，强制取消", len(not_done))
            for f in not_done:
                f.cancel()
        if self._producer:
            try:
                self._producer.close()
            except Exception as e:
                logger.warning("关闭 MQ 生产者连接异常: %s", e)
        logger.info("AI 模特图 MQ 消费者已完全停止（in-flight 任务已清理）")

    def _run(self):
        """消费者线程主逻辑"""
        try:
            # 创建生产者（用于发送结果消息）
            self._producer = MqProducer(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                username=settings.rabbitmq_username,
                password=settings.rabbitmq_password,
                virtual_host=settings.rabbitmq_vhost,
            )
            self._producer.connect()

            # 创建消费者
            self._consumer = MqConsumer(
                host=settings.rabbitmq_host,
                port=settings.rabbitmq_port,
                username=settings.rabbitmq_username,
                password=settings.rabbitmq_password,
                virtual_host=settings.rabbitmq_vhost,
            )
            self._consumer.connect()

            # 声明 Exchange + Queue + Binding
            self._consumer.declare_exchange(AI_MODEL_EXCHANGE, exchange_type="topic")
            self._consumer.declare_queue(AI_MODEL_GENERATE_QUEUE)
            self._consumer.bind(AI_MODEL_EXCHANGE, AI_MODEL_GENERATE_QUEUE, AI_MODEL_GENERATE_KEY)

            # 开始消费
            # prefetch_count=5，允许同时预取 5 条消息并行处理
            # 原 prefetch=1 时，单条任务 5 分钟超时期间无法消费下一条，QPS 极低（~0.0033）
            # 改为 5 后，QPS 提升到 ~0.0167（5 倍吞吐）
            self._consumer.start_consuming(
                queue=AI_MODEL_GENERATE_QUEUE,
                callback=self._on_message,
                auto_ack=False,
                prefetch_count=5,
            )
        except Exception as e:
            logger.error("MQ 消费者线程异常: %s", e, exc_info=True)

    def _on_message(self, ch, method, properties, body):
        """收到消息的回调（在消费者线程中执行）

        改为非阻塞回调模式，实现真正并行消费。
        - 提交任务后立即返回（不阻塞等待 future.result）
        - 用 _inflight dict 跟踪 in-flight 任务（delivery_tag → future），
          限制并发数不超过 prefetch_count（由 pika basic_qos 保证）
        - 任务完成回调中通过 ch.connection.add_callback_threadsafe
          调度回 pika 线程执行 basic_ack，实现跨线程 ack
        - 任务失败/超时也走相同回调路径发送结果并 ack（避免毒丸消息阻塞）
        - _inflight dict 的访问用 threading.Lock 保护（add_done_callback
          可能在不同线程触发）

        保留超时 600s、ack 兜底逻辑。

        无论成功/失败都 ack 消息，避免消息永久 Unacked。
        失败结果已通过 _run_with_timeout → _send_result 推给 Java 侧，
        无需重试消费。如 _send_result 也失败，Java 侧 ai_task 表有超时兜底。
        """
        delivery_tag = method.delivery_tag

        # 解析消息（失败时直接 ack 丢弃，避免毒丸消息阻塞）
        try:
            message = json.loads(body.decode("utf-8"))
        except Exception as e:
            logger.error("消息 JSON 解析失败，直接 ack 丢弃: %s", e, exc_info=True)
            try:
                ch.basic_ack(delivery_tag=delivery_tag)
            except Exception as ack_err:
                logger.error("解析失败后 ack 异常: %s", ack_err)
            return

        task_id = message.get("taskId", "")
        logger.info("收到模特图生成任务: taskId=%s, 商品数=%d",
                    task_id, len(message.get("items", [])))

        # 并发数防御性检查（prefetch_count=5 已由 pika basic_qos 保证）
        with self._inflight_lock:
            inflight_count = len(self._inflight)
            if inflight_count >= self._prefetch_count:
                logger.warning(
                    "in-flight 任务数 %d 已达上限 %d（不应发生，prefetch 已限制）",
                    inflight_count, self._prefetch_count,
                )

        # 提交任务到事件循环（非阻塞，立即返回 future）
        # _run_with_timeout 包装 _process_task，添加 600s 超时 + 异常兜底
        future = asyncio.run_coroutine_threadsafe(
            self._run_with_timeout(message),
            self._loop,
        )

        # 跟踪 in-flight 任务（线程安全，因为 done_callback 可能在不同线程触发）
        with self._inflight_lock:
            self._inflight[delivery_tag] = future

        # 注册完成回调，回调内通过 add_callback_threadsafe 调度回 pika 线程 ack
        # 闭包捕获 ch/delivery_tag/task_id（函数参数，按值捕获，线程安全）
        future.add_done_callback(
            lambda f: self._on_task_done(f, ch, delivery_tag, task_id)
        )

        logger.info("任务已提交（非阻塞）: taskId=%s, in-flight=%d",
                    task_id, inflight_count + 1)
        # 立即返回！pika 可继续投递下一条消息，实现真正并行消费

    async def _run_with_timeout(self, message: dict):
        """包装 _process_task 添加超时控制

        保持 _process_task 方法本身不变，仅在外层添加：
        - 600s 超时：超时后取消协程并发送失败结果
        - 异常兜底：_process_task 未捕获的异常（如 Redis/MQ 操作失败）
          也发送失败结果，避免消息成为毒丸

        _process_task 内部已处理工作流异常并通过 _send_result 推送结果，
        此方法仅处理 _process_task 自身抛出的异常（Redis/WS/MQ 操作失败等）。
        """
        task_id = message.get("taskId", "")
        shop_id = message.get("shopId")
        try:
            # 超时 600s（10 分钟），最坏耗时 ~246s + 网络抖动余量
            return await asyncio.wait_for(self._process_task(message), timeout=600)
        except asyncio.TimeoutError:
            # 超时后 wait_for 自动取消内部协程，无需手动 future.cancel()
            logger.error("任务处理超时（600s），已取消协程: taskId=%s", task_id)
            try:
                await asyncio.to_thread(
                    self._send_result,
                    task_id=task_id,
                    shop_id=shop_id,
                    status="FAILED",
                    error_msg="任务处理超时（600s）",
                )
            except Exception as send_err:
                logger.error("超时后发送失败结果也异常: taskId=%s, error=%s",
                             task_id, send_err, exc_info=True)
            return False
        except Exception as e:
            # _process_task 未捕获的异常（Redis/MQ 操作失败等）
            logger.error("任务处理未捕获异常: taskId=%s, error=%s",
                         task_id, e, exc_info=True)
            try:
                await asyncio.to_thread(
                    self._send_result,
                    task_id=task_id,
                    shop_id=shop_id,
                    status="FAILED",
                    error_msg=str(e),
                )
            except Exception as send_err:
                logger.error("发送失败结果也异常: taskId=%s, error=%s",
                             task_id, send_err, exc_info=True)
            return False

    def _on_task_done(self, future, ch, delivery_tag, task_id):
        """任务完成回调

        在 asyncio 事件循环线程中触发（future 完成时）。
        通过 add_callback_threadsafe 调度回 pika 线程执行 basic_ack，
        实现跨线程 ack（pika BlockingConnection 非线程安全，
        只能在 pika 线程中调用 channel 方法）。

        无论成功/失败/超时都 ack（失败结果已由 _run_with_timeout 发送）。
        """
        # 从 _inflight 移除（线程安全）
        with self._inflight_lock:
            self._inflight.pop(delivery_tag, None)

        # 检查结果并记录日志
        try:
            if future.cancelled():
                logger.warning("任务被取消: taskId=%s", task_id)
            else:
                exc = future.exception()
                if exc is not None:
                    logger.error("任务处理失败: taskId=%s, error=%s", task_id, exc)
                else:
                    result = future.result()
                    logger.info("任务处理完成: taskId=%s, success=%s", task_id, result)
        except Exception as e:
            logger.error("获取任务结果异常: taskId=%s, error=%s",
                         task_id, e, exc_info=True)

        # 跨线程 ack — 通过 add_callback_threadsafe 调度回 pika 线程
        # pika BlockingConnection 的 channel 方法只能在 pika 线程中调用
        try:
            ch.connection.add_callback_threadsafe(
                lambda: self._safe_ack(ch, delivery_tag)
            )
        except Exception as e:
            # 连接可能已关闭（stop 时），ack 失败消息将由 RabbitMQ 重投递
            # 幂等校验（Redis SETNX）防止重复处理
            logger.error("调度 ack 失败（连接可能已关闭）: taskId=%s, error=%s",
                         task_id, e, exc_info=True)

    def _safe_ack(self, ch, delivery_tag):
        """在 pika 线程中执行 basic_ack

        由 add_callback_threadsafe 调度到 pika 线程执行，
        确保 channel 操作的线程安全。
        """
        try:
            ch.basic_ack(delivery_tag=delivery_tag)
        except Exception as e:
            logger.error("MQ ack 失败（连接可能已断开，消息将由 RabbitMQ 重投递）: %s",
                         e, exc_info=True)

    async def _process_task(self, message: dict):
        """处理模特图生成任务（在主事件循环中执行）

        完整流程：
        1. 幂等校验（Redis SETNX，防 MQ 重复消费）
        2. 根据 generationMode + enableMultiAgent 切换：
           - generationMode="multi_outfit"：走多换装工作流
           - enableMultiAgent=true：本进程内调用 run_model_agent_workflow
           - 默认：走 ModelService.generate_model_images_chain（链式 VTON）
        3. 写 Redis 任务状态（供前端轮询兜底）
        4. WebSocket 推送（实时通知在线商家）
        5. 发 MQ 结果消息（Java 侧更新 ai_task 表 + 配额确认/回滚）

        消息体（ai.model.generate v2 + v3 + v5 扩展）：
        {
          "taskId", "userId", "shopId",
          "items": [{"itemId", "ossUrl", "category"}, ...],  # 按链式顺序排好
          "itemIds": [101, 102, 103],                        # 商家选定的商品 ID 列表
          "modelImageUrl": "...",                            # 模特图 URL（Java 已从系统池解析）
          "modelImageCandidates": [...],                     # 三级池候选（多 Agent 用）
          "enableMultiAgent": false,                         # v3 新增：是否启用多 Agent 决策
          "generationMode": "single",                        # v5 新增：生成模式 single/multi_outfit
          "outfitCombinations": [[101,201],[101,202]],       # v5 新增：多换装组合（可选，未传由 Python LLM 生成）
          "combinationReasons": ["...", "..."]               # v5 新增：组合推荐理由
        }

        v2 取消字段：saveToShopPool / uploadedModelInfo（上传即入池由 Java 上传接口完成）
        """
        from app.services.model_service import ModelService
        from app.services.model_agent_service import run_model_agent_workflow
        from app.api.deps import get_redis

        task_id = message["taskId"]
        items = message.get("items", [])
        item_ids = message.get("itemIds", [])
        model_image_url = message.get("modelImageUrl", "")
        user_id = message.get("userId")
        shop_id = message.get("shopId")
        enable_multi_agent = message.get("enableMultiAgent", False)
        generation_mode = message.get("generationMode", "single")

        start_time = time.monotonic()

        # 幂等校验：SETNX ai:task:idempotent:{taskId}（TTL 1h）
        redis = await get_redis()
        idempotent_key = f"ai:task:idempotent:{task_id}"
        acquired = await redis.set(idempotent_key, "1", ex=3600, nx=True)
        if not acquired:
            logger.warning("幂等校验：任务已处理，跳过: taskId=%s", task_id)
            record_mq_consume(queue=AI_MODEL_GENERATE_QUEUE, status="idempotent_skip")
            return False

        # 根据生成模式切换流程
        if generation_mode == "multi_outfit":
            # v5：多换装模式（多套组合并行 VTON + 独立评估 + 独立后处理）
            logger.info("[多换装] 启用多换装模式: taskId=%s, 商品数=%d",
                        task_id, len(items))
            try:
                result = await run_model_agent_workflow(message)
                success = result.get("success", False)
                result_urls = result.get("resultUrls")
                item_categories = result.get("itemCategories")
                error_msg = result.get("errorMsg")
                extra = {
                    "starRating": result.get("starRating", 0),
                    "overallScore": result.get("overallScore", 0.0),
                    "styleFeatures": result.get("styleFeatures", ""),
                    "styleFeaturesDivergence": result.get("styleFeaturesDivergence", ""),
                    "postProcessedImageUrl": result.get("postProcessedImageUrl"),
                    "agentEvaluations": result.get("agentEvaluations") or {},
                    "sceneResults": result.get("sceneResults") or [],
                    "outfitCombinations": result.get("outfitCombinations") or [],
                    "combinationReasons": result.get("combinationReasons") or [],
                    "poseResults": result.get("poseResults") or [],
                    "decisionReason": result.get("decisionReason", ""),
                }
            except Exception as e:
                logger.error("[多换装] 工作流执行异常: taskId=%s, error=%s",
                             task_id, e, exc_info=True)
                success = False
                result_urls = None
                item_categories = None
                error_msg = f"多换装工作流异常: {e}"
                extra = {}
        elif generation_mode == "multi_pose":
            # v5：多姿势模式（1 次 VTON + N 次 O1 图生图生成姿势变体）
            logger.info("[多姿势] 启用多姿势模式: taskId=%s, 商品数=%d, poseCount=%s",
                        task_id, len(items), message.get("poseCount", 3))
            try:
                result = await run_model_agent_workflow(message)
                success = result.get("success", False)
                result_urls = result.get("resultUrls")
                item_categories = result.get("itemCategories")
                error_msg = result.get("errorMsg")
                extra = {
                    "starRating": result.get("starRating", 0),
                    "overallScore": result.get("overallScore", 0.0),
                    "styleFeatures": result.get("styleFeatures", ""),
                    "styleFeaturesDivergence": result.get("styleFeaturesDivergence", ""),
                    "postProcessedImageUrl": result.get("postProcessedImageUrl"),
                    "agentEvaluations": result.get("agentEvaluations") or {},
                    "sceneResults": result.get("sceneResults") or [],
                    "poseResults": result.get("poseResults") or [],
                    "outfitCombinations": result.get("outfitCombinations") or [],
                    "combinationReasons": result.get("combinationReasons") or [],
                    "decisionReason": result.get("decisionReason", ""),
                }
            except Exception as e:
                logger.error("[多姿势] 工作流执行异常: taskId=%s, error=%s",
                             task_id, e, exc_info=True)
                success = False
                result_urls = None
                item_categories = None
                error_msg = f"多姿势工作流异常: {e}"
                extra = {}
        elif enable_multi_agent:
            # v4：多 Agent 决策架构（本进程内 LangGraph 工作流，无跨服务调用）
            logger.info("[多Agent] 启用多 Agent 决策: taskId=%s", task_id)
            try:
                result = await run_model_agent_workflow(message)
                success = result.get("success", False)
                result_urls = result.get("resultUrls")
                item_categories = result.get("itemCategories")
                error_msg = result.get("errorMsg")
                extra = {
                    "starRating": result.get("starRating", 0),
                    "overallScore": result.get("overallScore", 0.0),
                    "styleFeatures": result.get("styleFeatures", ""),
                    "styleFeaturesDivergence": result.get("styleFeaturesDivergence", ""),
                    "postProcessedImageUrl": result.get("postProcessedImageUrl"),
                    "agentEvaluations": result.get("agentEvaluations") or {},
                    "decisionReason": result.get("decisionReason", ""),
                    "issuesSummary": result.get("issuesSummary") or [],
                    "selectedCandidateIdx": result.get("selectedCandidateIdx", 0),
                }
            except Exception as e:
                logger.error("[多Agent] 工作流执行异常: taskId=%s, error=%s",
                             task_id, e, exc_info=True)
                success = False
                result_urls = None
                item_categories = None
                error_msg = f"多 Agent 工作流异常: {e}"
                extra = {}
        else:
            # 默认：链式 VTON（无 LLM 决策）
            service: ModelService | None = None
            try:
                service = ModelService()
                success, result_urls, item_categories, error_msg = \
                    await service.generate_model_images_chain(
                        task_id=task_id,
                        model_image_url=model_image_url,
                        items=items,
                    )
                extra = {}  # 链式 VTON 无额外字段
            except Exception as e:
                # 与多 Agent 路径保持一致：异常时仍走 Redis/WS/MQ 失败推送
                # 否则异常传播到 _on_message 外层，Redis 任务状态和 WS 推送会缺失
                logger.error("[链式VTON] 执行异常: taskId=%s, error=%s",
                             task_id, e, exc_info=True)
                success = False
                result_urls = None
                item_categories = None
                error_msg = f"链式 VTON 异常: {e}"
                extra = {}
            finally:
                # service 可能为 None（构造器异常），需 None 防护避免 NameError 掩盖原始异常
                if service is not None:
                    await service.close()

        # 写 Redis 任务状态（TTL 1h，供前端轮询）
        # 多 Agent / 多换装模式：extra 非空时额外写入评分/风格等字段
        if success:
            status_payload = {
                "status": "SUCCESS",
                "resultUrls": result_urls,
                "itemCategories": item_categories,
                "itemIds": item_ids,
                # 写入 userId 用于结果查询接口的越权校验
                "userId": user_id,
            }
            if extra:
                status_payload["starRating"] = extra.get("starRating", 0)
                status_payload["overallScore"] = extra.get("overallScore", 0.0)
                status_payload["styleFeatures"] = extra.get("styleFeatures", "")
                status_payload["styleFeaturesDivergence"] = extra.get(
                    "styleFeaturesDivergence", ""
                )
                status_payload["postProcessedImageUrl"] = extra.get(
                    "postProcessedImageUrl"
                )
                # v5 多换装模式专属字段
                if extra.get("sceneResults"):
                    status_payload["sceneResults"] = extra["sceneResults"]
                if extra.get("outfitCombinations"):
                    status_payload["outfitCombinations"] = extra["outfitCombinations"]
                if extra.get("combinationReasons"):
                    status_payload["combinationReasons"] = extra["combinationReasons"]
                # v5 多姿势模式专属字段
                if extra.get("poseResults"):
                    status_payload["poseResults"] = extra["poseResults"]
            status_data = json.dumps(status_payload, ensure_ascii=False)
            await redis.set(f"ai:task:status:{task_id}", status_data, ex=3600)
        else:
            status_data = json.dumps({
                "status": "FAILED",
                "errorMsg": error_msg or "生成失败",
                # 写入 userId 用于结果查询接口的越权校验
                "userId": user_id,
            }, ensure_ascii=False)
            await redis.set(f"ai:task:status:{task_id}", status_data, ex=3600)

        # WebSocket 推送（按 userId，商家可能开多页面）
        try:
            from app.api.v1.ws import ws_manager
            ws_message = {
                "taskId": task_id,
                "type": "AI_MODEL",
                "status": "SUCCESS" if success else "FAILED",
            }
            if success:
                ws_message["resultUrls"] = result_urls
                ws_message["itemCategories"] = item_categories
                ws_message["itemIds"] = item_ids
                if extra:
                    ws_message["starRating"] = extra.get("starRating", 0)
                    ws_message["overallScore"] = extra.get("overallScore", 0.0)
                    ws_message["styleFeatures"] = extra.get("styleFeatures", "")
                    ws_message["styleFeaturesDivergence"] = extra.get(
                        "styleFeaturesDivergence", ""
                    )
                    ws_message["postProcessedImageUrl"] = extra.get(
                        "postProcessedImageUrl"
                    )
                    # agentEvaluations 仅走 WebSocket 给前端展示，不进 MQ（Java 侧不持久化）
                    ws_message["agentEvaluations"] = extra.get("agentEvaluations") or {}
                    # v5 多换装模式专属字段
                    if extra.get("sceneResults"):
                        ws_message["sceneResults"] = extra["sceneResults"]
                    if extra.get("outfitCombinations"):
                        ws_message["outfitCombinations"] = extra["outfitCombinations"]
                    if extra.get("combinationReasons"):
                        ws_message["combinationReasons"] = extra["combinationReasons"]
                    # v5 多姿势模式专属字段
                    if extra.get("poseResults"):
                        ws_message["poseResults"] = extra["poseResults"]
            else:
                ws_message["errorMsg"] = error_msg or "生成失败"
            if user_id:
                await ws_manager.send_to_user(str(user_id), ws_message)
        except Exception as e:
            logger.warning("WS 推送失败（商家可能不在线）: taskId=%s, error=%s", task_id, e)

        # 发送结果到 MQ（Java 侧更新 ai_task 表 + 配额确认/回滚）
        if success:
            await asyncio.to_thread(
                self._send_result,
                task_id=task_id,
                shop_id=shop_id,
                status="SUCCESS",
                result_urls=result_urls,
                item_categories=item_categories,
                item_ids=item_ids,
                extra=extra,
            )
        else:
            await asyncio.to_thread(
                self._send_result,
                task_id=task_id,
                shop_id=shop_id,
                status="FAILED",
                error_msg=error_msg or "生成失败",
            )

        # 业务监控指标埋点
        duration = time.monotonic() - start_time
        record_model_generate(status="SUCCESS" if success else "FAILED", duration_seconds=duration)
        record_mq_consume(queue=AI_MODEL_GENERATE_QUEUE, status="success" if success else "failed")

        return success

    def _send_result(
        self,
        task_id: str,
        shop_id: int | None,
        status: str,
        result_urls: list[str] | None = None,
        item_categories: list[str] | None = None,
        item_ids: list[int] | None = None,
        error_msg: str | None = None,
        extra: dict | None = None,
    ):
        """发送结果消息到 ai.model.result 队列

        新增 extra 参数，多 Agent 模式下透传
        starRating/overallScore/styleFeatures/styleFeaturesDivergence/postProcessedImageUrl
        字段到 Java 侧，供 ai_task 表持久化 + 前端展示。
        链式 VTON 路径 extra 为 None 或空 dict，消息体与 v2 完全兼容。
        """
        if self._producer is None:
            logger.error("MQ 生产者未初始化，无法发送结果")
            return

        message = {
            "taskId": task_id,
            "shopId": shop_id,
            "status": status,
        }
        if result_urls:
            message["resultUrls"] = result_urls
        if item_categories:
            message["itemCategories"] = item_categories
        if item_ids:
            message["itemIds"] = item_ids
        if error_msg:
            message["errorMsg"] = error_msg

        # 多 Agent 模式专属字段（v3 扩展）
        if extra:
            message["starRating"] = extra.get("starRating", 0)
            message["overallScore"] = extra.get("overallScore", 0.0)
            message["styleFeatures"] = extra.get("styleFeatures", "")
            message["styleFeaturesDivergence"] = extra.get("styleFeaturesDivergence", "")
            if extra.get("postProcessedImageUrl"):
                message["postProcessedImageUrl"] = extra["postProcessedImageUrl"]
            # agentEvaluations 是 dict，需序列化为 JSON 字符串传输（Java 侧持久化为 JSON 字符串）
            if extra.get("agentEvaluations"):
                message["agentEvaluations"] = json.dumps(
                    extra["agentEvaluations"], ensure_ascii=False,
                )
            if extra.get("outfitCombinations"):
                message["outfitCombinations"] = extra["outfitCombinations"]
            if extra.get("combinationReasons"):
                message["combinationReasons"] = extra["combinationReasons"]
            if extra.get("sceneResults"):
                message["sceneResults"] = json.dumps(
                    extra["sceneResults"], ensure_ascii=False,
                )
            if extra.get("poseResults"):
                message["poseResults"] = json.dumps(
                    extra["poseResults"], ensure_ascii=False,
                )
            if extra.get("decisionReason"):
                message["decisionReason"] = extra["decisionReason"]

        self._producer.publish(
            exchange=AI_MODEL_EXCHANGE,
            routing_key=AI_MODEL_RESULT_KEY,
            message=message,
        )
