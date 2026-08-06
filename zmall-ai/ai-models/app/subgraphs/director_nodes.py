"""
导演节点（Supervisor · 主 Agent）v3 增强版

v3 增强点：
1. 策划阶段：合并 EU/Asia stylist 为单次 LLM 调用（节省 33% LLM 成本）
2. 策划阶段：决策多 VTON 顺序候选（1-3 个，供多 Agent 并行投票）
3. 评估阶段：ReAct 反思机制（子 Agent 可读取其他 Agent 评估结果做专家会诊）
4. 评估阶段：多候选投票（Director 综合评分选最优候选）
5. 评估阶段：决策可解释性（输出 decision_reason_cn + issues_summary）
6. 重评阶段：只跑受影响维度（按 post_process_actions[].type 选择 Agent）
7. 后处理回归校验：后处理后评分低于原评分 0.1 时回退到原图
8. LLM 调用：使用 _call_llm_with_retry（带重试 + fallback 标记 + 埋点）
9. LLM 结果缓存：策划阶段输出按 hash(items+model_info) 缓存，TTL 1h
"""
import asyncio
import json
import logging

from app.core.config import settings
from app.subgraphs._llm import (
    _call_llm_with_retry,
    LLM_PLAN_TIMEOUT,
)
from app.subgraphs.stylist_dual_subgraph import stylist_dual_plan, stylist_dual_review
from app.subgraphs.photographer_subgraph import (
    photographer_plan, photographer_review,
)
from app.subgraphs.lighting_subgraph import lighting_review
from app.subgraphs.makeup_subgraph import makeup_review
from app.prompts.director_prompts import (
    DIRECTOR_SYSTEM_PROMPT, DIRECTOR_PLAN_V3_PROMPT, DIRECTOR_REVIEW_V3_PROMPT,
)
from app.schemas.director_state import DirectorState

logger = logging.getLogger(__name__)

# VTON 顺序的默认排序（Java 侧原硬编码顺序，作为 LLM 决策失败时的降级）
# 移除"包/配饰"以及"鞋/帽子"——这几类不走 VTON，由 wan2.7-image 处理
# 2026-08-06 调整：鞋/帽子改走 wan2.7-image（aitryon-plus 不支持鞋/帽类换装），下装保留 VTON
DEFAULT_VTON_ORDER = ["全身套装", "上衣", "下装"]

# 多候选生成的商品数阈值（少于 3 件商品不生成多候选，避免无意义的重排）
MULTI_CANDIDATE_MIN_ITEMS = 3

# 多候选最大数量（成本控制）
MAX_CANDIDATES = 3

# 后处理回归校验阈值（后处理后评分下降超过此值则回退到原图）
POST_PROCESS_REGRESSION_THRESHOLD = 0.1


def _score_to_star(score: float) -> int:
    if score >= 0.9:
        return 5
    if score >= 0.8:
        return 4
    if score >= 0.6:
        return 3
    if score >= 0.4:
        return 2
    return 1


def _llm_configured() -> bool:
    """检查 LLM 是否已配置"""
    return bool(
        settings.llm_api_url and settings.llm_api_key
        and (settings.llm_text_model or settings.llm_vision_model)
    )


def _build_model_info(state: DirectorState) -> dict:
    """构造给 LLM 的模特图信息"""
    if state.get("uploaded_model_url"):
        return {"source": "商家上传", "url": state["uploaded_model_url"]}
    if state.get("selected_model_image"):
        m = state["selected_model_image"]
        return {
            "source": "系统池",
            "id": m.get("id"),
            "gender": m.get("gender"),
            "skinTone": m.get("skinTone"),
            "pose": m.get("pose"),
            "background": m.get("background"),
        }
    return {"source": "未指定"}


# ============================================================================
# 策划阶段节点（v3：合并 stylist + 多候选决策）
# ============================================================================

