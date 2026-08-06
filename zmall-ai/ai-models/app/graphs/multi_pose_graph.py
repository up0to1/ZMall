"""
AI 模特多姿势生成主图（v5 新增）

设计文档 v5：多姿势模式工作流
  entry → multi_pose_vton（单次链式 VTON，生成基准图）
        → multi_pose_plan（LLM 推荐 N 个姿势 prompt）
        → multi_pose_generate（并行 O1 图生图，生成 N 个姿势变体）
        → multi_pose_review_and_post（并行评估 + 独立后处理）
        → multi_pose_upload（汇总上传所有图）
        → END

核心特性：
- 同脸/同妆造/同服装：VTON 一次生成基准图，所有姿势变体共享同一基准
- 不同姿势：LLM 推荐多样化姿势 prompt（站立/坐姿/侧身/特写等混合）
- O1 图生图：以 VTON 基准图为参考，按 prompt 生成姿势变体
- 并行评估：每张图走完整 5 维度评估 + 决策
- 独立后处理：每张图按决策独立后处理（限 1 轮/张）
- 结果汇总：所有图统一上传，按姿势顺序返回

与多换装模式（multi_outfit_graph）的区别：
- multi_outfit：N 套商品组合 → N 次链式 VTON → N 张图（不同服装）
- multi_pose：1 套商品组合 → 1 次链式 VTON + N 次 O1 图生图 → N 张图（同服装不同姿势）

商品选择规则：
- multi_pose：1 件上装 + 1 件下装 / 1 件全身套装（与 single 模式相同）
- multi_outfit：可放宽到 2 件下装 + 1 件上装（多套搭配）
"""
import asyncio
import hashlib
import logging
from pathlib import Path

import httpx
from langgraph.graph import END, StateGraph

from app.schemas.director_state import DirectorState
from app.subgraphs.director_nodes import director_review_node
from app.subgraphs._llm import _call_llm_with_retry, LLM_PLAN_TIMEOUT
from app.core.config import settings
from shared.outfit_common import is_safe_image_url
from app.prompts.multi_pose_prompts import (
    MULTI_POSE_SYSTEM_PROMPT,
    MULTI_POSE_USER_PROMPT,
)

logger = logging.getLogger(__name__)

# 节点名称常量
NODE_VTON = "multi_pose_vton"
NODE_PLAN = "multi_pose_plan"
NODE_GENERATE = "multi_pose_generate"
NODE_REVIEW = "multi_pose_review_and_post"
NODE_UPLOAD = "multi_pose_upload"

# 默认姿势数量（成本与多样性平衡）
DEFAULT_POSE_COUNT = 3
MAX_POSE_COUNT = 4

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
    "姿势1": "pose1", "姿势2": "pose2", "姿势3": "pose3", "姿势4": "pose4",
}


