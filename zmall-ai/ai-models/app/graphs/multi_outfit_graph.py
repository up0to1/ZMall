"""
AI 模特多换装生成主图（v4 新增）

设计文档 v4：多换装模式工作流
  entry → multi_outfit_plan（搭配推荐）
        → multi_outfit_vton（并行 VTON，每套独立）
        → multi_outfit_review_and_post（并行评估 + 独立后处理）
        → multi_outfit_upload（汇总上传所有图）
        → END

核心特性：
- 搭配推荐：LLM 智能推荐 1-4 套合法组合（降级走笛卡尔积）
- 并行 VTON：每套组合独立链式 VTON，共用同一张模特基准图（同脸一致）
- 独立评估：每张图走完整 5 维度评估 + 决策
- 独立后处理：每张图按决策独立后处理（限 1 轮/张）
- 结果汇总：所有图统一上传，按场景顺序返回

与单图模式（model_director_graph）的关系：
- 单图模式：现有路径，1 套商品 + 1 次评估
- 多换装模式：本工作流，N 套商品 + N 次评估
- 由 model_consumer 根据 generationMode 路由
"""
import asyncio
import hashlib
import logging
from pathlib import Path

import httpx
from langgraph.graph import END, StateGraph

from app.schemas.director_state import DirectorState
from app.subgraphs.outfit_combination_subgraph import recommend_outfit_combinations
from app.subgraphs.director_nodes import director_review_node
from app.subgraphs._llm import _call_llm_with_retry, LLM_PLAN_TIMEOUT
from app.core.config import settings
from shared.outfit_common import is_safe_image_url
from app.prompts.director_prompts import DIRECTOR_SYSTEM_PROMPT, DIRECTOR_PLAN_V3_PROMPT

logger = logging.getLogger(__name__)

# 节点名称常量
NODE_PLAN = "multi_outfit_plan"
NODE_VTON = "multi_outfit_vton"
NODE_REVIEW = "multi_outfit_review_and_post"
NODE_UPLOAD = "multi_outfit_upload"

# VTON 支持的品类（千问 aitryon-plus 仅支持服装类虚拟换装，与 ai-outfit/nodes.py 对齐）
# 2026-08-06 调整：鞋/帽子从 VTON 移出（aitryon-plus 仅支持衣物换装，
# top_garment_url 是"上装"语义，把鞋/帽子塞进去接口虽返回成功但生成图中不含该单品）
# → 改走 wan2.7-image 图生图穿戴；下装（裤子/裙子）原生支持 bottom_garment_url，保留 VTON
VTON_CATEGORIES = ["上衣", "下装", "全身套装"]
# wan2.7-image 穿戴的品类（VTON 不支持配饰/包/鞋/帽子的虚拟穿戴，直接走 wan2.7-image 节省 VTON credits）
WAN_ACCESSORY_CATEGORIES = ["鞋", "包", "帽子", "配饰"]

# 模特图本地降级子目录
LOCAL_FALLBACK_SUBDIR = "model"

# 品类中→英文件名映射
_CATEGORY_FILENAME_MAP = {
    "上衣": "tops", "下装": "bottoms", "全身套装": "dress",
    "帽子": "hat", "鞋": "shoes", "包": "bag", "配饰": "accessory",
    "套装1": "outfit1", "套装2": "outfit2", "套装3": "outfit3", "套装4": "outfit4",
}


def _category_to_filename_safe(category: str, scene_idx: int = 0) -> str:
    """品类转文件名安全字符串，多换装模式下加场景前缀"""
    if category in _CATEGORY_FILENAME_MAP:
        return _CATEGORY_FILENAME_MAP[category]
    return f"outfit{scene_idx + 1}"


