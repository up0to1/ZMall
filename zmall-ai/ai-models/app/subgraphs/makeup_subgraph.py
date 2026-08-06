"""
化妆师子 Agent（v3 增强）

增强点：
1. 使用 _call_vision_llm_with_retry 接口（带重试 + fallback 标记 + 埋点）
2. 返回值新增 is_fallback 字段
3. 新增 other_reviews 参数（ReAct 反思机制）
"""
import json
import logging

from app.subgraphs._llm import _call_vision_llm_with_retry, encode_image_b64, LLM_REVIEW_TIMEOUT
from app.prompts.director_prompts import (
    MAKEUP_SYSTEM_PROMPT, MAKEUP_REVIEW_PROMPT,
    MAKEUP_REACT_REVIEW_PROMPT,
)

logger = logging.getLogger(__name__)


async def makeup_review(
    vision_model: str,
    image_bytes: bytes, gender: str, skin_tone: str, style_tags: list[str],
    other_reviews: dict | None = None,
) -> dict | None:
    """化妆师评估阶段：评估妆容 + 输出中文后处理意图

    Args:
        vision_model: 视觉模型名（如 qwen3.5-flash）
        image_bytes: VTON 结果图字节
        gender: 模特性别（male / female）
        skin_tone: 模特肤色（fair / medium / dark）
        style_tags: 商品风格标签
        other_reviews: 其他 Agent 的评估结果（ReAct 反思机制用）
    Returns:
        {
            "makeup_score": 0-1,
            "issues": [...],
            "post_process_intent_cn": "...",
            "is_fallback": bool
        }
    """
    fallback = {
        "makeup_score": 0.5,
        "issues": [],
        "post_process_intent_cn": "",
        "is_fallback": True,
    }
    image_b64 = encode_image_b64(image_bytes)

    if other_reviews:
        text_prompt = MAKEUP_REACT_REVIEW_PROMPT.format(
            image_b64="[图像已附]",
            gender=gender or "female",
            skin_tone=skin_tone or "medium",
            style_tags_json=json.dumps(style_tags, ensure_ascii=False),
            other_reviews_json=json.dumps(other_reviews, ensure_ascii=False),
        )
        agent_name = "makeup_review_react"
    else:
        text_prompt = MAKEUP_REVIEW_PROMPT.format(
            image_b64="[图像已附]",
            gender=gender or "female",
            skin_tone=skin_tone or "medium",
            style_tags_json=json.dumps(style_tags, ensure_ascii=False),
        )
        agent_name = "makeup_review"

    llm_result = await _call_vision_llm_with_retry(
        model=vision_model,
        system_prompt=MAKEUP_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
        agent_name=agent_name,
        timeout=LLM_REVIEW_TIMEOUT,
        temperature=0.0,
    )
    if llm_result.is_fallback or llm_result.data is None:
        return fallback
    return {
        "makeup_score": float(llm_result.data.get("makeup_score", 0.5)),
        "issues": list(llm_result.data.get("issues") or []),
        "post_process_intent_cn": llm_result.data.get("post_process_intent_cn", ""),
        "is_fallback": False,
    }
