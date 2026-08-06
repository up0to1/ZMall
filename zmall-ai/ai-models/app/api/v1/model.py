"""
AI 模特接口（商家端）

根据核心功能设计 §1：
  - POST /api/v1/model/generate → Java item-service 处理（校验+配额+写表+发MQ），Gateway 路由到 Java
  - POST /api/v1/model/publish  → Java item-service 处理（更新商品主图），Gateway 路由到 Java
  - GET  /api/v1/model/result/{taskId} → Python ai-models 处理（读 Redis 任务状态 + WS 推送兜底）

Python ai-models 的主要职责是 MQ 消费 ai.model.generate 队列，生成模特图后发结果到 ai.model.result 队列。

多换装模式搭配组合预览接口
  - POST /api/v1/model/outfit-combinations → 调用 LLM 推荐 1-4 套搭配组合
"""
import json
import logging
import re

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.api.deps import get_redis
from app.models.schemas import (
    ModelResultResponse,
    OutfitCombinationRequest,
    OutfitCombinationResponse,
)
from app.core.exceptions import TaskNotFoundException
from app.subgraphs.outfit_combination_subgraph import (
    recommend_outfit_combinations,
    _is_llm_configured,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/model", tags=["AI模特-商家端"])

TASK_STATUS_PREFIX = "ai:task:status:"

# H8：task_id UUID 格式校验，防止注入特殊字符污染 Redis key
_TASK_ID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


@router.get("/result/{task_id}", response_model=ModelResultResponse, summary="查询模特图结果（兜底轮询）")
async def get_result(task_id: str, request: Request):
    """查询模特图生成结果

    前端轮询此接口获取任务状态。
    正常流程：前端通过 WebSocket 实时收到结果，轮询仅作兜底。

    增加越权校验，仅任务所有者可查询结果。
    """
    # H8: UUID 格式校验，防止注入特殊字符污染 Redis key
    if not task_id or not _TASK_ID_PATTERN.match(task_id):
        return JSONResponse(status_code=400, content={"detail": "taskId 格式非法"})
    redis = await get_redis()
    data = await redis.get(f"{TASK_STATUS_PREFIX}{task_id}")
    if data:
        result = json.loads(data)
        # 越权校验——仅任务所有者可查询结果
        # userId 由 model_consumer.py 写入 Redis 任务状态（新数据含此字段）
        # request.state.user_id 由 AuthMiddleware 从 Gateway 透传的 user-info 头部注入
        task_user_id = result.get("userId")
        current_user_id = getattr(request.state, "user_id", None)
        if task_user_id is not None and current_user_id is not None:
            if int(task_user_id) != int(current_user_id):
                logger.warning(
                    "IDOR 越权拦截：用户 %s 尝试查询任务 %s（所有者 %s）的结果",
                    current_user_id, task_id, task_user_id,
                )
                return JSONResponse(status_code=403, content={"detail": "无权访问该任务"})
        # 兼容性：若 task_user_id 为 None（旧数据未写入 userId），暂不拦截，依赖 TTL 1h 自然失效
        return ModelResultResponse(
            taskId=task_id,
            status=result.get("status", "PROCESSING"),
            resultUrls=result.get("resultUrls"),
            errorMsg=result.get("errorMsg"),
        )
    raise TaskNotFoundException(f"任务 {task_id} 不存在或已过期")


@router.post(
    "/outfit-combinations",
    response_model=OutfitCombinationResponse,
    summary="预览多换装搭配组合（v5 多换装模式）",
)
async def preview_outfit_combinations(req: OutfitCombinationRequest, request: Request):
    """预览多换装模式的搭配组合

    商家在前端选择多件商品后，调用本接口预览 LLM 推荐的搭配组合。
    - 输入：商家选定的商品列表（含 itemId/category/name/color/styleTags）
    - 输出：1-4 套合法搭配组合 + 每套的推荐理由
    - LLM 不可用时降级为规则笛卡尔积

    用途：
    1. 前端展示"AI 已为您推荐 N 套搭配方案"预览
    2. 商家可基于预览结果调整商品选择，再提交生成任务
    3. Java 侧 createModelGenerateTask 也可调用本接口预生成组合
    """
    user_id = getattr(request.state, "user_id", None)
    items = [it.model_dump() for it in req.items]

    if not items:
        return OutfitCombinationResponse(
            combinations=[], reasons=[], source="fallback",
        )

    logger.info(
        "[搭配预览] userId=%s, 商品数=%d, items=%s",
        user_id, len(items), [it.get("itemId") for it in items],
    )

    use_llm = _is_llm_configured()
    combinations, reasons = await recommend_outfit_combinations(items, use_llm=use_llm)
    source = "llm" if use_llm else "fallback"

    logger.info(
        "[搭配预览] userId=%s, 推荐套数=%d, source=%s",
        user_id, len(combinations), source,
    )

    return OutfitCombinationResponse(
        combinations=combinations,
        reasons=reasons,
        source=source,
    )