async def director_plan_node(state: DirectorState) -> dict:
    """策划阶段节点：并行派发双视角 stylist + 摄影师 + 导演汇总决策多候选

    v3 优化：
    - 合并 EU/Asia stylist 为单次 LLM 调用（并行 3→2）
    - 导演决策 1-3 个 VTON 顺序候选（供多 Agent 并行投票）
    - LLM 结果缓存（相同商品+模特图秒级返回）

    Returns:
        更新 state 的字段：stylist_dual_plan, stylist_eu_plan, stylist_asia_plan,
        photographer_plan, vton_order_candidates, vton_order, vton_order_reason,
        selected_model_image, style_features, style_features_divergence,
        style_conflicts_summary
    """
    items = state.get("items", [])
    candidates = state.get("model_image_candidates", [])
    uploaded_model_url = state.get("uploaded_model_url")
    model_info = _build_model_info(state)

    text_model = settings.llm_text_model

    # 并行派发 2 个子 Agent（v3：原 3 个降为 2 个）
    tasks = [
        stylist_dual_plan(text_model, items, model_info),
    ]
    if not uploaded_model_url and candidates:
        tasks.append(photographer_plan(text_model, items, candidates))
    else:
        tasks.append(asyncio.sleep(0, result=None))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    stylist_dual_result = results[0] if not isinstance(results[0], Exception) else None
    photographer_result = results[1] if (len(results) > 1 and not isinstance(results[1], Exception)) else None

    if stylist_dual_result is None:
        stylist_dual_result = {
            "style_features": "", "eu_conflicts": [], "asia_conflicts": [],
            "divergence_description": "", "is_fallback": True,
        }

    # 选定模特图
    selected_model_image = None
    if uploaded_model_url:
        selected_model_image = {"url": uploaded_model_url, "source": "upload"}
    elif photographer_result and photographer_result.get("recommended_model_id"):
        rec_id = photographer_result["recommended_model_id"]
        candidate = next((c for c in candidates if c.get("id") == rec_id), None)
        if candidate:
            url = candidate.get("url") or candidate.get("imageUrl") or ""
            selected_model_image = {
                "url": url, "source": "system_pool",
                "id": candidate.get("id"),
                "gender": candidate.get("gender", "female"),
                "skinTone": candidate.get("skinTone", "medium"),
                "pose": candidate.get("pose", ""),
                "background": candidate.get("background", ""),
            }

    # 导演汇总：决策多 VTON 顺序候选 + 风格特征汇总
    vton_order_candidates, vton_order, vton_order_reason, style_features, style_features_divergence, style_conflicts_summary = (
        await _director_plan_collect_v3(
            stylist_dual_result, photographer_result,
            uploaded_model_url, items,
        )
    )

    # 向后兼容：从 dual_result 拆分 eu_plan / asia_plan
    stylist_eu_plan_compat = {
        "style_features": stylist_dual_result.get("style_features", ""),
        "style_conflicts": stylist_dual_result.get("eu_conflicts", []),
    }
    stylist_asia_plan_compat = {
        "style_features": stylist_dual_result.get("style_features", ""),
        "style_conflicts": stylist_dual_result.get("asia_conflicts", []),
    }

    logger.info(
        "[导演·策划v3] taskId=%s, candidates=%d, main_order=%s, style=%s, model_source=%s",
        state.get("task_id"), len(vton_order_candidates), vton_order, style_features,
        selected_model_image.get("source") if selected_model_image else "未指定",
    )

    return {
        "stylist_dual_plan": stylist_dual_result,
        # 向后兼容字段
        "stylist_eu_plan": stylist_eu_plan_compat,
        "stylist_asia_plan": stylist_asia_plan_compat,
        "photographer_plan": photographer_result,
        "vton_order_candidates": vton_order_candidates,
        "vton_order": vton_order,
        "vton_order_reason": vton_order_reason,
        "selected_model_image": selected_model_image or {},
        "style_features": style_features,
        "style_features_divergence": style_features_divergence,
        "style_conflicts_summary": style_conflicts_summary,
    }


