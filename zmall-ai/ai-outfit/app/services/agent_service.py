"""
风格驱动模式 Agent 编排服务

完整流程（参考核心功能设计）：
  同步：配额预扣 → 写任务状态 → 启动异步 LangGraph 工作流 → 返回 taskId
  异步：LangGraph 5 节点推理 → 更新 Redis + WS 推送 + MQ 通知配额确认/回滚

多轮反馈（参考核心功能设计）：
  POST /feedback → 读取历史 state → credits 预扣（每轮 5 credits）
  → LlmClient 解析反馈 → 构造新一轮 initial_state
  → 重新 ainvoke 工作流（节点1/2/3 根据反馈字段自适应） → MQ 通知配额确认/回滚
  最大轮次 3（首轮 + 2 轮反馈），超限或 action=accept 则终止。

关键约束：
- 与商品驱动模式共享 user_id 配额池（type=OUTFIT, id=userId）
- 异步任务超时 30s → 标记 FAILED + WS 推送 + MQ 通知回滚
- MQ 共用 ai.outfit.exchange，routing key = ai.outfit.result
"""
import asyncio
import base64
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import redis.asyncio as aioredis

from app.api.deps import (
    get_java_client, get_llm_client, get_mq_producer, get_redis,
    get_user_behavior_indexer,
    get_user_preference_reader, get_user_preference_updater,
    get_user_episode_store,
    get_qdrant_searcher, get_embed_client,
)
from app.services.photo_session import PHOTO_SESSION_URL_PREFIX
from app.services.task_checkpoint import (
    build_task_checkpoint,
    hydrate_task_checkpoint,
)
from app.core.config import settings
from app.graphs.outfit_graph import OutfitGraphRunner
from app.schemas.agent_state import AgentState
from app.tools.agent_tools import ToolExecutor
from shared.metrics import (
    record_agent_workflow,
    record_outfit_generate,
    record_quota_check,
)
# 共享模块：PIL 多件合成 + "换一套"会话计数（与 ai-models 商品驱动模式共用）
from shared.outfit_common import (
    incr_and_get_old_count,
    decr_session_count,
    should_deduct,
    CategoryConflictError,
    validate_category_combination,
    filter_conflicting_categories,
    estimate_vton_timeout,
    count_vton_categories,
)
# 共享模块：品类中文↔英文映射
from shared.qdrant_client.category_mapping import to_cn
from shared.memory_policy import should_persist_preference
# 共享模块：分布式锁（对齐 Java 侧 Redisson RLock，编程式 tryLock/unlock）
from shared.distributed_lock import DistributedLock

logger = logging.getLogger(__name__)


class WorkflowBusyError(Exception):
    """全局工作流并发槽位不足（等待超时），提示用户稍后再试"""


# 全局工作流并发信号量：限制同时运行的 LangGraph 生成工作流数量
# 服务为单 uvicorn 进程单事件循环，进程内信号量即可满足；
# 若将来多 worker 部署需替换为 Redis 分布式信号量
WORKFLOW_SEMAPHORE = asyncio.Semaphore(settings.workflow_max_concurrent)


@asynccontextmanager
async def _workflow_slot():
    """获取全局工作流并发槽位（必须 async with 成对使用，finally 释放）

    - 等待槽位超时 → 抛 WorkflowBusyError，调用方走失败路径（提示稍后再试）
    - 与任务自身的超时（workflow_timeout / ASYNC_TIMEOUT）独立：槽位等待不计入任务超时
    """
    try:
        await asyncio.wait_for(
            WORKFLOW_SEMAPHORE.acquire(),
            timeout=settings.workflow_slot_wait,
        )
    except asyncio.TimeoutError:
        raise WorkflowBusyError("当前 AI 生成任务较多，请稍后再试") from None
    try:
        yield
    finally:
        WORKFLOW_SEMAPHORE.release()

# 任务状态 Redis Key 前缀和 TTL（与 ai-models 保持一致，前端可统一轮询）
TASK_STATUS_PREFIX = "ai:task:status:"
TASK_STATUS_TTL = 3600  # 1 小时

# 多轮反馈 state 持久化 Key 前缀和 TTL
# 延长到 7 天：覆盖搭配历史页的用户反馈场景（历史记录可能在数小时/数天后访问）
# 7 天内反馈走 Redis state（完整功能，含 query_vector/seen_item_ids 等）；
# 超过 7 天走 DB 兜底（降级功能，仅支持 regenerate_all，不支持精准替换单品）
STATE_SNAPSHOT_PREFIX = "ai:outfit:state:"
STATE_SNAPSHOT_TTL = 7 * 24 * 3600  # 7 天

# 只允许基于当前 checkpoint 版本写入，避免旧的异步任务结果覆盖新状态。
# Redis Lua 保证"检查版本 + 写入 + 刷新 TTL"是一个原子操作。
_CHECKPOINT_CAS_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current then
    local decoded = cjson.decode(current)
    local current_version = tonumber(decoded['checkpoint_version'] or 0)
    if current_version ~= tonumber(ARGV[1]) then
        return 0
    end
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""

# O4 优化：seen_item_ids 跨会话持久化 Key 前缀和 TTL
# 业务价值：避免用户下次回来又看到上次推荐过的商品；30 天后自动衰减，商品可重推
# 存储：Redis ZSet，member=item_id，score=最近展示时间戳；按商品粒度衰减
SEEN_ITEMS_PREFIX = "ai:outfit:seen:"
SEEN_ITEMS_TTL = 30 * 24 * 3600  # 30 天

# MQ 常量（与 Java 侧 MqConstants 对应，共用 ai.outfit.exchange）
AI_OUTFIT_EXCHANGE = "ai.outfit.exchange"
AI_OUTFIT_RESULT_KEY = "ai.outfit.result"

# 异步任务超时（LangGraph 推理含 intent/search/outfit/reflection/upload 多节点，
# 时尚潮流查询 + LLM 决策耗时较长，放宽到 60s 避免误杀）
ASYNC_TIMEOUT = 60

# 配额类型（与商品驱动模式共享 user_id 配额池）
QUOTA_TYPE = "OUTFIT"

# ===== 两阶段架构常量 =====
# 阶段一候选推荐（2 credits）：生成 Top3 候选搭配供用户选定
QUOTA_TYPE_RECOMMEND = "OUTFIT_RECOMMEND"
CREDITS_RECOMMEND = 2  # 阶段一固定 2 credits

# 阶段二 VTON 生成（5×N credits，N=用户选定的搭配数）
QUOTA_TYPE_VTON = "OUTFIT_VTON"
CREDITS_VTON_PER_OUTFIT = 5  # 每套 VTON 5 credits

# VTON 阶段超时不再使用固定常量，改为按品类件数动态估算
# 见 shared.outfit_common.estimate_vton_timeout()
# - 1 件 VTON ≈ 150s
# - 2 件 VTON ≈ 225s
# - 3 件 VTON ≈ 315s（互斥后上限）
# - 5 件 VTON ≈ 600s（互斥前最坏情况）

# ===== 一阶段直出架构常量 =====
# ④ 风格驱动模式：推荐（2）+ VTON Top3（5×3=15）合并为单流程，预扣 17 credits
QUOTA_TYPE_DIRECT = "OUTFIT_DIRECT"
CREDITS_DIRECT_TOTAL = CREDITS_RECOMMEND + CREDITS_VTON_PER_OUTFIT * 3  # 17

# "换一套"会话计数已下沉到 shared.outfit_common（与 ai-models 商品驱动模式共用同一实现）
# 调用 incr_and_get_old_count / should_deduct / decr_session_count 即可