async def _download_image(url: str) -> bytes | None:
    """下载图片（trust_env=False 禁用系统代理）"""
    if not url:
        return None
    if url.startswith("/"):
        base = settings.nginx_external_base_url.rstrip("/")
        if not base:
            logger.error("图片URL是相对路径但 nginx_external_base_url 未配置: url=%s", url[:100])
            return None
        url = f"{base}{url}"
    # A2 SSRF 防护
    if not is_safe_image_url(url):
        logger.warning("SSRF 拦截: 非法图片 URL 已拒绝: %s", url[:120])
        return None
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.content
            logger.error("图片下载失败: url=%s, status=%s", url[:100], resp.status_code)
            return None
        except Exception as e:
            logger.error("图片下载异常: url=%s, error=%s", url[:100], e)
            return None


async def _wear_accessories_chain(
    base_image: bytes,
    accessory_items: list[dict],
    item_images_cache: dict[int, bytes],
    scene_idx: int,
) -> bytes:
    """对鞋/包/配饰依次调用 wan2.7-image 虚拟穿戴（链式，单件失败不中断）

    与 ai-outfit/nodes.py 的 _wear_accessories_chain 对齐：
    VTON（aitryon-plus）不支持配饰/包/鞋类，用 wan2.7-image 图生图实现。
    每件穿戴结果作为下一件的输入，形成链式穿戴。

    穿戴顺序：鞋 → 包 → 配饰（先穿鞋，再包，最后配饰点缀）

    Args:
        base_image: VTON 输出的人物图（已穿上服装）
        accessory_items: 鞋/包/配饰 商品列表
        item_images_cache: itemId → 商品图 bytes 缓存（避免重复下载）
        scene_idx: 场景索引（日志用）
    Returns:
        穿戴后的人物图；wan2.7-image 失败时返回原 base_image（不阻塞主流程）
    """
    if not accessory_items:
        return base_image

    from app.api.deps import get_gen_client

    gen_client = await get_gen_client()
    current_image = base_image
    success_count = 0

    # 穿戴顺序排序：鞋(0) → 帽子(1) → 包(2) → 配饰(3)，其余保持原序
    _WAN_WEAR_ORDER = {"鞋": 0, "帽子": 1, "包": 2, "配饰": 3}
    ordered_accessory = sorted(
        accessory_items,
        key=lambda it: _WAN_WEAR_ORDER.get(it.get("category"), 9),
    )

    for it in ordered_accessory:
        cat = it.get("category")
        item_id = it.get("itemId")
        accessory_bytes = item_images_cache.get(item_id)
        if accessory_bytes is None:
            logger.warning("[多换装·穿戴] 场景 %d 单品图未在缓存中: itemId=%s", scene_idx, item_id)
            continue

        worn = await gen_client.wear_accessory(current_image, accessory_bytes, cat)
        if worn is not None:
            current_image = worn
            success_count += 1
            logger.info("[多换装·穿戴] 场景 %d wan2.7-image 穿戴成功: category=%s",
                        scene_idx, cat)
        else:
            logger.warning("[多换装·穿戴] 场景 %d wan2.7-image 穿戴失败，跳过: category=%s",
                           scene_idx, cat)

    logger.info("[多换装·穿戴] 场景 %d 单品穿戴完成: 总数=%d, 成功=%d",
                scene_idx, len(accessory_items), success_count)
    return current_image


# ============================================================================
# 节点 1：搭配推荐（LLM 智能推荐多套组合）
# ============================================================================

async def multi_outfit_plan_node(state: DirectorState) -> dict:
    """搭配推荐节点：基于商家选定的商品生成 1-4 套搭配组合

    Returns:
        更新 state 的字段：outfit_combinations, combination_reasons
    """
    items = state.get("items", [])
    task_id = state.get("task_id", "")

    # 若上游已传入合法组合（Java 侧预生成），直接复用
    pre_combinations = state.get("outfit_combinations") or []
    if pre_combinations:
        logger.info(
            "[多换装·策划] taskId=%s, 复用上游组合: 套数=%d",
            task_id, len(pre_combinations),
        )
        return {
            "outfit_combinations": pre_combinations,
            "combination_reasons": state.get("combination_reasons") or [""] * len(pre_combinations),
        }

    # 调用 LLM 搭配推荐
    combinations, reasons = await recommend_outfit_combinations(items, use_llm=True)

    if not combinations:
        logger.error("[多换装·策划] taskId=%s, 搭配推荐失败，无合法组合", task_id)
        return {
            "outfit_combinations": [],
            "combination_reasons": [],
            "error": "搭配推荐失败，无合法组合",
        }

    logger.info(
        "[多换装·策划] taskId=%s, 商品数=%d, 推荐套数=%d",
        task_id, len(items), len(combinations),
    )

    return {
        "outfit_combinations": combinations,
        "combination_reasons": reasons,
    }


