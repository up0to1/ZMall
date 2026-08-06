"""
灯光师子 Agent（v3 增强）

增强点：
1. 使用 _call_vision_llm_with_retry 接口（带重试 + fallback 标记 + 埋点）
2. 返回值新增 is_fallback 字段，便于导演识别"LLM 调用失败"vs"真实打分 0.5"
3. 新增 view_other_reviews 工具支持（ReAct 反思机制，评估阶段可读取其他 Agent 的评估结果）

设计文档 §1.8.2 + §1.8.5：
- 仅评估阶段介入（策划阶段无图可评）
- 输出光照评分 + 中文后处理意图（由导演翻译为英文图生图 prompt）
"""
import json
import logging

from app.subgraphs._llm import _call_vision_llm_with_retry, encode_image_b64, LLM_REVIEW_TIMEOUT
from app.prompts.director_prompts import (
    LIGHTING_SYSTEM_PROMPT, LIGHTING_REVIEW_PROMPT,
    LIGHTING_REACT_REVIEW_PROMPT,
)

logger = logging.getLogger(__name__)


async def lighting_review(
    vision_model: str,
    image_bytes: bytes, style_tags: list[str], skin_tone: str,
    other_reviews: dict | None = None,
) -> dict | None:
    """灯光师评估阶段：评估光照 + 输出中文后处理意图

    Args:
        vision_model: 视觉模型名（如 qwen3.5-flash）
        image_bytes: VTON 结果图字节
        style_tags: 商品风格标签（如 ["商务", "通勤"]）
        skin_tone: 模特肤色（fair / medium / dark）
        other_reviews: 其他 Agent 的评估结果（ReAct 反思机制用）
            格式：{"stylist_eu": {...}, "makeup": {...}, "photographer": {...}}
            为 None 或空 dict 时走原 prompt（不引入反思）
    Returns:
        {
            "lighting_score": 0-1,
            "issues": [...],
            "post_process_intent_cn": "...",
            "is_fallback": bool
        }
    """
    fallback = {
        "lighting_score": 0.5,
        "issues": [],
        "post_process_intent_cn": "",
        "is_fallback": True,
    }
    image_b64 = encode_image_b64(image_bytes)

    # ReAct 反思机制：传入其他 Agent 的评估结果，让灯光师做"专家会诊"
    if other_reviews:
        other_reviews_json = json.dumps(other_reviews, ensure_ascii=False)
        text_prompt = LIGHTING_REACT_REVIEW_PROMPT.format(
            image_b64="[图像已附]",
            style_tags_json=json.dumps(style_tags, ensure_ascii=False),
            skin_tone=skin_tone or "medium",
            other_reviews_json=other_reviews_json,
        )
        agent_name = "lighting_review_react"
    else:
        text_prompt = LIGHTING_REVIEW_PROMPT.format(
            image_b64="[图像已附]",
            style_tags_json=json.dumps(style_tags, ensure_ascii=False),
            skin_tone=skin_tone or "medium",
        )
        agent_name = "lighting_review"

    llm_result = await _call_vision_llm_with_retry(
        model=vision_model,
        system_prompt=LIGHTING_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
        agent_name=agent_name,
        timeout=LLM_REVIEW_TIMEOUT,
        temperature=0.0,
    )
    if llm_result.is_fallback or llm_result.data is None:
        return fallback
    return {
        "lighting_score": float(llm_result.data.get("lighting_score", 0.5)),
        "issues": list(llm_result.data.get("issues") or []),
        "post_process_intent_cn": llm_result.data.get("post_process_intent_cn", ""),
        "is_fallback": False,
    }
