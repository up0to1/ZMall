"""
AI 模特多 Agent 决策服务（对外入口）

设计文档 §1.8.3 + §1.8.11：
被 ai-models 的 MQ 消费者（model_consumer._process_task）直接 import 调用，
执行完整多 Agent 工作流后返回结果。

支持多换装模式（multi_outfit）
- 根据 generationMode 路由到不同工作流
- generationMode="multi_outfit"：调多换装图（多套组合并行 VTON + 独立评估）
- generationMode="single" 或未指定：调单图模式工作流（多 Agent 决策）

输入：MQ 消息体（taskId/shopId/items/itemIds/modelImageUrl/modelImageCandidates/...）
输出：MQ 结果消息体（resultUrls/itemCategories/itemIds/starRating/overallScore/styleFeatures/...）
"""
import logging
from typing import Any

from app.graphs.model_director_graph import get_compiled_model_director_graph
from app.graphs.multi_outfit_graph import get_compiled_multi_outfit_graph
from app.graphs.multi_pose_graph import get_compiled_multi_pose_graph
from app.schemas.director_state import DirectorState

logger = logging.getLogger(__name__)


async def run_model_agent_workflow(message: dict) -> dict[str, Any]:
    """执行 AI 模特生成工作流（按 generationMode 路由）

    Args:
        message: MQ 消息体（来自 ai-models MQ 消费者直接 import 调用）
            {
              "taskId": "xxx",
              "shopId": 1001,
              "userId": 2001,
              "items": [{"itemId", "ossUrl", "category", "color", "styleTags"}, ...],
              "itemIds": [101, 102, 103],
              "modelImageUrl": "...",                    # 商家指定模特图（可选）
              "modelImageCandidates": [...],              # 三级池候选（商家未指定时用）
              "enableMultiAgent": false,                  # 是否启用多 Agent 决策（单图模式）
              "generationMode": "single",                 # v5：生成模式 single/multi_outfit
              "outfitCombinations": [[101,201],[101,202]],  # v5：多换装组合（可选）
              "combinationReasons": ["...", "..."]           # v5：组合推荐理由
            }
    Returns:
        {
          "success": bool,
          "resultUrls": [...],
          "itemCategories": [...],
          "itemIds": [...],
          "starRating": int,
          "overallScore": float,
          "styleFeatures": str,
          "styleFeaturesDivergence": str,
          "postProcessedImageUrl": str | None,
          "agentEvaluations": {...},
          "sceneResults": [...],          # v5：多换装模式专属
          "outfitCombinations": [...],    # v5：多换装模式专属
          "combinationReasons": [...],    # v5：多换装模式专属
          "errorMsg": str | None
        }
    """
    task_id = message.get("taskId", "")
    items = message.get("items", [])
    item_ids = message.get("itemIds", [])
    model_image_url = message.get("modelImageUrl", "")
    model_image_candidates = message.get("modelImageCandidates") or []
    generation_mode = message.get("generationMode", "single")

    # v5：路由到多图工作流
    if generation_mode == "multi_outfit":
        return await _run_multi_outfit_workflow(message)
    if generation_mode == "multi_pose":
        return await _run_multi_pose_workflow(message)

    # 默认：单图模式（多 Agent 决策）
    return await _run_single_workflow(message)