# ============================================================================
# 节点 2：并行 VTON（每套独立链式 VTON，共用同一张模特基准图）
# ============================================================================

async def multi_outfit_vton_node(state: DirectorState) -> dict:
    """并行 VTON 节点：每套组合独立链式 VTON，共用同一张模特基准图

    Returns:
        更新 state 的字段：scene_results（每个场景含 vton_results/final_image/item_categories）
    """
    from app.api.deps import get_vton_client

    vton_client = await get_vton_client()
    items = state.get("items", [])
    combinations = state.get("outfit_combinations") or []
    task_id = state.get("task_id", "")
    selected_model = state.get("selected_model_image", {})
    model_image_url = (
        state.get("uploaded_model_url")
        or selected_model.get("url")
        or selected_model.get("imageUrl")
    )

    if not model_image_url:
        return {"scene_results": [], "error": "无模特图"}

    if not combinations:
        return {"scene_results": [], "error": "无搭配组合"}

    # 下载模特图（所有场景共用）
    model_image = await _download_image(model_image_url)
    if model_image is None:
        return {"scene_results": [], "error": "模特图下载失败"}

    # 下载所有商品图（按 itemId 去重缓存）
    item_images_cache: dict[int, bytes] = {}
    for item in items:
        item_id = item.get("itemId")
        if item_id in item_images_cache:
            continue
        garment = await _download_image(item.get("ossUrl") or item.get("imageUrl", ""))
        if garment is None:
            logger.warning("[多换装·VTON] 商品图下载失败: itemId=%s", item_id)
            continue
        item_images_cache[item_id] = garment

    if not item_images_cache:
        return {"scene_results": [], "error": "所有商品图下载失败"}

    # 并行执行每套组合的链式 VTON
    async def _run_one_scene(scene_idx: int, combination: list[int]) -> dict:
        """跑单个场景的链式 VTON + wan2.7-image 配饰穿戴

        配饰/包类不走 VTON（aitryon-plus 不支持），
        VTON 成功后用 wan2.7-image 链式穿戴配饰/包类，与 ai-outfit/nodes.py 对齐。
        """
        id_to_item = {it.get("itemId"): it for it in items}
        scene_items = [id_to_item[i] for i in combination if i in id_to_item]

        # 按品类分组：服装类进 VTON，配饰/包类走 wan2.7-image
        vton_grouped: dict[str, list] = {cat: [] for cat in VTON_CATEGORIES}
        accessory_items: list[dict] = []
        for it in scene_items:
            cat = it.get("category")
            if cat in vton_grouped:
                vton_grouped[cat].append(it)
            elif cat in WAN_ACCESSORY_CATEGORIES:
                accessory_items.append(it)

        # VTON 链式顺序：全身套装→上衣→下装（鞋/帽子/包/配饰走 wan2.7-image 穿戴）
        ordered_vton_items: list[dict] = []
        for cat in ["全身套装", "上衣", "下装"]:
            ordered_vton_items.extend(vton_grouped.get(cat, []))

        # 收集 VTON 商品图
        garment_images: list[bytes] = []
        successful_categories: list[str] = []
        for item in ordered_vton_items:
            img = item_images_cache.get(item.get("itemId"))
            if img is None:
                continue
            garment_images.append(img)
            successful_categories.append(item.get("category", "未知"))

        if not garment_images:
            # 无 VTON 品类（仅下装/鞋/包/配饰）：直接用模特图作 base 走 wan2.7-image 穿戴
            if accessory_items:
                logger.info(
                    "[多换装·VTON] 场景 %d 无 VTON 品类，直接用模特图走 wan2.7-image 穿戴: combination=%s",
                    scene_idx, combination,
                )
                final_image = await _wear_accessories_chain(
                    model_image, accessory_items, item_images_cache, scene_idx,
                )
                item_categories = [it.get("category", "配饰") for it in accessory_items]
                return {
                    "scene_idx": scene_idx,
                    "combination": combination,
                    "vton_results": [],
                    "final_image": final_image,
                    "item_categories": item_categories,
                    "error": None,
                }
            logger.warning(
                "[多换装·VTON] 场景 %d 无可用服装商品图: combination=%s",
                scene_idx, combination,
            )
            return {
                "scene_idx": scene_idx,
                "combination": combination,
                "vton_results": [],
                "final_image": b"",
                "item_categories": [],
                "error": "无可用服装商品图",
            }

        try:
            intermediate_images = await vton_client.try_on_chain_with_intermediates(
                user_photo=model_image,
                garments=garment_images,
                categories=successful_categories,
                max_retries_per_item=1,
            )
        except Exception as e:
            logger.warning("[多换装·VTON] 场景 %d 链式 VTON 异常: %s", scene_idx, e)
            return {
                "scene_idx": scene_idx, "combination": combination,
                "vton_results": [], "final_image": b"",
                "item_categories": [], "error": f"VTON 异常: {e}",
            }

        if not intermediate_images:
            logger.warning(
                "[多换装·VTON] 场景 %d 链式 VTON 全部失败: combination=%s",
                scene_idx, combination,
            )
            return {
                "scene_idx": scene_idx, "combination": combination,
                "vton_results": [], "final_image": b"",
                "item_categories": [], "error": "VTON 全部失败",
            }

        final_image = intermediate_images[-1][0]
        vton_results = [img for img, _ in intermediate_images]
        item_categories = [
            successful_categories[idx] if idx < len(successful_categories) else "未知"
            for _, idx in intermediate_images
        ]

        # VTON 成功后，对配饰/包类调用 wan2.7-image 链式穿戴
        if accessory_items:
            final_image = await _wear_accessories_chain(
                final_image, accessory_items, item_images_cache, scene_idx,
            )
            for it in accessory_items:
                item_categories.append(it.get("category", "配饰"))

        logger.info(
            "[多换装·VTON] 场景 %d 成功: combination=%s, 中间图数=%d, final=%d bytes",
            scene_idx, combination, len(intermediate_images), len(final_image),
        )
        return {
            "scene_idx": scene_idx, "combination": combination,
            "vton_results": vton_results, "final_image": final_image,
            "item_categories": item_categories, "error": None,
        }

    # 并行执行所有场景
    scene_tasks = [
        _run_one_scene(idx, combo) for idx, combo in enumerate(combinations)
    ]
    scene_results = await asyncio.gather(*scene_tasks, return_exceptions=True)

    # 处理异常
    clean_scene_results: list[dict] = []
    for r in scene_results:
        if isinstance(r, Exception):
            logger.error("[多换装·VTON] 场景执行异常: %s", r)
            clean_scene_results.append({
                "scene_idx": len(clean_scene_results),
                "combination": [], "vton_results": [], "final_image": b"",
                "item_categories": [], "error": f"场景异常: {r}",
            })
        else:
            clean_scene_results.append(r)

    success_count = sum(1 for r in clean_scene_results if r.get("final_image"))
    logger.info(
        "[多换装·VTON] taskId=%s, 场景数=%d, 成功=%d",
        task_id, len(clean_scene_results), success_count,
    )

    if success_count == 0:
        return {
            "scene_results": clean_scene_results,
            "error": "所有场景 VTON 均失败",
        }

    return {"scene_results": clean_scene_results}