async def _director_plan_collect_v3(
    stylist_dual: dict, photographer: dict | None,
    uploaded_model_url: str | None, items: list[dict],
) -> tuple[list[list[str]], list[str], str, str, str, list[str]]:
    """导演策划阶段汇总（v3：多候选决策）

    LLM 不可用时降级：
    - 单候选：DEFAULT_VTON_ORDER 按 items 顺序过滤
    """
    items_categories = [it.get("category", "") for it in items]
    fallback_order = [c for c in DEFAULT_VTON_ORDER if c in items_categories]
    if not fallback_order:
        fallback_order = items_categories

    fallback_features = stylist_dual.get("style_features", "")
    fallback_divergence = stylist_dual.get("divergence_description", "")
    fallback_conflicts = (
        list(stylist_dual.get("eu_conflicts", []))
        + list(stylist_dual.get("asia_conflicts", []))
    )

    if not _llm_configured():
        # LLM 不可用 → 单候选降级
        return [fallback_order], fallback_order, "LLM 不可用，降级默认顺序", fallback_features, fallback_divergence, fallback_conflicts

    # 调 LLM 决策多候选
    user_prompt = DIRECTOR_PLAN_V3_PROMPT.format(
        stylist_dual_json=json.dumps(stylist_dual, ensure_ascii=False),
        photographer_json=json.dumps(photographer or {}, ensure_ascii=False),
        uploaded_model_url=uploaded_model_url or "未指定",
    )
    llm_result = await _call_llm_with_retry(
        model=settings.llm_text_model,
        system_prompt=DIRECTOR_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        agent_name="director_plan_v3",
        timeout=LLM_PLAN_TIMEOUT,
        temperature=0.3,
    )
    if llm_result.is_fallback or llm_result.data is None:
        return [fallback_order], fallback_order, "LLM 调用失败，降级默认顺序", fallback_features, fallback_divergence, fallback_conflicts

    # 解析多候选
    raw_candidates = llm_result.data.get("vton_order_candidates") or []
    valid_candidates: list[list[str]] = []
    for cand in raw_candidates[:MAX_CANDIDATES]:
        valid_cand = [c for c in cand if c in items_categories]
        if valid_cand and valid_cand not in valid_candidates:
            valid_candidates.append(valid_cand)

    # 商品数 < 3 时不生成多候选
    if len(items) < MULTI_CANDIDATE_MIN_ITEMS:
        valid_candidates = valid_candidates[:1]

    if not valid_candidates:
        valid_candidates = [fallback_order]

    main_order = valid_candidates[0]
    return (
        valid_candidates,
        main_order,
        llm_result.data.get("vton_order_reason", ""),
        llm_result.data.get("style_features", fallback_features),
        llm_result.data.get("style_features_divergence", fallback_divergence),
        list(llm_result.data.get("style_conflicts_summary") or fallback_conflicts),
    )


# ============================================================================
# 评估阶段节点（v3：多候选投票 + ReAct 反思 + 可解释性 + 重评只跑受影响维度）
# ============================================================================