async def _run_single_workflow(message: dict) -> dict[str, Any]:
    """执行单图模式工作流（多 Agent 决策架构）"""
    task_id = message.get("taskId", "")
    items = message.get("items", [])
    item_ids = message.get("itemIds", [])
    model_image_url = message.get("modelImageUrl", "")
    model_image_candidates = message.get("modelImageCandidates") or []

    logger.info(
        "[单图模式] 启动工作流: taskId=%s, 商品数=%d, 模特图来源=%s",
        task_id, len(items),
        "商家指定" if model_image_url else f"系统池候选({len(model_image_candidates)})",
    )

    # 构造初始 state
    initial_state: DirectorState = {
        "task_id": task_id,
        "shop_id": message.get("shopId", 0),
        "user_id": message.get("userId", 0),
        "item_ids": item_ids,
        "items": items,
        "model_image_candidates": model_image_candidates,
        "uploaded_model_url": model_image_url or None,
        "post_process_round": 0,
        "error": None,
    }

    try:
        graph = await get_compiled_model_director_graph()
        final_state = await graph.ainvoke(initial_state)

        result_urls = final_state.get("result_urls") or []
        item_categories = final_state.get("item_categories") or []
        error = final_state.get("error")

        if error or not result_urls:
            return {
                "success": False,
                "resultUrls": None,
                "itemCategories": None,
                "itemIds": item_ids,
                "starRating": 0,
                "overallScore": 0.0,
                "styleFeatures": final_state.get("style_features", ""),
                "styleFeaturesDivergence": final_state.get("style_features_divergence", ""),
                "postProcessedImageUrl": None,
                "agentEvaluations": _build_agent_evaluations(final_state),
                "decisionReason": final_state.get("decision_reason_cn", ""),
                "issuesSummary": final_state.get("issues_summary", []),
                "selectedCandidateIdx": final_state.get("selected_candidate_idx", 0),
                "errorMsg": error or "无结果图生成",
            }

        return {
            "success": True,
            "resultUrls": result_urls,
            "itemCategories": item_categories,
            "itemIds": item_ids,
            "starRating": final_state.get("star_rating", 3),
            "overallScore": final_state.get("overall_score", 0.5),
            "styleFeatures": final_state.get("style_features", ""),
            "styleFeaturesDivergence": final_state.get("style_features_divergence", ""),
            "postProcessedImageUrl": final_state.get("post_processed_image_url"),
            "agentEvaluations": _build_agent_evaluations(final_state),
            "decisionReason": final_state.get("decision_reason_cn", ""),
            "issuesSummary": final_state.get("issues_summary", []),
            "selectedCandidateIdx": final_state.get("selected_candidate_idx", 0),
            "errorMsg": None,
        }

    except Exception as e:
        logger.error("[单图模式] 工作流异常: taskId=%s, error=%s",
                     task_id, e, exc_info=True)
        return {
            "success": False,
            "resultUrls": None,
            "itemCategories": None,
            "itemIds": item_ids,
            "starRating": 0,
            "overallScore": 0.0,
            "styleFeatures": "",
            "styleFeaturesDivergence": "",
            "postProcessedImageUrl": None,
            "agentEvaluations": {},
            "errorMsg": f"工作流异常: {e}",
        }


async def _run_multi_outfit_workflow(message: dict) -> dict[str, Any]:
    """执行多换装工作流（v5 新增）

    多换装模式：多套商品组合并行 VTON + 独立评估 + 独立后处理 + 汇总上传
    场景：同脸/同妆造 + 不同服装 + 不同姿势（每套独立 VTON 自然产生不同姿势）
    """
    task_id = message.get("taskId", "")
    items = message.get("items", [])
    item_ids = message.get("itemIds", [])
    model_image_url = message.get("modelImageUrl", "")
    model_image_candidates = message.get("modelImageCandidates") or []
    outfit_combinations = message.get("outfitCombinations") or []
    combination_reasons = message.get("combinationReasons") or []

    logger.info(
        "[多换装模式] 启动工作流: taskId=%s, 商品数=%d, 预设组合数=%d, 模特图来源=%s",
        task_id, len(items), len(outfit_combinations),
        "商家指定" if model_image_url else f"系统池候选({len(model_image_candidates)})",
    )

    # 构造初始 state
    initial_state: DirectorState = {
        "task_id": task_id,
        "shop_id": message.get("shopId", 0),
        "user_id": message.get("userId", 0),
        "item_ids": item_ids,
        "items": items,
        "model_image_candidates": model_image_candidates,
        "uploaded_model_url": model_image_url or None,
        "generation_mode": "multi_outfit",
        "outfit_combinations": outfit_combinations,
        "combination_reasons": combination_reasons,
        "post_process_round": 0,
        "error": None,
    }

    try:
        graph = await get_compiled_multi_outfit_graph()
        final_state = await graph.ainvoke(initial_state)

        result_urls = final_state.get("result_urls") or []
        item_categories = final_state.get("item_categories") or []
        scene_results = final_state.get("scene_results") or []
        final_combinations = final_state.get("outfit_combinations") or []
        final_reasons = final_state.get("combination_reasons") or []
        error = final_state.get("error")

        # 多换装模式：scene_results 不可为空
        if error or not scene_results or not result_urls:
            return {
                "success": False,
                "resultUrls": None,
                "itemCategories": None,
                "itemIds": item_ids,
                "starRating": 0,
                "overallScore": 0.0,
                "styleFeatures": "",
                "styleFeaturesDivergence": "",
                "postProcessedImageUrl": None,
                "agentEvaluations": {},
                "sceneResults": [],
                "outfitCombinations": final_combinations,
                "combinationReasons": final_reasons,
                "decisionReason": "",
                "errorMsg": error or "多换装工作流无结果图生成",
            }

        # 汇总各场景评估数据（取平均分作为整体评分）
        avg_score, avg_star, agent_evals_summary = _aggregate_scene_evaluations(scene_results)
        # 取第 1 个场景的后处理图作为整体 postProcessedImageUrl（兼容前端展示）
        first_post_processed = next(
            (s.get("post_processed_image_url") for s in scene_results
             if s.get("post_processed_image_url")),
            None,
        )

        return {
            "success": True,
            "resultUrls": result_urls,
            "itemCategories": item_categories,
            "itemIds": item_ids,
            "starRating": avg_star,
            "overallScore": avg_score,
            "styleFeatures": "",  # 多换装模式无统一风格特征
            "styleFeaturesDivergence": "",
            "postProcessedImageUrl": first_post_processed,
            "agentEvaluations": agent_evals_summary,
            "sceneResults": _serialize_scene_results(scene_results),
            "outfitCombinations": final_combinations,
            "combinationReasons": final_reasons,
            "decisionReason": "",
            "errorMsg": None,
        }

    except Exception as e:
        logger.error("[多换装模式] 工作流异常: taskId=%s, error=%s",
                     task_id, e, exc_info=True)
        return {
            "success": False,
            "resultUrls": None,
            "itemCategories": None,
            "itemIds": item_ids,
            "starRating": 0,
            "overallScore": 0.0,
            "styleFeatures": "",
            "styleFeaturesDivergence": "",
            "postProcessedImageUrl": None,
            "agentEvaluations": {},
            "sceneResults": [],
            "outfitCombinations": outfit_combinations,
            "combinationReasons": combination_reasons,
            "errorMsg": f"多换装工作流异常: {e}",
        }