# ============================================================================
# 节点 3：并行评估 + 独立后处理
# ============================================================================

async def multi_outfit_review_and_post_node(state: DirectorState) -> dict:
    """并行评估 + 独立后处理节点：每张图走完整评估 + 决策 + 后处理

    实现策略：
    - 对每个成功的场景构造子 state，调用 director_review_node 评估
    - 评估决策为 post_process 的场景，独立调 O1 后处理
    - 后处理限 1 轮/张，后处理后重评，回归校验

    Returns:
        更新 scene_results，每个场景新增：agent_evaluations/director_decision/
        overall_score/star_rating/post_process_actions/post_processed_image/
        decision_reason_cn/issues_summary
    """
    scene_results = state.get("scene_results") or []
    items = state.get("items", [])
    selected_model = state.get("selected_model_image", {})

    async def _evaluate_one_scene(scene_idx: int, scene: dict) -> dict:
        """评估单个场景 + 后处理"""
        final_image = scene.get("final_image")
        if not final_image:
            # VTON 失败的场景跳过评估
            scene.update({
                "agent_evaluations": {}, "director_decision": "fail",
                "overall_score": 0.0, "star_rating": 0,
                "post_process_actions": [], "post_processed_image": None,
                "decision_reason_cn": scene.get("error", "VTON 失败"),
                "issues_summary": [],
            })
            return scene

        # 构造子 state 调用 director_review_node
        # 复用导演评估节点（含 ReAct 反思 + 多候选投票 + 重评逻辑）
        # 但多换装模式下每张图独立评估，不走多候选投票
        sub_state: DirectorState = {
            "task_id": state.get("task_id", ""),
            "shop_id": state.get("shop_id", 0),
            "user_id": state.get("user_id", 0),
            "items": items,
            "selected_model_image": selected_model,
            "final_image": final_image,
            "vton_results": scene.get("vton_results", []),
            "item_categories": scene.get("item_categories", []),
            "post_process_round": 0,
            "candidates_final_images": [],  # 强制单候选模式
        }

        # 首次评估
        review_result = await director_review_node(sub_state)
        decision = review_result.get("director_decision", "pass")
        actions = review_result.get("post_process_actions") or []
        prev_score = review_result.get("overall_score", 0.0)

        # 后处理（限 1 轮）
        post_processed_image = None
        if decision == "post_process" and actions:
            post_processed_image = await _post_process_one_image(
                final_image, actions, state.get("task_id", ""),
            )

            if post_processed_image is not None:
                # 后处理后重评
                re_review_state = {
                    **sub_state,
                    "final_image": post_processed_image,
                    "post_process_round": 1,
                    "post_process_actions": actions,
                    "overall_score": prev_score,
                    "stylist_dual_review": review_result.get("stylist_dual_review"),
                    "lighting_review": review_result.get("lighting_review"),
                    "makeup_review": review_result.get("makeup_review"),
                    "photographer_review": review_result.get("photographer_review"),
                }
                re_review_result = await director_review_node(re_review_state)
                new_score = re_review_result.get("overall_score", 0.0)

                # 回归校验：后处理后分数下降 > 0.1 则回退到 VTON 原图
                if new_score < prev_score - 0.1:
                    logger.warning(
                        "[多换装·评估] 场景 %d 后处理回归校验失败: prev=%.2f, new=%.2f, 回退原图",
                        scene_idx, prev_score, new_score,
                    )
                    post_processed_image = None
                    # 保留首次评估结果
                else:
                    # 用重评结果覆盖
                    review_result = re_review_result

        scene.update({
            "agent_evaluations": {
                "stylistEu": review_result.get("stylist_eu_review"),
                "stylistAsia": review_result.get("stylist_asia_review"),
                "lighting": review_result.get("lighting_review"),
                "makeup": review_result.get("makeup_review"),
                "photographer": review_result.get("photographer_review"),
            },
            "director_decision": review_result.get("director_decision", "pass"),
            "overall_score": review_result.get("overall_score", 0.0),
            "star_rating": review_result.get("star_rating", 3),
            "post_process_actions": actions,
            "post_processed_image": post_processed_image,
            "decision_reason_cn": review_result.get("decision_reason_cn", ""),
            "issues_summary": review_result.get("issues_summary", []),
        })
        return scene

    # 并行评估所有场景
    eval_tasks = [
        _evaluate_one_scene(idx, scene)
        for idx, scene in enumerate(scene_results)
    ]
    updated_scene_results = await asyncio.gather(*eval_tasks, return_exceptions=True)

    # 处理异常
    final_scene_results: list[dict] = []
    for r in updated_scene_results:
        if isinstance(r, Exception):
            logger.error("[多换装·评估] 场景评估异常: %s", r)
            final_scene_results.append({
                "scene_idx": len(final_scene_results),
                "combination": [], "vton_results": [], "final_image": b"",
                "item_categories": [], "error": f"评估异常: {r}",
                "agent_evaluations": {}, "director_decision": "fail",
                "overall_score": 0.0, "star_rating": 0,
                "post_process_actions": [], "post_processed_image": None,
                "decision_reason_cn": f"评估异常: {r}", "issues_summary": [],
            })
        else:
            final_scene_results.append(r)

    logger.info(
        "[多换装·评估] taskId=%s, 评估完成: 场景数=%d",
        state.get("task_id"), len(final_scene_results),
    )

    return {"scene_results": final_scene_results}


