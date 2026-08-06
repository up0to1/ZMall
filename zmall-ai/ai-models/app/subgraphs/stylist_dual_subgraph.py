"""
衣品审美大师双视角子 Agent（EU + Asia 合并版，v3 优化）

优化点：
- 原 EU/Asia 两次独立 LLM 调用合并为单次，节省 33% 策划阶段 LLM 成本
- 同一次 LLM 调用同时输出欧美和亚洲双视角的风格特征与冲突点
- 评估阶段同样合并为单次 Vision LLM 调用，双视角评分

与原 stylist_subgraph.py 的对应关系：
- stylist_dual_plan → 替代 stylist_eu_plan + stylist_asia_plan
- stylist_dual_review → 替代 stylist_eu_review + stylist_asia_review

返回值兼容：
- stylist_dual_plan 返回 {style_features, eu_conflicts, asia_conflicts, divergence_description}
  导演节点会拆分为 eu_plan / asia_plan 字段存入 state（向后兼容前端展示）
- stylist_dual_review 返回 {eu_vton_quality_score, asia_vton_quality_score, ...}
  导演节点会拆分为 eu_review / asia_review 字段存入 state
"""
import json
import logging

from app.prompts.director_prompts import (
    STYLIST_DUAL_SYSTEM_PROMPT,
    STYLIST_DUAL_PLAN_PROMPT,
    STYLIST_DUAL_REVIEW_PROMPT,
)
from app.subgraphs._llm import (
    _call_llm_with_retry, _call_vision_llm_with_retry,
    encode_image_b64, llm_cache,
    LLM_PLAN_TIMEOUT, LLM_REVIEW_TIMEOUT,
)

logger = logging.getLogger(__name__)


async def stylist_dual_plan(
    text_model: str,
    items: list[dict], model_info: dict,
) -> dict | None:
    """双视角衣品审美大师策划阶段：单次 LLM 调用输出 EU+Asia 双视角

    Args:
        text_model: 纯文本模型名（如 qwen-flash）
        items: 商品列表
        model_info: 模特图信息
    Returns:
        {
            "style_features": "...",
            "eu_conflicts": [...],
            "asia_conflicts": [...],
            "divergence_description": "...",
            "is_fallback": bool   # 是否为降级值
        }
    """
    fallback = {
        "style_features": "",
        "eu_conflicts": [],
        "asia_conflicts": [],
        "divergence_description": "",
        "is_fallback": True,
    }

    # LLM 结果缓存：相同商品+模特图的策划结果秒级返回
    cached = await llm_cache.get("stylist_dual_plan", items, model_info)
    if cached is not None:
        logger.info("[Stylist·双视角策划] 命中缓存，秒级返回")
        cached["is_fallback"] = False
        return cached

    user_prompt = STYLIST_DUAL_PLAN_PROMPT.format(
        items_json=json.dumps(items, ensure_ascii=False),
        model_info=json.dumps(model_info, ensure_ascii=False),
    )
    llm_result = await _call_llm_with_retry(
        model=text_model,
        system_prompt=STYLIST_DUAL_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        agent_name="stylist_dual_plan",
        timeout=LLM_PLAN_TIMEOUT,
        temperature=0.3,  # 策划阶段需要创意
    )
    if llm_result.is_fallback or llm_result.data is None:
        return fallback

    data = {
        "style_features": llm_result.data.get("style_features", ""),
        "eu_conflicts": list(llm_result.data.get("eu_conflicts") or []),
        "asia_conflicts": list(llm_result.data.get("asia_conflicts") or []),
        "divergence_description": llm_result.data.get("divergence_description", ""),
        "is_fallback": False,
    }

    # 写入缓存
    await llm_cache.set("stylist_dual_plan", items, model_info, data)
    return data


async def stylist_dual_review(
    vision_model: str,
    image_bytes: bytes, items: list[dict],
) -> dict | None:
    """双视角衣品审美大师评估阶段：单次 Vision LLM 调用输出 EU+Asia 双视角评分

    Args:
        vision_model: 视觉模型名（如 qwen3.5-flash）
        image_bytes: VTON 结果图字节
        items: 商品列表
    Returns:
        {
            "eu_vton_quality_score": 0.0-1.0,
            "asia_vton_quality_score": 0.0-1.0,
            "eu_color_distortion": "...",
            "asia_color_distortion": "...",
            "pattern_deformation": "...",
            "fit_issue": "...",
            "suggestion": "...",
            "is_fallback": bool
        }
    """
    fallback = {
        "eu_vton_quality_score": 0.5,
        "asia_vton_quality_score": 0.5,
        "eu_color_distortion": "",
        "asia_color_distortion": "",
        "pattern_deformation": "",
        "fit_issue": "",
        "suggestion": "",
        "is_fallback": True,
    }

    image_b64 = encode_image_b64(image_bytes)
    text_prompt = STYLIST_DUAL_REVIEW_PROMPT.format(
        image_b64="[图像已附]",
        items_json=json.dumps(items, ensure_ascii=False),
    )
    llm_result = await _call_vision_llm_with_retry(
        model=vision_model,
        system_prompt=STYLIST_DUAL_SYSTEM_PROMPT,
        text_prompt=text_prompt, image_b64=image_b64,
        agent_name="stylist_dual_review",
        timeout=LLM_REVIEW_TIMEOUT,
        temperature=0.0,  # 评估阶段需要稳定
    )
    if llm_result.is_fallback or llm_result.data is None:
        return fallback

    return {
        "eu_vton_quality_score": float(llm_result.data.get("eu_vton_quality_score", 0.5)),
        "asia_vton_quality_score": float(llm_result.data.get("asia_vton_quality_score", 0.5)),
        "eu_color_distortion": llm_result.data.get("eu_color_distortion", ""),
        "asia_color_distortion": llm_result.data.get("asia_color_distortion", ""),
        "pattern_deformation": llm_result.data.get("pattern_deformation", ""),
        "fit_issue": llm_result.data.get("fit_issue", ""),
        "suggestion": llm_result.data.get("suggestion", ""),
        "is_fallback": False,
    }
