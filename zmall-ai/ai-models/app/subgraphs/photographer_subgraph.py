"""
摄影师子 Agent

设计文档 §1.8.2 + §1.8.5：
- 策划阶段：从三级池推荐最匹配的模特图（仅商家未指定时调用）
- 评估阶段：评估 VTON 输出图的姿势自然度 + 构图完整性

ai-models 修正：LLM 配置从 settings 读取（不再依赖 ai-outfit 的 LlmClient）。
"""
import json
import logging

# retry 接口 _call_llm_with_retry / _call_vision_llm_with_retry
# （返回 LLMResult，含 is_fallback 标记，区分真实输出与降级值）
from app.subgraphs._llm import (
    _call_llm_with_retry,
    _call_vision_llm_with_retry,
    encode_image_b64,
    LLM_PLAN_TIMEOUT,
)
from app.prompts.director_prompts import (
    PHOTOGRAPHER_SYSTEM_PROMPT,
    PHOTOGRAPHER_PLAN_PROMPT, PHOTOGRAPHER_REVIEW_PROMPT,
)

logger = logging.getLogger(__name__)


async def photographer_plan(
    text_model: str,
    items: list[dict], candidates: list[dict],
) -> dict | None:
    """摄影师策划阶段：推荐模特图（仅商家未指定时调用）

    Returns:
        {"recommended_model_id": int, "pose_match_score": 0-1, "background_match_score": 0-1, "reason": "..."}
        LLM 失败时返回降级值（取候选第 1 个）
    """
    fallback = {
        "recommended_model_id": candidates[0].get("id") if candidates else None,
        "pose_match_score": 0.5, "background_match_score": 0.5,
        "reason": "LLM 不可用，降级取候选第 1 个",
    }
    if not candidates:
        return {"recommended_model_id": None, "pose_match_score": 0.0,
                "background_match_score": 0.0, "reason": "无候选模特图"}

    user_prompt = PHOTOGRAPHER_PLAN_PROMPT.format(
        items_json=json.dumps(items, ensure_ascii=False),
        candidates_json=json.dumps(candidates, ensure_ascii=False),
    )
    # 改用 _call_llm_with_retry，根据 LLMResult.is_fallback 判断降级
    result = await _call_llm_with_retry(
        model=text_model,
        system_prompt=PHOTOGRAPHER_SYSTEM_PROMPT, user_prompt=user_prompt,
        timeout=LLM_PLAN_TIMEOUT,
        agent_name="photographer_plan",
    )
    if result.is_fallback or result.data is None:
        return fallback
    data = result.data
    return {
        "recommended_model_id": data.get("recommended_model_id"),
        "pose_match_score": float(data.get("pose_match_score", 0.5)),
        "background_match_score": float(data.get("background_match_score", 0.5)),
        "reason": data.get("reason", ""),
    }


async def photographer_review(
    vision_model: str,
    image_bytes: bytes,
) -> dict | None:
    """摄影师评估阶段：评估 VTON 输出图的姿势自然度 + 构图完整性

    Returns:
        {"pose_naturalness_score": 0-1, "composition_break_score": 0-1, "issues": [...]}
        LLM 失败时返回降级值（评分 0.5 中位）
    """
    fallback = {
        "pose_naturalness_score": 0.5,
        "composition_break_score": 0.5,
        "issues": [],
    }
    image_b64 = encode_image_b64(image_bytes)
    text_prompt = PHOTOGRAPHER_REVIEW_PROMPT.format(image_b64="[图像已附]")
    # 改用 _call_vision_llm_with_retry，根据 LLMResult.is_fallback 判断降级
    result = await _call_vision_llm_with_retry(
        model=vision_model,
        system_prompt=PHOTOGRAPHER_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
        agent_name="photographer_review",
    )
    if result.is_fallback or result.data is None:
        return fallback
    data = result.data
    return {
        "pose_naturalness_score": float(data.get("pose_naturalness_score", 0.5)),
        "composition_break_score": float(data.get("composition_break_score", 0.5)),
        "issues": list(data.get("issues") or []),
    }