async def _post_process_one_image(
    source_image: bytes, actions: list[dict], task_id: str,
) -> bytes | None:
    """对单张图执行 O1 后处理"""
    from app.api.deps import get_gen_client

    prompt_parts = []
    for action in actions:
        action_prompt = action.get("action_prompt", "").strip()
        if action_prompt:
            prompt_parts.append(action_prompt)

    if not prompt_parts:
        return None

    combined_prompt = "; ".join(prompt_parts)
    if len(combined_prompt) > 2000:
        combined_prompt = combined_prompt[:2000]

    gen_client = await get_gen_client()
    try:
        edited_image = await gen_client.edit_image(
            source_image=source_image,
            prompt=combined_prompt,
            aspect_ratio="3:4",
        )
    except Exception as e:
        logger.error(
            "[多换装·后处理] taskId=%s, O1 异常: %s",
            task_id, e, exc_info=True,
        )
        return None

    if edited_image is None:
        logger.warning("[多换装·后处理] taskId=%s, O1 返回 None", task_id)
        return None

    logger.info(
        "[多换装·后处理] taskId=%s, 原图=%d bytes → 新图=%d bytes",
        task_id, len(source_image), len(edited_image),
    )
    return edited_image


# ============================================================================
# 节点 4：汇总上传
# ============================================================================

