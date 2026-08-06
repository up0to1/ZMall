"""
衣品审美大师子 Agent（EU + Asia 双视角）

设计文档 §1.8.2 + §1.8.5：衣品审美大师在策划阶段输出风格特征描述（信息层），
评估阶段评 VTON 执行质量（不评商品组合合理性）。

实现方式：每个子 Agent 是一个 async 函数（不是独立 StateGraph），被导演节点用
asyncio.gather 并行调用。这种方式比 LangGraph Send API 更简单可控。

ai-models 修正：LLM 配置从 settings 读取（不再依赖 ai-outfit 的 LlmClient 类），
所有 LLM 调用通过 app.subgraphs._llm 中的工具函数完成。
"""
import json
import logging

from app.prompts.director_prompts import (
    STYLIST_EU_SYSTEM_PROMPT, STYLIST_EU_PLAN_PROMPT, STYLIST_EU_REVIEW_PROMPT,
    STYLIST_ASIA_SYSTEM_PROMPT, STYLIST_ASIA_PLAN_PROMPT, STYLIST_ASIA_REVIEW_PROMPT,
)
from app.subgraphs._llm import (
    _call_llm, _call_vision_llm, encode_image_b64,
    LLM_PLAN_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ===== 衣品审美大师 EU =====

async def stylist_eu_plan(
    text_model: str,
    items: list[dict], model_info: dict,
) -> dict | None:
    """EU 衣品审美大师策划阶段：输出风格特征 + 欧美视角冲突点（信息层）

    Args:
        text_model: 纯文本模型名（如 qwen-flash），由调用方从 settings 传入
        items: 商品列表
        model_info: 模特图信息
    Returns:
        {"style_features": "...", "style_conflicts": [...]}
        LLM 失败时返回降级值 {"style_features": "", "style_conflicts": []}
    """
    fallback = {"style_features": "", "style_conflicts": []}
    user_prompt = STYLIST_EU_PLAN_PROMPT.format(
        items_json=json.dumps(items, ensure_ascii=False),
        model_info=json.dumps(model_info, ensure_ascii=False),
    )
    result = await _call_llm(
        model=text_model,
        system_prompt=STYLIST_EU_SYSTEM_PROMPT, user_prompt=user_prompt,
        timeout=LLM_PLAN_TIMEOUT,
    )
    if result is None:
        return fallback
    return {
        "style_features": result.get("style_features", ""),
        "style_conflicts": list(result.get("style_conflicts") or []),
    }


async def stylist_eu_review(
    vision_model: str,
    image_bytes: bytes, items: list[dict],
) -> dict | None:
    """EU 衣品审美大师评估阶段：评 VTON 执行质量（颜色失真/图案变形/贴合度/风格破坏）

    Args:
        vision_model: 视觉模型名（如 qwen3.5-flash），由调用方从 settings 传入
        image_bytes: VTON 结果图字节
        items: 商品列表
    Returns:
        {"vton_quality_score": 0.0-1.0, "color_distortion": "...", ...}
        LLM 失败时返回降级值（评分 0.5 中位）
    """
    fallback = {
        "vton_quality_score": 0.5, "color_distortion": "",
        "pattern_deformation": "", "fit_issue": "", "suggestion": "",
    }
    image_b64 = encode_image_b64(image_bytes)
    text_prompt = STYLIST_EU_REVIEW_PROMPT.format(
        image_b64=f"[图像已附]",
        items_json=json.dumps(items, ensure_ascii=False),
    )
    result = await _call_vision_llm(
        model=vision_model,
        system_prompt=STYLIST_EU_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
    )
    if result is None:
        return fallback
    return {
        "vton_quality_score": float(result.get("vton_quality_score", 0.5)),
        "color_distortion": result.get("color_distortion", ""),
        "pattern_deformation": result.get("pattern_deformation", ""),
        "fit_issue": result.get("fit_issue", ""),
        "suggestion": result.get("suggestion", ""),
    }


# ===== 衣品审美大师 Asia =====

async def stylist_asia_plan(
    text_model: str,
    items: list[dict], model_info: dict,
) -> dict | None:
    """Asia 衣品审美大师策划阶段：输出风格特征 + 亚洲视角冲突点"""
    fallback = {"style_features": "", "style_conflicts": []}
    user_prompt = STYLIST_ASIA_PLAN_PROMPT.format(
        items_json=json.dumps(items, ensure_ascii=False),
        model_info=json.dumps(model_info, ensure_ascii=False),
    )
    result = await _call_llm(
        model=text_model,
        system_prompt=STYLIST_ASIA_SYSTEM_PROMPT, user_prompt=user_prompt,
        timeout=LLM_PLAN_TIMEOUT,
    )
    if result is None:
        return fallback
    return {
        "style_features": result.get("style_features", ""),
        "style_conflicts": list(result.get("style_conflicts") or []),
    }


async def stylist_asia_review(
    vision_model: str,
    image_bytes: bytes, items: list[dict],
) -> dict | None:
    """Asia 衣品审美大师评估阶段：评 VTON 执行质量"""
    fallback = {
        "vton_quality_score": 0.5, "color_distortion": "",
        "pattern_deformation": "", "fit_issue": "", "suggestion": "",
    }
    image_b64 = encode_image_b64(image_bytes)
    text_prompt = STYLIST_ASIA_REVIEW_PROMPT.format(
        image_b64=f"[图像已附]",
        items_json=json.dumps(items, ensure_ascii=False),
    )
    result = await _call_vision_llm(
        model=vision_model,
        system_prompt=STYLIST_ASIA_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
    )
    if result is None:
        return fallback
    return {
        "vton_quality_score": float(result.get("vton_quality_score", 0.5)),
        "color_distortion": result.get("color_distortion", ""),
        "pattern_deformation": result.get("pattern_deformation", ""),
        "fit_issue": result.get("fit_issue", ""),
        "suggestion": result.get("suggestion", ""),
    }