def _category_to_filename_safe(category: str, pose_idx: int = 0) -> str:
    """品类转文件名安全字符串，多姿势模式下加姿势前缀"""
    if category in _CATEGORY_FILENAME_MAP:
        return _CATEGORY_FILENAME_MAP[category]
    return f"pose{pose_idx + 1}"


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
    accessory_images_cache: dict[int, bytes],
) -> bytes:
    """对鞋/包/配饰依次调用 wan2.7-image 虚拟穿戴（链式，单件失败不中断）

    与 ai-outfit/nodes.py 的 _wear_accessories_chain 对齐：
    VTON（aitryon-plus）不支持配饰/包/鞋类，用 wan2.7-image 图生图实现。
    每件穿戴结果作为下一件的输入，形成链式穿戴。

    穿戴顺序：鞋 → 包 → 配饰（先穿鞋，再包，最后配饰点缀）

    Args:
        base_image: VTON 输出的人物图（已穿上服装）
        accessory_items: 鞋/包/配饰 商品列表
        accessory_images_cache: itemId → 商品图 bytes 缓存
    Returns:
        穿戴后的人物图；wan2.7-image 失败时返回原 base_image
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
        accessory_bytes = accessory_images_cache.get(item_id)
        if accessory_bytes is None:
            logger.warning("[多姿势·穿戴] 单品图未在缓存中: itemId=%s", item_id)
            continue

        worn = await gen_client.wear_accessory(current_image, accessory_bytes, cat)
        if worn is not None:
            current_image = worn
            success_count += 1
            logger.info("[多姿势·穿戴] wan2.7-image 穿戴成功: category=%s", cat)
        else:
            logger.warning("[多姿势·穿戴] wan2.7-image 穿戴失败，跳过: category=%s", cat)

    logger.info("[多姿势·穿戴] 单品穿戴完成: 总数=%d, 成功=%d",
                len(accessory_items), success_count)
    return current_image


# ============================================================================
# 节点 1：单次链式 VTON（生成基准图，所有姿势变体共享）
# ============================================================================

async def multi_pose_vton_node(state: DirectorState) -> dict:
    """单次链式 VTON 节点：生成基准图

    multi_pose 模式只需 1 次 VTON，所有姿势变体基于此图生成。
    商品按 VTON 链式顺序排序（全身套装→上衣→下装）。
    鞋/帽子/包/配饰不走 VTON（aitryon-plus 不支持），
    VTON 后用 wan2.7-image 链式穿戴（与 ai-outfit/nodes.py 对齐）。

    Returns:
        更新 state 的字段：vton_results, final_image, item_categories
        （基准图存入 final_image，供下游 multi_pose_generate 节点使用）
    """
    from app.api.deps import get_vton_client

    vton_client = await get_vton_client()
    items = state.get("items", [])
    task_id = state.get("task_id", "")
    selected_model = state.get("selected_model_image", {})
    model_image_url = (
        state.get("uploaded_model_url")
        or selected_model.get("url")
        or selected_model.get("imageUrl")
    )

    if not model_image_url:
        return {"vton_results": [], "final_image": b"", "error": "无模特图"}

    if not items:
        return {"vton_results": [], "final_image": b"", "error": "无商品"}

    # 下载模特图
    model_image = await _download_image(model_image_url)
    if model_image is None:
        return {"vton_results": [], "final_image": b"", "error": "模特图下载失败"}

    # 按品类分组：服装类进 VTON，配饰/包类走 wan2.7-image
    vton_grouped: dict[str, list] = {cat: [] for cat in VTON_CATEGORIES}
    accessory_items: list[dict] = []
    for item in items:
        cat = item.get("category")
        if cat in vton_grouped:
            vton_grouped[cat].append(item)
        elif cat in WAN_ACCESSORY_CATEGORIES:
            accessory_items.append(item)

    # VTON 链式顺序：全身套装→上衣→下装（鞋/帽子/包/配饰走 wan2.7-image 穿戴）
    ordered_vton_items: list[dict] = []
    for cat in ["全身套装", "上衣", "下装"]:
        ordered_vton_items.extend(vton_grouped.get(cat, []))

    # 下载 VTON 商品图
    garment_images: list[bytes] = []
    successful_categories: list[str] = []
    for item in ordered_vton_items:
        garment = await _download_image(item.get("ossUrl") or item.get("imageUrl", ""))
        if garment is None:
            logger.warning(
                "[多姿势·VTON] 商品图下载失败，跳过: itemId=%s",
                item.get("itemId"),
            )
            continue
        garment_images.append(garment)
        successful_categories.append(item.get("category", "未知"))

    # 下载配饰/包/下装/鞋类商品图（供 wan2.7-image 使用，先构建 cache）
    accessory_images_cache: dict[int, bytes] = {}
    for item in accessory_items:
        garment = await _download_image(item.get("ossUrl") or item.get("imageUrl", ""))
        if garment is not None:
            accessory_images_cache[item.get("itemId")] = garment

    if not garment_images:
        # 无 VTON 品类（仅下装/鞋/包/配饰）：直接用模特图作 base 走 wan2.7-image 穿戴
        if accessory_items:
            logger.info("[多姿势·VTON] 无 VTON 品类，直接用模特图走 wan2.7-image 穿戴")
            base_image = await _wear_accessories_chain(
                model_image, accessory_items, accessory_images_cache,
            )
            item_categories = [it.get("category", "配饰") for it in accessory_items]
            return {
                "vton_results": [],
                "final_image": base_image,
                "item_categories": item_categories,
                "error": None,
            }
        return {"vton_results": [], "final_image": b"", "error": "所有服装商品图下载失败"}

    # 链式 VTON（含中间图）
    try:
        intermediate_images = await vton_client.try_on_chain_with_intermediates(
            user_photo=model_image,
            garments=garment_images,
            categories=successful_categories,
            max_retries_per_item=1,
        )
    except Exception as e:
        logger.error("[多姿势·VTON] 链式 VTON 异常: %s", e, exc_info=True)
        return {"vton_results": [], "final_image": b"", "error": f"链式 VTON 异常: {e}"}

    if not intermediate_images:
        return {"vton_results": [], "final_image": b"", "error": "链式 VTON 全部失败"}

    # 基准图 = VTON 最终图
    base_image = intermediate_images[-1][0]
    vton_results = [img for img, _ in intermediate_images]
    item_categories = [
        successful_categories[idx] if idx < len(successful_categories) else "未知"
        for _, idx in intermediate_images
    ]

    # VTON 成功后，对配饰/包类调用 wan2.7-image 链式穿戴
    if accessory_items:
        base_image = await _wear_accessories_chain(
            base_image, accessory_items, accessory_images_cache,
        )
        for it in accessory_items:
            item_categories.append(it.get("category", "配饰"))

    logger.info(
        "[多姿势·VTON] taskId=%s, 基准图生成成功: 中间图数=%d, base=%d bytes",
        task_id, len(intermediate_images), len(base_image),
    )

    return {
        "vton_results": vton_results,
        "final_image": base_image,
        "item_categories": item_categories,
    }


# ============================================================================
# 节点 2：LLM 推荐 N 个姿势 prompt
# ============================================================================

async def multi_pose_plan_node(state: DirectorState) -> dict:
    """LLM 推荐姿势 prompt 节点

    基于商品描述生成 N 个多样化的姿势 prompt（中文，供 wan2.7-image 图生图使用）。
    LLM 不可用时降级为预设姿势模板。

    Returns:
        更新 state 的字段：pose_prompts
    """
    items = state.get("items", [])
    task_id = state.get("task_id", "")
    pose_count = state.get("pose_count", DEFAULT_POSE_COUNT)
    pose_count = max(1, min(pose_count, MAX_POSE_COUNT))

    # 构造 outfit 描述
    outfit_parts = []
    for it in items:
        name = it.get("name", "")
        category = it.get("category", "")
        color = it.get("color", "")
        desc = f"{color} {category}".strip()
        if name:
            desc = f"{desc} ({name})".strip()
        if desc:
            outfit_parts.append(desc)
    outfit_desc = " + ".join(outfit_parts) if outfit_parts else "fashion outfit"

    # LLM 不可用时走预设模板
    if not _is_llm_configured():
        logger.info("[多姿势·策划] LLM 不可用，走预设姿势模板")
        poses = _generate_fallback_poses(outfit_desc, pose_count)
        return {"pose_prompts": poses}

    user_prompt = MULTI_POSE_USER_PROMPT.format(
        pose_count=pose_count,
        outfit_desc=outfit_desc,
    )

    try:
        llm_result = await _call_llm_with_retry(
            model=settings.llm_text_model,
            system_prompt=MULTI_POSE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            agent_name="multi_pose_plan",
            timeout=LLM_PLAN_TIMEOUT,
            temperature=0.4,
        )
    except Exception as e:
        logger.warning("[多姿势·策划] LLM 调用异常，走预设模板: %s", e)
        return {"pose_prompts": _generate_fallback_poses(outfit_desc, pose_count)}

    if llm_result.is_fallback or llm_result.data is None:
        logger.warning("[多姿势·策划] LLM 返回 fallback，走预设模板")
        return {"pose_prompts": _generate_fallback_poses(outfit_desc, pose_count)}

    raw_poses = llm_result.data.get("poses") or []
    if not raw_poses or not isinstance(raw_poses, list):
        logger.warning("[多姿势·策划] LLM 输出 poses 为空，走预设模板")
        return {"pose_prompts": _generate_fallback_poses(outfit_desc, pose_count)}

    # 校验每个 pose 必须含 prompt 字段
    valid_poses: list[dict] = []
    for idx, p in enumerate(raw_poses[:pose_count]):
        if not isinstance(p, dict):
            continue
        prompt = (p.get("prompt") or "").strip()
        if not prompt:
            continue
        valid_poses.append({
            "name": p.get("name") or f"Pose {idx + 1}",
            "prompt": prompt,
            "intent_cn": p.get("intent_cn") or "",
        })

    if not valid_poses:
        logger.warning("[多姿势·策划] LLM 输出全非法，走预设模板")
        return {"pose_prompts": _generate_fallback_poses(outfit_desc, pose_count)}

    logger.info(
        "[多姿势·策划] taskId=%s, LLM 推荐姿势数=%d",
        task_id, len(valid_poses),
    )
    return {"pose_prompts": valid_poses}


def _generate_fallback_poses(outfit_desc: str, pose_count: int) -> list[dict]:
    """LLM 不可用时的降级：预设姿势模板（中文 prompt，与 v5 设计对齐）"""
    templates = [
        {
            "name": "正面站立",
            "prompt": f"同一位模特，同一套服装（{outfit_desc}），同样的妆容和发型，"
                      "全身正面视角，直立站姿，双手自然下垂，目视前方，"
                      "影棚灯光，中性背景，电商画册风格。",
            "intent_cn": "正面站立，双手自然下垂，目视前方",
        },
        {
            "name": "三七分站姿",
            "prompt": f"同一位模特，同一套服装（{outfit_desc}），同样的妆容和发型，"
                      "三七分站姿，单手叉腰，微微侧头，柔和微笑，目光看向侧前方，"
                      "影棚灯光带轻微阴影，中性背景。",
            "intent_cn": "三七分站姿，单手叉腰，微微侧头",
        },
        {
            "name": "侧面轮廓",
            "prompt": f"同一位模特，同一套服装（{outfit_desc}），同样的妆容和发型，"
                      "侧面轮廓视角，双手交叉胸前，目光向外，"
                      "戏剧性侧光，中性灰色背景，时尚大片风格。",
            "intent_cn": "侧面轮廓，双手交叉胸前，目光向外",
        },
        {
            "name": "行走抓拍",
            "prompt": f"同一位模特，同一套服装（{outfit_desc}），同样的妆容和发型，"
                      "行走中抓拍，一只脚向前，自然摆臂，"
                      "编辑级风格，柔和自然光，极简背景。",
            "intent_cn": "行走中抓拍，自然摆臂，编辑级风格",
        },
    ]
    return templates[:max(1, min(pose_count, MAX_POSE_COUNT))]


def _is_llm_configured() -> bool:
    """检查 LLM 是否已配置"""
    return bool(
        settings.llm_api_url and settings.llm_api_key
        and settings.llm_text_model
    )


# ============================================================================
# 节点 3：并行 O1 图生图（生成 N 个姿势变体）
# ============================================================================

async def multi_pose_generate_node(state: DirectorState) -> dict:
    """并行 O1 图生图节点：基于 VTON 基准图生成 N 个姿势变体

    Returns:
        更新 state 的字段：pose_results（每个姿势含 final_image/pose_name/pose_prompt）
    """
    from app.api.deps import get_gen_client

    gen_client = await get_gen_client()
    base_image = state.get("final_image", b"")
    pose_prompts = state.get("pose_prompts") or []
    task_id = state.get("task_id", "")

    if not base_image:
        return {"pose_results": [], "error": "无基准图（VTON 失败）"}

    if not pose_prompts:
        return {"pose_results": [], "error": "无姿势 prompt"}

    async def _generate_one_pose(pose_idx: int, pose: dict) -> dict:
        """生成单个姿势变体"""
        prompt = pose.get("prompt", "")
        name = pose.get("name", f"Pose {pose_idx + 1}")
        intent_cn = pose.get("intent_cn", "")

        if not prompt:
            return {
                "pose_idx": pose_idx, "pose_name": name, "pose_prompt": prompt,
                "intent_cn": intent_cn, "final_image": b"", "error": "无 prompt",
            }

        try:
            edited_image = await gen_client.edit_image(
                source_image=base_image,
                prompt=prompt,
                aspect_ratio="3:4",
            )
        except Exception as e:
            logger.warning("[多姿势·生成] 姿势 %d O1 异常: %s", pose_idx, e)
            return {
                "pose_idx": pose_idx, "pose_name": name, "pose_prompt": prompt,
                "intent_cn": intent_cn, "final_image": b"",
                "error": f"O1 异常: {e}",
            }

        if edited_image is None:
            logger.warning("[多姿势·生成] 姿势 %d O1 返回 None", pose_idx)
            return {
                "pose_idx": pose_idx, "pose_name": name, "pose_prompt": prompt,
                "intent_cn": intent_cn, "final_image": b"",
                "error": "O1 返回 None",
            }

        logger.info(
            "[多姿势·生成] 姿势 %d 成功: name=%s, final=%d bytes",
            pose_idx, name, len(edited_image),
        )
        return {
            "pose_idx": pose_idx, "pose_name": name, "pose_prompt": prompt,
            "intent_cn": intent_cn, "final_image": edited_image, "error": None,
        }

    # 并行生成所有姿势
    pose_tasks = [
        _generate_one_pose(idx, pose)
        for idx, pose in enumerate(pose_prompts)
    ]
    pose_results = await asyncio.gather(*pose_tasks, return_exceptions=True)

    # 处理异常
    clean_pose_results: list[dict] = []
    for r in pose_results:
        if isinstance(r, Exception):
            logger.error("[多姿势·生成] 姿势执行异常: %s", r)
            clean_pose_results.append({
                "pose_idx": len(clean_pose_results),
                "pose_name": f"Pose {len(clean_pose_results) + 1}",
                "pose_prompt": "", "intent_cn": "",
                "final_image": b"", "error": f"姿势异常: {r}",
            })
        else:
            clean_pose_results.append(r)

    success_count = sum(1 for r in clean_pose_results if r.get("final_image"))
    logger.info(
        "[多姿势·生成] taskId=%s, 姿势数=%d, 成功=%d",
        task_id, len(clean_pose_results), success_count,
    )

    if success_count == 0:
        return {
            "pose_results": clean_pose_results,
            "error": "所有姿势 O1 图生图均失败",
        }

    return {"pose_results": clean_pose_results}


# ============================================================================
# 节点 4：并行评估 + 独立后处理
# ============================================================================

async def multi_pose_review_and_post_node(state: DirectorState) -> dict:
    """并行评估 + 独立后处理节点：每张姿势图走完整评估 + 决策 + 后处理

    Returns:
        更新 pose_results，每个姿势新增：agent_evaluations/director_decision/
        overall_score/star_rating/post_process_actions/post_processed_image/
        decision_reason_cn/issues_summary
    """
    pose_results = state.get("pose_results") or []
    items = state.get("items", [])
    selected_model = state.get("selected_model_image", {})

    async def _evaluate_one_pose(pose_idx: int, pose: dict) -> dict:
        """评估单个姿势 + 后处理"""
        final_image = pose.get("final_image")
        if not final_image:
            # O1 失败的姿势跳过评估
            pose.update({
                "agent_evaluations": {}, "director_decision": "fail",
                "overall_score": 0.0, "star_rating": 0,
                "post_process_actions": [], "post_processed_image": None,
                "decision_reason_cn": pose.get("error", "O1 图生图失败"),
                "issues_summary": [],
            })
            return pose

        # 构造子 state 调用 director_review_node
        sub_state: DirectorState = {
            "task_id": state.get("task_id", ""),
            "shop_id": state.get("shop_id", 0),
            "user_id": state.get("user_id", 0),
            "items": items,
            "selected_model_image": selected_model,
            "final_image": final_image,
            "vton_results": [],
            "item_categories": [],
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

                # 回归校验：后处理后分数下降 > 0.1 则回退到 O1 原图
                if new_score < prev_score - 0.1:
                    logger.warning(
                        "[多姿势·评估] 姿势 %d 后处理回归校验失败: prev=%.2f, new=%.2f, 回退原图",
                        pose_idx, prev_score, new_score,
                    )
                    post_processed_image = None
                else:
                    review_result = re_review_result

        pose.update({
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
        return pose

    # 并行评估所有姿势
    eval_tasks = [
        _evaluate_one_pose(idx, pose)
        for idx, pose in enumerate(pose_results)
    ]
    updated_pose_results = await asyncio.gather(*eval_tasks, return_exceptions=True)

    # 处理异常
    final_pose_results: list[dict] = []
    for r in updated_pose_results:
        if isinstance(r, Exception):
            logger.error("[多姿势·评估] 姿势评估异常: %s", r)
            final_pose_results.append({
                "pose_idx": len(final_pose_results),
                "pose_name": f"Pose {len(final_pose_results) + 1}",
                "pose_prompt": "", "intent_cn": "",
                "final_image": b"", "error": f"评估异常: {r}",
                "agent_evaluations": {}, "director_decision": "fail",
                "overall_score": 0.0, "star_rating": 0,
                "post_process_actions": [], "post_processed_image": None,
                "decision_reason_cn": f"评估异常: {r}", "issues_summary": [],
            })
        else:
            final_pose_results.append(r)

    logger.info(
        "[多姿势·评估] taskId=%s, 评估完成: 姿势数=%d",
        state.get("task_id"), len(final_pose_results),
    )

    return {"pose_results": final_pose_results}


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
            "[多姿势·后处理] taskId=%s, O1 异常: %s",
            task_id, e, exc_info=True,
        )
        return None

    if edited_image is None:
        logger.warning("[多姿势·后处理] taskId=%s, O1 返回 None", task_id)
        return None

    logger.info(
        "[多姿势·后处理] taskId=%s, 原图=%d bytes → 新图=%d bytes",
        task_id, len(source_image), len(edited_image),
    )
    return edited_image


# ============================================================================
# 节点 5：汇总上传
# ============================================================================

async def multi_pose_upload_node(state: DirectorState) -> dict:
    """汇总上传节点：上传所有姿势的最终图（含后处理版）

    Returns:
        更新 pose_results（每个姿势新增 result_urls/post_processed_image_url）
        + 全局 result_urls（按姿势顺序汇总）+ item_categories
    """
    from app.api.deps import get_oss_uploader

    oss_uploader = await get_oss_uploader()
    task_id = state.get("task_id", "unknown")
    pose_results = state.get("pose_results") or []
    vton_results = state.get("vton_results") or []
    item_categories_base = state.get("item_categories") or []

    all_result_urls: list[str] = []
    all_item_categories: list[str] = []

    # 上传 VTON 中间图（基准图的中间过程，供前端查看换装过程）
    for idx, (image_data, category) in enumerate(
        zip(vton_results, item_categories_base), start=1
    ):
        url = await asyncio.to_thread(
            _upload_image_with_fallback,
            oss_uploader, image_data, task_id, idx,
            category, 0,
        )
        if url:
            all_result_urls.append(url)
            all_item_categories.append(category)

    # 上传每个姿势的最终图 + 后处理版
    for pose in pose_results:
        pose_idx = pose.get("pose_idx", 0)
        final_image = pose.get("final_image")
        post_processed = pose.get("post_processed_image")
        pose_name = pose.get("pose_name", f"Pose {pose_idx + 1}")

        pose_result_urls: list[str] = []

        # 上传姿势最终图
        if final_image:
            category = f"pose{pose_idx + 1}"
            url = await asyncio.to_thread(
                _upload_image_with_fallback,
                oss_uploader, final_image, task_id,
                100 + pose_idx + 1,  # step 避免与 VTON 中间图冲突
                category, pose_idx,
            )
            if url:
                pose_result_urls.append(url)
                all_result_urls.append(url)
                all_item_categories.append(f"{pose_name}")

        # 上传后处理版（如有）
        post_processed_url = None
        if post_processed:
            post_processed_url = await asyncio.to_thread(
                _upload_image_with_fallback,
                oss_uploader, post_processed, task_id,
                200 + pose_idx + 1,
                f"optimized_pose{pose_idx + 1}", pose_idx,
            )
            if post_processed_url:
                pose_result_urls.append(post_processed_url)
                all_result_urls.append(post_processed_url)
                all_item_categories.append(f"optimized_{pose_name}")

        pose["result_urls"] = pose_result_urls
        pose["post_processed_image_url"] = post_processed_url

    logger.info(
        "[多姿势·上传] taskId=%s, 姿势数=%d, 总图数=%d",
        task_id, len(pose_results), len(all_result_urls),
    )

    return {
        "pose_results": pose_results,
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
    step: int, category: str, pose_idx: int = 0,
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

    return _save_to_local(image_data, task_id, step, category, pose_idx)


def _save_to_local(
    image_data: bytes, task_id: str, step: int,
    category: str, pose_idx: int = 0,
) -> str | None:
    """OSS 降级时把图片落地到 nginx 静态目录"""
    local_dir = _get_local_fallback_dir()
    if local_dir is None:
        logger.error("NGINX_UPLOADS_ROOT 未配置，无法本地降级存储")
        return None
    local_dir.mkdir(parents=True, exist_ok=True)
    md5_prefix = hashlib.md5(image_data).hexdigest()[:8]
    safe_category = _category_to_filename_safe(category, pose_idx)
    filename = f"{task_id}_p{pose_idx}_{step}_{safe_category}_{md5_prefix}.jpg"
    local_path = local_dir / filename
    if not local_path.exists():
        local_path.write_bytes(image_data)
    url = f"{_get_local_fallback_url_prefix()}/{filename}"
    logger.info("OSS 降级：模特图已存本地: %s", url)
    return url


# ============================================================================
# 工作流编排
# ============================================================================

def build_multi_pose_graph():
    """构建 AI 模特多姿势生成主图

    拓扑：
      entry → multi_pose_vton（单次链式 VTON，生成基准图）
            → multi_pose_plan（LLM 推荐姿势 prompt）
            → multi_pose_generate（并行 O1 图生图，生成 N 个姿势变体）
            → multi_pose_review_and_post（并行评估+后处理）
            → multi_pose_upload（汇总上传）
            → END
    """
    workflow = StateGraph(DirectorState)

    workflow.add_node(NODE_VTON, multi_pose_vton_node)
    workflow.add_node(NODE_PLAN, multi_pose_plan_node)
    workflow.add_node(NODE_GENERATE, multi_pose_generate_node)
    workflow.add_node(NODE_REVIEW, multi_pose_review_and_post_node)
    workflow.add_node(NODE_UPLOAD, multi_pose_upload_node)

    workflow.set_entry_point(NODE_VTON)
    workflow.add_edge(NODE_VTON, NODE_PLAN)
    workflow.add_edge(NODE_PLAN, NODE_GENERATE)
    workflow.add_edge(NODE_GENERATE, NODE_REVIEW)
    workflow.add_edge(NODE_REVIEW, NODE_UPLOAD)
    workflow.add_edge(NODE_UPLOAD, END)

    compiled = workflow.compile()
    logger.info("LangGraph AI 模特多姿势主图已编译: v5 多姿势模式")
    return compiled


# 编译一次，全局复用
_compiled_multi_pose_graph = None
_compile_lock = asyncio.Lock()


async def get_compiled_multi_pose_graph():
    """获取编译后的图单例（asyncio.Lock 保护）"""
    global _compiled_multi_pose_graph
    if _compiled_multi_pose_graph is None:
        async with _compile_lock:
            if _compiled_multi_pose_graph is None:
                _compiled_multi_pose_graph = build_multi_pose_graph()
    return _compiled_multi_pose_graph