def _aggregate_scene_evaluations(scene_results: list[dict]) -> tuple[float, int, dict]:
    """汇总各场景的评估数据（取平均分作为整体评分）"""
    valid_scenes = [s for s in scene_results if s.get("final_image")]
    if not valid_scenes:
        return 0.0, 0, {}

    avg_score = sum(s.get("overall_score", 0.0) for s in valid_scenes) / len(valid_scenes)
    avg_star = round(sum(s.get("star_rating", 3) for s in valid_scenes) / len(valid_scenes))

    # 汇总各 Agent 评估（取第 1 个成功场景的作为代表展示）
    first_evals = valid_scenes[0].get("agent_evaluations") or {}
    return avg_score, avg_star, first_evals


async def _run_multi_pose_workflow(message: dict) -> dict[str, Any]:
    """执行多姿势工作流（v5 新增）

    多姿势模式：1 次链式 VTON 生成基准图 + N 次 O1 图生图生成姿势变体 + 独立评估 + 汇总上传
    场景：同脸/同妆造/同服装 + 不同姿势（站立/坐姿/侧身/特写等混合）
    """
    task_id = message.get("taskId", "")
    items = message.get("items", [])
    item_ids = message.get("itemIds", [])
    model_image_url = message.get("modelImageUrl", "")
    model_image_candidates = message.get("modelImageCandidates") or []
    pose_count = message.get("poseCount", 3)

    logger.info(
        "[多姿势模式] 启动工作流: taskId=%s, 商品数=%d, 姿势数=%d, 模特图来源=%s",
        task_id, len(items), pose_count,
        "商家指定" if model_image_url else f"系统池候选({len(model_image_candidates)})",
    )

    # 构造初始 state
    initial_state: DirectorState = {
        "task_id": task_id,
        "shop_id": message.get("shopId", 0),
        "user_id": message.get("userId", 0),
        "item_ids": item_ids,
        "items": items,
        "model_image_candidates": model_image_candidates,
        "uploaded_model_url": model_image_url or None,
        "generation_mode": "multi_pose",
        "pose_count": pose_count,
        "post_process_round": 0,
        "error": None,
    }

    try:
        graph = await get_compiled_multi_pose_graph()
        final_state = await graph.ainvoke(initial_state)

        result_urls = final_state.get("result_urls") or []
        item_categories = final_state.get("item_categories") or []
        pose_results = final_state.get("pose_results") or []
        error = final_state.get("error")

        # 多姿势模式：pose_results 不可为空
        if error or not pose_results or not result_urls:
            return {
                "success": False,
                "resultUrls": None,
                "itemCategories": None,
                "itemIds": item_ids,
                "starRating": 0,
                "overallScore": 0.0,
                "styleFeatures": "",
                "styleFeaturesDivergence": "",
                "postProcessedImageUrl": None,
                "agentEvaluations": {},
                "sceneResults": [],
                "poseResults": [],
                "outfitCombinations": [],
                "combinationReasons": [],
                "decisionReason": "",
                "errorMsg": error or "多姿势工作流无结果图生成",
            }

        # 汇总各姿势评估数据（取平均分作为整体评分）
        avg_score, avg_star, agent_evals_summary = _aggregate_pose_evaluations(pose_results)
        # 取第 1 个姿势的后处理图作为整体 postProcessedImageUrl（兼容前端展示）
        first_post_processed = next(
            (p.get("post_processed_image_url") for p in pose_results
             if p.get("post_processed_image_url")),
            None,
        )

        return {
            "success": True,
            "resultUrls": result_urls,
            "itemCategories": item_categories,
            "itemIds": item_ids,
            "starRating": avg_star,
            "overallScore": avg_score,
            "styleFeatures": "",
            "styleFeaturesDivergence": "",
            "postProcessedImageUrl": first_post_processed,
            "agentEvaluations": agent_evals_summary,
            "sceneResults": [],  # 多姿势模式无场景，统一为空
            "poseResults": _serialize_pose_results(pose_results),
            "outfitCombinations": [],
            "combinationReasons": [],
            "decisionReason": "",
            "errorMsg": None,
        }

    except Exception as e:
        logger.error("[多姿势模式] 工作流异常: taskId=%s, error=%s",
                     task_id, e, exc_info=True)
        return {
            "success": False,
            "resultUrls": None,
            "itemCategories": None,
            "itemIds": item_ids,
            "starRating": 0,
            "overallScore": 0.0,
            "styleFeatures": "",
            "styleFeaturesDivergence": "",
            "postProcessedImageUrl": None,
            "agentEvaluations": {},
            "sceneResults": [],
            "poseResults": [],
            "outfitCombinations": [],
            "combinationReasons": [],
            "errorMsg": f"多姿势工作流异常: {e}",
        }