async def multi_outfit_upload_node(state: DirectorState) -> dict:
    """汇总上传节点：上传所有场景的最终图（含后处理版）

    Returns:
        更新 scene_results（每个场景新增 result_urls/post_processed_image_url）
        + 全局 result_urls（按场景顺序汇总）
    """
    from app.api.deps import get_oss_uploader

    oss_uploader = await get_oss_uploader()
    task_id = state.get("task_id", "unknown")
    scene_results = state.get("scene_results") or []

    all_result_urls: list[str] = []
    all_item_categories: list[str] = []

    for scene in scene_results:
        scene_idx = scene.get("scene_idx", 0)
        vton_results = scene.get("vton_results") or []
        item_categories = scene.get("item_categories") or []
        post_processed = scene.get("post_processed_image")

        scene_result_urls: list[str] = []

        # 上传中间图 + 最终图
        for idx, (image_data, category) in enumerate(
            zip(vton_results, item_categories), start=1
        ):
            url = await asyncio.to_thread(
                _upload_image_with_fallback,
                oss_uploader, image_data, task_id, scene_idx * 10 + idx,
                category, scene_idx,
            )
            if url:
                scene_result_urls.append(url)
                all_result_urls.append(url)
                all_item_categories.append(category)

        # 上传后处理版（如有）
        post_processed_url = None
        if post_processed:
            post_processed_url = await asyncio.to_thread(
                _upload_image_with_fallback,
                oss_uploader, post_processed, task_id,
                scene_idx * 10 + len(vton_results) + 1,
                f"optimized_scene{scene_idx + 1}", scene_idx,
            )
            if post_processed_url:
                scene_result_urls.append(post_processed_url)
                all_result_urls.append(post_processed_url)
                all_item_categories.append(f"optimized_scene{scene_idx + 1}")

        scene["result_urls"] = scene_result_urls
        scene["post_processed_image_url"] = post_processed_url

    logger.info(
        "[多换装·上传] taskId=%s, 场景数=%d, 总图数=%d",
        task_id, len(scene_results), len(all_result_urls),
    )

    return {
        "scene_results": scene_results,
        "result_urls": all_result_urls,
        "item_categories": all_item_categories,
    }