async def director_review_node(state: DirectorState) -> dict:
    """评估阶段节点（v3 增强）

    v3 优化：
    1. 多候选投票：对每个候选分别评估，选综合得分最高的
    2. ReAct 反思：子 Agent 可读取其他 Agent 评估结果做专家会诊
    3. 决策可解释性：输出 decision_reason_cn + issues_summary
    4. 重评阶段：只跑受影响维度（按 post_process_actions[].type 选择 Agent）

    Returns:
        更新 state 的字段：stylist_dual_review, stylist_eu_review, stylist_asia_review,
        lighting_review, makeup_review, photographer_review, director_decision,
        overall_score, star_rating, post_process_actions, decision_reason_cn,
        issues_summary, selected_candidate_idx, prev_overall_score
    """
    final_image = state.get("final_image")
    candidates_final_images = state.get("candidates_final_images") or []
    items = state.get("items", [])
    selected_model = state.get("selected_model_image", {})
    post_process_round = state.get("post_process_round", 0)
    post_process_actions = state.get("post_process_actions") or []

    style_tags = []
    for it in items:
        style_tags.extend(it.get("styleTags") or [])
    style_tags = list(set(style_tags))

    gender = selected_model.get("gender", "female")
    skin_tone = selected_model.get("skinTone", "medium")

    if not final_image:
        logger.warning("[导演·评估v3] 无 final_image，跳过评估，默认 pass")
        return {
            "stylist_dual_review": None, "stylist_eu_review": None, "stylist_asia_review": None,
            "lighting_review": None, "makeup_review": None, "photographer_review": None,
            "director_decision": "pass", "overall_score": 0.5,
            "star_rating": 3, "post_process_actions": [],
            "decision_reason_cn": "无图可评估", "issues_summary": [],
            "selected_candidate_idx": 0,
        }

    vision_model = settings.llm_vision_model

    # ===== 多候选投票模式（仅首评，重评走单候选路径评估后处理效果）=====
    # 重评阶段（post_process_round > 0）不再触发多候选投票，否则会用
    # 后处理前的 candidates_final_images 覆盖刚处理后得到的 final_image
    if len(candidates_final_images) > 1 and post_process_round == 0:
        return await _review_multi_candidates(
            state, candidates_final_images, items, style_tags,
            gender, skin_tone, vision_model,
        )

    # ===== 单候选模式（向后兼容）=====
    # 判断是否为重评阶段（post_process_round > 0）
    is_re_review = post_process_round > 0

    if is_re_review:
        # 重评阶段：只跑受影响维度
        review_results = await _review_only_affected(
            final_image, items, style_tags, gender, skin_tone,
            vision_model, post_process_actions, state,
        )
    else:
        # 首评：全量评估（v3：合并双视角 + ReAct 反思）
        review_results = await _review_full_with_react(
            final_image, items, style_tags, gender, skin_tone, vision_model,
        )

    # 导演汇总决策（v3：可解释性 + 回归校验）
    prev_overall_score = state.get("overall_score", 0.0) if is_re_review else 0.0
    decision_result = await _director_review_collect_v3(
        review_results, is_re_review=is_re_review,
        prev_overall_score=prev_overall_score,
        prev_post_process_actions=post_process_actions,
    )

    # 后处理回归校验：重评后若分数下降超过阈值，回退到原图
    if is_re_review and decision_result["overall_score"] < prev_overall_score - POST_PROCESS_REGRESSION_THRESHOLD:
        logger.warning(
            "[导演·评估v3] 后处理回归校验失败：prev=%.2f, new=%.2f, 回退到 VTON 原图",
            prev_overall_score, decision_result["overall_score"],
        )
        # 回退到 VTON 原图（清除后处理图）
        vton_results = state.get("vton_results") or []
        if vton_results:
            decision_result["final_image_override"] = vton_results[-1]
        decision_result["decision_reason_cn"] = (
            f"后处理后评分从 {prev_overall_score:.2f} 降至 {decision_result['overall_score']:.2f}，"
            f"回退到 VTON 原图"
        )
        decision_result["director_decision"] = "pass"  # 强制 pass，不再后处理

    # 向后兼容：从 dual_review 拆分 eu_review / asia_review
    dual_review = review_results.get("stylist_dual_review")
    eu_review_compat = None
    asia_review_compat = None
    if dual_review:
        eu_review_compat = {
            "vton_quality_score": dual_review.get("eu_vton_quality_score", 0.5),
            "color_distortion": dual_review.get("eu_color_distortion", ""),
            "pattern_deformation": dual_review.get("pattern_deformation", ""),
            "fit_issue": dual_review.get("fit_issue", ""),
            "suggestion": dual_review.get("suggestion", ""),
            "is_fallback": dual_review.get("is_fallback", False),
        }
        asia_review_compat = {
            "vton_quality_score": dual_review.get("asia_vton_quality_score", 0.5),
            "color_distortion": dual_review.get("asia_color_distortion", ""),
            "pattern_deformation": dual_review.get("pattern_deformation", ""),
            "fit_issue": dual_review.get("fit_issue", ""),
            "suggestion": dual_review.get("suggestion", ""),
            "is_fallback": dual_review.get("is_fallback", False),
        }

    result = {
        "stylist_dual_review": dual_review,
        "stylist_eu_review": eu_review_compat,
        "stylist_asia_review": asia_review_compat,
        "lighting_review": review_results.get("lighting_review"),
        "makeup_review": review_results.get("makeup_review"),
        "photographer_review": review_results.get("photographer_review"),
        "director_decision": decision_result["director_decision"],
        "overall_score": decision_result["overall_score"],
        "star_rating": decision_result["star_rating"],
        "post_process_actions": decision_result["post_process_actions"],
        "decision_reason_cn": decision_result["decision_reason_cn"],
        "issues_summary": decision_result["issues_summary"],
        "selected_candidate_idx": 0,
    }
    if is_re_review:
        result["prev_overall_score"] = prev_overall_score
    if "final_image_override" in decision_result:
        result["final_image"] = decision_result["final_image_override"]

    logger.info(
        "[导演·评估v3] taskId=%s, decision=%s, score=%.2f, star=%d, post_process=%d项, reason=%s",
        state.get("task_id"), decision_result["director_decision"],
        decision_result["overall_score"], decision_result["star_rating"],
        len(decision_result["post_process_actions"]),
        decision_result["decision_reason_cn"][:50],
    )

    return result


