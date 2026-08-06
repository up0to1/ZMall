"""
AI 模特多 Agent 决策 HTTP 接口（调试用）

注：MQ 消费路径（model_consumer._process_task）直接 import 调用
run_model_agent_workflow，不走 HTTP。此接口仅用于：
  - 本地开发调试（curl 触发单次多 Agent 工作流）
  - 健康检查时验证多 Agent 服务可用性
  - 后续如需对外暴露多 Agent 能力（如管理后台手动触发）
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.model_agent_service import run_model_agent_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/model", tags=["AI 模特多 Agent 决策（调试接口）"])


class ModelAgentRequest(BaseModel):
    """AI 模特多 Agent 请求体（与 ai.model.generate MQ 消息体对齐）"""
    taskId: str
    shopId: int | None = None
    userId: int | None = None
    items: list[dict]
    itemIds: list[int] = []
    modelImageUrl: str | None = None
    modelImageCandidates: list[dict] = []
    saveToShopPool: bool = False


@router.post("/agent/generate", summary="执行 AI 模特多 Agent 决策工作流（调试用）")
async def generate_with_multi_agent(req: ModelAgentRequest):
    """执行 AI 模特多 Agent 决策工作流（调试接口，MQ 消费走直接 import）

    流程：
    1. 策划阶段：5 角色 Agent 并行评估（EU/Asia 衣品审美 + 摄影师推荐模特图）
    2. VTON 执行：按导演决策的顺序链式 VTON
    3. 评估阶段：5 角色 Agent 并行评估（VTON 执行质量 + 光照 + 妆容 + 构图）
    4. 后处理（可选）：按灯光师/化妆师建议调图（限 1 轮）
    5. OSS 上传：所有中间图 + 最终图 + 后处理版

    返回结果与 ai.model.result MQ 消息体对齐。
    """
    message = {
        "taskId": req.taskId,
        "shopId": req.shopId or 0,
        "userId": req.userId or 0,
        "items": req.items,
        "itemIds": req.itemIds,
        "modelImageUrl": req.modelImageUrl,
        "modelImageCandidates": req.modelImageCandidates,
        "saveToShopPool": req.saveToShopPool,
    }
    return await run_model_agent_workflow(message)