def _aggregate_pose_evaluations(pose_results: list[dict]) -> tuple[float, int, dict]:
    """汇总各姿势的评估数据（取平均分作为整体评分）"""
    valid_poses = [p for p in pose_results if p.get("final_image")]
    if not valid_poses:
        return 0.0, 0, {}

    avg_score = sum(p.get("overall_score", 0.0) for p in valid_poses) / len(valid_poses)
    avg_star = round(sum(p.get("star_rating", 3) for p in valid_poses) / len(valid_poses))

    # 汇总各 Agent 评估（取第 1 个成功姿势的作为代表展示）
    first_evals = valid_poses[0].get("agent_evaluations") or {}
    return avg_score, avg_star, first_evals


def _serialize_pose_results(pose_results: list[dict]) -> list[dict]:
    """序列化姿势结果（移除 bytes 字段，仅保留可序列化内容）

    bytes 字段（final_image/post_processed_image）在
    multi_pose_upload_node 已上传为 URL，这里删除原始 bytes 以避免
    MQ 消息序列化失败。
    """
    serializable: list[dict] = []
    for pose in pose_results:
        p = {k: v for k, v in pose.items() if not isinstance(v, (bytes, bytearray))}
        p.pop("final_image", None)
        p.pop("post_processed_image", None)
        serializable.append(p)
    return serializable


def _serialize_scene_results(scene_results: list[dict]) -> list[dict]:
    """序列化场景结果（移除 bytes 字段，仅保留可序列化内容）

    bytes 字段（vton_results/final_image/post_processed_image）在
    multi_outfit_upload_node 已上传为 URL，这里删除原始 bytes 以避免
    MQ 消息序列化失败。
    """
    serializable: list[dict] = []
    for scene in scene_results:
        s = {k: v for k, v in scene.items() if not isinstance(v, (bytes, bytearray))}
        # vton_results 是 list[bytes]，也要剔除
        s.pop("vton_results", None)
        s.pop("final_image", None)
        s.pop("post_processed_image", None)
        serializable.append(s)
    return serializable


def _build_agent_evaluations(state: dict) -> dict:
    """构造 5 角色 Agent 评估详情（内部日志用，不展示商家）"""
    return {
        "stylistEu": state.get("stylist_eu_review"),
        "stylistAsia": state.get("stylist_asia_review"),
        "lighting": state.get("lighting_review"),
        "makeup": state.get("makeup_review"),
        "photographer": state.get("photographer_review"),
    }