def _get_local_fallback_dir() -> Path | None:
    root = settings.nginx_uploads_root
    if not root:
        return None
    return Path(root) / LOCAL_FALLBACK_SUBDIR


def _get_local_fallback_url_prefix() -> str:
    return f"{settings.nginx_uploads_url_prefix.rstrip('/')}/{LOCAL_FALLBACK_SUBDIR}"


def _upload_image_with_fallback(
    oss_uploader, image_data: bytes, task_id: str,
    step: int, category: str, scene_idx: int = 0,
) -> str | None:
    """上传图片到 OSS，失败时降级到本地 nginx 静态目录"""
    try:
        url = oss_uploader.upload_image(
            file_data=image_data,
            directory=f"model/{task_id}",
            file_ext="jpg",
        )
        if url is not None:
            return url
    except Exception as e:
        logger.warning("OSS 上传异常，降级本地: step=%d, error=%s", step, e)

    return _save_to_local(image_data, task_id, step, category, scene_idx)


def _save_to_local(
    image_data: bytes, task_id: str, step: int,
    category: str, scene_idx: int = 0,
) -> str | None:
    """OSS 降级时把图片落地到 nginx 静态目录"""
    local_dir = _get_local_fallback_dir()
    if local_dir is None:
        logger.error("NGINX_UPLOADS_ROOT 未配置，无法本地降级存储")
        return None
    local_dir.mkdir(parents=True, exist_ok=True)
    md5_prefix = hashlib.md5(image_data).hexdigest()[:8]
    safe_category = _category_to_filename_safe(category, scene_idx)
    filename = f"{task_id}_s{scene_idx}_{step}_{safe_category}_{md5_prefix}.jpg"
    local_path = local_dir / filename
    if not local_path.exists():
        local_path.write_bytes(image_data)
    url = f"{_get_local_fallback_url_prefix()}/{filename}"
    logger.info("OSS 降级：模特图已存本地: %s", url)
    return url


# ============================================================================
# 工作流编排
# ============================================================================

def build_multi_outfit_graph():
    """构建 AI 模特多换装生成主图

    拓扑：
      entry → multi_outfit_plan（搭配推荐）
            → multi_outfit_vton（并行 VTON）
            → multi_outfit_review_and_post（并行评估+后处理）
            → multi_outfit_upload（汇总上传）
            → END
    """
    workflow = StateGraph(DirectorState)

    workflow.add_node(NODE_PLAN, multi_outfit_plan_node)
    workflow.add_node(NODE_VTON, multi_outfit_vton_node)
    workflow.add_node(NODE_REVIEW, multi_outfit_review_and_post_node)
    workflow.add_node(NODE_UPLOAD, multi_outfit_upload_node)

    workflow.set_entry_point(NODE_PLAN)
    workflow.add_edge(NODE_PLAN, NODE_VTON)
    workflow.add_edge(NODE_VTON, NODE_REVIEW)
    workflow.add_edge(NODE_REVIEW, NODE_UPLOAD)
    workflow.add_edge(NODE_UPLOAD, END)

    compiled = workflow.compile()
    logger.info("LangGraph AI 模特多换装主图已编译: v4 多换装模式")
    return compiled


# 编译一次，全局复用
_compiled_multi_outfit_graph = None
_compile_lock = asyncio.Lock()


async def get_compiled_multi_outfit_graph():
    """获取编译后的图单例（asyncio.Lock 保护）"""
    global _compiled_multi_outfit_graph
    if _compiled_multi_outfit_graph is None:
        async with _compile_lock:
            if _compiled_multi_outfit_graph is None:
                _compiled_multi_outfit_graph = build_multi_outfit_graph()
    return _compiled_multi_outfit_graph