class AgentService:
    """U1 统一架构编排服务（商品驱动 + 风格驱动）

    商品驱动模式（generate_outfit）：
      - 入参 item_ids（主商品 ID 列表），mode="product"
      - 节点1 走 _intent_understanding_product 分支（拉主商品 + encode_text）
      - 只生成 1 套搭配，不支持多轮反馈
      - WS/MQ 消息 type="OUTFIT_PRODUCT"

    风格驱动模式（recommend + feedback）：
      - 入参 style_tags/scene_desc/color 等，mode="agent"
      - 节点1 走原 intent_understanding 分支（encode_text）
      - 生成 3 套搭配，支持多轮反馈（最多 3 轮）
      - WS/MQ 消息 type="OUTFIT_AGENT"

    两种模式共享：
      - user_id 配额池（type=OUTFIT, id=userId）
      - 分布式锁 lock:outfit:recommend:user:{userId}（防止并发扣费错位）
      - "换一套"会话计数器
      - LangGraph 6 节点工作流（节点1 按 mode 分支，节点3/3.5/4 按 mode 分支）
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        # 待执行的异步任务集合，防止被 GC 回收（Python 文档要求）
        self._pending_tasks: set[asyncio.Task] = set()

    # ============================================================
    # U1 统一架构：商品驱动模式入口
    # ============================================================
    async def generate_outfit(
        self,
        user_id: int,
        item_ids: list[int],
        photo_session_key: str | None,
        system_model_id: int | None = None,
        system_model_image_url: str | None = None,
        system_model_gender: str | None = None,
        user_body_profile_id: int | None = None,
        user_city: str | None = None,
        user_country: str | None = None,
    ) -> tuple[str, str | None]:
        """U1 统一架构：商品驱动模式入口（原 ai-models outfit_service.generate_outfit 迁移）

        与风格驱动模式共享 user_id 配额池。
        - 单次换装生成扣 5 credits（OUTFIT_VTON，与风格驱动阶段二一致）
        - 失败自动回滚 credits
        - MQ 消息 phase="vton"，Java 侧 AiOutfitResultListener 路由到 CreditsService

        与 recommend() 的差异：
        - 入参是 item_ids（主商品 ID 列表），不是 style_tags/scene_desc
        - mode="product" 透传到 LangGraph state，节点1 走 _intent_understanding_product 分支
        - 不支持多轮反馈（无 feedback() 方法）
        - WS 消息 type="OUTFIT_PRODUCT"（风格驱动是 OUTFIT_AGENT）
        - 不保存 state 快照（无反馈需求）
        - 共享 user_id 配额池和分布式锁（lock:outfit:recommend:user:{userId}）
          确保同一用户的商品驱动 + 风格驱动任务串行化

        "换一套"配额规则与 recommend() 一致（每次生成都需要扣费，不支持免费重试）。

        Returns:
            (taskId, errorMsg)：
              - 成功：(taskId, None)
              - 配额不足：(taskId, "AI 生成次数或余额不足")
              - 服务异常：(taskId, "配额服务不可用")
        """
        task_id = str(uuid.uuid4())

        # 共享分布式锁：与 recommend() 同一把锁，防止商品驱动 + 风格驱动并发扣费错位
        recommend_lock_key = f"lock:outfit:recommend:user:{user_id}"
        async with DistributedLock(self.redis, recommend_lock_key,
                                    wait_timeout=3, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("generate_outfit 并发限流：userId=%s 锁被占用，拒绝本次请求", user_id)
                return task_id, "上一条搭配还在生成中，请稍候"

            # 0."换一套"会话计数判断（与 recommend 共用同一计数器）
            old_count = await incr_and_get_old_count(self.redis, user_id)
            need_deduct = should_deduct(old_count)
            logger.info("[商品驱动] 换一套计数: userId=%s, oldCount=%s, needDeduct=%s, taskId=%s",
                         user_id, old_count, need_deduct, task_id)

            # 1. v3 credits 预扣（5 credits，OUTFIT_VTON 类型，与风格驱动阶段二对齐）
            if need_deduct:
                java_client = await get_java_client()
                credits_result = await java_client.credits_deduct(
                    user_id=user_id,
                    quota_type=QUOTA_TYPE_VTON,
                    task_id=task_id,
                    credits=CREDITS_VTON_PER_OUTFIT,
                )
                if credits_result is None:
                    await decr_session_count(self.redis, user_id)
                    record_quota_check(quota_type=QUOTA_TYPE_VTON, result="failed")
                    return task_id, "配额服务不可用，请稍后重试"
                if not credits_result.get("success"):
                    await decr_session_count(self.redis, user_id)
                    msg = credits_result.get("msg", "AI 生成次数或余额不足")
                    logger.warning("[商品驱动] credits 预扣被拒绝: userId=%s, taskId=%s, msg=%s",
                                    user_id, task_id, msg)
                    record_quota_check(quota_type=QUOTA_TYPE_VTON, result="insufficient")
                    return task_id, msg

                record_quota_check(quota_type=QUOTA_TYPE_VTON, result="ok")
                logger.info("[商品驱动] credits 预扣成功: userId=%s, taskId=%s, credits=%s, balance=%s",
                             user_id, task_id, CREDITS_VTON_PER_OUTFIT,
                             credits_result.get("balance"))
            else:
                # need_deduct 恒为 True（不支持免费重试），此分支不会走到
                pass

        # 2. 写入任务状态到 Redis
        status = json.dumps({
            "status": "PROCESSING",
            "taskId": task_id,
            "userId": user_id,
            "taskType": "OUTFIT_PRODUCT",
            "createdAt": datetime.now().isoformat(),
        }, ensure_ascii=False)
        await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", status, ex=TASK_STATUS_TTL)

        # 3. 启动异步 LangGraph 工作流（mode="product"）
        # stage="vton" 让 _notify_mq 走 credits 路径（phase="vton"）
        task = asyncio.create_task(self._async_generate_outfit(
            task_id=task_id,
            user_id=user_id,
            item_ids=item_ids,
            photo_session_key=photo_session_key,
            need_deduct=need_deduct,
            system_model_id=system_model_id,
            system_model_image_url=system_model_image_url,
            system_model_gender=system_model_gender,
            user_body_profile_id=user_body_profile_id,
            user_city=user_city,
            user_country=user_country,
        ))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        logger.info("[商品驱动] 任务已创建: taskId=%s, userId=%s, itemIds=%s, needDeduct=%s, "
                     "systemModelId=%s, systemModelGender=%s",
                     task_id, user_id, item_ids, need_deduct,
                     system_model_id, system_model_gender)
        return task_id, None

    async def _async_generate_outfit(
        self,
        task_id: str,
        user_id: int,
        item_ids: list[int],
        photo_session_key: str | None,
        need_deduct: bool = True,
        system_model_id: int | None = None,
        system_model_image_url: str | None = None,
        system_model_gender: str | None = None,
        user_body_profile_id: int | None = None,
        user_city: str | None = None,
        user_country: str | None = None,
    ):
        """U1 统一架构：商品驱动模式异步执行 LangGraph 工作流

        与 _async_recommend 的差异：
        - initial_state 携带 mode="product" + main_item_ids，不携带 style_tags/scene_desc 等风格驱动字段
        - 节点1 走 _intent_understanding_product 分支（拉主商品 + encode_text + 推导互补品类）
        - 不读取用户偏好（商品驱动主商品已锁定，无需偏好增强召回）
        - 不解析衣橱三类 ID（商品驱动用户已选定主商品）
        - _on_success/_on_failure 传 mode="product"

        成功时保存 state 快照，支持多轮反馈。
        """
        start_time = time.monotonic()
        try:
            # 构造商品驱动模式 initial_state
            initial_state: AgentState = {
                "task_id": task_id,
                "user_id": user_id,
                "mode": "product",  # U1 统一架构：触发商品驱动分支
                "main_item_ids": list(item_ids),
                "photo_session_key": photo_session_key,
                "style_tags": [],       # 商品驱动不依赖 style_tags
                "scene_desc": None,
                "color": None,
                "categories": [],
                "shop_ids": None,
                "round": 1,
                "error": None,
                # 性别与服装匹配：透传到节点1 商品驱动分支
                # 节点1 按优先级确定 target_gender：system_model_gender > user_photo 分析
                # 主商品本身不参与性别过滤（用户已选定）
                "system_model_id": system_model_id,
                "system_model_image_url": system_model_image_url,
                "system_model_gender": system_model_gender,
                # 身体信息档案（真人照片模式必填，系统模特体验版可不填）
                "user_body_profile_id": user_body_profile_id,
                # 天气服务：前端 IP 定位获取用户城市，节点1 调 get_weather 用
                "user_city": user_city,
                "user_country": user_country,
            }

            # 超时控制：整个 LangGraph 工作流 ASYNC_TIMEOUT 秒
            # 全局并发槽位：限制同时运行的生成工作流数量
            async with _workflow_slot():
                final_state = await asyncio.wait_for(
                    OutfitGraphRunner.run(
                        task_id=task_id,
                        user_id=user_id,
                        style_tags=[],
                        scene_desc=None,
                        photo_session_key=photo_session_key,
                        initial_state=initial_state,
                    ),
                    timeout=ASYNC_TIMEOUT,
                )

            error = final_state.get("error")
            outfits = final_state.get("final_outfits") or []

            if error or not outfits:
                await self._on_failure(task_id, user_id, error or "未生成有效搭配",
                                        need_deduct, mode="product", stage="vton")
                self._record_workflow_metrics_product(start_time, "FAILED")
            else:
                await self._on_success(task_id, user_id, outfits, need_deduct,
                                       mode="product", stage="vton")
                # 保存 state 快照供多轮反馈读取（与风格驱动一致）
                await self._save_state(task_id, final_state)
                self._record_workflow_metrics_product(start_time, "SUCCESS")

        except WorkflowBusyError as e:
            logger.warning("[商品驱动] 工作流并发限流: taskId=%s, msg=%s", task_id, e)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "BUSY")
        except asyncio.TimeoutError:
            logger.error("[商品驱动] LangGraph 工作流超时: taskId=%s", task_id)
            await self._on_failure(task_id, user_id, "生成超时，请重试",
                                    need_deduct, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "TIMEOUT")
        except Exception as e:
            logger.error("[商品驱动] LangGraph 工作流异常: taskId=%s, error=%s",
                          task_id, e, exc_info=True)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "FAILED")

    def _record_workflow_metrics_product(self, start_time: float, status: str):
        """记录商品驱动模式 LangGraph 工作流耗时与结果"""
        duration = time.monotonic() - start_time
        record_agent_workflow(duration_seconds=duration, status=status)
        record_outfit_generate(status=status, mode="product", duration_seconds=duration)

    # ============================================================
    # 商品驱动模式多轮反馈（与风格驱动 feedback 对齐）
    # ============================================================
    async def feedback_product(
        self,
        task_id: str,
        user_id: int,
        feedback: str,
        outfit_index: int | None = None,
        item_index: int | None = None,
        dislike_colors: list[str] | None = None,
        dislike_item_ids: list[int] | None = None,
        retry_vton_item_ids: list[int] | None = None,
        note: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """商品驱动模式多轮反馈入口

        与风格驱动 feedback 的差异：
        - 主商品 isMain=True 不参与替换（用户已选定）
        - 不支持 wantStyleTags / adjust_style（商品驱动无 style_tags 概念）
        - action 限制为：accept / replace_single / replace / regenerate_all
        - LLM 解析 feedback 时将 adjust_style 等不支持 action 降级为 regenerate_all
        - 每轮扣 credits（与风格驱动一致）

        Returns:
            (taskId, errorMsg, errorCode)：
              - 成功：(taskId, None, None)
              - 任务不存在：(taskId, "原任务不存在或已过期", "NOT_FOUND")
              - 已采纳终态：(taskId, "当前搭配已采纳", "FINISHED")
              - 并发限流：(taskId, "正在处理上一条反馈", "CONCURRENT")
              - 轮次超限：(taskId, "已达到最大反馈轮次", "ROUND_LIMIT")
        """
        # 1. 读取历史 state
        prev_state = await self._load_state(task_id, expected_user_id=user_id)
        if prev_state is None:
            # DB 兜底：Redis state 过期，从 DB 搭配记录反向构造降级 state
            # 降级限制：丢失 query_vector / candidate_items_by_category / seen_item_ids 等，
            # 反馈只能走 regenerate_all，不支持 replace_single
            prev_state = await self._build_fallback_state_from_db(task_id, user_id, mode="product")
            if prev_state is None:
                return task_id, "原任务不存在或已过期，无法继续反馈", "NOT_FOUND"
            logger.info("[DB 兜底-商品驱动] Redis state 过期，从 DB 构造降级 state: taskId=%s", task_id)
        # 商品驱动模式的 state 快照应携带 mode="product"
        if prev_state.get("mode") != "product":
            logger.warning("[商品驱动-反馈] state 快照 mode 非 product: taskId=%s, mode=%s",
                            task_id, prev_state.get("mode"))
            return task_id, "任务类型不匹配，无法反馈", "NOT_FOUND"

        # 检查 finished 标记（accept 后不允许再次反馈）
        if prev_state.get("finished"):
            logger.info("[商品驱动] 任务已采纳完结，拒绝再次反馈: taskId=%s", task_id)
            return task_id, "当前搭配已采纳，无法继续反馈", "FINISHED"

        # 2. 检查轮次上限
        prev_round = prev_state.get("round", 1)
        max_rounds = settings.feedback_max_rounds
        if prev_round >= max_rounds:
            logger.info("[商品驱动] 反馈轮次超限: taskId=%s, round=%d, max=%d",
                         task_id, prev_round, max_rounds)
            return task_id, f"已达到最大反馈轮次（{max_rounds} 轮）", "ROUND_LIMIT"

        # 3. 分布式锁保证"读 state + 推进 round + 写 PROCESSING"原子性
        lock_key = f"lock:outfit:feedback:product:{task_id}"
        async with DistributedLock(self.redis, lock_key,
                                    wait_timeout=0, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("[商品驱动] 反馈并发限流：taskId=%s 锁被占用", task_id)
                return task_id, "正在处理上一条反馈，请稍候", "CONCURRENT"

            # 锁内双重检查
            prev_state = await self._load_state(task_id, expected_user_id=user_id)
            if prev_state is None:
                # DB 兜底（与锁外一致）
                prev_state = await self._build_fallback_state_from_db(
                    task_id, user_id, mode="product")
                if prev_state is None:
                    return task_id, "原任务不存在或已过期，无法继续反馈", "NOT_FOUND"
            if prev_state.get("finished"):
                return task_id, "当前搭配已采纳，无法继续反馈", "FINISHED"
            prev_round = prev_state.get("round", 1)
            if prev_round >= max_rounds:
                return task_id, f"已达到最大反馈轮次（{max_rounds} 轮）", "ROUND_LIMIT"

            new_round = prev_round + 1

            # 3. credits 预扣（每轮反馈扣 credits，与风格驱动反馈轮一致）
            # 复用 QUOTA_TYPE_VTON + CREDITS_VTON_PER_OUTFIT（5 credits/轮）
            java_client = await get_java_client()
            credits_result = await java_client.credits_deduct(
                user_id=user_id,
                quota_type=QUOTA_TYPE_VTON,
                task_id=task_id,
                credits=CREDITS_VTON_PER_OUTFIT,
            )
            if credits_result is None:
                logger.warning("[商品驱动] 反馈轮 credits 预扣失败（服务不可用）: taskId=%s, userId=%s",
                               task_id, user_id)
                return task_id, "配额服务不可用，请稍后重试", None
            if not credits_result.get("success"):
                msg = credits_result.get("msg", "AI 生成次数或余额不足")
                logger.warning("[商品驱动] 反馈轮 credits 预扣被拒绝: taskId=%s, userId=%s, msg=%s",
                               task_id, user_id, msg)
                return task_id, msg, None

            record_quota_check(quota_type=QUOTA_TYPE_VTON, result="ok")
            logger.info("[商品驱动] 反馈轮 credits 预扣成功: taskId=%s, userId=%s, round=%d, credits=%d, balance=%s",
                         task_id, user_id, new_round, CREDITS_VTON_PER_OUTFIT,
                         credits_result.get("balance"))

            # 锁内同步推进 state 的 round，防止并发请求读到旧 round 重复推进
            prev_state["round"] = new_round
            await self._save_state(task_id, prev_state)

            # 4. 写入 Redis 任务状态为 PROCESSING
            status = json.dumps({
                "status": "PROCESSING",
                "taskId": task_id,
                "userId": user_id,
                "taskType": "OUTFIT_PRODUCT",
                "round": new_round,
                "createdAt": datetime.now().isoformat(),
            }, ensure_ascii=False)
            await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", status, ex=TASK_STATUS_TTL)

        # 用户画像不写入任务快照，启动反馈工作流前从长期画像重新加载
        prev_state = await self._restore_feedback_runtime(prev_state, user_id)

        # 5. 启动异步反馈任务
        task = asyncio.create_task(self._async_feedback_product(
            task_id=task_id,
            user_id=user_id,
            prev_state=prev_state,
            feedback=feedback,
            outfit_index=outfit_index,
            item_index=item_index,
            dislike_colors=dislike_colors,
            dislike_item_ids=dislike_item_ids,
            retry_vton_item_ids=retry_vton_item_ids,
            note=note,
            new_round=new_round,
        ))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        logger.info("[商品驱动] 反馈任务已启动: taskId=%s, round=%d, feedback=%s",
                     task_id, new_round, feedback[:50] if feedback else None)
        return task_id, None, None

    async def _async_feedback_product(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        feedback: str,
        outfit_index: int | None,
        item_index: int | None,
        dislike_colors: list[str] | None,
        dislike_item_ids: list[int] | None,
        retry_vton_item_ids: list[int] | None,
        note: str | None,
        new_round: int,
    ):
        """商品驱动模式异步执行反馈轮

        与 _async_feedback 差异：
        - 不支持 ReAct（note 仅作为 feedback 补充，不触发 Tool calling）
        - action=adjust_style 降级为 regenerate_all
        - 无 want_style_tags 处理
        - WS 消息 type=OUTFIT_PRODUCT（与首轮一致，前端按此过滤）
        - _build_replace_single_state_product 保留主商品（isMain=True）
        """
        start_time = time.monotonic()
        prev_round = new_round - 1

        try:
            # ----- 1. LLM 解析反馈 -----
            try:
                llm_client = await get_llm_client()
                parsed = await llm_client.parse_feedback(feedback)
            except Exception as e:
                logger.error("[商品驱动] LLM 反馈解析异常: taskId=%s, error=%s", task_id, e)
                await self._on_failure(task_id, user_id, "反馈解析失败，请稍后重试",
                                        need_deduct=True, mode="product", stage="vton")
                self._record_workflow_metrics_product(start_time, "FAILED")
                return

            # ----- 2. 前端字段覆盖（优先级 > LLM 解析）-----
            if outfit_index is not None:
                parsed["outfit_index"] = outfit_index
                if parsed.get("action") != "accept":
                    parsed["action"] = "replace_single"
            if item_index is not None:
                parsed["item_index"] = item_index
            if dislike_colors is not None:
                parsed["dislike_colors"] = list(dislike_colors)
            if dislike_item_ids is not None:
                parsed["dislike_item_ids"] = list(dislike_item_ids)
            if retry_vton_item_ids is not None:
                parsed["retry_vton_item_ids"] = list(retry_vton_item_ids)

            action = parsed.get("action", "regenerate_all")
            # 商品驱动模式不支持 adjust_style（无 style_tags 概念），降级为 regenerate_all
            if action in ("adjust_style", "want_style"):
                logger.info("[商品驱动] action=%s 不支持，降级为 regenerate_all: taskId=%s",
                             action, task_id)
                action = "regenerate_all"
                parsed["action"] = action

            logger.info("[商品驱动] 反馈解析: taskId=%s, round=%d→%d, action=%s, "
                         "outfitIdx=%s, itemIdx=%s, dislikeColors=%s, dislikeItems=%s, "
                         "retryVtonItems=%s, feedback=%s",
                         task_id, prev_round, new_round, action,
                         parsed.get("outfit_index"), parsed.get("item_index"),
                         parsed.get("dislike_colors"), parsed.get("dislike_item_ids"),
                         parsed.get("retry_vton_item_ids"), feedback[:50])

            # ----- 3. action=accept：用户满意，不重新生成 -----
            if action == "accept":
                await self._ws_push(user_id, {
                    "taskId": task_id,
                    "type": "OUTFIT_PRODUCT",
                    "status": "ACCEPTED",
                    "msg": "已采纳当前搭配",
                })
                accept_status = json.dumps({
                    "status": "SUCCESS",
                    "userId": user_id,
                    "taskType": "OUTFIT_PRODUCT",
                    "round": new_round,
                    "accepted": True,
                    "finished": True,
                    "finishedAt": datetime.now().isoformat(),
                }, ensure_ascii=False)
                await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", accept_status, ex=TASK_STATUS_TTL)
                prev_state["finished"] = True
                prev_state["round"] = new_round
                await self._save_state(task_id, prev_state)
                self._record_workflow_metrics_product(start_time, "SUCCESS")
                return

            # ----- 4. 同会话累积 user_dislike_colors -----
            prev_dislike_colors: list[str] = list(prev_state.get("user_dislike_colors") or [])
            new_dislike_colors: list[str] = list(parsed.get("dislike_colors") or [])
            merged_dislike_colors = list(dict.fromkeys(prev_dislike_colors + new_dislike_colors))
            if merged_dislike_colors != prev_dislike_colors:
                logger.info("[商品驱动] user_dislike_colors 累积: taskId=%s, %s → %s",
                             task_id, prev_dislike_colors, merged_dislike_colors)

            # 提取 dislike_styles 和 preferred_price_range
            new_dislike_styles: list[str] = list(parsed.get("dislike_styles") or [])
            new_price_range = parsed.get("preferred_price_range") or None
            allow_long_term_memory = should_persist_preference(
                feedback,
                note,
                explicit_user_field=dislike_colors is not None,
            )

            # 异步持久化用户偏好（dislike_colors / dislike_styles / preferred_price_range）
            if allow_long_term_memory and (new_dislike_colors or new_dislike_styles or new_price_range):
                pref_task = asyncio.create_task(self._persist_user_preference(
                    user_id=user_id,
                    dislike_colors=new_dislike_colors or None,
                    dislike_styles=new_dislike_styles or None,
                    preferred_price_range=new_price_range,
                ))
                self._pending_tasks.add(pref_task)
                pref_task.add_done_callback(self._pending_tasks.discard)

            # ----- 5. 构造新一轮 initial_state -----
            target_category = parsed.get("target_category")
            categories = prev_state.get("category_constraints", ["上衣", "下装", "鞋"])

            # 累积历史搭配
            prev_outfits = prev_state.get("outfit_candidates", [])
            history = list(prev_state.get("history_outfits", []))
            if prev_outfits:
                history.append(prev_outfits)
                if len(history) > 3:
                    history = history[-3:]

            if action == "replace_single":
                initial_state, error_msg = self._build_replace_single_state_product(
                    task_id=task_id,
                    user_id=user_id,
                    prev_state=prev_state,
                    parsed=parsed,
                    feedback=feedback,
                    new_round=new_round,
                    history=history,
                    categories=categories,
                    merged_dislike_colors=merged_dislike_colors,
                )
                if error_msg:
                    await self._on_failure(task_id, user_id, error_msg,
                                            need_deduct=True, mode="product", stage="vton")
                    self._record_workflow_metrics_product(start_time, "FAILED")
                    return
            else:
                # action=regenerate_all 或 action=replace
                if action == "replace" and target_category:
                    keep_categories = [c for c in categories if c != target_category]
                else:
                    keep_categories = []

                initial_state = self._build_feedback_state_product(
                    task_id=task_id,
                    user_id=user_id,
                    prev_state=prev_state,
                    parsed=parsed,
                    feedback=feedback,
                    new_round=new_round,
                    history=history,
                    categories=categories,
                    keep_categories=keep_categories,
                    merged_dislike_colors=merged_dislike_colors,
                )

            # 反馈任务使用锁内推进后的 checkpoint 版本，避免异步结果覆盖后续反馈。
            initial_state["checkpoint_version"] = prev_state.get("checkpoint_version", 0)

            # ----- 6. 跑 LangGraph 工作流 -----
            # 全局并发槽位：限制同时运行的生成工作流数量
            async with _workflow_slot():
                final_state = await asyncio.wait_for(
                    OutfitGraphRunner.run(
                        task_id=task_id,
                        user_id=user_id,
                        style_tags=[],
                        scene_desc=None,
                        photo_session_key=initial_state.get("photo_session_key"),
                        initial_state=initial_state,
                    ),
                    timeout=ASYNC_TIMEOUT,
                )

            error = final_state.get("error")
            outfits = final_state.get("final_outfits") or []

            if error or not outfits:
                await self._on_failure(task_id, user_id, error or "未生成有效搭配",
                                        need_deduct=True, mode="product", stage="vton")
                self._record_workflow_metrics_product(start_time, "FAILED")
            else:
                await self._on_success(task_id, user_id, outfits,
                                        need_deduct=True, mode="product", stage="vton")
                await self._save_state(task_id, final_state)
                self._record_workflow_metrics_product(start_time, "SUCCESS")

        except WorkflowBusyError as e:
            logger.warning("[商品驱动] 反馈轮工作流并发限流: taskId=%s, msg=%s", task_id, e)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "BUSY")
        except asyncio.TimeoutError:
            logger.error("[商品驱动] 反馈轮工作流超时: taskId=%s", task_id)
            await self._on_failure(task_id, user_id, "生成超时，请重试",
                                    need_deduct=True, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "TIMEOUT")
        except Exception as e:
            logger.error("[商品驱动] 反馈轮工作流异常: taskId=%s, error=%s",
                          task_id, e, exc_info=True)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, mode="product", stage="vton")
            self._record_workflow_metrics_product(start_time, "FAILED")

    def _build_feedback_state_product(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        parsed: dict,
        feedback: str,
        new_round: int,
        history: list,
        categories: list[str],
        keep_categories: list[str],
        merged_dislike_colors: list[str],
    ) -> AgentState:
        """构造商品驱动模式反馈轮 initial_state（regenerate_all / replace）

        与风格驱动差异：
        - 携带 mode="product" + main_item_ids，节点1 走 _intent_understanding_product 反馈轮分支
        - 复用 prev_state 中的 _main_item_info（节点1 反馈轮不再拉商品详情）
        - 不传 style_tags / scene_desc / color 等风格驱动字段
        """
        return {
            "task_id": task_id,
            "user_id": user_id,
            "mode": "product",
            "main_item_ids": prev_state.get("main_item_ids", []),
            "photo_session_key": prev_state.get("photo_session_key"),
            "style_tags": [],
            "scene_desc": None,
            "color": None,
            "shop_ids": prev_state.get("shop_ids"),
            "season": None,
            "categories": [],
            "category_constraints": categories,
            "round": new_round,
            "feedback": feedback,
            "feedback_parsed": parsed,
            "keep_categories": keep_categories,
            "history_outfits": history,
            "seen_item_ids": prev_state.get("seen_item_ids", set()),
            "user_dislike_colors": merged_dislike_colors,
            "dislike_item_ids": parsed.get("dislike_item_ids") or [],
            "retry_vton_item_ids": parsed.get("retry_vton_item_ids") or [],
            "query_vector": prev_state.get("query_vector"),
            "query_text": prev_state.get("query_text"),
            "feedback_note": None,
            # 复用首轮的 _main_item_info（节点1 反馈轮不再拉商品详情）
            "_main_item_info": prev_state.get("_main_item_info"),
            # 性别与服装匹配：反馈轮必须透传性别字段
            # 否则节点1 无法确定 target_gender，Qdrant 不过滤性别，可能返回跨性别商品
            "system_model_id": prev_state.get("system_model_id"),
            "system_model_image_url": prev_state.get("system_model_image_url"),
            "system_model_gender": prev_state.get("system_model_gender"),
            "target_gender": prev_state.get("target_gender"),
            "gender_source": prev_state.get("gender_source"),
            "user_body_profile_id": prev_state.get("user_body_profile_id"),
            "error": None,
        }

    def _build_replace_single_state_product(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        parsed: dict,
        feedback: str,
        new_round: int,
        history: list,
        categories: list[str],
        merged_dislike_colors: list[str],
    ) -> tuple[AgentState, str | None]:
        """构造商品驱动模式 replace_single（点哪换哪）的 initial_state

        与风格驱动差异：
        - 主商品 isMain=True 不参与替换（即使被点到也跳过）
        - 保留品类复用 prev_candidates 的保留单品

        Returns:
            (initial_state, error_msg)：error_msg 非空表示索引越界
        """
        target_category = parsed.get("target_category")
        prev_outfits = prev_state.get("outfit_candidates", [])
        outfit_idx = parsed.get("outfit_index")
        item_idx = parsed.get("item_index")

        if outfit_idx is None or outfit_idx < 0 or outfit_idx >= len(prev_outfits):
            return None, "outfitIndex 越界或不合法"
        outfit = prev_outfits[outfit_idx]
        outfit_items = outfit.get("items", [])

        # 商品驱动模式：若 item_idx 指向主商品（isMain=True），拒绝替换
        if item_idx is not None and 0 <= item_idx < len(outfit_items):
            if outfit_items[item_idx].get("isMain"):
                return None, "主商品不可替换，请选择互补商品"

        # 若未指定 item_idx，但指定了 target_category，按品类定位
        if item_idx is None and target_category:
            for i, it in enumerate(outfit_items):
                if it.get("category") == target_category and not it.get("isMain"):
                    item_idx = i
                    break

        if item_idx is None or item_idx < 0 or item_idx >= len(outfit_items):
            return None, "itemIndex 越界或不合法"

        target_item = outfit_items[item_idx]
        target_cat = target_item.get("category")
        if not target_cat:
            return None, "待替换单品缺少品类字段"

        # 保留除待替换之外的其他单品（主商品 + 其他互补商品）
        keep_items = [it for i, it in enumerate(outfit_items) if i != item_idx]
        keep_categories = [it.get("category") for it in keep_items if it.get("category")]

        # 构造 prev_candidates：保留品类只有 1 件"保留单品"（_kept_from_prev=True）
        prev_candidates: dict[str, list[dict]] = {}
        for it in keep_items:
            cat = it.get("category")
            if cat:
                prev_candidates[cat] = [{
                    "item_id": it.get("itemId") or it.get("item_id"),
                    "category": cat,
                    "price": it.get("price"),
                    "color": it.get("color"),
                    "shop_id": it.get("shopId"),
                    "cross_shop": it.get("crossShop", False),
                    "score": it.get("score", 1.0),
                    "_kept_from_prev": True,
                }]

        # 从 seen_item_ids 中移除保留单品（不应被去重过滤掉）
        prev_seen = set(prev_state.get("seen_item_ids", set()))
        for it in keep_items:
            iid = it.get("itemId") or it.get("item_id")
            if iid in prev_seen:
                prev_seen.discard(iid)

        logger.info("[商品驱动-点哪换哪] taskId=%s, outfitIdx=%s, itemIdx=%s, "
                     "targetCat=%s, keep=%s",
                     task_id, outfit_idx, item_idx, target_cat, keep_categories)

        initial_state: AgentState = {
            "task_id": task_id,
            "user_id": user_id,
            "mode": "product",
            "main_item_ids": prev_state.get("main_item_ids", []),
            "photo_session_key": prev_state.get("photo_session_key"),
            "style_tags": [],
            "scene_desc": None,
            "color": None,
            "shop_ids": prev_state.get("shop_ids"),
            "season": None,
            "categories": [],
            "category_constraints": categories,
            "round": new_round,
            "feedback": feedback,
            "feedback_parsed": parsed,
            "keep_categories": keep_categories,
            "history_outfits": history,
            "seen_item_ids": prev_seen,
            "candidate_items_by_category": prev_candidates,
            "user_dislike_colors": merged_dislike_colors,
            "dislike_item_ids": parsed.get("dislike_item_ids") or [],
            "retry_vton_item_ids": parsed.get("retry_vton_item_ids") or [],
            "query_vector": prev_state.get("query_vector"),
            "query_text": prev_state.get("query_text"),
            "feedback_note": None,
            "_main_item_info": prev_state.get("_main_item_info"),
            # 性别与服装匹配：点哪换哪反馈轮必须透传性别字段
            "system_model_id": prev_state.get("system_model_id"),
            "system_model_image_url": prev_state.get("system_model_image_url"),
            "system_model_gender": prev_state.get("system_model_gender"),
            "target_gender": prev_state.get("target_gender"),
            "gender_source": prev_state.get("gender_source"),
            "user_body_profile_id": prev_state.get("user_body_profile_id"),
            "error": None,
        }
        return initial_state, None

    # ============================================================
    # 风格驱动模式入口（原 recommend）
    # ============================================================
    async def recommend(
        self,
        user_id: int,
        style_tags: list[str],
        scene_desc: str | None,
        photo_session_key: str | None,
        color: list[str] | None = None,
        categories: list[str] | None = None,
        shop_ids: list[int] | None = None,
        note: str | None = None,
        wardrobe_item_ids: list[int] | None = None,
        cart_item_ids: list[int] | None = None,
        order_item_ids: list[int] | None = None,
        search_item_ids: list[int] | None = None,
        user_body_profile_id: int | None = None,
        system_model_id: int | None = None,
        system_model_image_url: str | None = None,
        system_model_gender: str | None = None,
        user_city: str | None = None,
        user_country: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """同步入口：换一套计数判断 → 配额预扣（首次或再次换一套时）→ 写任务状态 → 启动异步工作流

        双模式入口（④ 风格驱动 / ⑥ 用户选定）：
        - ④ 风格驱动：style_tags/scene_desc/color + shop_ids（全平台或指定店铺）
          → LLM 去 Qdrant 检索互补商品 → 组合决策 → VTON
          → 阶段一 2 credits（OUTFIT_RECOMMEND）
        - ⑥ 用户选定：wardrobe_item_ids/cart_item_ids/order_item_ids/search_item_ids 非空
          → 用户已选定全部单品，直接 VTON（跳过 Qdrant 检索 + 组合决策）
          → 单阶段 5 credits（OUTFIT_VTON，1 套 VTON）

        "换一套"配额规则：
        - 每次生成都需要扣费（不支持免费重试）
        - 会话计数仅用于并发控制和统计，不影响扣费逻辑

        结构化输入：
        - color/categories/shop_id/note 透传到 LangGraph state
        - 节点1 解析 note 合并到结构化字段，节点2 按 shop_id/color 过滤 + 缺货跨店降级
        - styleTags 改可选，与 color/sceneDesc/note 任一非空即可

        衣橱功能 + 搜索单品：
        - wardrobe_item_ids：user_wardrobe.id 列表（衣橱条目 ID，非商品 ID），
          _async_recommend 调 WardrobeClient 解析出 itemType=1 条目对应的 itemId
        - cart_item_ids/order_item_ids/search_item_ids：直接就是商品 ID
        - 四类在 _async_recommend 中合并去重为 state.wardrobe_item_ids（统一为商品 ID）
        - 节点2 调 JavaClient.get_items_by_ids 拉商品详情注入 candidate_items_by_category
        - 节点3 强制保留这些"用户选定"商品（不参与笛卡尔积）

        前端约束：
        - 同品类只能选 1 件（上衣/下装/全身套装/鞋/帽子/包/配饰互斥）
        - 全身套装与上衣/下装互斥（全身套装已覆盖上下身）
        - 全局上限 5 件（含四类来源合计）

        Returns:
            (taskId, errorMsg, errorCode)：
              - 成功：(taskId, None, None)
              - 并发限流：(taskId, "上一条搭配还在生成中，请稍候", "CONCURRENT")
              - credits 不足：(taskId, "AI 生成次数或余额不足", None)
              - 服务异常：(taskId, "配额服务不可用", None)
            errorCode 供 API 层映射不同 HTTP 状态码：
              - CONCURRENT → 429（并发限流）
              - None → 403（credits 不足 / 配额服务不可用）
        """
        task_id = str(uuid.uuid4())

        # 用分布式锁包住"INCR + credits_deduct"临界区，
        # 避免同一用户并发请求导致"换一套"计数与配额扣费错位。
        # 对齐 Java 侧 Redisson RLock 模式（参考 SeckillOrderListener）：
        #   - waitTime=3s：给前一个请求完成配额操作的时间（短等待避免直接拒绝）
        #   - leaseTime=30s：兜底防死锁
        #   - key 命名：lock:outfit:recommend:user:{userId}（按用户维度串行化）
        recommend_lock_key = f"lock:outfit:recommend:user:{user_id}"
        async with DistributedLock(self.redis, recommend_lock_key,
                                    wait_timeout=3, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("recommend 并发限流：userId=%s 锁被占用，拒绝本次请求", user_id)
                return task_id, "上一条搭配还在生成中，请稍候", "CONCURRENT"

            # 0."换一套"会话计数判断（原子 INCR 并获取旧值，shared.outfit_common 实现）
            old_count = await incr_and_get_old_count(self.redis, user_id)
            need_deduct = should_deduct(old_count)
            logger.info("换一套计数: userId=%s, oldCount=%s, needDeduct=%s, taskId=%s",
                         user_id, old_count, need_deduct, task_id)

            # 1. credits 预扣
            # ⑥ 用户选定模式：OUTFIT_VTON（5 credits，1 套 VTON 直接生成）
            # ④ 风格驱动模式：OUTFIT_DIRECT（17 credits，一阶段直出 推荐+VTON Top3）
            is_user_picked = bool(wardrobe_item_ids or cart_item_ids or order_item_ids or search_item_ids)
            if is_user_picked:
                quota_type_deduct = QUOTA_TYPE_VTON
                credits_amount = CREDITS_VTON_PER_OUTFIT
            else:
                quota_type_deduct = QUOTA_TYPE_DIRECT
                credits_amount = CREDITS_DIRECT_TOTAL

            if need_deduct:
                java_client = await get_java_client()
                credits_result = await java_client.credits_deduct(
                    user_id=user_id,
                    quota_type=quota_type_deduct,
                    task_id=task_id,
                    credits=credits_amount,
                )
                if credits_result is None:
                    # 扣费失败，回滚计数
                    await decr_session_count(self.redis, user_id)
                    record_quota_check(quota_type=quota_type_deduct, result="failed")
                    return task_id, "配额服务不可用，请稍后重试", None
                if not credits_result.get("success"):
                    await decr_session_count(self.redis, user_id)
                    msg = credits_result.get("msg", "AI 生成次数或余额不足")
                    logger.warning("credits 预扣被拒绝: userId=%s, taskId=%s, msg=%s",
                                    user_id, task_id, msg)
                    record_quota_check(quota_type=quota_type_deduct, result="insufficient")
                    return task_id, msg, None

                record_quota_check(quota_type=quota_type_deduct, result="ok")
                logger.info("credits 预扣成功: userId=%s, taskId=%s, type=%s, credits=%d, balance=%s",
                             user_id, task_id, quota_type_deduct, credits_amount,
                             credits_result.get("balance"))
            else:
                # need_deduct 恒为 True（不支持免费重试），此分支不会走到
                pass

        # 2. 写入任务状态到 Redis
        # 对外 stage 统一为 "vton"：
        # - ⑥ 用户选定模式：单阶段 VTON
        # - ④ 风格驱动模式：一阶段直出（推荐+VTON 合并），前端直接展示 VTON 结果
        # taskType：⑥=OUTFIT_VTON，④=OUTFIT_DIRECT
        # 注意：LangGraph 内部 state.stage 仍用 "user_picked"/"recommend" 用于节点路由，
        #       对外（Redis 任务状态 / WS 推送 / 结果查询）统一用 "vton"
        stage = "vton"
        task_type = "OUTFIT_VTON" if is_user_picked else "OUTFIT_DIRECT"
        status = json.dumps({
            "status": "PROCESSING",
            "taskId": task_id,
            "userId": user_id,
            "taskType": task_type,
            "stage": stage,
            "createdAt": datetime.now().isoformat(),
        }, ensure_ascii=False)
        await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", status, ex=TASK_STATUS_TTL)

        # 3. 启动异步 LangGraph 工作流（不阻塞 HTTP 响应）
        # 保存引用防止被 GC 回收，任务完成后从集合移除
        # need_deduct 透传到异步链路（当前恒为 True，保留参数兼容）
        # 衣橱三类 ID 原样透传到 _async_recommend，在那里解析合并为商品 ID 列表
        task = asyncio.create_task(self._async_recommend(
            task_id=task_id,
            user_id=user_id,
            style_tags=style_tags,
            scene_desc=scene_desc,
            photo_session_key=photo_session_key,
            need_deduct=need_deduct,
            color=color,
            categories=categories,
            shop_ids=shop_ids,
            note=note,
            wardrobe_entry_ids=wardrobe_item_ids,
            cart_item_ids=cart_item_ids,
            order_item_ids=order_item_ids,
            search_item_ids=search_item_ids,
            is_user_picked=is_user_picked,
            user_body_profile_id=user_body_profile_id,
            system_model_id=system_model_id,
            system_model_image_url=system_model_image_url,
            system_model_gender=system_model_gender,
            user_city=user_city,
            user_country=user_country,
        ))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        logger.info("任务已创建: taskId=%s, userId=%s, stage=%s, styleTags=%s, color=%s, "
                     "shopIds=%s, categories=%s, note=%s, needDeduct=%s, "
                     "wardrobeEntryIds=%s, cartItemIds=%s, orderItemIds=%s, searchItemIds=%s, "
                     "systemModelId=%s, systemModelGender=%s, bodyProfileId=%s",
                     task_id, user_id, stage, style_tags, color, shop_ids, categories, note, need_deduct,
                     wardrobe_item_ids, cart_item_ids, order_item_ids, search_item_ids,
                     system_model_id, system_model_gender, user_body_profile_id)
        return task_id, None, None

    async def _async_recommend(
        self,
        task_id: str,
        user_id: int,
        style_tags: list[str],
        scene_desc: str | None,
        photo_session_key: str | None,
        need_deduct: bool = True,
        color: list[str] | None = None,
        categories: list[str] | None = None,
        shop_ids: list[int] | None = None,
        note: str | None = None,
        wardrobe_entry_ids: list[int] | None = None,
        cart_item_ids: list[int] | None = None,
        order_item_ids: list[int] | None = None,
        search_item_ids: list[int] | None = None,
        is_user_picked: bool = False,
        user_body_profile_id: int | None = None,
        system_model_id: int | None = None,
        system_model_image_url: str | None = None,
        system_model_gender: str | None = None,
        user_city: str | None = None,
        user_country: str | None = None,
    ):
        """异步执行 LangGraph 工作流

        超时控制 30s；成功/失败均更新 Redis + WS 推送 + MQ 通知。
        结构化输入字段透传到 OutfitGraphRunner.run 的 initial_state。
        """
        start_time = time.monotonic()
        # ⑥ 用户选定模式：生成中占位记录的 id（失败/超时时清理，避免残留空记录）
        placeholder_record_id: int | None = None
        try:
            # ----- 读取用户偏好（跨会话持久化）-----
            # 失败不阻塞主流程，仅记日志
            user_pref_dislike_colors: list[str] = []
            user_pref_dislike_styles: list[str] = []
            user_pref_like_styles: list[str] = []
            user_pref_budget_max: float | None = None
            try:
                reader = await get_user_preference_reader()
                pref = await asyncio.to_thread(reader.get_preference, user_id)
                if pref:
                    user_pref_dislike_colors = list(pref.get("dislike_colors") or [])
                    user_pref_dislike_styles = list(pref.get("dislike_styles") or [])
                    user_pref_like_styles = list(pref.get("like_styles") or [])
                    price_range = pref.get("preferred_price_range")
                    if (isinstance(price_range, list) and len(price_range) == 2
                            and price_range[1] > 0):
                        user_pref_budget_max = float(price_range[1])
                    logger.info("已加载用户偏好: userId=%s, dislikeColors=%s, dislikeStyles=%s, likeStyles=%s, budgetMax=%s",
                                 user_id, user_pref_dislike_colors, user_pref_dislike_styles, user_pref_like_styles, user_pref_budget_max)
            except Exception as e:
                logger.warning("读取用户偏好失败（不影响主流程）: %s", e)

            # 合并用户偏好到首轮 state：
            # - like_styles 合并到 style_tags（增强召回）
            # - dislike_colors 注入 user_dislike_colors（节点2 must_not 过滤）
            # - dislike_styles 注入 user_dislike_styles（节点3 LLM 决策参考，避免推荐不喜欢的风格）
            # - preferred_price_range.max → budget_max（节点3 价格过滤）
            merged_style_tags = list(dict.fromkeys(list(style_tags) + user_pref_like_styles))
            merged_budget_max = user_pref_budget_max

            # ----- 个性化推荐画像 -----
            # 加载用户画像（懒加载 + Redis 缓存 24h），合并 top_styles 增强召回，
            # 透传 user_profile 到 state 供节点1 query_vector 融合 + 节点3 跨会话去重。
            # 失败不阻塞主流程，画像为空时按原逻辑执行。
            user_profile: dict = {}
            try:
                from app.services.profile_service import get_profile_service
                profile_service = await get_profile_service()
                user_profile = await profile_service.get_or_load_profile(user_id)
                # 仅当画像置信度 > 0 时才合并 top_styles（避免空画像稀释用户意图）
                if user_profile.get("profile_confidence", 0) > 0:
                    profile_top_styles = user_profile.get("top_styles") or []
                    if profile_top_styles:
                        # 合并画像 top_styles（去重保序，最多取 Top2 避免稀释用户当前意图）
                        merged_style_tags = list(dict.fromkeys(
                            merged_style_tags + profile_top_styles[:2]
                        ))
                    # 画像 price_distribution.median 作为 budget_max 兜底
                    # （用户未设显式偏好且画像有价格数据时）
                    if merged_budget_max is None:
                        price_dist = user_profile.get("price_distribution") or {}
                        median_price = price_dist.get("median")
                        if median_price and median_price > 0:
                            merged_budget_max = float(median_price)
                logger.info(
                    "已加载用户画像: userId=%s, confidence=%s, topStyles=%s, topColors=%s, mergedStyleTags=%s",
                    user_id, user_profile.get("profile_confidence"),
                    user_profile.get("top_styles"), user_profile.get("top_colors"),
                    merged_style_tags,
                )
            except Exception as e:
                logger.warning("加载用户画像失败（不影响主流程）: %s", e)

            # ----- 衣橱功能：解析三类 ID → 合并为商品 ID 列表 -----
            # wardrobe_entry_ids 是 user_wardrobe.id（非商品 ID），需调 WardrobeClient 解析：
            #   - itemType=1（商品条目）→ 取 itemId 加入合并池
            #   - itemType=2/3（用户自定义图片/自拍）→ 方案B：CLIP 编码 + Qdrant 相似检索
            #     用 Jina CLIP v2 编码图片 URL，在 Qdrant item_style collection 检索相似商品
            #     向量缓存在 Redis（7 天 TTL），避免同一图片反复调 Jina API
            # cart_item_ids / order_item_ids 已是商品 ID，直接合并
            merged_wardrobe_item_ids: list[int] = []
            # 单品来源映射（item_id → wardrobe/cart/order/search），透传给节点1.5 打 source 标签
            item_sources: dict[int, str] = {}
            seen_ids: set[int] = set()

            if wardrobe_entry_ids:
                try:
                    java_client = await get_java_client()
                    wardrobe_entries = await java_client.get_wardrobe_items_by_ids(
                        list(wardrobe_entry_ids)
                    )
                    custom_image_entries = []
                    for entry in wardrobe_entries:
                        entry_type = entry.get("itemType")
                        if entry_type == 1:
                            # 商品条目：直接取 itemId
                            item_id = entry.get("itemId")
                            if item_id is None:
                                continue
                            try:
                                item_id_int = int(item_id)
                            except (TypeError, ValueError):
                                continue
                            if item_id_int in seen_ids:
                                continue
                            seen_ids.add(item_id_int)
                            merged_wardrobe_item_ids.append(item_id_int)
                            item_sources[item_id_int] = "wardrobe"
                        elif entry_type in (2, 3):
                            # 方案B：用户自定义图片/自拍 → CLIP 编码 + Qdrant 相似检索
                            photo_url = entry.get("photoUrl")
                            if photo_url:
                                custom_image_entries.append(entry)
                            else:
                                logger.info("[衣橱] 自定义图片无 photoUrl，跳过: wardrobeId=%s",
                                             entry.get("id"))
                        else:
                            logger.info("[衣橱] 跳过不支持类型: wardrobeId=%s, itemType=%s",
                                         entry.get("id"), entry_type)

                    # 批量处理自定义图片 → CLIP 编码 → Qdrant 相似商品召回
                    if custom_image_entries:
                        try:
                            custom_item_ids = await self._resolve_custom_images_to_items(
                                custom_image_entries, seen_ids
                            )
                            merged_wardrobe_item_ids.extend(custom_item_ids)
                            for cid in custom_item_ids:
                                item_sources[cid] = "wardrobe"
                        except Exception as e:
                            logger.warning("[衣橱] 自定义图片召回失败（不阻塞主流程）: %s", e)

                    logger.info("[衣橱] 解析 wardrobe 条目 %d 个 → 商品 ID %d 个（含自定义图片召回）: taskId=%s",
                                 len(wardrobe_entry_ids), len(merged_wardrobe_item_ids), task_id)
                except Exception as e:
                    logger.warning("[衣橱] 解析 wardrobe 条目失败（不阻塞主流程）: %s", e)

            # 合并 cart_item_ids / order_item_ids / search_item_ids（去重保序，记录来源）
            # search_item_ids：与 cart/order 一样直接是商品 ID，无需解析
            for src, src_name in (
                (cart_item_ids, "cart"),
                (order_item_ids, "order"),
                (search_item_ids, "search"),
            ):
                if not src:
                    continue
                for iid in src:
                    if iid is None:
                        continue
                    try:
                        iid_int = int(iid)
                    except (TypeError, ValueError):
                        continue
                    if iid_int in seen_ids:
                        continue
                    seen_ids.add(iid_int)
                    merged_wardrobe_item_ids.append(iid_int)
                    item_sources[iid_int] = src_name

            # 用户选定单品的中文品类列表（品类互斥校验分支填充；超时动态估算同样用到，先初始化兜底）
            picked_categories: list[str] = []

            # 品类互斥校验（衣橱/购物车/订单/搜索合并后）
            # 拉商品详情 → 提取 category → 校验全身套装与上衣/下装互斥 + 全局上限 5 件
            # 校验失败：记录 error，后续 _async_recommend 退出前走 _on_failure 退还 credits
            if merged_wardrobe_item_ids and is_user_picked:
                category_conflict_err: str | None = None
                try:
                    java_client = await get_java_client()
                    picked_items = await java_client.get_items_by_ids(
                        list(merged_wardrobe_item_ids)
                    )
                    picked_categories = []
                    for it in picked_items:
                        if not it or it.get("id") is None:
                            continue
                        cat = to_cn(it.get("category")) or ""
                        if cat:
                            picked_categories.append(cat)
                    # 合并用户显式指定的 categories（若同时指定）
                    all_categories = list(categories or []) + picked_categories
                    try:
                        validate_category_combination(all_categories)
                    except CategoryConflictError as e:
                        category_conflict_err = e.details
                        logger.warning(
                            "[衣橱品类校验] 失败: taskId=%s, userId=%s, "
                            "pickedCategories=%s, conflict=%s",
                            task_id, user_id, picked_categories, e.details,
                        )
                except Exception as e:
                    # 拉商品详情失败不阻塞主流程（后续节点1.5/2 会再拉一次）
                    logger.warning(
                        "[衣橱品类校验] 拉商品详情失败（跳过校验）: taskId=%s, error=%s",
                        task_id, e,
                    )

                if category_conflict_err:
                    await self._on_failure(
                        task_id, user_id, category_conflict_err,
                        need_deduct, stage="vton",
                    )
                    self._record_workflow_metrics(start_time, "FAILED")
                    return

            # 构造首轮 initial_state（含结构化输入字段 + 用户偏好）
            # O3 优化：EpisodicMemory - 读取用户最近搭配事件，作为"上次推荐回顾"
            # 传到 state 供节点3 LLM prompt 使用，提升复购率
            current_month = datetime.now().month
            current_season = (
                "spring" if current_month in (3, 4, 5)
                else "summer" if current_month in (6, 7, 8)
                else "autumn" if current_month in (9, 10, 11)
                else "winter"
            )
            recent_episodes = await self._load_recent_episodes(
                user_id,
                style_tags=merged_style_tags,
                scene_desc=scene_desc,
                season=current_season,
                categories=categories or [],
            )

            # O4 优化：加载跨会话 seen_item_ids（30 天衰减）
            # 业务价值：避免用户下次回来又看到上次推荐过的商品；30 天前的自动过期
            cross_session_seen = await self._load_cross_session_seen_items(user_id)

            initial_state: AgentState = {
                "task_id": task_id,
                "user_id": user_id,
                # ⑥ 用户选定模式：stage="user_picked"，跳过 Qdrant 检索 + 组合决策，直接 VTON
                # ④ 风格驱动模式：stage="recommend"，阶段一候选推荐（跳过 VTON）
                "stage": "user_picked" if is_user_picked else "recommend",
                "style_tags": merged_style_tags,
                "scene_desc": scene_desc,
                "photo_session_key": photo_session_key,
                "color": color,
                "color_is_explicit": bool(color),
                "categories": categories or [],
                "shop_ids": shop_ids,
                "note": note,
                "budget_max": merged_budget_max,
                "round": 1,
                "error": None,
                # 用户偏好字段
                "user_dislike_colors": user_pref_dislike_colors,
                "user_dislike_styles": user_pref_dislike_styles,  # 不喜欢的风格，节点3 LLM 决策参考
                "dislike_item_ids": [],
                "retry_vton_item_ids": [],
                "want_style_tags": [],
                # 衣橱功能：用户选定商品 ID（衣橱解析后 + 购物车 + 订单合并）
                # ⑥ 用户选定模式：wardrobe_item_ids 非空，build_wardrobe_outfit 节点直接构建搭配
                # ④ 风格驱动模式：wardrobe_item_ids 可空，节点2 正常 Qdrant 检索
                "wardrobe_item_ids": merged_wardrobe_item_ids,
                # 单品来源映射（item_id → wardrobe/cart/order/search），节点1.5 打 source 标签用
                "wardrobe_item_sources": item_sources,
                # O3 优化：EpisodicMemory - 历史搭配事件（跨会话，节点3 LLM 决策参考）
                "recent_episodes": recent_episodes,
                # O4 优化：跨会话 seen_item_ids（30 天衰减，避免重复推荐）
                "seen_item_ids": cross_session_seen,
                # 性别与服装匹配：透传到节点1 解析 target_gender
                # 节点1 按优先级确定 target_gender：system_model_gender > user_photo 分析 > user_body_profile.gender
                "user_body_profile_id": user_body_profile_id,
                "system_model_id": system_model_id,
                "system_model_image_url": system_model_image_url,
                "system_model_gender": system_model_gender,
                # 天气服务：前端 IP 定位获取用户城市
                # 节点1 调 get_weather(city=user_city) 获取实时天气 + 推导季节
                # 留空时 get_weather 内部用默认城市"北京"兜底
                "user_city": user_city,
                "user_country": user_country,
                # 个性化推荐画像：
                # - 节点1 用 style_vector 融合 query_vector（提升召回相关性）
                # - 节点3 用 top_colors / dislike_colors 跨会话去重（避免重复推荐）
                # - profile_confidence=0 时节点1/3 自动降级为原逻辑
                "user_profile": user_profile,
            }

            # 超时控制：整个 LangGraph 工作流
            # ⑥ 用户选定模式：工作流内含 VTON 生成（耗时大头，单件最坏 180s），
            #    按选定单品品类数动态估算超时（estimate_vton_timeout：0件≈120s / 1件≈162s / 2件≈270s / 3件≈378s，上限 600s）
            # ④ 风格驱动模式：阶段一候选推荐（不含 VTON），用固定 ASYNC_TIMEOUT
            if is_user_picked:
                vton_category_count = count_vton_categories(picked_categories)
                workflow_timeout = estimate_vton_timeout(vton_category_count)
                logger.info(
                    "[用户选定] 动态超时: taskId=%s, vtonCategories=%d, timeout=%ds",
                    task_id, vton_category_count, workflow_timeout,
                )
            else:
                workflow_timeout = ASYNC_TIMEOUT

            # ⑥ 用户选定模式：任务启动即写占位记录（accepted=0+pending，结果为空），
            # 使"生成中"的任务能出现在搭配历史页，点「查看进度」进入结果页看进度；
            # 成功后 _auto_save_records 按 task_id+outfit_index upsert 更新为真实结果
            if is_user_picked:
                placeholder_record_id = await self._save_pending_placeholder(
                    task_id, user_id, initial_state,
                )

            # 全局并发槽位：限制同时运行的生成工作流数量（与任务自身超时独立）
            async with _workflow_slot():
                final_state = await asyncio.wait_for(
                    OutfitGraphRunner.run(
                        task_id=task_id,
                        user_id=user_id,
                        style_tags=style_tags,
                        scene_desc=scene_desc,
                        photo_session_key=photo_session_key,
                        initial_state=initial_state,
                    ),
                    timeout=workflow_timeout,
                )

            # 判断结果：有 error 字段或 final_outfits 为空 → 失败
            error = final_state.get("error")
            outfits = final_state.get("final_outfits") or []

            # 对外 stage 统一为 "vton"（前端直接展示 VTON 结果）
            success_stage = "vton"

            if error or not outfits:
                await self._on_failure(task_id, user_id, error or "未生成有效搭配",
                                        need_deduct, stage=success_stage)
                await self._cleanup_placeholder_record(placeholder_record_id, user_id, task_id)
                self._record_workflow_metrics(start_time, "FAILED")
                return

            if is_user_picked:
                # ⑥ 用户选定模式：候选即 VTON 结果（LangGraph 内部已跑完 VTON），直接成功
                await self._on_success(task_id, user_id, outfits, need_deduct,
                                        stage=success_stage)
                # 自动入库（accepted=0+pending，未采纳）：生成结果后即使用户不点
                # 满意/不满意直接退出，也能在搭配历史"待采纳"中查看（与风格驱动一阶段直出一致）
                await self._auto_save_records(
                    task_id=task_id,
                    user_id=user_id,
                    vton_state=final_state,
                    vton_outfits=outfits,
                    photo_session_key=photo_session_key,
                    credits_consumed=CREDITS_VTON_PER_OUTFIT * len(outfits),
                )
                self._record_workflow_metrics(start_time, "SUCCESS")
                return

            # ④ 风格驱动模式：一阶段直出，对 Top3 全部跑 VTON
            # 构造 vton_only initial_state（selected_outfit_indexes = 全部索引）
            # 关键：透传 system_model_* 字段和节点1 已下载的 user_photo，
            # 避免 vton_only 阶段（不跑节点1）因 user_photo=None 走随机/默认女模特兜底
            vton_initial_state: AgentState = {
                "task_id": task_id,
                "user_id": user_id,
                "stage": "vton",
                "parent_task_id": task_id,
                "selected_outfit_indexes": list(range(len(outfits))),
                "outfit_candidates": outfits,
                "photo_session_key": photo_session_key,
                "style_tags": final_state.get("style_tags") or [],
                "scene_desc": final_state.get("scene_desc"),
                "color": final_state.get("color"),
                "season": final_state.get("season"),
                "use_default_model": final_state.get("use_default_model", False),
                "user_visual_profile": final_state.get("user_visual_profile"),
                "vton_credits_per_outfit": CREDITS_VTON_PER_OUTFIT,
                "round": 1,
                "error": None,
                "partial_failures": [],
                # 系统模特字段透传（vton_only 不跑节点1，必须显式传递）
                "system_model_id": final_state.get("system_model_id"),
                "system_model_image_url": final_state.get("system_model_image_url"),
                "system_model_gender": final_state.get("system_model_gender"),
                "target_gender": final_state.get("target_gender"),
                "gender_source": final_state.get("gender_source"),
                # user_photo 透传：节点1 已下载的系统模特图 bytes，
                # 直接复用避免 vton_only 重复下载
                "user_photo": final_state.get("user_photo"),
            }

            # 动态超时：根据品类件数估算（1件≈150s, 2件≈225s, 3件≈315s, 5件≈600s）
            # 一阶段直出对 Top3 全部跑 VTON，每套品类组合相同，按 categories 件数计算
            vton_category_count = count_vton_categories(categories or [])
            vton_timeout = estimate_vton_timeout(vton_category_count)
            logger.info(
                "[一阶段直出] 动态超时: taskId=%s, vtonCategories=%d, timeout=%ds",
                task_id, vton_category_count, vton_timeout,
            )

            # 全局并发槽位：阶段二 VTON 生成也计入全局工作流并发
            async with _workflow_slot():
                vton_state = await asyncio.wait_for(
                    OutfitGraphRunner.run_vton_only(vton_initial_state),
                    timeout=vton_timeout,
                )

            vton_error = vton_state.get("error")
            vton_outfits = vton_state.get("final_outfits") or []
            vton_partial_failures = vton_state.get("partial_failures") or []

            if vton_error or not vton_outfits:
                # VTON 全部失败 → 回滚 17 credits
                await self._on_failure(task_id, user_id,
                                        vton_error or "VTON 生成失败，已退还 credits",
                                        need_deduct, stage=success_stage)
                self._record_workflow_metrics(start_time, "FAILED")
                return

            # VTON 部分失败/全部成功 → 确认 17 credits
            await self._on_success(task_id, user_id, vton_outfits, need_deduct,
                                    stage=success_stage)
            # 保存 state 快照（供 accept 读取 VTON resultUrl）
            await self._save_state(task_id, vton_state)
            # 补充 credits_consumed 到 task status（审计字段）
            await self._update_task_status_credits(task_id, CREDITS_DIRECT_TOTAL)

            # 自动入库：三套 VTON 结果写入 ai_outfit_record（accepted=0，未采纳）
            # VTON 失败的套用第一件单品图兜底，失败容忍不阻塞主流程
            await self._auto_save_records(
                task_id=task_id,
                user_id=user_id,
                vton_state=vton_state,
                vton_outfits=vton_outfits,
                photo_session_key=photo_session_key,
            )

            # O4 优化：跨会话持久化 seen_item_ids（30 天衰减）
            final_seen = final_state.get("seen_item_ids") or set()
            displayed_ids = self._extract_displayed_item_ids(final_state)
            if final_seen and displayed_ids:
                await self._save_cross_session_seen_items(
                    user_id, final_seen, refresh_item_ids=displayed_ids,
                )
            self._record_workflow_metrics(start_time, "SUCCESS")

        except WorkflowBusyError as e:
            logger.warning("工作流并发限流: taskId=%s, msg=%s", task_id, e)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct, stage="vton")
            await self._cleanup_placeholder_record(placeholder_record_id, user_id, task_id)
            self._record_workflow_metrics(start_time, "BUSY")
        except asyncio.TimeoutError:
            logger.error("LangGraph 工作流超时: taskId=%s", task_id)
            await self._on_failure(task_id, user_id, "生成超时，请重试",
                                    need_deduct, stage="vton")
            await self._cleanup_placeholder_record(placeholder_record_id, user_id, task_id)
            self._record_workflow_metrics(start_time, "TIMEOUT")
        except Exception as e:
            logger.error("LangGraph 工作流异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct, stage="vton")
            await self._cleanup_placeholder_record(placeholder_record_id, user_id, task_id)
            self._record_workflow_metrics(start_time, "FAILED")

    def _record_workflow_metrics(self, start_time: float, status: str):
        """记录 LangGraph 工作流耗时与结果"""
        duration = time.monotonic() - start_time
        record_agent_workflow(duration_seconds=duration, status=status)
        record_outfit_generate(status=status, mode="agent", duration_seconds=duration)

    async def _save_pending_placeholder(
        self, task_id: str, user_id: int, vton_state: dict,
    ) -> int | None:
        """⑥ 用户选定模式：生成中占位入库（accepted=0+pending，结果为空）

        用户从衣橱/购物车/订单选定单品后任务启动即写入 1 条占位记录
        （outfitIndex=0，outfitJson='[]'，vtonResultUrl=None），使"生成中"的
        任务能出现在搭配历史页并可点入结果页查看进度；
        成功后 _auto_save_records 按 task_id+outfit_index upsert 更新为真实结果。
        入库失败不阻塞主流程，返回 record id 供失败清理使用。
        """
        try:
            java_client = await get_java_client()
            from app.schemas.outfit import OutfitRecordDTO

            model_image_source = "system_pool" if (
                vton_state.get("use_default_model") or vton_state.get("system_model_image_url")
            ) else "photo"
            placeholder_dto = OutfitRecordDTO(
                taskId=task_id,
                userId=user_id,
                round=vton_state.get("round", 1),
                outfitIndex=0,
                outfitJson="[]",  # 空结果占位，前端据此显示"生成中"
                vtonResultUrl=None,
                userPhotoUrl=None,
                modelImageSource=model_image_source,
                modelImageId=vton_state.get("model_image_id") or vton_state.get("system_model_id"),
                systemModelImageUrl=vton_state.get("system_model_image_url"),
                acceptedAction="pending",
                accepted=0,
                creditsConsumed=0,
            ).model_dump(exclude_none=True)
            record = await java_client.create_outfit_record(
                user_id=user_id, record_dto=placeholder_dto,
            )
            if record and record.get("id"):
                logger.info("[占位入库] 生成中占位记录已写入: taskId=%s, recordId=%s",
                            task_id, record.get("id"))
                return record.get("id")
            logger.warning("[占位入库] 返回空: taskId=%s", task_id)
            return None
        except Exception as e:
            logger.warning("[占位入库] 失败（不阻塞主流程）: taskId=%s, error=%s",
                           task_id, e)
            return None

    async def _cleanup_placeholder_record(
        self, placeholder_record_id: int | None, user_id: int, task_id: str,
    ) -> None:
        """任务失败/超时时清理生成中占位记录（避免残留空记录）"""
        if not placeholder_record_id:
            return
        try:
            java_client = await get_java_client()
            await java_client.delete_outfit_record(user_id, placeholder_record_id)
            logger.info("[占位入库] 任务失败已清理占位记录: taskId=%s, recordId=%s",
                        task_id, placeholder_record_id)
        except Exception as e:
            logger.warning("[占位入库] 清理占位记录失败（不阻塞主流程）: taskId=%s, recordId=%s, error=%s",
                           task_id, placeholder_record_id, e)

    async def _auto_save_records(
        self,
        task_id: str,
        user_id: int,
        vton_state: dict,
        vton_outfits: list[dict],
        photo_session_key: str | None,
        credits_consumed: int = CREDITS_DIRECT_TOTAL,
    ) -> None:
        """一阶段直出自动入库：三套 VTON 结果写入 ai_outfit_record（accepted=0，未采纳）

        - VTON 失败的套用第一件单品图兜底作 vtonResultUrl
        - 入库失败不阻塞主流程（仅 warning 日志）
        - 不写 user_wardrobe（用户未主动采纳）
        - 不发送 OUTFIT_ACCEPT 事件
        """
        try:
            java_client = await get_java_client()

            # 模特图来源（从 vton_state 读取）
            model_image_source = vton_state.get("model_image_source")
            if not model_image_source:
                # 系统模特（用户选定或默认模特池）→ system_pool；用户自拍 → photo
                # 2026-08-06 修复：用户选定系统模特时 system_model_image_url 非空，
                # 不能仅凭 use_default_model 判定（use_default_model=False 但仍是系统模特）
                model_image_source = "system_pool" if (
                    vton_state.get("use_default_model") or vton_state.get("system_model_image_url")
                ) else "photo"
            model_image_id = vton_state.get("model_image_id") or vton_state.get("system_model_id")

            # 用户原自拍照 URL（仅 model_image_source=photo 时有意义）
            user_photo_url: str | None = None
            if model_image_source == "photo" and photo_session_key:
                try:
                    user_photo_url = await self.redis.get(
                        f"{PHOTO_SESSION_URL_PREFIX}{photo_session_key}"
                    )
                except Exception as e:
                    logger.warning("[自动入库] 读取用户原照片 URL 失败: taskId=%s, error=%s",
                                   task_id, e)

            # 三套分别入库（VTON 失败的套 vtonResultUrl=None，前端展示"生成失败"）
            # 使用 OutfitResult / OutfitRecordDTO 模型统一字段名，避免手动对齐 Java DTO
            from app.schemas.outfit import OutfitRecordDTO, OutfitResult
            for idx, outfit in enumerate(vton_outfits):
                # dict → OutfitResult（字段名统一 camelCase）
                outfit_model = OutfitResult.model_validate(outfit)
                vton_url = outfit_model.resultUrl  # None=VTON失败，不用商品图冒充

                outfit_json = outfit_model.model_dump_json(exclude_none=False)

                # OutfitRecordDTO 字段名严格对齐 Java AiOutfitRecordCreateDTO
                record_dto = OutfitRecordDTO(
                    taskId=task_id,
                    userId=user_id,
                    round=vton_state.get("round", 1),
                    outfitIndex=idx,
                    outfitJson=outfit_json,
                    vtonResultUrl=vton_url,  # None=VTON失败
                    userPhotoUrl=user_photo_url,
                    modelImageSource=model_image_source,
                    modelImageId=model_image_id,
                    systemModelImageUrl=vton_state.get("system_model_image_url"),  # 用户选定的初始模特图 URL
                    acceptedAction="pending",
                    accepted=0,
                    creditsConsumed=credits_consumed,
                ).model_dump(exclude_none=True)

                try:
                    record = await java_client.create_outfit_record(
                        user_id=user_id,
                        record_dto=record_dto,
                    )
                    if record:
                        logger.info("[自动入库] 成功: taskId=%s, userId=%s, idx=%s, vton=%s, recordId=%s",
                                    task_id, user_id, idx,
                                    "ok" if vton_url else "FAILED",
                                    record.get("id"))
                    else:
                        logger.warning("[自动入库] 返回空: taskId=%s, idx=%s", task_id, idx)
                except Exception as e:
                    logger.warning("[自动入库] 第 %d 套入库失败（不阻塞）: taskId=%s, error=%s",
                                   idx, task_id, e)

        except Exception as e:
            logger.error("[自动入库] 异常（不阻塞主流程）: taskId=%s, error=%s",
                         task_id, e, exc_info=True)

    # ============================================================
    # v3 阶段二：用户选定搭配 → VTON 生成入口
    # ============================================================
    async def select(
        self,
        parent_task_id: str,
        user_id: int,
        selected_outfit_indexes: list[int],
        photo_session_key: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """v3 阶段二入口：用户选定阶段一的 Top3 搭配子集后，触发 VTON 生成

        流程：
          ① 读取阶段一 state 快照（parent_task_id）→ 取 outfit_candidates + 用户偏好等
          ② credits 预扣（OUTFIT_VTON，5×N credits，N=用户选定的搭配数）
          ③ 写任务状态 PROCESSING（新 taskId，stage="vton"）
          ④ 启动异步 _async_vton 跑 VTON-only 工作流
          ⑤ HTTP 返回 (taskId, None, None)，前端轮询 task status

        失败规则：
          - 阶段二 VTON 全部失败 → 全额 rollback（_on_failure, need_deduct=True）
          - 阶段二 VTON 部分失败 → 不退还（_on_success, need_deduct=True，partial_failures 审计）
          - 阶段二 VTON API 故障 → 全额 rollback（_on_failure）
          - credits 预扣失败 → 不启动任务，返回 errorMsg

        Args:
            parent_task_id: 阶段一 taskId（用于读取 state 快照中的 outfit_candidates）
            user_id: 用户 ID
            selected_outfit_indexes: 用户选定的搭配索引（Top3 中的 0/1/2 子集）
            photo_session_key: 用户照片会话 Key（场景 B VTON 用）；
                               None 时回退用阶段一 photo_session_key

        Returns:
            (taskId, errorMsg, errorCode)：
              - 成功：(taskId, None, None)
              - 阶段一任务不存在：(taskId, "阶段一任务不存在或已过期", "NOT_FOUND")
              - 阶段一未完结：(taskId, "阶段一任务尚未完成", "NOT_FINISHED")
              - 索引越界：(taskId, "选定的搭配索引不合法", "BAD_INDEX")
              - credits 不足：(taskId, "AI credits 余额不足")
              - 服务异常：(taskId, "配额服务不可用")
        """
        task_id = str(uuid.uuid4())

        # 1. 读取阶段一 state 快照
        parent_state = await self._load_state(parent_task_id, user_id)
        if parent_state is None:
            return task_id, "阶段一任务不存在或已过期", "NOT_FOUND"
        # 检查阶段一是否已完成（state 中应有 outfit_candidates 字段）
        parent_outfits = parent_state.get("outfit_candidates") or []
        if not parent_outfits:
            return task_id, "阶段一任务尚未生成候选搭配", "NOT_FINISHED"

        # 2. 索引合法性校验（Top3 中的 0/1/2 子集，至少 1 个，至多 3 个）
        if not selected_outfit_indexes:
            return task_id, "请至少选定一套搭配", "BAD_INDEX"
        for idx in selected_outfit_indexes:
            if not isinstance(idx, int) or idx < 0 or idx >= len(parent_outfits):
                return task_id, f"搭配索引 {idx} 越界（合法范围 0-{len(parent_outfits) - 1}）", "BAD_INDEX"
        # 去重保序
        selected_indexes = list(dict.fromkeys(selected_outfit_indexes))

        # 3. credits 预扣（阶段二 OUTFIT_VTON，5×N credits）
        credits_to_deduct = CREDITS_VTON_PER_OUTFIT * len(selected_indexes)
        # 共享分布式锁：与阶段一/商品驱动同锁，确保同一用户多阶段任务串行化
        recommend_lock_key = f"lock:outfit:recommend:user:{user_id}"
        async with DistributedLock(self.redis, recommend_lock_key,
                                    wait_timeout=3, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("select 并发限流：userId=%s 锁被占用", user_id)
                return task_id, "上一条搭配还在生成中，请稍候", "CONCURRENT"

            java_client = await get_java_client()
            credits_result = await java_client.credits_deduct(
                user_id=user_id,
                quota_type=QUOTA_TYPE_VTON,
                task_id=task_id,
                credits=credits_to_deduct,
            )
            if credits_result is None:
                record_quota_check(quota_type=QUOTA_TYPE_VTON, result="failed")
                return task_id, "配额服务不可用，请稍后重试", None
            if not credits_result.get("success"):
                msg = credits_result.get("msg", "AI credits 余额不足")
                logger.warning("阶段二 credits 预扣被拒绝: userId=%s, taskId=%s, msg=%s",
                                user_id, task_id, msg)
                record_quota_check(quota_type=QUOTA_TYPE_VTON, result="insufficient")
                return task_id, msg, None

            record_quota_check(quota_type=QUOTA_TYPE_VTON, result="ok")
            logger.info("阶段二 credits 预扣成功: userId=%s, taskId=%s, selectedCount=%d, credits=%d, balance=%s",
                         user_id, task_id, len(selected_indexes), credits_to_deduct,
                         credits_result.get("balance"))

        # 4. 写任务状态到 Redis（阶段二，stage="vton"）
        status = json.dumps({
            "status": "PROCESSING",
            "taskId": task_id,
            "userId": user_id,
            "taskType": "OUTFIT_VTON",
            "stage": "vton",
            "parentTaskId": parent_task_id,
            "selectedOutfitIndexes": selected_indexes,
            "createdAt": datetime.now().isoformat(),
        }, ensure_ascii=False)
        await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", status, ex=TASK_STATUS_TTL)

        # 5. 启动异步 VTON 工作流
        # 用户照片会话 Key：优先用前端传入，否则回退用阶段一 photo_session_key
        actual_photo_session_key = photo_session_key or parent_state.get("photo_session_key")

        task = asyncio.create_task(self._async_vton(
            task_id=task_id,
            parent_task_id=parent_task_id,
            user_id=user_id,
            selected_indexes=selected_indexes,
            parent_state=parent_state,
            photo_session_key=actual_photo_session_key,
            credits_consumed=credits_to_deduct,
        ))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        logger.info("阶段二 VTON 任务已创建: taskId=%s, parentTaskId=%s, userId=%s, selected=%s, credits=%d",
                     task_id, parent_task_id, user_id, selected_indexes, credits_to_deduct)
        return task_id, None, None

    async def _async_vton(
        self,
        task_id: str,
        parent_task_id: str,
        user_id: int,
        selected_indexes: list[int],
        parent_state: dict,
        photo_session_key: str | None,
        credits_consumed: int,
    ):
        """阶段二异步执行 VTON-only 工作流

        失败规则：
        - 全部失败 → _on_failure 全额 rollback credits
        - 部分失败 → _on_success 不退还（partial_failures 记录审计）
        - VTON API 故障 → _on_failure 全额 rollback credits

        Args:
            credits_consumed: 本次预扣的 credits 数（用于 task status 审计字段）
        """
        start_time = time.monotonic()
        try:
            # 构造阶段二 initial_state
            # 从阶段一 state 透传：outfit_candidates / 用户偏好 / 风格场景字段
            # 关键：透传 system_model_* 字段和节点1 已下载的 user_photo，
            # 避免 vton_only 阶段（不跑节点1）因 user_photo=None 走随机/默认女模特兜底
            initial_state: AgentState = {
                "task_id": task_id,
                "user_id": user_id,
                "stage": "vton",  # v3：阶段二 VTON 生成
                "parent_task_id": parent_task_id,
                "selected_outfit_indexes": selected_indexes,
                "vton_credits_per_outfit": CREDITS_VTON_PER_OUTFIT,
                # 透传阶段一状态
                "outfit_candidates": parent_state.get("outfit_candidates") or [],
                "photo_session_key": photo_session_key,
                # 节点4 场景 A 兜底需要：风格/场景/颜色用于 AI 文生图 prompt
                "style_tags": parent_state.get("style_tags") or [],
                "scene_desc": parent_state.get("scene_desc"),
                "color": parent_state.get("color"),
                "season": parent_state.get("season"),
                # 节点4 场景 A 判断：use_default_model
                "use_default_model": parent_state.get("use_default_model", False),
                "user_visual_profile": parent_state.get("user_visual_profile"),
                # round 字段：阶段二固定为 1（独立 taskId，不复用阶段一 round）
                "round": 1,
                "error": None,
                # 系统模特字段透传（vton_only 不跑节点1，必须显式传递）
                "system_model_id": parent_state.get("system_model_id"),
                "system_model_image_url": parent_state.get("system_model_image_url"),
                "system_model_gender": parent_state.get("system_model_gender"),
                "target_gender": parent_state.get("target_gender"),
                "gender_source": parent_state.get("gender_source"),
                # user_photo 透传：阶段一节点1 已下载的系统模特图 bytes
                "user_photo": parent_state.get("user_photo"),
                "partial_failures": [],
            }

            # 动态超时：从 parent_state.outfit_candidates 提取品类组合计算
            # 阶段二只对用户选定的套装跑 VTON，品类数来自阶段一 LLM 决策结果
            parent_outfits = parent_state.get("outfit_candidates") or []
            vton_cats: set[str] = set()
            for outfit in parent_outfits:
                for it in (outfit.get("items") or []):
                    cat = it.get("category")
                    if cat:
                        vton_cats.add(cat)
            vton_category_count = count_vton_categories(list(vton_cats))
            vton_timeout = estimate_vton_timeout(vton_category_count)
            logger.info(
                "[阶段二VTON] 动态超时: taskId=%s, parentTaskId=%s, "
                "vtonCategories=%d, timeout=%ds",
                task_id, parent_task_id, vton_category_count, vton_timeout,
            )

            # 全局并发槽位：限制同时运行的生成工作流数量
            async with _workflow_slot():
                final_state = await asyncio.wait_for(
                    OutfitGraphRunner.run_vton_only(initial_state),
                    timeout=vton_timeout,
                )

            error = final_state.get("error")
            outfits = final_state.get("final_outfits") or []
            partial_failures = final_state.get("partial_failures") or []
            selected_count = len(selected_indexes)

            # 失败规则判定
            # 全部失败：partial_failures 覆盖全部 selected_indexes
            all_failed = (len(partial_failures) >= selected_count) or (not outfits)
            # VTON API 故障：error 非空
            api_failed = bool(error)

            if api_failed or all_failed:
                # 全额 rollback credits
                fail_msg = error or "VTON 生成全部失败，已退还 credits"
                await self._on_failure(task_id, user_id, fail_msg,
                                        need_deduct=True, stage="vton")
                self._record_vton_metrics(start_time, "FAILED", len(partial_failures))
            else:
                # 部分失败或全部成功 → 不退还 credits（_on_success 走 confirm）
                # 把 credits_consumed 写到 task status 供前端展示
                await self._on_success(task_id, user_id, outfits, need_deduct=True,
                                        stage="vton")
                # 阶段二 state 快照（供 accept 入库读取 VTON resultUrl）
                await self._save_state(task_id, final_state)
                # 补充 credits_consumed 到 task status（审计字段）
                await self._update_task_status_credits(task_id, credits_consumed)
                # 自动入库：所有 VTON 结果永久保存到 ai_outfit_record（accepted=0，未采纳）
                # 用户后续满意/不满意仅更新状态，不删除记录
                # 失败容忍不阻塞主流程（仅 warning 日志）
                await self._auto_save_records(
                    task_id=task_id,
                    user_id=user_id,
                    vton_state=final_state,
                    vton_outfits=outfits,
                    photo_session_key=photo_session_key,
                )
                self._record_vton_metrics(start_time, "SUCCESS", len(partial_failures))

        except WorkflowBusyError as e:
            logger.warning("阶段二 VTON 工作流并发限流: taskId=%s, msg=%s", task_id, e)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, stage="vton")
            self._record_vton_metrics(start_time, "BUSY", 0)
        except asyncio.TimeoutError:
            logger.error("阶段二 VTON 工作流超时: taskId=%s", task_id)
            await self._on_failure(task_id, user_id, "VTON 生成超时，请重试",
                                    need_deduct=True, stage="vton")
            self._record_vton_metrics(start_time, "TIMEOUT", 0)
        except Exception as e:
            logger.error("阶段二 VTON 工作流异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, stage="vton")
            self._record_vton_metrics(start_time, "FAILED", 0)

    def _record_vton_metrics(self, start_time: float, status: str, partial_failures_count: int):
        """记录阶段二 VTON 工作流耗时与结果"""
        duration = time.monotonic() - start_time
        record_agent_workflow(duration_seconds=duration, status=status)
        record_outfit_generate(status=status, mode="vton", duration_seconds=duration)
        if partial_failures_count > 0:
            logger.info("[阶段二] partial_failures=%d (credits 不退还)", partial_failures_count)

    async def _update_task_status_credits(self, task_id: str, credits_consumed: int):
        """补充 creditsConsumed 审计字段到 task status（v3 阶段二成功时调用）"""
        try:
            data = await self.redis.get(f"{TASK_STATUS_PREFIX}{task_id}")
            if not data:
                return
            status = json.loads(data)
            status["creditsConsumed"] = credits_consumed
            await self.redis.set(
                f"{TASK_STATUS_PREFIX}{task_id}",
                json.dumps(status, ensure_ascii=False),
                ex=TASK_STATUS_TTL,
            )
        except Exception as e:
            logger.warning("补充 creditsConsumed 字段失败: taskId=%s, error=%s", task_id, e)

    # ============================================================
    # v3 阶段二完结：用户满意入库（accept）
    # ============================================================
    async def accept(
        self,
        task_id: str,
        user_id: int,
        outfit_index: int,
        accepted_action: str,
        size_map: dict[str, str] | None = None,
    ) -> tuple[str, str | None, str | None]:
        """v3 用户满意入库：用户在阶段二 VTON 结果中选 [满意-加购整套] 或 [满意-下单整套]

        流程：
          ① 读取阶段二 state 快照 → 取 final_outfits[outfit_index]
          ② 构造 AiOutfitRecordCreateDTO → 调 JavaClient.create_outfit_record 入库
          ③ 标记任务 finished=True，阻止再次反馈
          ④ O3：异步记录搭配事件到 Qdrant（EpisodicMemory）

        Args:
            task_id: 阶段二 VTON 任务 ID
            user_id: 用户 ID
            outfit_index: 用户满意的搭配索引（0-based，需在 final_outfits 范围内）
            accepted_action: cart（加购整套）/ order（下单整套）
            size_map: 用户确认的尺码映射 {itemId: "L"}，透传到 record.size_map

        Returns:
            (taskId, errorMsg, errorCode)：
              - 成功：(taskId, None, None)
              - 任务不存在：(taskId, "任务不存在或已过期", "NOT_FOUND")
              - 任务未完结：(taskId, "任务尚未完成", "NOT_FINISHED")
              - 已采纳：(taskId, "当前搭配已采纳", "FINISHED")
              - 索引越界：(taskId, "搭配索引不合法", "BAD_INDEX")
              - 入库失败：(taskId, "入库失败，请稍后重试")
              - acceptedAction 不合法：(taskId, "acceptedAction 必须为 cart 或 order", "BAD_ACTION")
        """
        # 0. acceptedAction 校验
        if accepted_action not in ("cart", "order"):
            return task_id, "acceptedAction 必须为 cart 或 order", "BAD_ACTION"

        # 加分布式锁防止并发双击导致重复入库
        accept_lock_key = f"lock:outfit:accept:task:{task_id}"
        async with DistributedLock(self.redis, accept_lock_key,
                                    wait_timeout=0, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("accept 并发限流：taskId=%s 锁被占用", task_id)
                return task_id, "正在处理采纳请求，请稍候", "CONCURRENT"

            # 1. 读取阶段二 state 快照
            state = await self._load_state(task_id, expected_user_id=user_id)
            db_record_fallback: dict | None = None  # DB 兜底记录
            if state is None:
                # 兜底1：从 task status 读 final_outfits（state 快照可能已过期）
                task_status = await self.get_task_result(task_id, user_id)
                if not task_status:
                    # 兜底2：Redis 完全过期，从 DB 读 ai_outfit_record
                    # VTON 生成时已自动入库 accepted=0，此处兜底读取
                    try:
                        java_client = await get_java_client()
                        db_record_fallback = await java_client.get_outfit_record_by_task(
                            user_id=user_id, task_id=task_id, outfit_index=outfit_index,
                        )
                    except Exception as e:
                        logger.warning("DB 兜底查询搭配记录失败: taskId=%s, error=%s", task_id, e)
                    if not db_record_fallback:
                        return task_id, "任务不存在或已过期", "NOT_FOUND"
                    # 已采纳过的记录直接返回 FINISHED
                    if db_record_fallback.get("accepted") == 1:
                        return task_id, "当前搭配已采纳", "FINISHED"
                    if not db_record_fallback.get("vtonResultUrl"):
                        return task_id, "该搭配未生成 VTON 效果图，无法入库", "BAD_INDEX"
                    # 用 DB 数据构造 target_outfit
                    outfits = []
                    target_outfit = {
                        "resultUrl": db_record_fallback.get("vtonResultUrl"),
                        "items": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                  .get("items") or []),
                        "reason": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                   .get("reason") or ""),
                        "score": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                  .get("score") or 0.0),
                    }
                    vton_result_url = target_outfit["resultUrl"]
                    # 跳过下方索引校验（DB 已按 outfit_index 精确查询）
                    logger.info("[accept] 使用 DB 兜底数据: taskId=%s, idx=%s, recordId=%s",
                                task_id, outfit_index, db_record_fallback.get("id"))
                else:
                    if task_status.get("status") != "SUCCESS":
                        return task_id, "任务尚未完成", "NOT_FINISHED"
                    outfits = task_status.get("outfits") or []
                    if not outfits:
                        # task_status 存在但 outfits 空 → 再走 DB 兜底
                        try:
                            java_client = await get_java_client()
                            db_record_fallback = await java_client.get_outfit_record_by_task(
                                user_id=user_id, task_id=task_id, outfit_index=outfit_index,
                            )
                        except Exception as e:
                            logger.warning("DB 兜底查询搭配记录失败: taskId=%s, error=%s", task_id, e)
                        if not db_record_fallback:
                            return task_id, "任务尚未完成", "NOT_FINISHED"
                        if db_record_fallback.get("accepted") == 1:
                            return task_id, "当前搭配已采纳", "FINISHED"
                        if not db_record_fallback.get("vtonResultUrl"):
                            return task_id, "该搭配未生成 VTON 效果图，无法入库", "BAD_INDEX"
                        target_outfit = {
                            "resultUrl": db_record_fallback.get("vtonResultUrl"),
                            "items": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                      .get("items") or []),
                            "reason": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                       .get("reason") or ""),
                            "score": (json.loads(db_record_fallback.get("outfitJson") or "{}")
                                      .get("score") or 0.0),
                        }
                        vton_result_url = target_outfit["resultUrl"]
                        logger.info("[accept] 使用 DB 兜底数据（task_status 无 outfits）: taskId=%s, idx=%s",
                                    task_id, outfit_index)
            else:
                if state.get("finished"):
                    return task_id, "当前搭配已采纳", "FINISHED"
                # 阶段二的 final_outfits 在 state 快照中
                outfits = state.get("final_outfits") or []
                if not outfits:
                    # 兜底：尝试从 task status 读
                    task_status = await self.get_task_result(task_id, user_id)
                    outfits = (task_status or {}).get("outfits") or []
                if not outfits:
                    return task_id, "任务尚未完成", "NOT_FINISHED"

            # 2. 索引合法性校验（仅对走 state/task_status 路径的 outfits 校验）
            if db_record_fallback is None:
                if not isinstance(outfit_index, int) or outfit_index < 0 or outfit_index >= len(outfits):
                    return task_id, f"搭配索引不合法（合法范围 0-{len(outfits) - 1}）", "BAD_INDEX"

                # 3. 取目标搭配 + VTON 结果图 URL
                target_outfit = outfits[outfit_index]
                vton_result_url = target_outfit.get("resultUrl")
                if not vton_result_url:
                    return task_id, "该搭配未生成 VTON 效果图，无法入库", "BAD_INDEX"

            # 锁内提前标记 finished，防止并发请求通过 finished 检查
            # 后续业务逻辑（入库/WS推送/事件发送）在锁外执行，不影响响应时间
            if state is not None:
                state["finished"] = True
                state["accepted_outfit_index"] = outfit_index
                await self._save_state(task_id, state)
            # 同步更新 task status
            try:
                task_status_snap = await self.get_task_result(task_id, user_id) or {}
                task_status_snap["accepted"] = True
                task_status_snap["finished"] = True
                task_status_snap["acceptedOutfitIndex"] = outfit_index
                task_status_snap["acceptedAction"] = accepted_action
                await self.redis.set(
                    f"{TASK_STATUS_PREFIX}{task_id}",
                    json.dumps(task_status_snap, ensure_ascii=False),
                    ex=TASK_STATUS_TTL,
                )
            except Exception as e:
                logger.warning("锁内预标记 finished 失败: taskId=%s, error=%s", task_id, e)

        # 4. 构造 AiOutfitRecordCreateDTO 并入库
        # outfitJson：完整套装详情 JSON 字符串（items + reason + sizeMap）
        # 尺码推荐：sizeMap 写入 outfitJson 而非新增表字段（最小改动）
        # 后续购物车/订单页可从 record.outfitJson 解析读回用户确认的尺码
        outfit_json = json.dumps({
            "items": target_outfit.get("items") or [],
            "reason": target_outfit.get("reason") or "",
            "score": target_outfit.get("score") or 0.0,
            "sizeMap": size_map or {},
        }, ensure_ascii=False)

        # 模特图来源：根据阶段二 state 中的 use_default_model + user_photo 推断
        # - photo：用户上传自拍照
        # - system_pool：系统模特图池命中
        # - ai_generated：AI 文生图兜底
        # 节点4 加载默认模特图时会在 state 中记录 source，此处透传；
        # 兜底：use_default_model=False → photo，True → system_pool
        # DB 兜底场景：优先用 DB record 中保存的值（VTON 自动入库时已记录）
        if db_record_fallback:
            model_image_source = db_record_fallback.get("modelImageSource") or "photo"
            model_image_id = db_record_fallback.get("modelImageId")
        else:
            model_image_source = state.get("model_image_source") if state else None
            if not model_image_source:
                # 系统模特（用户选定或默认模特池）→ system_pool；用户自拍 → photo
                # 2026-08-06 修复：与自动入库一致，用户选定系统模特（system_model_image_url 非空）
                # 不能仅凭 use_default_model 判定（use_default_model=False 但仍是系统模特）
                model_image_source = "system_pool" if (
                    state and (state.get("use_default_model") or state.get("system_model_image_url"))
                ) else "photo"
            model_image_id = (state.get("model_image_id") if state else None) or (state.get("system_model_id") if state else None)

        # 从 Redis 读取用户原自拍照持久化 URL（accept 入库用）
        # Redis Key ai:photo:session:url:{sessionKey}，TTL 30min（与照片会话同步）
        # 场景 A（用户未上传照片）或 Redis 过期 → user_photo_url 为 None
        # 用 photo_session_key（= "{userId}:{sessionId}"）而非 user_id 构造 Key
        # DB 兜底场景：Redis 已过期，直接用 DB record 中保存的 userPhotoUrl
        user_photo_url: str | None = None
        if db_record_fallback:
            user_photo_url = db_record_fallback.get("userPhotoUrl")
        else:
            try:
                _psk = state.get("photo_session_key") if state else None
                if _psk:
                    user_photo_url = await self.redis.get(f"{PHOTO_SESSION_URL_PREFIX}{_psk}")
            except Exception as e:
                logger.warning("读取用户原自拍照 URL 失败（不阻塞 accept）: userId=%s, error=%s",
                               user_id, e)
        # 仅 model_image_source=photo 时才有意义传 user_photo_url；场景 A 强制 None
        if model_image_source != "photo":
            user_photo_url = None

        # 系统默认模特图 URL（用户选定的初始模特图，2026-08-06 新增）
        # 衣橱"模特/原始照片"展示用：真人照片模式无此值，系统模特模式非空
        system_model_image_url = (state.get("system_model_image_url") if state else None)

        # creditsConsumed：从 task status 读（_async_vton 成功时写入）
        # DB 兜底场景：直接用 DB record 中的值
        credits_consumed = 0
        if db_record_fallback:
            credits_consumed = int(db_record_fallback.get("creditsConsumed") or 0)
        else:
            try:
                task_status = await self.get_task_result(task_id, user_id)
                if task_status:
                    credits_consumed = int(task_status.get("creditsConsumed") or 0)
            except Exception:
                pass

        record_dto = {
            "taskId": task_id,
            "userId": user_id,
            "round": (db_record_fallback.get("round") if db_record_fallback
                      else (state.get("round", 1) if state else 1)),
            "outfitIndex": outfit_index,
            "outfitJson": outfit_json,
            "vtonResultUrl": vton_result_url,
            "userPhotoUrl": user_photo_url,  # 用户原自拍照 URL
            "modelImageSource": model_image_source,
            "modelImageId": model_image_id,
            "systemModelImageUrl": system_model_image_url,  # 用户选定的初始模特图 URL
            # 2026-08-06：'order' 动作延迟到订单创建成功后再标记（trade-service 下单回调
            # /items/outfit/records/mark-ordered 置 acceptedAction=order + orderId）。
            # 此处先写 'saved'（已满意保存），避免下单前搭配历史误显示"已下单"。
            "acceptedAction": ("saved" if accepted_action == "order" else accepted_action),
            "creditsConsumed": credits_consumed,
        }

        try:
            java_client = await get_java_client()
            record = await java_client.create_outfit_record(
                user_id=user_id,
                record_dto=record_dto,
            )
            if record is None:
                logger.error("入库搭配记录失败: taskId=%s, userId=%s, outfitIdx=%s",
                              task_id, user_id, outfit_index)
                return task_id, "入库失败，请稍后重试", None
            logger.info("入库搭配记录成功: taskId=%s, userId=%s, outfitIdx=%s, recordId=%s, action=%s",
                         task_id, user_id, outfit_index, record.get("id"), accepted_action)
        except Exception as e:
            logger.error("入库搭配记录异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            return task_id, "入库失败，请稍后重试", None

        # 同步写入 user_wardrobe（item_type=4 AI 搭配效果图）
        # 失败容忍：写入失败不阻塞 accept 主流程（仅 warning 日志）
        # 用户仍可从 /outfit-history.html 查看搭配，对账任务可后续补写
        try:
            record_id = record.get("id") if record else None
            if record_id:
                # 衣橱"模特/原始照片"：真人照片模式用用户自拍照，系统模特模式用选定的初始模特图
                wardrobe_original_photo = user_photo_url if model_image_source == "photo" else system_model_image_url
                wardrobe_entry = await java_client.add_wardrobe_outfit(
                    user_id=user_id,
                    outfit_result_url=vton_result_url,
                    original_photo_url=wardrobe_original_photo,
                    outfit_json=outfit_json,
                    record_id=int(record_id),
                )
                if wardrobe_entry:
                    logger.info("AI 搭配效果图已写入衣橱: taskId=%s, userId=%s, wardrobeId=%s, recordId=%s",
                                 task_id, user_id, wardrobe_entry.get("id"), record_id)
                else:
                    logger.warning("AI 搭配效果图写入衣橱返回空（不影响 accept）: taskId=%s, userId=%s",
                                    task_id, user_id)
        except Exception as e:
            logger.warning("写入 AI 搭配效果图到衣橱异常（不阻塞 accept）: taskId=%s, userId=%s, error=%s",
                            task_id, user_id, e)

        # 5. 标记任务 finished（已在锁内预标记，此处补充 recordId + finishedAt）
        try:
            # 更新 task status（锁内已标记 accepted/finished/acceptedOutfitIndex/acceptedAction，
            # 此处补充 recordId 和 finishedAt）
            task_status = await self.get_task_result(task_id, user_id) or {}
            task_status["recordId"] = record.get("id") if record else None
            task_status["finishedAt"] = datetime.now().isoformat()
            await self.redis.set(
                f"{TASK_STATUS_PREFIX}{task_id}",
                json.dumps(task_status, ensure_ascii=False),
                ex=TASK_STATUS_TTL,
            )
        except Exception as e:
            logger.warning("补充 task status 字段失败（不影响入库结果）: taskId=%s, error=%s",
                            task_id, e)

        # 6. WS 推送"已采纳"通知
        await self._ws_push(user_id, {
            "taskId": task_id,
            "type": "OUTFIT_ACCEPTED",
            "status": "ACCEPTED",
            "outfitIndex": outfit_index,
            "acceptedAction": accepted_action,
            "recordId": record.get("id") if record else None,
            "msg": "已采纳并加入" + ("购物车" if accepted_action == "cart" else "下单流程"),
        })

        # 7. O3 优化：异步记录搭配事件到 Qdrant（EpisodicMemory）
        # 下次进入随心搭时读取作为"上次推荐回顾"，提升复购率
        try:
            accepted_items = target_outfit.get("items") or []
            episode_task = asyncio.create_task(self._record_episode(
                user_id=user_id,
                task_id=task_id,
                accepted_items=accepted_items,
                style_tags=state.get("style_tags", []) if state else [],
                scene_desc=state.get("scene_desc") if state else None,
                season=state.get("season") if state else None,
            ))
            self._pending_tasks.add(episode_task)
            episode_task.add_done_callback(self._pending_tasks.discard)
        except Exception as e:
            logger.warning("[EpisodicMemory] 记录搭配事件失败（不影响主流程）: %s", e)

        # 8. 个性化推荐画像：发送 OUTFIT_ACCEPT 用户行为事件 + 主动失效画像缓存
        # 业务价值：用户采纳的搭配是最强信号（权重 3.0），写入 Qdrant user_behavior 后，
        # 下次画像聚合时用于 top_styles/top_colors/price_distribution/style_vector 增强。
        # fire-and-forget 模式，不阻塞 accept 主流程响应
        try:
            accept_event_task = asyncio.create_task(self._send_outfit_accept_events(
                user_id=user_id,
                task_id=task_id,
                outfit_index=outfit_index,
                target_outfit=target_outfit,
                state=state,
            ))
            self._pending_tasks.add(accept_event_task)
            accept_event_task.add_done_callback(self._pending_tasks.discard)
        except Exception as e:
            logger.warning("[Phase 2.5] 创建 OUTFIT_ACCEPT 发送任务失败（不影响主流程）: %s", e)
        try:
            from app.services.profile_service import get_profile_service
            profile_service = await get_profile_service()
            invalidate_task = asyncio.create_task(profile_service.invalidate_profile(user_id))
            self._pending_tasks.add(invalidate_task)
            invalidate_task.add_done_callback(self._pending_tasks.discard)
        except Exception as e:
            logger.warning("[Phase 2.5] 创建画像缓存失效任务失败（不影响主流程）: %s", e)

        logger.info("accept 完成: taskId=%s, userId=%s, outfitIdx=%s, action=%s",
                     task_id, user_id, outfit_index, accepted_action)
        return task_id, None, None

    async def _send_outfit_accept_events(
        self,
        user_id: int,
        task_id: str,
        outfit_index: int,
        target_outfit: dict,
        state: dict | None,
    ) -> None:
        """Phase 2.5：为采纳搭配中的每件商品发送 OUTFIT_ACCEPT 用户行为事件

        消息流向：Python ai-outfit → user.behavior.exchange → Python UserBehaviorMqConsumer
        → text-embedding-v4 文本编码 → Qdrant zmall_user_behavior collection

        字段映射（target_outfit.items 结构由 nodes.py 节点3 输出）：
          - itemId / name / image / price / category / color / shopId 直接透传
          - season 从 item 透传（可能为 None，EAV属性）
          - imageUrl = item.image（前端展示字段名 image，MQ 字段名 imageUrl）
          - styleTags / targetGender 当前未在 front_items 透传，留空（画像仍可从
            color/price/vector 聚合；后续 nodes.py 透传这些字段时自动生效）
          - userGender 从 state 读取（性别对齐检查用）

        Args:
            user_id: 用户 ID
            task_id: 阶段二 VTON 任务 ID
            outfit_index: 用户满意的搭配索引
            target_outfit: final_outfits[outfitIndex]，含 items / reason / score / resultUrl
            state: 阶段二 state 快照（可能为 None，兜底读 task status）
        """
        items = target_outfit.get("items") or []
        if not items:
            logger.warning("[Phase 2.5] 采纳搭配无 items，跳过 OUTFIT_ACCEPT 事件发送: taskId=%s", task_id)
            return

        # 从 state 读取用户性别（性别对齐检查用，缺失时 None）
        # AgentState 无 user_gender 字段，使用 target_gender（已确定的搭配目标性别）替代
        user_gender = None
        if state:
            user_gender = state.get("target_gender")

        # MQ 常量（与 Java 侧 MqConstants 对齐）
        USER_BEHAVIOR_EXCHANGE = "user.behavior.exchange"
        USER_BEHAVIOR_KEY_PREFIX = "user.behavior."
        BEHAVIOR_TYPE_OUTFIT_ACCEPT = "OUTFIT_ACCEPT"

        routing_key = f"{USER_BEHAVIOR_KEY_PREFIX}{BEHAVIOR_TYPE_OUTFIT_ACCEPT}"
        timestamp = datetime.now().isoformat()

        try:
            mq_producer = await get_mq_producer()
        except Exception as e:
            logger.warning("[Phase 2.5] 获取 MQ 生产者失败，跳过 OUTFIT_ACCEPT 事件发送: %s", e)
            return

        success_count = 0
        for item in items:
            item_id = item.get("itemId")
            if not item_id:
                continue
            # 构造消息体（字段与 Java 侧 UserBehaviorMessage 对齐，camelCase）
            message = {
                "userId": user_id,
                "itemId": int(item_id),
                "shopId": item.get("shopId"),
                "category": item.get("category"),
                "name": item.get("name"),  # 纯文本向量检索的核心文本
                "color": item.get("color"),
                "season": item.get("season"),  # EAV属性，可能为 None
                "price": float(item["price"]) if item.get("price") is not None else None,
                "type": BEHAVIOR_TYPE_OUTFIT_ACCEPT,
                "timestamp": timestamp,
                "imageUrl": item.get("image"),
                "styleTags": item.get("styleTags") or None,  # 从 front_items 透传
                "itemGender": item.get("itemGender"),  # 从 front_items 透传
                "userGender": user_gender,
                "extra": {
                    "outfitTaskId": task_id,
                    "outfitIndex": outfit_index,
                },
            }
            try:
                # MqProducer.publish 是同步阻塞（pika BlockingConnection），放线程池
                await asyncio.to_thread(
                    mq_producer.publish,
                    USER_BEHAVIOR_EXCHANGE,
                    routing_key,
                    message,
                )
                success_count += 1
            except Exception as e:
                logger.warning(
                    "[Phase 2.5] 发送 OUTFIT_ACCEPT 事件失败（单条不阻塞批量）: "
                    "userId=%s, itemId=%s, error=%s",
                    user_id, item_id, e,
                )

        logger.info(
            "[Phase 2.5] OUTFIT_ACCEPT 事件发送完成: taskId=%s, userId=%s, outfitIdx=%s, "
            "total=%d, success=%d",
            task_id, user_id, outfit_index, len(items), success_count,
        )

    async def _handle_refine_action(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        parsed: dict,
        new_round: int,
        start_time: float,
    ):
        """处理 refine 动作：对上一轮 VTON 结果调用千问 aitryon-refiner 精修

        业务场景（设计文档）：用户对 VTON 整体效果不满意但喜欢那套衣服单品，
        触发二次精修提升还原度。不走 LangGraph 工作流，直接：
        1. 下载上一轮 VTON 结果（作为 coarse_image）
        2. 重新加载用户照片（作为 person_image）
        3. 调 refine_vton_result（千问 aitryon-refiner）
        4. 上传精修图到 OSS
        5. 更新 final_outfits + 推送 WS + 更新 task status

        失败时降级为 _on_failure（不扣配额，refine 是免费精修）。
        """
        from app.api.deps import get_oss_uploader
        from app.tools.nodes import refine_vton_result, _download_image

        # 1. 确定精修哪套搭配（默认第 0 套）
        outfit_idx = parsed.get("outfit_index") or 0
        if not isinstance(outfit_idx, int) or outfit_idx < 0:
            outfit_idx = 0
        final_outfits = prev_state.get("final_outfits", [])
        if not final_outfits:
            await self._on_failure(task_id, user_id, "上一轮无搭配结果，无法精修",
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "FAILED")
            return
        if outfit_idx >= len(final_outfits):
            outfit_idx = 0
        target_outfit = final_outfits[outfit_idx]

        # 2. 获取上一轮 VTON 结果 URL
        prev_result_url = target_outfit.get("resultUrl")
        if not prev_result_url:
            await self._on_failure(task_id, user_id, "上一轮搭配无 VTON 结果图，无法精修",
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "FAILED")
            return

        # 3. 下载上一轮 VTON 结果作为 coarse_image
        prev_vton_bytes = await _download_image(prev_result_url)
        if prev_vton_bytes is None:
            await self._on_failure(task_id, user_id, "下载上一轮 VTON 结果图失败",
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "FAILED")
            return

        # 4. 重新加载用户照片（user_photo 是 bytes，不持久化，每轮重新加载）
        #    优先级：system_model_image_url > photo_session_key（用户自拍 Redis）
        user_photo: bytes | None = None
        system_model_image_url = prev_state.get("system_model_image_url")
        if system_model_image_url:
            user_photo = await _download_image(system_model_image_url)
        if user_photo is None:
            photo_session_key = prev_state.get("photo_session_key")
            if photo_session_key and user_id is not None:
                try:
                    # 用 photo_session_key 构造 Redis Key（多设备隔离）
                    photo_base64 = await self.redis.get(f"ai:photo:session:{photo_session_key}")
                    if photo_base64:
                        user_photo = base64.b64decode(photo_base64)
                except Exception as e:
                    logger.warning("[精修] 加载用户自拍照片失败: taskId=%s, error=%s", task_id, e)

        if not user_photo:
            await self._on_failure(task_id, user_id, "用户照片加载失败，无法精修",
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "FAILED")
            return

        # 5. 确定性别（refiner 必填：woman | man）
        gender = prev_state.get("system_model_gender") or "woman"

        # 6. 获取 outfit items（用于提取服饰图）
        outfit_items = target_outfit.get("items", [])

        # 7. 调用精修
        refined_bytes = await refine_vton_result(
            user_photo=user_photo,
            prev_vton_bytes=prev_vton_bytes,
            outfit_items=outfit_items,
            gender=gender,
            task_id=task_id,
        )

        if refined_bytes is None:
            # 精修失败：降级用原 VTON 图（不报错，让用户继续看到原结果）
            logger.warning("[精修] 精修失败，降级用原 VTON 图: taskId=%s", task_id)
            await self._on_success(
                task_id, user_id, final_outfits,
                need_deduct=True, mode="agent", stage="vton",
            )
            self._record_workflow_metrics(start_time, "SUCCESS")
            return

        # 8. 上传精修结果到 OSS
        try:
            oss_uploader = await get_oss_uploader()
            refined_url = await asyncio.to_thread(
                oss_uploader.upload_image, refined_bytes, "outfit-refined", "jpg",
            )
        except Exception as e:
            logger.error("[精修] OSS 上传失败，降级用原 VTON 图: taskId=%s, error=%s",
                         task_id, e)
            await self._on_success(
                task_id, user_id, final_outfits,
                need_deduct=True, mode="agent", stage="vton",
            )
            self._record_workflow_metrics(start_time, "SUCCESS")
            return

        if not refined_url:
            logger.error("[精修] OSS 上传返回 None，降级用原 VTON 图: taskId=%s", task_id)
            await self._on_success(
                task_id, user_id, final_outfits,
                need_deduct=True, mode="agent", stage="vton",
            )
            self._record_workflow_metrics(start_time, "SUCCESS")
            return

        # 9. 更新 final_outfits（标记 isRefined）
        final_outfits[outfit_idx]["resultUrl"] = refined_url
        final_outfits[outfit_idx]["isRefined"] = True

        # 10. 更新 state（持久化 final_outfits，供下一轮反馈使用）
        prev_state["final_outfits"] = final_outfits
        prev_state["round"] = new_round
        await self._save_state(task_id, prev_state)

        # 11. 推送结果（复用 _on_success 推送 WS + task status）
        await self._on_success(
            task_id, user_id, final_outfits,
            need_deduct=True, mode="agent", stage="vton",
        )
        logger.info("[精修] 精修完成并推送: taskId=%s, outfitIdx=%d, refinedUrl=%s",
                     task_id, outfit_idx, str(refined_url)[:80])
        self._record_workflow_metrics(start_time, "SUCCESS")

    async def _on_success(self, task_id: str, user_id: int, outfits: list[dict],
                          need_deduct: bool = True, mode: str = "agent",
                          stage: str | None = None):
        """推理成功：更新 Redis + WS 推送 + MQ 通知确认配额

        need_deduct 当前恒为 True（不支持免费重试），保留参数兼容。
        U1 统一架构：mode 参数区分消息 type（OUTFIT_AGENT vs OUTFIT_PRODUCT）。
        v3 两阶段架构：stage 参数区分 MQ 消息 phase（candidate/vton/null），
        Java 侧 AiOutfitResultListener 按 phase 路由到 ICreditsService 或 IQuotaService。

        商品驱动模式（mode="product"）走 v3 credits 后，
        WS type 仍保留 OUTFIT_PRODUCT（前端 outfit-product.html 按此过滤），
        仅 MQ phase 走 "vton" 路径（Java 侧路由到 CreditsService）。

        数据模型：outfits (list[dict]) → OutfitResult 校验后序列化，
        Redis/WS 均用 TaskResultResponse / WsOutfitMessage 结构稳定字段。
        """
        from app.schemas.outfit import OutfitResult, TaskResultResponse, WsOutfitMessage

        # WS type：商品驱动保持 OUTFIT_PRODUCT（前端按此过滤），风格驱动按 stage 调整
        ws_type = "OUTFIT_PRODUCT" if mode == "product" else "OUTFIT_AGENT"
        task_type = "OUTFIT_PRODUCT" if mode == "product" else "OUTFIT_AGENT"

        # 风格驱动模式：按 stage 调整 WS 消息 type 和 taskType
        # 商品驱动模式：stage 仅用于 MQ phase 路由，不覆盖 WS type
        if mode != "product":
            if stage == "recommend":
                ws_type = "OUTFIT_RECOMMEND_RESULT"
                task_type = "OUTFIT_RECOMMEND"
            elif stage == "vton" or stage == "user_picked":
                # ⑥ 用户选定模式也属于 VTON 生成，复用 OUTFIT_VTON 消息类型
                ws_type = "OUTFIT_VTON_RESULT"
                task_type = "OUTFIT_VTON"

        # 1. 转换 outfits dict → OutfitResult（字段名统一 camelCase，extra="allow" 透传审计字段）
        outfit_models = [OutfitResult.model_validate(o) for o in outfits]
        finished_at = datetime.now().isoformat()

        # 2. 更新 Redis 任务状态（TaskResultResponse 结构化）
        task_result = TaskResultResponse(
            status="SUCCESS",
            taskId=task_id,
            userId=user_id,
            taskType=task_type,
            stage=stage,
            outfits=outfit_models,
            finishedAt=finished_at,
        )
        await self.redis.set(
            f"{TASK_STATUS_PREFIX}{task_id}",
            task_result.model_dump_json(),
            ex=TASK_STATUS_TTL,
        )

        # 3. WebSocket 推送（WsOutfitMessage 结构化）
        ws_msg = WsOutfitMessage(
            type=ws_type,
            taskId=task_id,
            status="SUCCESS",
            stage=stage,
            outfits=outfit_models,
        )
        await self._ws_push(user_id, ws_msg.model_dump())

        # 4. MQ 通知 Java 确认配额（need_deduct 恒为 True，不支持免费重试）
        if not need_deduct:
            logger.warning("need_deduct=False 不应出现（已禁用免费重试）: taskId=%s", task_id)
            return
        await self._notify_mq(task_id, user_id, "SUCCESS", mode=mode, stage=stage)

        logger.info("%s推理成功: taskId=%s, userId=%s, stage=%s, outfits=%d",
                     "商品驱动" if mode == "product" else "风格驱动",
                     task_id, user_id, stage, len(outfit_models))

    async def _on_failure(self, task_id: str, user_id: int, error_msg: str,
                          need_deduct: bool = True, mode: str = "agent",
                          stage: str | None = None):
        """推理失败：更新 Redis + WS 推送 + MQ 通知回滚配额

        need_deduct 当前恒为 True（不支持免费重试），保留参数兼容。
        U1 统一架构：mode 参数区分消息 type（OUTFIT_AGENT vs OUTFIT_PRODUCT）。
        v3 两阶段架构：stage 参数区分 MQ 消息 phase（candidate/vton/null）。

        商品驱动模式（mode="product"）走 v3 credits 后，
        WS type 仍保留 OUTFIT_PRODUCT（前端 outfit-product.html 按此过滤），
        仅 MQ phase 走 "vton" 路径（Java 侧路由到 CreditsService）。
        """
        from app.schemas.outfit import TaskResultResponse, WsOutfitMessage

        # WS type：商品驱动保持 OUTFIT_PRODUCT（前端按此过滤），风格驱动按 stage 调整
        ws_type = "OUTFIT_PRODUCT" if mode == "product" else "OUTFIT_AGENT"
        task_type = "OUTFIT_PRODUCT" if mode == "product" else "OUTFIT_AGENT"

        # 风格驱动模式：按 stage 调整 WS 消息 type 和 taskType
        # 商品驱动模式：stage 仅用于 MQ phase 路由，不覆盖 WS type
        if mode != "product":
            if stage == "recommend":
                ws_type = "OUTFIT_RECOMMEND_RESULT"
                task_type = "OUTFIT_RECOMMEND"
            elif stage == "vton" or stage == "user_picked":
                # ⑥ 用户选定模式也属于 VTON 生成，复用 OUTFIT_VTON 消息类型
                ws_type = "OUTFIT_VTON_RESULT"
                task_type = "OUTFIT_VTON"

        finished_at = datetime.now().isoformat()

        # 1. 更新 Redis 任务状态（TaskResultResponse 结构化）
        task_result = TaskResultResponse(
            status="FAILED",
            taskId=task_id,
            userId=user_id,
            taskType=task_type,
            stage=stage,
            errorMsg=error_msg,
            finishedAt=finished_at,
        )
        await self.redis.set(
            f"{TASK_STATUS_PREFIX}{task_id}",
            task_result.model_dump_json(),
            ex=TASK_STATUS_TTL,
        )

        # 2. WebSocket 推送失败提示（WsOutfitMessage 结构化）
        ws_msg = WsOutfitMessage(
            type=ws_type,
            taskId=task_id,
            status="FAILED",
            stage=stage,
            errorMsg=error_msg,
        )
        # 兼容前端老逻辑：保留 msg 字段
        ws_dict = ws_msg.model_dump()
        ws_dict["msg"] = "生成失败，已退还 credits" if need_deduct else "生成失败"
        await self._ws_push(user_id, ws_dict)

        # 3. MQ 通知 Java 回滚配额（need_deduct 恒为 True，不支持免费重试）
        if not need_deduct:
            logger.warning("need_deduct=False 不应出现（已禁用免费重试）: taskId=%s", task_id)
            return
        # 携带 errorMsg 供 Java 侧写入 ai_task 表
        await self._notify_mq(task_id, user_id, "FAILED", error_msg=error_msg,
                              mode=mode, stage=stage)

        logger.warning("%s推理失败: taskId=%s, userId=%s, stage=%s, error=%s",
                        "商品驱动" if mode == "product" else "风格驱动",
                        task_id, user_id, stage, error_msg)

    async def _ws_push(self, user_id: int, message: dict):
        """WebSocket 推送（延迟导入避免循环依赖）

        ai-outfit 自身维护 ws_manager 单例（前端在风格驱动页面应连接
        /api/v1/outfit/agent/ws/{userId}）。用户不在线时静默跳过，
        前端可走 GET /api/v1/outfit/agent/result/{taskId} 轮询兜底。
        """
        try:
            from app.api.ws import ws_manager
            await ws_manager.send_to_user(str(user_id), message)
        except Exception as e:
            logger.warning("WS 推送失败（用户可能不在线）: userId=%s, error=%s", user_id, e)

    async def _notify_mq(self, task_id: str, user_id: int, status: str,
                         error_msg: str | None = None, mode: str = "agent",
                         stage: str | None = None):
        """MQ 通知 Java 配额确认/回滚（共用 ai.outfit.exchange）

        失败消息携带 errorMsg，与 Java 侧 AiOutfitResultMessage 字段对齐，
        便于 Java 端把失败原因写入 ai_task.error_msg 字段。
        MQ 失败时 fallback 调用 JavaClient.quota_confirm/rollback（HTTP），
        避免 RabbitMQ 抖动期间用户配额冻结记录长期滞留。
        U1 统一架构：mode 参数区分消息 type（OUTFIT_AGENT vs OUTFIT_PRODUCT），
        Java 侧按 type 路由到不同处理逻辑（商品驱动写 ai_task.outfitItems，风格驱动写 outfits）。
        v3 两阶段架构：stage 参数区分 MQ 消息 phase（candidate/vton/null）：
        - stage="recommend" → phase="candidate"（阶段一，调 ICreditsService.confirm/rollback OUTFIT_RECOMMEND）
        - stage="vton" → phase="vton"（阶段二，调 ICreditsService.confirm/rollback OUTFIT_VTON）
        - stage=None → phase=None（旧版单阶段，Java 侧走原 IQuotaService 路径）
        Java 侧 AiOutfitResultListener 按 phase 字段路由到 ICreditsService 或 IQuotaService。
        """
        ws_type = "OUTFIT_PRODUCT" if mode == "product" else "OUTFIT_AGENT"
        # v3 两阶段：按 stage 调整消息 type 和 phase
        if stage == "recommend":
            ws_type = "OUTFIT_RECOMMEND_RESULT"
            phase = "candidate"
        elif stage == "vton" or stage == "user_picked":
            # ⑥ 用户选定模式也属于 VTON 生成，phase="vton"
            ws_type = "OUTFIT_VTON_RESULT"
            phase = "vton"
        else:
            phase = None  # 旧版兼容
        try:
            # MqProducer.publish 是同步阻塞调用，包到线程池避免阻塞事件循环
            producer = await get_mq_producer()
            message = {
                "taskId": task_id,
                "type": ws_type,
                "userId": user_id,
                "status": status,
                "phase": phase,  # v3：Java 侧按 phase 路由到 Credits/Quota
            }
            if error_msg:
                message["errorMsg"] = error_msg
            await asyncio.to_thread(
                producer.publish,
                AI_OUTFIT_EXCHANGE,
                AI_OUTFIT_RESULT_KEY,
                message,
            )
        except Exception as e:
            logger.error("MQ 通知配额%s失败，尝试 HTTP 兜底: taskId=%s, error=%s",
                          "确认" if status == "SUCCESS" else "回滚", task_id, e)
            # MQ 失败时 HTTP 兜底，避免配额冻结记录泄漏
            # v3：按 phase 选择走 credits_* 还是 quota_* 接口
            try:
                java_client = await get_java_client()
                if phase is not None:
                    # v3 credits 路径
                    quota_type = (QUOTA_TYPE_VTON if phase == "vton"
                                  else QUOTA_TYPE_RECOMMEND)
                    if status == "SUCCESS":
                        await java_client.credits_confirm(
                            user_id=user_id,
                            quota_type=quota_type,
                            task_id=task_id,
                        )
                    else:
                        await java_client.credits_rollback(
                            user_id=user_id,
                            quota_type=quota_type,
                            task_id=task_id,
                        )
                else:
                    # 旧版 quota 路径
                    if status == "SUCCESS":
                        await java_client.quota_confirm(
                            user_id=user_id,
                            quota_type=QUOTA_TYPE,
                            quota_id=user_id,
                            task_id=task_id,
                        )
                    else:
                        await java_client.quota_rollback(
                            user_id=user_id,
                            quota_type=QUOTA_TYPE,
                            quota_id=user_id,
                            task_id=task_id,
                        )
                logger.info("HTTP 兜底配额%s成功: taskId=%s, phase=%s",
                             "确认" if status == "SUCCESS" else "回滚", task_id, phase)
            except Exception as http_e:
                logger.error("HTTP 兜底配额%s也失败（需人工介入对账）: taskId=%s, error=%s",
                              "确认" if status == "SUCCESS" else "回滚", task_id, http_e)
                # 双失败时写 Redis 告警标记，供 Java 侧定时对账扫描
                # Key: ai:quota:alert:{taskId}，TTL 7 天，value 含 userId/status/errorMsg
                # Java 侧可定时扫描 ai:quota:alert:* 自动回滚冻结记录或触发告警
                try:
                    alert_data = json.dumps({
                        "taskId": task_id,
                        "userId": user_id,
                        "status": status,  # SUCCESS=需确认 / FAILED=需回滚
                        "phase": phase,
                        "mqError": str(e),
                        "httpError": str(http_e),
                        "createdAt": datetime.now().isoformat(),
                    }, ensure_ascii=False)
                    await self.redis.set(
                        f"ai:quota:alert:{task_id}",
                        alert_data,
                        ex=7 * 24 * 3600,  # 7 天 TTL
                    )
                    logger.warning("配额双失败告警已写入 Redis: taskId=%s, key=ai:quota:alert:%s",
                                    task_id, task_id)
                except Exception as alert_e:
                    logger.error("写 Redis 告警标记也失败: taskId=%s, error=%s", task_id, alert_e)

    async def get_task_result(self, task_id: str, expected_user_id: int | None = None) -> dict | None:
        """查询任务状态（兜底轮询用）

        Args:
            task_id: 任务 ID
            expected_user_id: 期望的用户 ID，传入时校验 task 归属（防 IDOR）

        Returns:
            TaskResultResponse 序列化后的 dict（前端可直接消费）；
            任务不存在或归属不匹配返回 None。

        数据模型：Redis 存的是 TaskResultResponse.model_dump_json()，
        这里反序列化为 TaskResultResponse 后再 dump dict，确保字段名稳定。
        """
        from app.schemas.outfit import TaskResultResponse

        data = await self.redis.get(f"{TASK_STATUS_PREFIX}{task_id}")
        if not data:
            # Redis 状态已过期（TTL=1h）：回退查 MySQL ai_outfit_record 恢复历史任务结果，
            # 供搭配历史页"查看搭配"入口主动进入生成结果页（2026-08-06 新增）
            return await self._get_result_from_db(task_id, expected_user_id)
        try:
            # Pydantic 反序列化校验 + 字段名统一（避免节点写入时字段名漂移）
            task_result = TaskResultResponse.model_validate_json(data)
        except Exception as e:
            logger.warning("任务结果反序列化失败（降级返回原始 dict）: taskId=%s, error=%s",
                           task_id, e)
            result = json.loads(data)
            # 补 taskId 字段（历史 Redis 数据可能缺失，导致 response_model 校验失败）
            if not result.get("taskId"):
                result["taskId"] = task_id
            # IDOR 防护：校验 task 归属用户
            if expected_user_id is not None:
                task_user_id = result.get("userId")
                if task_user_id != expected_user_id:
                    logger.warning("IDOR 拦截(get_task_result): taskId=%s, expected=%s, actual=%s",
                                   task_id, expected_user_id, task_user_id)
                    return None
            return result

        # IDOR 防护：校验 task 归属用户
        if expected_user_id is not None and task_result.userId is not None:
            if task_result.userId != expected_user_id:
                logger.warning("IDOR 拦截(get_task_result): taskId=%s, expected=%s, actual=%s",
                               task_id, expected_user_id, task_result.userId)
                return None

        # 僵尸任务检测：PROCESSING 状态超时自动标记为 FAILED
        # 场景：服务重启/进程崩溃导致异步任务中断，Redis 中 PROCESSING 状态残留（TTL=1h）
        # 前端轮询会一直看到 PROCESSING，无法显示结果
        if task_result.status == "PROCESSING":
            created_at = task_result.model_extra.get("createdAt") if task_result.model_extra else None
            if not created_at:
                # 无 createdAt 字段（极老数据），用 Redis TTL 兜底判断
                ttl = await self.redis.ttl(f"{TASK_STATUS_PREFIX}{task_id}")
                # TTL 远小于 3600 说明已经存在很久了
                if ttl > 0 and ttl < TASK_STATUS_TTL - 600:
                    logger.warning("[僵尸任务] PROCESSING 状态超时（TTL 兜底）: taskId=%s, ttl=%s",
                                   task_id, ttl)
                    await self._on_failure(task_id, task_result.userId or 0,
                                          "生成超时（服务异常重启），请重新搭配",
                                          need_deduct=True, mode="agent",
                                          stage=task_result.stage)
                    # 重新读取更新后的状态
                    data = await self.redis.get(f"{TASK_STATUS_PREFIX}{task_id}")
                    if data:
                        try:
                            task_result = TaskResultResponse.model_validate_json(data)
                        except Exception:
                            pass
            else:
                try:
                    from datetime import datetime as _dt
                    created = _dt.fromisoformat(created_at)
                    elapsed = (_dt.now() - created).total_seconds()
                    # 动态超时：阶段二 VTON 最长 378s + 120s 缓冲 = 498s
                    # 用户选定模式（单套 VTON）最长 120s + 60s 缓冲 = 180s
                    stage = task_result.stage
                    if stage in ("vton", "user_picked"):
                        timeout_threshold = 500  # VTON 生成最长 ~8 分钟
                    else:
                        timeout_threshold = 120  # 阶段一候选推荐最长 ~2 分钟
                    if elapsed > timeout_threshold:
                        logger.warning("[僵尸任务] PROCESSING 状态超时: taskId=%s, elapsed=%ds, threshold=%ds",
                                       task_id, int(elapsed), timeout_threshold)
                        await self._on_failure(task_id, task_result.userId or 0,
                                              "生成超时（服务异常重启），请重新搭配",
                                              need_deduct=True, mode="agent",
                                              stage=task_result.stage)
                        # 重新读取更新后的状态
                        data = await self.redis.get(f"{TASK_STATUS_PREFIX}{task_id}")
                        if data:
                            try:
                                task_result = TaskResultResponse.model_validate_json(data)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning("[僵尸任务] 时间解析失败: taskId=%s, createdAt=%s, error=%s",
                                   task_id, created_at, e)

        # 返回 dict（FastAPI 响应序列化）
        return task_result.model_dump(by_alias=False, exclude_none=False)

    async def _get_result_from_db(self, task_id: str, expected_user_id: int | None) -> dict | None:
        """Redis 状态过期后，从 MySQL ai_outfit_record 恢复任务结果（历史记录查看入口用）

        - 数据源：hm-item.ai_outfit_record（按 task_id 查所有 outfit_index 记录）
        - 组装：每条 record 的 outfit_json（OutfitResult JSON） + vtonResultUrl 拼成 outfits
        - accepted/acceptedAction 取已采纳（accepted=1）的那套，否则默认待采纳
        - IDOR 防护：expected_user_id 传入时校验 record.user_id
        - 查询/解析失败返回 None（保持原"任务不存在"语义）
        """
        try:
            from app.core.config import settings
            from shared.db_client import DbClient

            db = DbClient(
                host=settings.mysql_host,
                port=settings.mysql_port,
                username=settings.mysql_username,
                password=settings.mysql_password,
                database=settings.mysql_database,
            )
            rows = db.execute(
                "SELECT task_id, user_id, outfit_index, outfit_json, vton_result_url, "
                "accepted, accepted_action, created_at "
                "FROM ai_outfit_record WHERE task_id = :task_id ORDER BY outfit_index",
                {"task_id": task_id},
            )
            if not rows:
                return None

            user_id = rows[0].user_id
            if expected_user_id is not None and user_id != expected_user_id:
                logger.warning("IDOR 拦截(DB 回退): taskId=%s, expected=%s, actual=%s",
                               task_id, expected_user_id, user_id)
                return None

            outfits: list[dict] = []
            accepted = 0
            accepted_action = "pending"
            accepted_index = 0
            for row in rows:
                try:
                    outfit = json.loads(row.outfit_json) if row.outfit_json else {}
                except Exception:
                    outfit = {}
                if not isinstance(outfit, dict):
                    outfit = {}
                outfit["resultUrl"] = row.vton_result_url
                outfit.setdefault("isVtonGenerated", bool(row.vton_result_url))
                outfits.append(outfit)
                if getattr(row, "accepted", None) == 1:
                    accepted = 1
                    accepted_action = getattr(row, "accepted_action", None) or "saved"
                    accepted_index = row.outfit_index

            result_dict = {
                "status": "SUCCESS",
                "taskId": task_id,
                "userId": user_id,
                "stage": "vton",
                "outfits": outfits,
                "accepted": accepted,
                "acceptedAction": accepted_action,
                "outfitIndex": accepted_index,
            }
            # 用 TaskResultResponse 校验组装结果（防旧数据字段类型不匹配导致 response_model 500）
            from app.schemas.outfit import TaskResultResponse
            validated = TaskResultResponse.model_validate(result_dict)
            return validated.model_dump(by_alias=False, exclude_none=False)
        except Exception as e:
            logger.warning("从 DB 恢复任务结果失败: taskId=%s, error=%s", task_id, e)
            return None

    # ============================================================
    # 多轮反馈
    # ============================================================

    async def _save_state(self, task_id: str, state: dict) -> bool:
        """持久化可恢复的任务 checkpoint 到 Redis（供多轮反馈读取）。

        这里只保存任务上下文，不再保存完整 LangGraph runtime state：
        - 图片、生成结果、画像、事件、天气和临时候选池由其它存储或下一轮重建；
        - checkpoint_version 通过 Redis Lua CAS 递增，拒绝旧异步任务的过期写入；
        - 返回 False 表示版本冲突或写入失败，调用方仍可继续主流程，MySQL 负责结果兜底。
        """
        try:
            current_version = int(state.get("checkpoint_version", 0) or 0)
            next_version = current_version + 1
            snapshot = build_task_checkpoint(state, version=next_version)
            payload = json.dumps(snapshot, ensure_ascii=False)
            key = f"{STATE_SNAPSHOT_PREFIX}{task_id}"
            written = await self.redis.eval(
                _CHECKPOINT_CAS_SCRIPT,
                1,
                key,
                current_version,
                payload,
                STATE_SNAPSHOT_TTL,
            )
            if not written:
                logger.warning(
                    "checkpoint 版本冲突，跳过旧状态写入: taskId=%s, expected=%s",
                    task_id,
                    current_version,
                )
                return False
            # 让当前异步流程继续携带最新版本，后续保存可以安全 CAS。
            state["checkpoint_version"] = next_version
            logger.info(
                "任务 checkpoint 已保存: taskId=%s, round=%s, version=%s, fields=%s",
                task_id,
                snapshot.get("round", 1),
                next_version,
                len(snapshot),
            )
            return True
        except Exception as e:
            # 保存失败不阻断主流程，后续反馈可从 MySQL 降级恢复。
            logger.warning("任务 checkpoint 保存失败: taskId=%s, error=%s", task_id, e)
            return False

    async def _load_state(self, task_id: str, expected_user_id: int | None = None) -> dict | None:
        """读取历史 state 快照（反馈轮用）

        Args:
            task_id: 任务 ID
            expected_user_id: 期望的用户 ID，传入时校验 task 归属（防 IDOR）

        Returns:
            state dict（seen_item_ids 已转回 set），不存在或归属不匹配返回 None
        """
        data = await self.redis.get(f"{STATE_SNAPSHOT_PREFIX}{task_id}")
        if not data:
            return None
        try:
            state = json.loads(data)
            # IDOR 防护：校验 task 归属用户
            if expected_user_id is not None:
                state_user_id = state.get("user_id")
                if state_user_id != expected_user_id:
                    logger.warning("IDOR 拦截: taskId=%s, expected_user_id=%s, actual_user_id=%s",
                                   task_id, expected_user_id, state_user_id)
                    return None
            return hydrate_task_checkpoint(state)
        except Exception as e:
            logger.warning("state 快照解析失败: taskId=%s, error=%s", task_id, e)
            return None

    async def _restore_feedback_runtime(self, state: dict, user_id: int) -> dict:
        """恢复不会写入 task checkpoint 的运行时画像。

        用户画像属于跨会话长期记忆，任务快照只保存可恢复的任务上下文。
        反馈轮开始前重新读取画像，既保持个性化，又避免使用过期的画像副本。
        画像服务不可用时按空画像继续，节点会自动走无画像降级路径。
        """
        if state.get("user_profile"):
            return state
        try:
            from app.services.profile_service import get_profile_service

            profile_service = await get_profile_service()
            state["user_profile"] = await profile_service.get_or_load_profile(user_id)
        except Exception as e:
            logger.warning(
                "反馈轮恢复用户画像失败（按空画像继续）: taskId=%s, userId=%s, error=%s",
                state.get("task_id"), user_id, e,
            )
            state["user_profile"] = {}
        return state

    async def _build_fallback_state_from_db(
        self, task_id: str, user_id: int, mode: str = "agent",
    ) -> dict | None:
        """DB 兜底：Redis state 过期时，从 ai_outfit_record 反向构造降级 state

        场景：用户在搭配历史页/生成结果页点击"不满意"提交反馈，但 Redis state 快照
        已过期（超过 STATE_SNAPSHOT_TTL=7 天），无法走正常的 replace_single 分支。

        降级限制：
          - 丢失 query_vector / candidate_items_by_category / seen_item_ids 等运行时状态
          - 反馈只能走 regenerate_all（全量重新生成），不支持 replace_single（精准替换单品）
          - LLM 解析出的 replace_single 会在 _async_feedback 中因 keep_categories=[]
            和 candidate_items_by_category 缺失而降级为 regenerate_all

        Args:
            mode: "agent"=风格驱动（3 套），"product"=商品驱动（1 套）

        Returns:
            降级 state dict，或 None（DB 中无此 taskId 的记录）
        """
        try:
            java_client = await get_java_client()
            # 风格驱动入库 3 套（outfit_index=0/1/2），商品驱动入库 1 套（outfit_index=0）
            max_idx = 3 if mode == "agent" else 1
            db_records: list[dict] = []
            max_round = 1
            any_accepted = False
            for idx in range(max_idx):
                try:
                    rec = await java_client.get_outfit_record_by_task(
                        user_id=user_id, task_id=task_id, outfit_index=idx,
                    )
                except Exception as e:
                    logger.warning("[DB 兜底] 查询记录失败: taskId=%s, idx=%d, error=%s",
                                   task_id, idx, e)
                    rec = None
                if not rec:
                    break  # 顺序入库，遇到空即止
                db_records.append(rec)
                # round 取最大值（反馈轮次递增）
                rec_round = rec.get("round") or 1
                if isinstance(rec_round, (int, float)) and rec_round > max_round:
                    max_round = int(rec_round)
                if rec.get("accepted") == 1:
                    any_accepted = True

            if not db_records:
                return None

            # 已采纳的记录 → finished=True（feedback 入口会拒绝再次反馈）
            if any_accepted:
                logger.info("[DB 兜底] 记录已采纳，构造 finished state: taskId=%s", task_id)

            # 从 DB 记录构造 outfit_candidates（用于 history_outfits 去重）
            outfit_candidates: list[dict] = []
            all_items: list[dict] = []
            for rec in db_records:
                try:
                    outfit_json = json.loads(rec.get("outfitJson") or "{}")
                except Exception:
                    outfit_json = {}
                items = outfit_json.get("items") or []
                all_items.extend(items)
                outfit_candidates.append({
                    "items": items,
                    "reason": outfit_json.get("reason") or "",
                    "score": outfit_json.get("score") or 0.0,
                    "resultUrl": rec.get("vtonResultUrl"),
                })

            # 商品驱动模式：从 items 中恢复 main_item_ids 和 _main_item_info
            main_item_ids: list[int] = []
            main_item_info: dict | None = None
            if mode == "product":
                for it in all_items:
                    if it.get("isMain") and it.get("itemId"):
                        main_item_ids.append(it["itemId"])
                        if main_item_info is None:
                            main_item_info = it
                if not main_item_ids:
                    logger.warning("[DB 兜底] 商品驱动模式未找到主商品: taskId=%s", task_id)
                    return None  # 商品驱动无主商品无法继续

            # 降级 state：仅包含 regenerate_all 所需的最小字段集
            # 缺失字段（query_vector/candidate_items_by_category/seen_item_ids 等）
            # 会让节点1/2 重新计算，可接受
            fallback_state = {
                "task_id": task_id,
                "user_id": user_id,
                "mode": mode,
                "stage": "vton",
                "round": max_round,
                # 输入字段：DB 未存储，用默认值（节点1 会重新编码向量）
                "style_tags": [],
                "scene_desc": None,
                "photo_session_key": None,
                "color": None,
                "shop_ids": None,
                "categories": None,
                "category_constraints": ["上衣", "下装", "鞋"],
                "budget_max": None,
                "season": None,
                # 节点1 输出：丢失，节点1 会重新计算
                "query_vector": None,
                "query_text": "",
                "user_photo": None,
                "user_visual_profile": None,
                "use_default_model": True,
                # 节点2 输出：丢失，节点2 会重新检索
                "candidate_items_by_category": {},
                # 节点3 输出：从 DB 恢复（用于 history_outfits 去重）
                "outfit_candidates": outfit_candidates,
                "top_candidates_pool": [],
                # 反馈字段
                "history_outfits": [outfit_candidates] if outfit_candidates else [],
                "seen_item_ids": set(),
                "user_dislike_colors": [],
                "dislike_item_ids": [],
                "retry_vton_item_ids": [],
                "finished": any_accepted,
                # 性别与服装匹配：丢失，节点1/2 跳过性别过滤
                "system_model_id": None,
                "system_model_image_url": None,
                "system_model_gender": None,
                "target_gender": None,
                "gender_source": None,
                "user_body_profile_id": None,
                "user_body_profile": None,
                "user_profile": {},
                "error": None,
            }

            # 商品驱动模式专用字段
            if mode == "product":
                fallback_state["main_item_ids"] = main_item_ids
                fallback_state["_main_item_info"] = main_item_info
                # _main_item_bytes 丢失，节点1 反馈轮会重新下载

            logger.info("[DB 兜底] 构造降级 state 成功: taskId=%s, mode=%s, records=%d, round=%d, accepted=%s",
                        task_id, mode, len(db_records), max_round, any_accepted)
            return fallback_state
        except Exception as e:
            logger.error("[DB 兜底] 构造降级 state 异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            return None

    # 衣橱自定义图片/自拍参与 AI 搭配召回（方案B）
    _CLIP_CACHE_PREFIX = "clip:wardrobe:"
    _CLIP_CACHE_TTL = 7 * 24 * 3600  # 7 天

    async def _resolve_custom_images_to_items(
        self,
        custom_entries: list[dict],
        seen_ids: set[int],
    ) -> list[int]:
        """将衣橱自定义图片（itemType=2/3）通过向量编码 + Qdrant 相似检索转为商品 ID

        方案B：
        1. 从 Redis 缓存读向量（key=clip:wardrobe:{wardrobeId}）
        2. 未命中缓存 → 编码 → 写缓存（7 天 TTL）
        3. 用向量在 Qdrant item_style collection 检索相似商品（top 3）
        4. 返回去重后的商品 ID 列表

        ⚠️ 已知限制：
        text-embedding-v4 不支持图片编码，encode_image_url 已移除。
        此方法会优雅降级返回空列表（不影响主流程）。
        后续改进：用 LLM 视觉模型（qwen3.5-flash）描述照片内容 → encode_text 编码描述文本。
        已缓存的向量（迁移前用 Jina 编码的）仍可用，但新照片无法编码。

        失败不抛异常（返回空列表），不影响主流程。
        """
        result_ids: list[int] = []
        redis = await get_redis()
        searcher = await get_qdrant_searcher()
        embed_client = await get_embed_client()

        for entry in custom_entries:
            wardrobe_id = entry.get("id")
            photo_url = entry.get("photoUrl")
            if not photo_url:
                continue

            cache_key = f"{self._CLIP_CACHE_PREFIX}{wardrobe_id}"

            # 1. 尝试从 Redis 缓存读向量
            vector = None
            try:
                cached = await redis.get(cache_key)
                if cached:
                    vector = json.loads(cached)
                    logger.info("[衣橱] CLIP 向量命中缓存: wardrobeId=%s", wardrobe_id)
            except Exception:
                pass

            # 2. 未命中 → 编码（纯文本向量模式下跳过，encode_image_url 已移除）
            if not vector:
                if not hasattr(embed_client, 'encode_image_url'):
                    logger.debug("[衣橱] 纯文本向量模式不支持图片编码，跳过: wardrobeId=%s", wardrobe_id)
                    continue
                try:
                    vector = await embed_client.encode_image_url(photo_url)
                    if vector and len(vector) > 0:
                        # 写缓存（fire-and-forget，失败不阻塞）
                        try:
                            await redis.setex(
                                cache_key, self._CLIP_CACHE_TTL,
                                json.dumps(vector),
                            )
                        except Exception:
                            pass
                        logger.info("[衣橱] CLIP 编码成功并缓存: wardrobeId=%s", wardrobe_id)
                    else:
                        logger.warning("[衣橱] CLIP 编码返回空向量: wardrobeId=%s", wardrobe_id)
                        continue
                except Exception as e:
                    logger.warning("[衣橱] CLIP 编码失败: wardrobeId=%s, error=%s", wardrobe_id, e)
                    continue

            # 3. Qdrant 相似商品检索（top 3，无品类/颜色/季节限制，纯视觉相似）
            try:
                results = await asyncio.to_thread(
                    searcher.search_complementary_items,
                    vector,
                    None,    # shop_ids：全平台
                    None,    # category：不限品类
                    None,    # color：不限颜色
                    None,    # season：不限季节
                    None,    # dislike_colors
                    None,    # target_gender
                    3,       # limit
                    0.5,     # score_threshold
                )
                for r in results:
                    item_id = r.get("item_id")
                    if item_id is None:
                        continue
                    try:
                        item_id_int = int(item_id)
                    except (TypeError, ValueError):
                        continue
                    if item_id_int in seen_ids:
                        continue
                    seen_ids.add(item_id_int)
                    result_ids.append(item_id_int)
                logger.info("[衣橱] 自定义图片召回: wardrobeId=%s → %d 个商品",
                             wardrobe_id, len(results))
            except Exception as e:
                logger.warning("[衣橱] Qdrant 相似检索失败: wardrobeId=%s, error=%s", wardrobe_id, e)

        return result_ids

    async def _persist_user_preference(
        self,
        user_id: int,
        dislike_colors: list[str] | None = None,
        like_styles: list[str] | None = None,
        preferred_price_range: list | None = None,
        dislike_styles: list[str] | None = None,
    ) -> None:
        """异步持久化用户偏好到 Qdrant（跨会话累积）

        - fire-and-forget：调用方用 asyncio.create_task 启动，不阻塞主流程
        - 失败仅记日志：偏好丢失不影响当次推荐
        - 合并 upsert：与已有记录合并去重
        - 补齐 dislike_styles 和 preferred_price_range 字段采集
        """
        try:
            updater = await get_user_preference_updater()
            # upsert_preference 为 async（内部用分布式锁保证原子性）
            await updater.upsert_preference(
                user_id,
                dislike_colors,
                dislike_styles,
                like_styles,
                preferred_price_range,
            )
        except Exception as e:
            logger.warning("持久化用户偏好失败（不影响主流程）: userId=%s, error=%s", user_id, e)

    async def _record_episode(
        self,
        user_id: int,
        task_id: str,
        accepted_items: list[dict],
        style_tags: list[str],
        scene_desc: str | None,
        season: str | None,
    ) -> None:
        """O3 优化：异步记录用户搭配事件到 Qdrant（EpisodicMemory）

        - accept 时调用：记录用户采纳的搭配详情
        - 下次进入随心搭时读取：作为"上次推荐回顾"输入 LLM prompt
        - fire-and-forget：失败不阻塞主流程
        """
        try:
            episode_store = await get_user_episode_store()
            await asyncio.to_thread(
                episode_store.add_episode,
                user_id,
                task_id,
                accepted_items,
                style_tags,
                scene_desc,
                season,
            )
        except Exception as e:
            logger.warning("[EpisodicMemory] 记录搭配事件失败（不影响主流程）: %s", e)

    async def _load_recent_episodes(
        self,
        user_id: int,
        style_tags: list[str] | None = None,
        scene_desc: str | None = None,
        season: str | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """O3 优化：读取用户最近的搭配事件（首轮推荐时调用）

        Returns:
            最近 5 条搭配事件（按时间降序），失败返回空列表
        """
        try:
            episode_store = await get_user_episode_store()
            episodes = await asyncio.to_thread(episode_store.get_recent_episodes, user_id)
            episodes = self._filter_relevant_episodes(
                episodes,
                style_tags=style_tags,
                scene_desc=scene_desc,
                season=season,
                categories=categories,
            )
            if episodes:
                logger.info("[EpisodicMemory] 已加载历史搭配事件: userId=%s, count=%d",
                             user_id, len(episodes))
            return episodes
        except Exception as e:
            logger.warning("[EpisodicMemory] 加载历史搭配事件失败（不影响主流程）: %s", e)
            return []

    @staticmethod
    def _filter_relevant_episodes(
        episodes: list[dict],
        style_tags: list[str] | None = None,
        scene_desc: str | None = None,
        season: str | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """过滤明显不相关的历史事件，避免把旧场景直接灌给 LLM。

        事件记忆仍按最近时间读取，但当前季节冲突且风格、场景、品类都没有
        重合时不召回；其余事件按相关性排序后最多保留 5 条。历史数据缺少
        新字段时兼容为普通最近事件。
        """
        if not episodes:
            return []

        def terms(value) -> set[str]:
            if isinstance(value, str):
                return {part.strip().casefold() for part in value.replace("，", " ").split()
                        if part.strip()}
            if isinstance(value, (list, tuple, set)):
                return {str(part).strip().casefold() for part in value if str(part).strip()}
            return set()

        current_styles = terms(style_tags)
        current_scene = terms(scene_desc)
        current_categories = terms(categories)
        ranked: list[tuple[int, int, dict]] = []
        for position, episode in enumerate(episodes):
            if not isinstance(episode, dict):
                continue
            episode_styles = terms(episode.get("style_tags"))
            episode_scene = terms(episode.get("scene_desc"))
            episode_categories = terms([
                item.get("category") for item in episode.get("accepted_items", [])
                if isinstance(item, dict)
            ])
            score = 0
            score += 3 * len(current_styles & episode_styles)
            score += 2 * len(current_categories & episode_categories)
            score += len(current_scene & episode_scene)
            episode_season = episode.get("season")
            season_conflict = bool(season and episode_season and season != episode_season)
            if season_conflict and score == 0:
                continue
            if season and episode_season == season:
                score += 2
            ranked.append((score, -position, episode))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [episode for _, _, episode in ranked[:5]]

    @staticmethod
    def _extract_displayed_item_ids(state: dict) -> set[int]:
        """提取本轮真正展示的商品，用于刷新其去重时间。

        不能把 state 中累积的全部 seen_item_ids 都重新写成当前时间，
        否则每次推荐都会把历史商品的 30 天生命周期整体续期。
        衣橱/主商品由用户明确选择，不应污染跨会话推荐去重池。
        """
        outfits = state.get("final_outfits") or state.get("outfit_candidates") or []
        displayed: set[int] = set()
        for outfit in outfits:
            for item in (outfit or {}).get("items", []):
                if item.get("isWardrobePicked") or item.get("_wardrobe_picked"):
                    continue
                if item.get("isMain"):
                    continue
                raw_id = item.get("itemId") or item.get("item_id")
                try:
                    if raw_id is not None:
                        displayed.add(int(raw_id))
                except (TypeError, ValueError):
                    continue
        return displayed

    async def _load_cross_session_seen_items(self, user_id: int) -> set[int]:
        """从 Redis ZSet 加载跨会话去重记录，并按商品粒度清理过期成员。

        兼容旧版本 JSON 字符串 key：读取到旧格式后转换为 ZSet，避免升级时丢失去重数据。
        读取失败仍返回空集合，去重不是主推荐链路的硬依赖。
        """
        key = f"{SEEN_ITEMS_PREFIX}{user_id}"
        cutoff = datetime.now().timestamp() - SEEN_ITEMS_TTL
        try:
            # 升级兼容：旧版本 key 是 string(JSON)，不能先执行 ZSet 命令，否则会触发 WRONGTYPE。
            key_type = None
            try:
                key_type = await self.redis.type(key)
            except Exception:
                pass
            if key_type in ("string", b"string"):
                legacy_raw = await self.redis.get(key)
                legacy = json.loads(legacy_raw) if legacy_raw else {}
                migrated: dict[str, float] = {}
                fresh_ids = set()
                for item_id, ts_str in legacy.items():
                    try:
                        ts = datetime.fromisoformat(ts_str).timestamp()
                        if ts > cutoff:
                            item_id_int = int(item_id)
                            fresh_ids.add(item_id_int)
                            migrated[str(item_id_int)] = ts
                    except (ValueError, TypeError):
                        continue
                if migrated:
                    await self.redis.delete(key)
                    await self.redis.zadd(key, migrated)
                    await self.redis.expire(key, SEEN_ITEMS_TTL)
                return fresh_ids

            await self.redis.zremrangebyscore(key, "-inf", cutoff)
            raw_ids = await self.redis.zrangebyscore(key, cutoff, "+inf")
            if raw_ids:
                fresh_ids = set()
                for raw_id in raw_ids:
                    try:
                        fresh_ids.add(int(raw_id))
                    except (TypeError, ValueError):
                        continue
                logger.info("[O4] 加载跨会话 seen_item_ids(ZSet): userId=%s, fresh=%d",
                            user_id, len(fresh_ids))
                return fresh_ids

            return set()
        except Exception as e:
            logger.warning("[O4] 加载跨会话 seen_item_ids 失败（不影响主流程）: %s", e)
            return set()

    async def _save_cross_session_seen_items(
        self,
        user_id: int,
        seen_item_ids: set[int],
        refresh_item_ids: set[int] | None = None,
    ) -> None:
        """以 ZSet 保存跨会话去重记录，只刷新本轮实际展示的商品时间。"""
        key = f"{SEEN_ITEMS_PREFIX}{user_id}"
        try:
            now = datetime.now().timestamp()
            cutoff = now - SEEN_ITEMS_TTL
            await self.redis.zremrangebyscore(key, "-inf", cutoff)
            refresh_ids = set(refresh_item_ids if refresh_item_ids is not None else seen_item_ids)
            refresh_ids = {int(item_id) for item_id in refresh_ids if item_id is not None}
            if refresh_ids:
                await self.redis.zadd(key, {str(item_id): now for item_id in refresh_ids})
                await self.redis.expire(key, SEEN_ITEMS_TTL)
            logger.info("[O4] 保存跨会话 seen_item_ids(ZSet): userId=%s, refreshed=%d",
                        user_id, len(refresh_ids))
        except Exception as e:
            logger.warning("[O4] 保存跨会话 seen_item_ids 失败（不影响主流程）: %s", e)

    async def feedback(
        self,
        task_id: str,
        user_id: int,
        feedback: str,
        outfit_index: int | None = None,
        item_index: int | None = None,
        dislike_colors: list[str] | None = None,
        dislike_item_ids: list[int] | None = None,
        retry_vton_item_ids: list[int] | None = None,
        want_style_tags: list[str] | None = None,
        note: str | None = None,
    ) -> tuple[str, str | None, str | None]:
        """多轮反馈入口：轻量同步入口 + 完整异步处理

        Returns:
            (taskId, errorMsg, errorCode)：
              - 成功：(taskId, None, None)
              - 任务不存在：(taskId, "原任务不存在或已过期", "NOT_FOUND")
              - 已采纳终态：(taskId, "当前搭配已采纳", "FINISHED")
              - 并发限流：(taskId, "正在处理上一条反馈", "CONCURRENT")
              - 轮次超限：(taskId, "已达到最大反馈轮次", "ROUND_LIMIT")
              - 其他错误：(taskId, "具体错误信息", None)
            errorCode 供 API 层映射不同 HTTP 状态码（见 outfit_agent.py）

        同步阶段（<100ms，立即返回 task_id）：
          - 读取历史 state
          - 检查轮次上限
          - 写入 Redis 任务状态 PROCESSING
          - 启动异步任务

        异步阶段（_async_feedback，ReAct + LangGraph 全在内）：
          - ReAct 解析（note 非空）或 parse_feedback
          - action 处理（accept/replace_single/replace/regenerate_all/adjust_style）
          - 构造 initial_state + 跑 LangGraph 工作流
          - 成功/失败通过 WS 推送 + Redis 任务状态更新

        与 /recommend 一致：立即返回 task_id，前端轮询 task status。
        错误（任务不存在/轮次超限）仍同步返回 errorMsg。

        Args:
            outfit_index: 用户点击的搭配索引（0-based），由前端传入。
                          LLM 解析 feedback 时若识别到"第N套"也会填充此字段，
                          前端传入的优先级更高（覆盖 LLM 结果）。
            item_index: 用户点击的单品索引（0-based），同上。
            dislike_colors: 用户明确表示不喜欢的颜色（前端表单传入，优先于 LLM 解析）。
                            会累积到 user_dislike_colors，同会话内持续生效。
            dislike_item_ids: 本轮不喜欢的商品 ID（前端表单传入），仅本轮生效不累积。
                              商品本身用户不喜欢，节点2 后置过滤掉这些商品。
            retry_vton_item_ids: 本轮 VTON 效果差的商品 ID（前端表单传入），仅本轮生效不累积。
                                  商品本身 OK，仅 VTON 生成效果不还原，节点5 仅对这些商品重新换装（不换商品）。
            want_style_tags: 用户想要追加的风格（前端表单传入），节点1 合并到 style_tags。
            note: 自然语言备注补充。非空时触发 ReAct Tool calling，
                  LLM 自主调 update_user_preference/get_item_details/search_items。
                  前端结构化字段优先级 > ReAct 解析结果。

        Returns:
            (taskId, errorMsg)：
              - 成功：(taskId, None)（异步任务已启动，前端轮询 task status）
              - 任务不存在：(taskId, "原任务不存在或已过期")
              - 轮次超限：(taskId, "已达到最大反馈轮次（3 轮）")
              - 其他错误（解析失败/索引越界等）：异步阶段通过 task status 反馈
        """
        # 1. 读取历史 state
        prev_state = await self._load_state(task_id, expected_user_id=user_id)
        if prev_state is None:
            # DB 兜底：Redis state 过期（超过 7 天），从 DB 搭配记录反向构造降级 state
            # 降级限制：丢失 query_vector / candidate_items_by_category / seen_item_ids 等运行时状态，
            # 反馈只能走 regenerate_all（全量重新生成），不支持 replace_single（精准替换单品）
            prev_state = await self._build_fallback_state_from_db(task_id, user_id)
            if prev_state is None:
                return task_id, "原任务不存在或已过期，无法继续反馈", "NOT_FOUND"
            logger.info("[DB 兜底] Redis state 过期，从 DB 构造降级 state: taskId=%s", task_id)

        # 检查 finished 标记，accept 后不允许再次反馈
        if prev_state.get("finished"):
            logger.info("任务已采纳完结，拒绝再次反馈: taskId=%s", task_id)
            return task_id, "当前搭配已采纳，无法继续反馈", "FINISHED"

        # 2. 检查轮次上限（首轮=1，最大 3 轮）
        prev_round = prev_state.get("round", 1)
        max_rounds = settings.feedback_max_rounds
        if prev_round >= max_rounds:
            logger.info("反馈轮次超限: taskId=%s, round=%d, max=%d",
                         task_id, prev_round, max_rounds)
            return task_id, f"已达到最大反馈轮次（{max_rounds} 轮）", "ROUND_LIMIT"

        # 用分布式锁保证"读 state + 推进 round + 写 PROCESSING"
        # 临界区的原子性。对齐 Java 侧 Redisson RLock 模式（参考 SeckillOrderListener）：
        #   - waitTime=0：抢不到锁立即返回，避免请求堆积
        #   - leaseTime=30s：兜底防死锁（业务正常几毫秒完成，30s 是极端兜底）
        #   - key 命名：lock:outfit:feedback:task:{taskId}
        # 锁内完成 round 推进 + state 写入，确保并发请求串行化
        lock_key = f"lock:outfit:feedback:task:{task_id}"
        async with DistributedLock(self.redis, lock_key,
                                    wait_timeout=0, lease_timeout=30) as acquired:
            if not acquired:
                logger.info("反馈并发限流：taskId=%s 锁被占用，拒绝本次请求", task_id)
                return task_id, "正在处理上一条反馈，请稍候", "CONCURRENT"

            # 锁内双重检查：可能在等待锁期间状态已被其他请求改变
            prev_state = await self._load_state(task_id, expected_user_id=user_id)
            if prev_state is None:
                # DB 兜底（与锁外一致）
                prev_state = await self._build_fallback_state_from_db(task_id, user_id)
                if prev_state is None:
                    return task_id, "原任务不存在或已过期，无法继续反馈", "NOT_FOUND"
            if prev_state.get("finished"):
                return task_id, "当前搭配已采纳，无法继续反馈", "FINISHED"
            prev_round = prev_state.get("round", 1)
            if prev_round >= max_rounds:
                return task_id, f"已达到最大反馈轮次（{max_rounds} 轮）", "ROUND_LIMIT"

            new_round = prev_round + 1

            # 3. credits 预扣（每轮反馈扣 credits，与首轮 VTON 一致）
            # 复用 QUOTA_TYPE_VTON + CREDITS_VTON_PER_OUTFIT（5 credits/轮），
            # Java 侧 CreditsService 按 OUTFIT_VTON 类型处理扣费/回滚
            java_client = await get_java_client()
            credits_result = await java_client.credits_deduct(
                user_id=user_id,
                quota_type=QUOTA_TYPE_VTON,
                task_id=task_id,
                credits=CREDITS_VTON_PER_OUTFIT,
            )
            if credits_result is None:
                logger.warning("反馈轮 credits 预扣失败（服务不可用）: taskId=%s, userId=%s",
                               task_id, user_id)
                return task_id, "配额服务不可用，请稍后重试", None
            if not credits_result.get("success"):
                msg = credits_result.get("msg", "AI 生成次数或余额不足")
                logger.warning("反馈轮 credits 预扣被拒绝: taskId=%s, userId=%s, msg=%s",
                               task_id, user_id, msg)
                return task_id, msg, None

            record_quota_check(quota_type=QUOTA_TYPE_VTON, result="ok")
            logger.info("反馈轮 credits 预扣成功: taskId=%s, userId=%s, round=%d, credits=%d, balance=%s",
                         task_id, user_id, new_round, CREDITS_VTON_PER_OUTFIT,
                         credits_result.get("balance"))

            # 锁内同步更新 state 快照的 round，防止并发 feedback 请求读到旧 round 重复推进
            # 仅更新 TASK_STATUS 的 round 不够，state 快照的 round 也在异步任务 _async_feedback 中才更新，
            # 导致锁释放后到异步任务保存 state 之间存在时间窗口，并发请求可能读到旧 round 再次推进
            prev_state["round"] = new_round
            await self._save_state(task_id, prev_state)

            # 4. 写入 Redis 任务状态为 PROCESSING（立即返回 task_id，前端可轮询）
            status = json.dumps({
                "status": "PROCESSING",
                "taskId": task_id,
                "userId": user_id,
                "taskType": "OUTFIT_AGENT",
                "round": new_round,
                "createdAt": datetime.now().isoformat(),
            }, ensure_ascii=False)
            await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", status, ex=TASK_STATUS_TTL)

        # 用户画像不写入任务快照，启动反馈工作流前从长期画像重新加载
        prev_state = await self._restore_feedback_runtime(prev_state, user_id)

        # 4. 启动异步任务（ReAct 解析 + LangGraph 工作流全在内）
        task = asyncio.create_task(self._async_feedback(
            task_id=task_id,
            user_id=user_id,
            prev_state=prev_state,
            feedback=feedback,
            outfit_index=outfit_index,
            item_index=item_index,
            dislike_colors=dislike_colors,
            dislike_item_ids=dislike_item_ids,
            retry_vton_item_ids=retry_vton_item_ids,
            want_style_tags=want_style_tags,
            note=note,
            new_round=new_round,
        ))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

        logger.info("反馈任务已启动（异步）: taskId=%s, round=%d, note=%s",
                     task_id, new_round, note[:30] if note else None)
        return task_id, None, None

    async def _supersede_disliked_item_behaviors(
        self,
        user_id: int,
        item_ids: list[int],
        reason: str,
    ) -> None:
        """将明确不喜欢的商品对应行为标记为弃用，并刷新派生画像。"""
        try:
            indexer = await get_user_behavior_indexer()
            total = 0
            for item_id in item_ids:
                try:
                    total += await asyncio.to_thread(
                        indexer.supersede_by_item,
                        user_id,
                        int(item_id),
                        reason,
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        "忽略非法不喜欢商品 ID: userId=%s, itemId=%s",
                        user_id,
                        item_id,
                    )
            if total:
                from app.services.profile_service import get_profile_service
                profile_service = await get_profile_service()
                await profile_service.invalidate_profile(user_id)
                logger.info(
                    "已纠正用户商品行为记忆: userId=%s, itemCount=%d, memoryCount=%d",
                    user_id,
                    len(item_ids),
                    total,
                )
        except Exception as e:
            logger.warning(
                "纠正用户商品行为记忆失败（不影响主流程）: userId=%s, itemIds=%s, error=%s",
                user_id,
                item_ids,
                e,
            )

    async def _async_feedback(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        feedback: str,
        outfit_index: int | None,
        item_index: int | None,
        dislike_colors: list[str] | None,
        dislike_item_ids: list[int] | None,
        retry_vton_item_ids: list[int] | None,
        want_style_tags: list[str] | None,
        note: str | None,
        new_round: int,
    ):
        """异步执行反馈轮：ReAct 解析 → action 处理 → LangGraph 工作流

        与 _async_recommend 区别：
        - credits 在同步入口 feedback() 预扣（每轮 5 credits），异步任务通过 MQ 确认/回滚
        - 复用同一 taskId，前端通过 round 字段区分轮次
        - 成功后更新 state 快照，支持继续反馈
        - 失败（解析失败/索引越界/工作流异常）通过 task status 反馈，并回滚 credits
        """
        start_time = time.monotonic()
        prev_round = new_round - 1

        try:
            # ----- 1. 反馈解析：note 非空走 ReAct（P2），否则走 parse_feedback -----
            try:
                llm_client = await get_llm_client()
                is_react_path = bool(note and note.strip())
                if is_react_path:
                    prev_state_summary = {
                        "task_id": task_id,
                        "style_tags": prev_state.get("style_tags", []),
                        "color": prev_state.get("color"),
                        "categories": prev_state.get("category_constraints", []),
                        "shop_ids": prev_state.get("shop_ids"),
                        "prev_outfits": prev_state.get("outfit_candidates", []),
                        "recent_episodes": prev_state.get("recent_episodes", []),
                    }
                    allow_long_term_memory = should_persist_preference(note)
                    tool_executor = ToolExecutor(
                        user_id=user_id,
                        allow_persistent_memory=allow_long_term_memory,
                    )
                    parsed = await llm_client.react_feedback(
                        note=note.strip(),
                        prev_state_summary=prev_state_summary,
                        tool_executor=tool_executor,
                        max_rounds=3,
                    )
                    logger.info("[ReAct] 反馈解析: taskId=%s, note=%s → %s",
                                 task_id, note[:50], parsed)
                else:
                    parsed = await llm_client.parse_feedback(feedback)
            except Exception as e:
                logger.error("LLM 反馈解析异常: taskId=%s, error=%s", task_id, e)
                await self._on_failure(task_id, user_id, "反馈解析失败，请稍后重试",
                                        need_deduct=True, stage="vton")
                self._record_workflow_metrics(start_time, "FAILED")
                return

            # ----- 2. 前端字段覆盖（优先级 > LLM 解析）-----
            if outfit_index is not None:
                parsed["outfit_index"] = outfit_index
                # refine 和 accept 不被 outfit_index 覆盖为 replace_single
                # refine：用户想精修指定搭配的换装效果，保留 outfit_index 即可
                if parsed.get("action") not in ("accept", "refine"):
                    parsed["action"] = "replace_single"
            if item_index is not None:
                parsed["item_index"] = item_index
            if dislike_colors is not None:
                parsed["dislike_colors"] = list(dislike_colors)
            if dislike_item_ids is not None:
                parsed["dislike_item_ids"] = list(dislike_item_ids)
            if retry_vton_item_ids is not None:
                parsed["retry_vton_item_ids"] = list(retry_vton_item_ids)
            if want_style_tags is not None:
                parsed["want_style_tags"] = list(want_style_tags)

            # 明确不喜欢某件商品时，同时弃用该商品对应的历史行为信号。
            # 当前任务仍由 dislike_item_ids 过滤，长期画像则异步纠正，失败不阻塞换装流程。
            disliked_item_ids = parsed.get("dislike_item_ids") or []
            if disliked_item_ids:
                correction_task = asyncio.create_task(
                    self._supersede_disliked_item_behaviors(
                        user_id=user_id,
                        item_ids=disliked_item_ids,
                        reason="用户反馈不喜欢该商品",
                    )
                )
                self._pending_tasks.add(correction_task)
                correction_task.add_done_callback(self._pending_tasks.discard)

            action = parsed.get("action", "regenerate_all")
            logger.info("反馈解析: taskId=%s, round=%d→%d, action=%s, outfitIdx=%s, itemIdx=%s, "
                         "dislikeColors=%s, dislikeItems=%s, retryVtonItems=%s, wantStyleTags=%s, feedback=%s",
                         task_id, prev_round, new_round, action,
                         parsed.get("outfit_index"), parsed.get("item_index"),
                         parsed.get("dislike_colors"), parsed.get("dislike_item_ids"),
                         parsed.get("retry_vton_item_ids"), parsed.get("want_style_tags"),
                         feedback[:50])

            # ----- 3. action=accept：用户满意，不重新生成 -----
            if action == "accept":
                await self._ws_push(user_id, {
                    "taskId": task_id,
                    "type": "OUTFIT_AGENT_FEEDBACK",
                    "status": "ACCEPTED",
                    "msg": "已采纳当前搭配",
                })
                # accept 时更新 task status 为 SUCCESS（无 outfits 字段）
                accept_status = json.dumps({
                    "status": "SUCCESS",
                    "userId": user_id,
                    "taskType": "OUTFIT_AGENT",
                    "round": new_round,
                    "accepted": True,
                    "finished": True,  # 标记已完结，阻止再次反馈
                    "finishedAt": datetime.now().isoformat(),
                }, ensure_ascii=False)
                await self.redis.set(f"{TASK_STATUS_PREFIX}{task_id}", accept_status, ex=TASK_STATUS_TTL)
                # 同步更新 state 快照中的 finished 标记
                # 否则 feedback() 入口读 prev_state 时 finished 字段缺失，可再次触发反馈
                prev_state["finished"] = True
                prev_state["round"] = new_round
                await self._save_state(task_id, prev_state)

                # O3 优化：EpisodicMemory - accept 时记录搭配事件到 Qdrant
                # 下次进入随心搭时读取作为"上次推荐回顾"，提升复购率
                # fire-and-forget，失败不阻塞主流程
                try:
                    prev_outfits = prev_state.get("outfit_candidates", [])
                    if prev_outfits:
                        # 用户采纳的是 outfit_index 指定的搭配，默认第 0 套
                        # 边界保护：LLM 可能返回 null/负数/越界值，统一回退到第 0 套
                        outfit_idx = parsed.get("outfit_index", 0)
                        if not isinstance(outfit_idx, int) or outfit_idx < 0 or outfit_idx >= len(prev_outfits):
                            outfit_idx = 0
                        accepted_outfit = prev_outfits[outfit_idx]
                        accepted_items = accepted_outfit.get("items", [])
                        episode_task = asyncio.create_task(self._record_episode(
                            user_id=user_id,
                            task_id=task_id,
                            accepted_items=accepted_items,
                            style_tags=prev_state.get("style_tags", []),
                            scene_desc=prev_state.get("scene_desc"),
                            season=prev_state.get("season"),
                        ))
                        self._pending_tasks.add(episode_task)
                        episode_task.add_done_callback(self._pending_tasks.discard)
                except Exception as e:
                    logger.warning("[EpisodicMemory] 记录搭配事件失败（不影响主流程）: %s", e)

                self._record_workflow_metrics(start_time, "SUCCESS")
                return

            # ----- 3.5 action=refine：VTON 结果精修（千问 aitryon-refiner）-----
            # 业务场景：用户对整体效果不满意但喜欢那套衣服单品，触发二次精修提升还原度
            # 不走 LangGraph 工作流，直接调 RefinerClient + 上传 OSS + 推送结果
            if action == "refine":
                await self._handle_refine_action(
                    task_id=task_id,
                    user_id=user_id,
                    prev_state=prev_state,
                    parsed=parsed,
                    new_round=new_round,
                    start_time=start_time,
                )
                return

            # ----- 4. 同会话累积 user_dislike_colors-----
            prev_dislike_colors: list[str] = list(prev_state.get("user_dislike_colors") or [])
            new_dislike_colors: list[str] = list(parsed.get("dislike_colors") or [])
            merged_dislike_colors = list(dict.fromkeys(prev_dislike_colors + new_dislike_colors))
            if merged_dislike_colors != prev_dislike_colors:
                logger.info("[用户偏好] taskId=%s, user_dislike_colors 累积: %s → %s",
                             task_id, prev_dislike_colors, merged_dislike_colors)

            # ----- 5. 异步 upsert 用户偏好到 Qdrant-----
            # - dislike_colors/dislike_styles/preferred_price_range 在 ReAct 路径下由 Tool 已写过，跳过避免双写
            # - like_styles（accept 时）无论是否 ReAct 路径都持久化（避免 ReAct 路径下
            #   LLM 未调 update_user_preference Tool 导致 like_styles 丢失）
            # 补齐 dislike_styles 和 preferred_price_range 持久化
            new_dislike_styles: list[str] = list(parsed.get("dislike_styles") or [])
            new_price_range = parsed.get("preferred_price_range") or None
            is_react_path = bool(note and note.strip())
            allow_long_term_memory = should_persist_preference(
                feedback,
                note,
                explicit_user_field=dislike_colors is not None,
            )
            should_persist_dislike = (
                not is_react_path and allow_long_term_memory and bool(new_dislike_colors)
            )
            should_persist_dislike_styles = (
                not is_react_path and allow_long_term_memory and bool(new_dislike_styles)
            )
            should_persist_price = (
                not is_react_path and allow_long_term_memory and bool(new_price_range)
            )
            # 单次 accept 属于强行为信号，不直接把整套风格写成长期显式偏好；
            # 用户明确说“以后喜欢/记住这个风格”时才持久化。
            should_persist_like = action == "accept" and allow_long_term_memory
            if should_persist_dislike or should_persist_like or should_persist_dislike_styles or should_persist_price:
                # 保存 Task 引用防止被 GC 回收（对齐 _async_recommend 模式）
                pref_task = asyncio.create_task(self._persist_user_preference(
                    user_id=user_id,
                    dislike_colors=new_dislike_colors if should_persist_dislike else None,
                    like_styles=(list(prev_state.get("style_tags", []))
                                  if should_persist_like else None),
                    dislike_styles=new_dislike_styles if should_persist_dislike_styles else None,
                    preferred_price_range=new_price_range if should_persist_price else None,
                ))
                self._pending_tasks.add(pref_task)
                pref_task.add_done_callback(self._pending_tasks.discard)

            # ----- 6. 构造新一轮 initial_state -----
            target_category = parsed.get("target_category")
            categories = prev_state.get("category_constraints", ["上衣", "下装", "鞋"])

            # 累积历史搭配
            prev_outfits = prev_state.get("outfit_candidates", [])
            history = list(prev_state.get("history_outfits", []))
            if prev_outfits:
                history.append(prev_outfits)
                if len(history) > 3:
                    history = history[-3:]

            if action == "replace_single":
                initial_state, error_msg = self._build_replace_single_state(
                    task_id=task_id,
                    user_id=user_id,
                    prev_state=prev_state,
                    parsed=parsed,
                    feedback=feedback,
                    note=note,
                    new_round=new_round,
                    history=history,
                    categories=categories,
                    merged_dislike_colors=merged_dislike_colors,
                )
                if error_msg:
                    await self._on_failure(task_id, user_id, error_msg,
                                            need_deduct=True, stage="vton")
                    self._record_workflow_metrics(start_time, "FAILED")
                    return
            else:
                if action == "replace" and target_category:
                    keep_categories = [c for c in categories if c != target_category]
                else:
                    keep_categories = []

                initial_state = {
                    "task_id": task_id,
                    "user_id": user_id,
                    "style_tags": prev_state.get("style_tags", []),
                    "scene_desc": prev_state.get("scene_desc"),
                    "photo_session_key": prev_state.get("photo_session_key"),
                    "color": prev_state.get("color"),
                    "color_is_explicit": prev_state.get("color_is_explicit", bool(prev_state.get("color"))),
                    "shop_ids": prev_state.get("shop_ids"),
                    "season": prev_state.get("season"),
                    "categories": prev_state.get("categories", []),
                    "category_constraints": categories,
                    "budget_max": prev_state.get("budget_max"),
                    "round": new_round,
                    "feedback": feedback,
                    "feedback_parsed": parsed,
                    "keep_categories": keep_categories,
                    "history_outfits": history,
                    "seen_item_ids": prev_state.get("seen_item_ids", set()),
                    "user_dislike_colors": merged_dislike_colors,
                    "dislike_item_ids": parsed.get("dislike_item_ids") or [],
                    "retry_vton_item_ids": parsed.get("retry_vton_item_ids") or [],
                    "want_style_tags": parsed.get("want_style_tags") or [],
                    "query_vector": prev_state.get("query_vector"),
                    "query_text": prev_state.get("query_text"),
                    "feedback_note": note,
                    # 性别与服装匹配：风格驱动反馈轮透传性别字段
                    "system_model_id": prev_state.get("system_model_id"),
                    "system_model_image_url": prev_state.get("system_model_image_url"),
                    "system_model_gender": prev_state.get("system_model_gender"),
                    "target_gender": prev_state.get("target_gender"),
                    "gender_source": prev_state.get("gender_source"),
                    "user_body_profile_id": prev_state.get("user_body_profile_id"),
                    # 反馈轮透传 user_profile，保持个性化增强一致性
                    "user_profile": prev_state.get("user_profile") or {},
                    "error": None,
                }

            # 反馈任务使用锁内推进后的 checkpoint 版本，避免异步结果覆盖后续反馈。
            initial_state["checkpoint_version"] = prev_state.get("checkpoint_version", 0)

            # ----- 7. 跑 LangGraph 工作流 -----
            # 全局并发槽位：限制同时运行的生成工作流数量
            async with _workflow_slot():
                final_state = await asyncio.wait_for(
                    OutfitGraphRunner.run(
                        task_id=task_id,
                        user_id=user_id,
                        style_tags=initial_state.get("style_tags", []),
                        scene_desc=initial_state.get("scene_desc"),
                        photo_session_key=initial_state.get("photo_session_key"),
                        initial_state=initial_state,
                    ),
                    timeout=ASYNC_TIMEOUT,
                )

            error = final_state.get("error")
            outfits = final_state.get("final_outfits") or []

            if error or not outfits:
                await self._on_failure(task_id, user_id, error or "未生成有效搭配",
                                        need_deduct=True, stage="vton")
                self._record_workflow_metrics(start_time, "FAILED")
            else:
                await self._on_success(task_id, user_id, outfits,
                                       need_deduct=True, stage="vton")
                await self._save_state(task_id, final_state)
                # O4 优化：反馈轮成功后也持久化 seen_item_ids（与首轮对齐）
                # 否则反馈轮新推荐的商品不会进入跨会话去重池，下次会话可能重推
                final_seen = final_state.get("seen_item_ids") or set()
                displayed_ids = self._extract_displayed_item_ids(final_state)
                if final_seen and displayed_ids:
                    await self._save_cross_session_seen_items(
                        user_id, final_seen, refresh_item_ids=displayed_ids,
                    )
                self._record_workflow_metrics(start_time, "SUCCESS")

        except WorkflowBusyError as e:
            logger.warning("反馈轮工作流并发限流: taskId=%s, msg=%s", task_id, e)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "BUSY")
        except asyncio.TimeoutError:
            logger.error("反馈轮工作流超时: taskId=%s", task_id)
            await self._on_failure(task_id, user_id, "生成超时，请重试",
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "TIMEOUT")
        except Exception as e:
            logger.error("反馈轮工作流异常: taskId=%s, error=%s", task_id, e, exc_info=True)
            await self._on_failure(task_id, user_id, str(e),
                                    need_deduct=True, stage="vton")
            self._record_workflow_metrics(start_time, "FAILED")

    def _build_replace_single_state(
        self,
        task_id: str,
        user_id: int,
        prev_state: dict,
        parsed: dict,
        feedback: str,
        note: str | None,
        new_round: int,
        history: list,
        categories: list[str],
        merged_dislike_colors: list[str],
    ) -> tuple[AgentState, str | None]:
        """构造 replace_single（点哪换哪）的 initial_state

        Returns:
            (initial_state, error_msg)：error_msg 非空表示索引越界
        """
        target_category = parsed.get("target_category")
        prev_outfits = prev_state.get("outfit_candidates", [])
        outfit_idx = parsed.get("outfit_index")
        item_idx = parsed.get("item_index")

        if outfit_idx is None or outfit_idx < 0 or outfit_idx >= len(prev_outfits):
            return None, "outfitIndex 越界或不合法"
        outfit = prev_outfits[outfit_idx]
        outfit_items = outfit.get("items", [])

        if item_idx is None and target_category:
            for i, it in enumerate(outfit_items):
                if it.get("category") == target_category:
                    item_idx = i
                    break

        if item_idx is None or item_idx < 0 or item_idx >= len(outfit_items):
            return None, "itemIndex 越界或不合法"

        target_item = outfit_items[item_idx]
        target_cat = target_item.get("category")
        if not target_cat:
            return None, "待替换单品缺少品类字段"

        keep_items = [it for i, it in enumerate(outfit_items) if i != item_idx]
        keep_categories = [it.get("category") for it in keep_items if it.get("category")]

        prev_candidates: dict[str, list[dict]] = {}
        for it in keep_items:
            cat = it.get("category")
            if cat:
                prev_candidates[cat] = [{
                    "item_id": it.get("itemId") or it.get("item_id"),
                    "category": cat,
                    "price": it.get("price"),
                    "score": it.get("score", 0),
                    "_kept_from_prev": True,
                }]

        prev_seen = set(prev_state.get("seen_item_ids", set()))
        for it in keep_items:
            iid = it.get("itemId") or it.get("item_id")
            if iid in prev_seen:
                prev_seen.discard(iid)

        logger.info("[点哪换哪] taskId=%s, outfitIdx=%s, itemIdx=%s, targetCat=%s, keep=%s",
                     task_id, outfit_idx, item_idx, target_cat, keep_categories)

        initial_state: AgentState = {
            "task_id": task_id,
            "user_id": user_id,
            "style_tags": prev_state.get("style_tags", []),
            "scene_desc": prev_state.get("scene_desc"),
            "photo_session_key": prev_state.get("photo_session_key"),
            "color": prev_state.get("color"),
            "shop_ids": prev_state.get("shop_ids"),
            "season": prev_state.get("season"),
            "categories": prev_state.get("categories", []),
            "category_constraints": categories,
            "budget_max": prev_state.get("budget_max"),
            "round": new_round,
            "feedback": feedback,
            "feedback_parsed": parsed,
            "keep_categories": keep_categories,
            "history_outfits": history,
            "seen_item_ids": prev_seen,
            "candidate_items_by_category": prev_candidates,
            "user_dislike_colors": merged_dislike_colors,
            "dislike_item_ids": parsed.get("dislike_item_ids") or [],
            "retry_vton_item_ids": parsed.get("retry_vton_item_ids") or [],
            "want_style_tags": parsed.get("want_style_tags") or [],
            "query_vector": prev_state.get("query_vector"),
            "query_text": prev_state.get("query_text"),
            "feedback_note": note,
            # 性别与服装匹配：风格驱动点哪换哪透传性别字段
            "system_model_id": prev_state.get("system_model_id"),
            "system_model_image_url": prev_state.get("system_model_image_url"),
            "system_model_gender": prev_state.get("system_model_gender"),
            "target_gender": prev_state.get("target_gender"),
            "gender_source": prev_state.get("gender_source"),
            "user_body_profile_id": prev_state.get("user_body_profile_id"),
            # 点哪换哪反馈轮透传 user_profile，保持个性化增强一致性
            "user_profile": prev_state.get("user_profile") or {},
            "error": None,
        }
        return initial_state, None


# ===== 单例（asyncio.Lock 保护延迟初始化）=====
_agent_service: AgentService | None = None
_agent_service_lock = asyncio.Lock()


async def get_agent_service() -> AgentService:
    global _agent_service
    if _agent_service is None:
        async with _agent_service_lock:
            if _agent_service is None:
                redis = await get_redis()
                _agent_service = AgentService(redis)
    return _agent_service