async def _review_full_with_react(
    final_image: bytes, items: list[dict], style_tags: list[str],
    gender: str, skin_tone: str, vision_model: str,
) -> dict:
    """首评：全量评估 5 维度（v3：合并双视角 + ReAct 反思）

    两阶段执行：
    1. 第一阶段：并行评估 5 个 Agent（无 ReAct）
    2. 第二阶段：让 lighting/makeup 读取其他 Agent 结果做 ReAct 反思（可选）

    为了控制成本，ReAct 反思仅在第一阶段的 lighting/makeup 评分 < 0.6 时触发。
    """
    # 第一阶段：并行评估 5 个 Agent（合并双视角，4 个并行调用）
    tasks = [
        stylist_dual_review(vision_model, final_image, items),
        lighting_review(vision_model, final_image, style_tags, skin_tone),
        makeup_review(vision_model, final_image, gender, skin_tone, style_tags),
        photographer_review(vision_model, final_image),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    def _safe_get(idx, fallback):
        r = results[idx]
        if isinstance(r, Exception):
            logger.warning("子 Agent %d 异常: %s", idx, r)
            return fallback
        return r

    dual_review = _safe_get(0, {
        "eu_vton_quality_score": 0.5, "asia_vton_quality_score": 0.5,
        "eu_color_distortion": "", "asia_color_distortion": "",
        "pattern_deformation": "", "fit_issue": "", "suggestion": "",
        "is_fallback": True,
    })
    lighting_result = _safe_get(1, {
        "lighting_score": 0.5, "issues": [], "post_process_intent_cn": "",
        "is_fallback": True,
    })
    makeup_result = _safe_get(2, {
        "makeup_score": 0.5, "issues": [], "post_process_intent_cn": "",
        "is_fallback": True,
    })
    photographer_r = _safe_get(3, {
        "pose_naturalness_score": 0.5, "composition_break_score": 0.5,
        "issues": [], "is_fallback": True,
    })

    # 第二阶段：ReAct 反思（仅在 lighting/makeup 评分 < 0.6 时触发，控制成本）
    react_enabled = (
        not lighting_result.get("is_fallback", False)
        and not makeup_result.get("is_fallback", False)
        and (
            lighting_result.get("lighting_score", 1.0) < 0.6
            or makeup_result.get("makeup_score", 1.0) < 0.6
        )
    )

    if react_enabled and _llm_configured():
        logger.info("[导演·评估v3] 触发 ReAct 反思（lighting/makeup 评分 < 0.6）")
        # 构造其他 Agent 评估结果摘要供 lighting/makeup 反思
        other_reviews_for_lighting = {
            "stylist_dual": {
                "eu_score": dual_review.get("eu_vton_quality_score"),
                "asia_score": dual_review.get("asia_vton_quality_score"),
                "color_distortion": dual_review.get("eu_color_distortion"),
                "suggestion": dual_review.get("suggestion"),
            },
            "makeup": {
                "score": makeup_result.get("makeup_score"),
                "issues": makeup_result.get("issues"),
            },
            "photographer": {
                "pose_score": photographer_r.get("pose_naturalness_score"),
                "issues": photographer_r.get("issues"),
            },
        }
        other_reviews_for_makeup = {
            "stylist_dual": {
                "eu_score": dual_review.get("eu_vton_quality_score"),
                "asia_score": dual_review.get("asia_vton_quality_score"),
                "suggestion": dual_review.get("suggestion"),
            },
            "lighting": {
                "score": lighting_result.get("lighting_score"),
                "issues": lighting_result.get("issues"),
            },
            "photographer": {
                "pose_score": photographer_r.get("pose_naturalness_score"),
                "issues": photographer_r.get("issues"),
            },
        }

        # 并行重跑 lighting + makeup（带 ReAct）
        react_tasks = [
            lighting_review(vision_model, final_image, style_tags, skin_tone, other_reviews_for_lighting),
            makeup_review(vision_model, final_image, gender, skin_tone, style_tags, other_reviews_for_makeup),
        ]
        react_results = await asyncio.gather(*react_tasks, return_exceptions=True)
        if not isinstance(react_results[0], Exception):
            lighting_result = react_results[0]
        if not isinstance(react_results[1], Exception):
            makeup_result = react_results[1]

    return {
        "stylist_dual_review": dual_review,
        "lighting_review": lighting_result,
        "makeup_review": makeup_result,
        "photographer_review": photographer_r,
    }


async def _review_only_affected(
    final_image: bytes, items: list[dict], style_tags: list[str],
    gender: str, skin_tone: str, vision_model: str,
    post_process_actions: list[dict], state: DirectorState,
) -> dict:
    """重评阶段：只跑受影响维度（v3 优化，节省 LLM 成本）

    根据 post_process_actions[].type 决定重评哪些 Agent：
    - type="lighting" → 只重跑 lighting_review
    - type="makeup" → 只重跑 makeup_review
    - 其他维度（stylist/photographer）沿用首次评分
    """
    affected_types = {a.get("type") for a in post_process_actions if a.get("type")}
    logger.info(
        "[导演·评估v3] 重评阶段：受影响维度=%s，只重跑对应 Agent",
        list(affected_types),
    )

    # 沿用首次评分
    dual_review = state.get("stylist_dual_review")
    lighting_result = state.get("lighting_review")
    makeup_result = state.get("makeup_review")
    photographer_r = state.get("photographer_review")

    # 只重跑受影响的 Agent
    tasks_to_run = []
    task_names = []
    if "lighting" in affected_types:
        tasks_to_run.append(lighting_review(vision_model, final_image, style_tags, skin_tone))
        task_names.append("lighting")
    if "makeup" in affected_types:
        tasks_to_run.append(makeup_review(vision_model, final_image, gender, skin_tone, style_tags))
        task_names.append("makeup")

    if tasks_to_run:
        results = await asyncio.gather(*tasks_to_run, return_exceptions=True)
        for name, r in zip(task_names, results):
            if isinstance(r, Exception):
                logger.warning("[导演·评估v3] 重评 %s 异常: %s", name, r)
                continue
            if name == "lighting":
                lighting_result = r
            elif name == "makeup":
                makeup_result = r

    return {
        "stylist_dual_review": dual_review,
        "lighting_review": lighting_result,
        "makeup_review": makeup_result,
        "photographer_review": photographer_r,
    }


async def _review_multi_candidates(
    state: DirectorState, candidates_final_images: list[bytes],
    items: list[dict], style_tags: list[str],
    gender: str, skin_tone: str, vision_model: str,
) -> dict:
    """多候选投票模式：对每个候选分别评估，选综合得分最高的

    v3 新增：多 Agent 并行生成 + Director 投票
    """
    logger.info(
        "[导演·评估v3] 多候选投票模式：候选数=%d",
        len(candidates_final_images),
    )

    # 对每个候选并行评估
    # 为了控制成本，每个候选用简化版评估（只跑 stylist_dual + lighting + makeup）
    # 综合得分最高的候选再跑完整 5 维度评估
    async def _eval_candidate(image: bytes) -> dict:
        tasks = [
            stylist_dual_review(vision_model, image, items),
            lighting_review(vision_model, image, style_tags, skin_tone),
            makeup_review(vision_model, image, gender, skin_tone, style_tags),
            photographer_review(vision_model, image),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            "stylist_dual_review": results[0] if not isinstance(results[0], Exception) else None,
            "lighting_review": results[1] if not isinstance(results[1], Exception) else None,
            "makeup_review": results[2] if not isinstance(results[2], Exception) else None,
            "photographer_review": results[3] if not isinstance(results[3], Exception) else None,
        }

    # 并行评估所有候选
    candidate_evals = await asyncio.gather(
        *[_eval_candidate(img) for img in candidates_final_images],
        return_exceptions=True,
    )

    # 计算每个候选的综合得分
    candidate_scores = []
    for idx, eval_result in enumerate(candidate_evals):
        if isinstance(eval_result, Exception):
            logger.warning("[导演·评估v3] 候选 %d 评估异常: %s", idx, eval_result)
            candidate_scores.append(0.0)
            continue
        dual = eval_result.get("stylist_dual_review") or {}
        lighting = eval_result.get("lighting_review") or {}
        makeup = eval_result.get("makeup_review") or {}
        photographer = eval_result.get("photographer_review") or {}

        eu_score = float(dual.get("eu_vton_quality_score", 0.5))
        asia_score = float(dual.get("asia_vton_quality_score", 0.5))
        lighting_score = float(lighting.get("lighting_score", 0.5))
        makeup_score = float(makeup.get("makeup_score", 0.5))
        pose_score = float(photographer.get("pose_naturalness_score", 0.5))
        composition_score = 1.0 - float(photographer.get("composition_break_score", 0.5))

        overall = (
            eu_score * 0.2 + asia_score * 0.2 + lighting_score * 0.2
            + makeup_score * 0.15 + pose_score * 0.15 + composition_score * 0.1
        )
        candidate_scores.append(overall)

    # 选得分最高的候选
    best_idx = candidate_scores.index(max(candidate_scores))
    best_eval = candidate_evals[best_idx] if not isinstance(candidate_evals[best_idx], Exception) else {}

    logger.info(
        "[导演·评估v3] 候选投票结果: scores=%s, best_idx=%d",
        [round(s, 3) for s in candidate_scores], best_idx,
    )

    # 更新 state：用最佳候选的图作为 final_image
    best_image = candidates_final_images[best_idx]
    best_vton_results = state.get("candidates_vton_results", [])[best_idx] if best_idx < len(state.get("candidates_vton_results", [])) else [best_image]
    best_item_categories = state.get("candidates_item_categories", [])[best_idx] if best_idx < len(state.get("candidates_item_categories", [])) else []

    # 后续走导演汇总决策
    prev_overall_score = 0.0
    decision_result = await _director_review_collect_v3(
        best_eval, is_re_review=False,
        prev_overall_score=prev_overall_score,
        prev_post_process_actions=[],
    )

    # 向后兼容拆分
    dual_review = best_eval.get("stylist_dual_review")
    eu_review_compat = None
    asia_review_compat = None
    if dual_review:
        eu_review_compat = {
            "vton_quality_score": dual_review.get("eu_vton_quality_score", 0.5),
            "color_distortion": dual_review.get("eu_color_distortion", ""),
            "pattern_deformation": dual_review.get("pattern_deformation", ""),
            "fit_issue": dual_review.get("fit_issue", ""),
            "suggestion": dual_review.get("suggestion", ""),
            "is_fallback": dual_review.get("is_fallback", False),
        }
        asia_review_compat = {
            "vton_quality_score": dual_review.get("asia_vton_quality_score", 0.5),
            "color_distortion": dual_review.get("asia_color_distortion", ""),
            "pattern_deformation": dual_review.get("pattern_deformation", ""),
            "fit_issue": dual_review.get("fit_issue", ""),
            "suggestion": dual_review.get("suggestion", ""),
            "is_fallback": dual_review.get("is_fallback", False),
        }

    return {
        "stylist_dual_review": dual_review,
        "stylist_eu_review": eu_review_compat,
        "stylist_asia_review": asia_review_compat,
        "lighting_review": best_eval.get("lighting_review"),
        "makeup_review": best_eval.get("makeup_review"),
        "photographer_review": best_eval.get("photographer_review"),
        "director_decision": decision_result["director_decision"],
        "overall_score": decision_result["overall_score"],
        "star_rating": decision_result["star_rating"],
        "post_process_actions": decision_result["post_process_actions"],
        "decision_reason_cn": decision_result["decision_reason_cn"],
        "issues_summary": decision_result["issues_summary"],
        "selected_candidate_idx": best_idx,
        # 更新 final_image 为最佳候选
        "final_image": best_image,
        "vton_results": best_vton_results,
        "item_categories": best_item_categories,
    }


async def _director_review_collect_v3(
    review_results: dict,
    is_re_review: bool = False,
    prev_overall_score: float = 0.0,
    prev_post_process_actions: list[dict] | None = None,
) -> dict:
    """导演评估阶段汇总 + 决策（v3：可解释性 + 多候选投票）

    Returns:
        {
            "director_decision": "pass" | "post_process",
            "overall_score": float,
            "star_rating": int,
            "post_process_actions": list[dict],
            "decision_reason_cn": str,
            "issues_summary": list[str],
        }
    """
    dual_review = review_results.get("stylist_dual_review") or {}
    lighting_result = review_results.get("lighting_review") or {}
    makeup_result = review_results.get("makeup_review") or {}
    photographer_r = review_results.get("photographer_review") or {}

    eu_score = float(dual_review.get("eu_vton_quality_score", 0.5))
    asia_score = float(dual_review.get("asia_vton_quality_score", 0.5))
    lighting_score = float(lighting_result.get("lighting_score", 0.5))
    makeup_score = float(makeup_result.get("makeup_score", 0.5))
    pose_score = float(photographer_r.get("pose_naturalness_score", 0.5))
    composition_score = 1.0 - float(photographer_r.get("composition_break_score", 0.5))

    overall = (
        eu_score * 0.2 + asia_score * 0.2 + lighting_score * 0.2
        + makeup_score * 0.15 + pose_score * 0.15 + composition_score * 0.1
    )

    # 收集问题清单
    issues: list[str] = []
    if dual_review.get("eu_color_distortion"):
        issues.append(f"EU视角颜色失真: {dual_review['eu_color_distortion']}")
    if dual_review.get("asia_color_distortion"):
        issues.append(f"Asia视角颜色失真: {dual_review['asia_color_distortion']}")
    if dual_review.get("pattern_deformation"):
        issues.append(f"图案变形: {dual_review['pattern_deformation']}")
    if dual_review.get("fit_issue"):
        issues.append(f"贴合度问题: {dual_review['fit_issue']}")
    issues.extend(lighting_result.get("issues") or [])
    issues.extend(makeup_result.get("issues") or [])
    issues.extend(photographer_r.get("issues") or [])

    # LLM 不可用 → 规则决策
    if not _llm_configured():
        return _rule_based_decision_v3(
            overall, eu_score, asia_score, lighting_score, makeup_score,
            lighting_result, makeup_result, issues,
        )

    # 调 LLM 决策（v3 增强版：可解释性）
    user_prompt = DIRECTOR_REVIEW_V3_PROMPT.format(
        stylist_eu_json=json.dumps({
            "vton_quality_score": eu_score,
            "color_distortion": dual_review.get("eu_color_distortion", ""),
            "suggestion": dual_review.get("suggestion", ""),
        }, ensure_ascii=False),
        stylist_asia_json=json.dumps({
            "vton_quality_score": asia_score,
            "color_distortion": dual_review.get("asia_color_distortion", ""),
        }, ensure_ascii=False),
        lighting_json=json.dumps(lighting_result, ensure_ascii=False),
        makeup_json=json.dumps(makeup_result, ensure_ascii=False),
        photographer_json=json.dumps(photographer_r, ensure_ascii=False),
        candidates_section="",  # 单候选模式：candidates_section 为空
    )
    llm_result = await _call_llm_with_retry(
        model=settings.llm_text_model,
        system_prompt=DIRECTOR_SYSTEM_PROMPT, user_prompt=user_prompt,
        agent_name="director_review_v3",
        timeout=LLM_PLAN_TIMEOUT,
        temperature=0.0,  # 评估决策需要稳定
    )
    if llm_result.is_fallback or llm_result.data is None:
        return _rule_based_decision_v3(
            overall, eu_score, asia_score, lighting_score, makeup_score,
            lighting_result, makeup_result, issues,
        )

    decision = llm_result.data.get("decision", "pass")
    if decision not in ("pass", "post_process"):
        decision = "pass"
    overall_score = float(llm_result.data.get("overall_score", overall))
    star_rating = int(llm_result.data.get("star_rating", _score_to_star(overall_score)))
    if not 1 <= star_rating <= 5:
        star_rating = _score_to_star(overall_score)
    post_process_actions = list(llm_result.data.get("post_process_actions") or [])
    decision_reason_cn = llm_result.data.get("decision_reason_cn", "")
    issues_summary = list(llm_result.data.get("issues_summary") or issues)

    return {
        "director_decision": decision,
        "overall_score": overall_score,
        "star_rating": star_rating,
        "post_process_actions": post_process_actions,
        "decision_reason_cn": decision_reason_cn,
        "issues_summary": issues_summary,
    }


def _rule_based_decision_v3(
    overall: float, eu_score: float, asia_score: float,
    lighting_score: float, makeup_score: float,
    lighting_result: dict, makeup_result: dict, issues: list[str],
) -> dict:
    """规则降级决策（LLM 不可用时使用，v3 增强可解释性）"""
    star = _score_to_star(overall)

    avg_vton_quality = (eu_score + asia_score) / 2
    needs_post = False
    decision_reason_parts = []

    if lighting_score < 0.6:
        needs_post = True
        decision_reason_parts.append(f"光照评分 {lighting_score:.2f} 低于 0.6 阈值")
    if makeup_score < 0.6:
        needs_post = True
        decision_reason_parts.append(f"妆容评分 {makeup_score:.2f} 低于 0.6 阈值")
    if avg_vton_quality < 0.5 and lighting_score >= 0.7 and makeup_score >= 0.7:
        needs_post = True
        decision_reason_parts.append(f"VTON 执行质量 {avg_vton_quality:.2f} 低于 0.5")

    decision = "post_process" if needs_post else "pass"
    decision_reason_cn = "；".join(decision_reason_parts) if decision_reason_parts else "各项评分达标"

    return {
        "director_decision": decision,
        "overall_score": overall,
        "star_rating": star,
        "post_process_actions": [],  # 规则降级时不填充 actions（无法生成中文 prompt）
        "decision_reason_cn": decision_reason_cn,
        "issues_summary": issues,
    }
