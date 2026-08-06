"""
AI 模特多 Agent 决策主图

设计文档 §1.8.4：主图节点拓扑
  entry → director_plan（策划）→ vton_execute（VTON 执行）
        → director_review（评估）→ [条件分支]
        ├─ pass → oss_upload → END
        └─ post_process → director_review（重评，限 1 轮）→ ...

- 单候选时向后兼容原路径
"""
import asyncio
import hashlib
import logging
from pathlib import Path

import httpx
from langgraph.graph import END, StateGraph

from app.schemas.director_state import DirectorState
from app.subgraphs.director_nodes import director_plan_node, director_review_node
from app.core.config import settings
from shared.outfit_common import is_safe_image_url

logger = logging.getLogger(__name__)

# 节点名称常量
NODE_PLAN = "director_plan"
NODE_VTON = "vton_execute"
NODE_REVIEW = "director_review"
NODE_POST_PROCESS = "post_process"
NODE_OSS_UPLOAD = "oss_upload"

# 后处理最大轮次（设计文档 §1.8.3：后处理限 1 轮，避免成本失控）
MAX_POST_PROCESS_ROUNDS = 1

# 模特图 OSS 降级时子目录名
LOCAL_FALLBACK_SUBDIR = "model"


def _get_local_fallback_dir() -> Path | None:
    root = settings.nginx_uploads_root
    if not root:
        return None
    return Path(root) / LOCAL_FALLBACK_SUBDIR


def _get_local_fallback_url_prefix() -> str:
    return f"{settings.nginx_uploads_url_prefix.rstrip('/')}/{LOCAL_FALLBACK_SUBDIR}"


# 品类中→英文件名映射（避免中文文件名编码问题）
_CATEGORY_FILENAME_MAP = {
    "上衣": "tops", "下装": "bottoms", "全身套装": "dress",
    "帽子": "hat", "鞋": "shoes", "包": "bag", "配饰": "accessory",
}


def _category_to_filename_safe(category: str) -> str:
    return _CATEGORY_FILENAME_MAP.get(category, "item")


async def vton_execute_node(state: DirectorState) -> dict:
    """VTON 执行节点（多候选并行执行）

    - 单候选：按 vton_order 顺序执行链式 VTON（向后兼容）
    - 多候选：按 vton_order_candidates 并行跑链式 VTON，结果存入
      candidates_vton_results / candidates_final_images /
      candidates_item_categories；同时用主候选（第 1 个）填充
      vton_results / final_image / item_categories 作为默认值，
      director_review_node 投票后会用最佳候选覆盖。

    Returns:
        更新 state 的字段：
        - 单候选：vton_results, final_image, item_categories
        - 多候选：上述 + candidates_vton_results, candidates_final_images,
          candidates_item_categories
    """
    from app.api.deps import get_vton_client

    vton_client = await get_vton_client()
    items = state.get("items", [])
    vton_order = state.get("vton_order") or []
    vton_order_candidates = state.get("vton_order_candidates") or []
    selected_model = state.get("selected_model_image", {})
    model_image_url = (
        state.get("uploaded_model_url")
        or selected_model.get("url")
        or selected_model.get("imageUrl")
    )

    if not model_image_url:
        return {"vton_results": [], "final_image": b"", "error": "无模特图"}

    # 下载模特图（所有候选共用一张）
    model_image = await _download_image(model_image_url)
    if model_image is None:
        return {"vton_results": [], "final_image": b"", "error": "模特图下载失败"}

    # 下载所有商品图（按 itemId 去重缓存，避免多候选重复下载）
    item_images_cache: dict[int, bytes] = {}
    for item in items:
        item_id = item.get("itemId")
        if item_id in item_images_cache:
            continue
        garment = await _download_image(item.get("ossUrl") or item.get("imageUrl", ""))
        if garment is None:
            logger.warning(
                "[VTON执行] 商品图下载失败，跳过: itemId=%s", item_id,
            )
            continue
        item_images_cache[item_id] = garment

    if not item_images_cache:
        return {"vton_results": [], "final_image": b"", "error": "所有商品图下载失败"}

    # ===== 单候选模式（向后兼容）=====
    if len(vton_order_candidates) <= 1:
        return await _vton_execute_single(
            state, vton_client, items, vton_order,
            model_image, item_images_cache,
        )

    # ===== 多候选并行模式（v3 新增）=====
    return await _vton_execute_multi(
        state, vton_client, items, vton_order_candidates,
        model_image, item_images_cache,
    )


async def _vton_execute_single(
    state: DirectorState, vton_client, items: list[dict],
    vton_order: list[str], model_image: bytes,
    item_images_cache: dict[int, bytes],
) -> dict:
    """单候选 VTON 执行（向后兼容）"""
    # 按 vton_order 重排 items（如果导演决策了顺序）
    if vton_order:
        order_map = {cat: i for i, cat in enumerate(vton_order)}
        items_sorted = sorted(items, key=lambda it: order_map.get(it.get("category", ""), 999))
    else:
        items_sorted = items

    # 按顺序从缓存取商品图
    garment_images: list[bytes] = []
    successful_categories: list[str] = []
    for item in items_sorted:
        img = item_images_cache.get(item.get("itemId"))
        if img is None:
            continue
        garment_images.append(img)
        successful_categories.append(item.get("category", "未知"))

    if not garment_images:
        return {"vton_results": [], "final_image": b"", "error": "所有商品图下载失败"}

    # 链式 VTON（含中间图）
    try:
        intermediate_images = await vton_client.try_on_chain_with_intermediates(
            user_photo=model_image,
            garments=garment_images,
            max_retries_per_item=1,
        )
    except Exception as e:
        logger.error("[VTON执行·单候选] 链式 VTON 异常: %s", e, exc_info=True)
        return {"vton_results": [], "final_image": b"", "error": f"链式 VTON 异常: {e}"}

    if not intermediate_images:
        return {"vton_results": [], "final_image": b"", "error": "链式 VTON 全部失败"}

    # intermediate_images 是 [(image, original_garment_idx), ...]
    # 必须用 original_idx 对齐 successful_categories，禁止用
    # successful_categories[:len(intermediate_images)] 从头部截取——中间件失败
    # continue 后长度不一致会导致品类标签与图片错位。
    final_image = intermediate_images[-1][0]
    vton_results = [img for img, _ in intermediate_images]
    item_categories = [
        successful_categories[idx] if idx < len(successful_categories) else "未知"
        for _, idx in intermediate_images
    ]
    logger.info(
        "[VTON执行·单候选] taskId=%s, 中间图数=%d, final_image=%d bytes",
        state.get("task_id"), len(intermediate_images), len(final_image),
    )

    return {
        "vton_results": vton_results,
        "final_image": final_image,
        "item_categories": item_categories,
    }


async def _vton_execute_multi(
    state: DirectorState, vton_client, items: list[dict],
    vton_order_candidates: list[list[str]], model_image: bytes,
    item_images_cache: dict[int, bytes],
) -> dict:
    """多候选并行 VTON 执行（v3 新增）

    对每个候选顺序并行跑链式 VTON，结果分别存入 candidates_* 字段。
    主候选（第 1 个）的结果同时填充 vton_results / final_image /
    item_categories 作为默认值（director_review 投票后会用最佳候选覆盖）。

    若某候选失败，从候选列表中剔除（不参与投票）。
    若所有候选都失败，返回 error。
    """
    task_id = state.get("task_id")

    async def _run_one_candidate(
        cand_idx: int, order: list[str],
    ) -> tuple[int, list[bytes], bytes, list[str]] | None:
        """跑单个候选的链式 VTON

        Returns:
            (cand_idx, vton_results, final_image, item_categories) 或 None（失败）
        """
        # 按候选顺序重排 items
        order_map = {cat: i for i, cat in enumerate(order)}
        items_sorted = sorted(
            items, key=lambda it: order_map.get(it.get("category", ""), 999),
        )
        garment_images: list[bytes] = []
        successful_categories: list[str] = []
        for item in items_sorted:
            img = item_images_cache.get(item.get("itemId"))
            if img is None:
                continue
            garment_images.append(img)
            successful_categories.append(item.get("category", "未知"))

        if not garment_images:
            logger.warning(
                "[VTON执行·多候选] 候选 %d 无可用商品图，跳过: order=%s",
                cand_idx, order,
            )
            return None

        try:
            intermediate_images = await vton_client.try_on_chain_with_intermediates(
                user_photo=model_image,
                garments=garment_images,
                max_retries_per_item=1,
            )
        except Exception as e:
            logger.warning(
                "[VTON执行·多候选] 候选 %d 链式 VTON 异常: %s",
                cand_idx, e,
            )
            return None

        if not intermediate_images:
            logger.warning(
                "[VTON执行·多候选] 候选 %d 链式 VTON 全部失败: order=%s",
                cand_idx, order,
            )
            return None

        final_image = intermediate_images[-1][0]
        vton_results = [img for img, _ in intermediate_images]
        item_categories = [
            successful_categories[idx] if idx < len(successful_categories) else "未知"
            for _, idx in intermediate_images
        ]
        logger.info(
            "[VTON执行·多候选] 候选 %d 成功: order=%s, 中间图数=%d, final=%d bytes",
            cand_idx, order, len(intermediate_images), len(final_image),
        )
        return (cand_idx, vton_results, final_image, item_categories)

    # 并行执行所有候选
    candidate_tasks = [
        _run_one_candidate(idx, order)
        for idx, order in enumerate(vton_order_candidates)
    ]
    candidate_results = await asyncio.gather(*candidate_tasks, return_exceptions=True)

    # 过滤成功结果（保留原 cand_idx 以便投票时对齐）
    successful: list[tuple[int, list[bytes], bytes, list[str]]] = []
    for r in candidate_results:
        if isinstance(r, Exception):
            logger.warning("[VTON执行·多候选] 候选执行异常: %s", r)
            continue
        if r is not None:
            successful.append(r)

    if not successful:
        logger.error(
            "[VTON执行·多候选] taskId=%s, 全部 %d 个候选均失败",
            task_id, len(vton_order_candidates),
        )
        return {
            "vton_results": [], "final_image": b"",
            "error": "所有 VTON 顺序候选均失败",
        }

    # 构造多候选字段（按候选索引排序，便于 director_review 对齐）
    successful.sort(key=lambda x: x[0])
    candidates_vton_results = [r[1] for r in successful]
    candidates_final_images = [r[2] for r in successful]
    candidates_item_categories = [r[3] for r in successful]

    # 主候选（cand_idx=0）若有结果则作为默认值，否则用第 1 个成功的候选
    main_candidate = next((r for r in successful if r[0] == 0), None)
    if main_candidate is None:
        main_candidate = successful[0]

    _, main_vton_results, main_final_image, main_item_categories = main_candidate

    logger.info(
        "[VTON执行·多候选] taskId=%s, 候选数=%d, 成功数=%d, 主候选idx=%d",
        task_id, len(vton_order_candidates), len(successful), main_candidate[0],
    )

    return {
        # 主候选默认值（director_review 投票后会用最佳候选覆盖）
        "vton_results": main_vton_results,
        "final_image": main_final_image,
        "item_categories": main_item_categories,
        # 多候选字段（供 director_review 投票）
        "candidates_vton_results": candidates_vton_results,
        "candidates_final_images": candidates_final_images,
        "candidates_item_categories": candidates_item_categories,
    }


async def post_process_node(state: DirectorState) -> dict:
    """后处理节点：按导演决策的后处理动作调用千问 wan2.7-image 图生图

    实现方案：千问 wan2.7-image（图生图）
    - 定位"高特征一致性，精准细节修改"——保持 VTON 主体不变，只改指定细节
    - 复用千问平台鉴权（与 VTON 同一阿里百炼账号，复用 llm_api_key）
    - 后处理限 1 轮（由 _should_post_process 控制）

    Returns:
        更新 state 的字段：post_processed_image, final_image, post_process_round
    """
    from app.api.deps import get_gen_client

    actions = state.get("post_process_actions") or []
    final_image = state.get("final_image", b"")
    round_num = state.get("post_process_round", 0) + 1

    if not actions or not final_image:
        logger.info("[后处理] 无后处理动作或无图，跳过: taskId=%s", state.get("task_id"))
        return {"post_processed_image": None, "post_process_round": round_num}

    # 合并后处理动作为一条 prompt
    # 每个动作含 {type, action_prompt, source_intent_cn}
    # 多个动作合并为分号分隔的中文 prompt，保留 source_intent_cn 用于日志
    prompt_parts = []
    for action in actions:
        action_prompt = action.get("action_prompt", "").strip()
        if action_prompt:
            prompt_parts.append(action_prompt)
    if not prompt_parts:
        logger.warning(
            "[后处理] actions 无有效 prompt，降级使用 VTON 原图: taskId=%s",
            state.get("task_id"),
        )
        return {
            "post_processed_image": final_image,
            "final_image": final_image,
            "post_process_round": round_num,
        }
    combined_prompt = "; ".join(prompt_parts)
    # 限定 prompt 长度（O1 上限 2500 字符）
    if len(combined_prompt) > 2000:
        combined_prompt = combined_prompt[:2000]
        logger.warning("[后处理] prompt 过长，已截断到 2000 字符: taskId=%s", state.get("task_id"))

    # 调用 O1 图生图
    gen_client = await get_gen_client()
    try:
        edited_image = await gen_client.edit_image(
            source_image=final_image,
            prompt=combined_prompt,
            aspect_ratio="3:4",  # 模特图默认竖图
        )
    except Exception as e:
        logger.error(
            "[后处理] O1 图生图异常，降级使用 VTON 原图: taskId=%s, error=%s",
            state.get("task_id"), e, exc_info=True,
        )
        return {
            "post_processed_image": final_image,
            "final_image": final_image,
            "post_process_round": round_num,
        }

    if edited_image is None:
        logger.warning(
            "[后处理] O1 图生图返回 None，降级使用 VTON 原图: taskId=%s, actions=%s",
            state.get("task_id"), [a.get("type") for a in actions],
        )
        return {
            "post_processed_image": final_image,
            "final_image": final_image,
            "post_process_round": round_num,
        }

    logger.info(
        "[后处理] O1 图生图成功: taskId=%s, actions=%s, 原图=%d bytes → 新图=%d bytes",
        state.get("task_id"),
        [a.get("type") for a in actions],
        len(final_image), len(edited_image),
    )

    # 关键：后处理后的图必须同步更新 final_image，否则下游 director_review_node
    # 重评时读到的还是 VTON 原图，后处理实际无效
    return {
        "post_processed_image": edited_image,
        "final_image": edited_image,
        "post_process_round": round_num,
    }


async def oss_upload_node(state: DirectorState) -> dict:
    """OSS 上传节点：上传所有中间图 + 最终图（含后处理版）

    Returns:
        更新 state 的字段：result_urls, post_processed_image_url
    """
    from app.api.deps import get_oss_uploader

    oss_uploader = await get_oss_uploader()
    task_id = state.get("task_id", "unknown")
    vton_results = state.get("vton_results", [])
    item_categories = state.get("item_categories") or []
    post_processed = state.get("post_processed_image")

    result_urls: list[str] = []
    # item_categories 已在 vton_execute_node 中按成功件 idx 对齐，
    # 与 vton_results 同源（均来自 intermediate_images），长度一致，无需截取。
    successful_categories = item_categories

    for idx, (image_data, category) in enumerate(
        zip(vton_results, successful_categories), start=1
    ):
        url = await asyncio.to_thread(
            _upload_image_with_fallback,
            oss_uploader, image_data, task_id, idx, category,
        )
        if url:
            result_urls.append(url)

    # 上传后处理版（如有）
    post_processed_url = None
    if post_processed:
        post_processed_url = await asyncio.to_thread(
            _upload_image_with_fallback,
            oss_uploader, post_processed, task_id, len(vton_results) + 1, "optimized",
        )

    logger.info(
        "[OSS上传] taskId=%s, 中间图=%d, 后处理图=%s",
        task_id, len(result_urls), "有" if post_processed_url else "无",
    )

    return {
        "result_urls": result_urls,
        "post_processed_image_url": post_processed_url,
    }


def _upload_image_with_fallback(
    oss_uploader, image_data: bytes, task_id: str,
    step: int, category: str,
) -> str | None:
    """上传图片到 OSS，失败时降级到本地 nginx 静态目录（同步函数，供 asyncio.to_thread 调用）"""
    # OSS 上传
    try:
        url = oss_uploader.upload_image(
            file_data=image_data,
            directory=f"model/{task_id}",
            file_ext="jpg",
        )
        if url is not None:
            return url
    except Exception as e:
        logger.warning("OSS 上传异常，降级到本地: step=%d, error=%s", step, e)

    # 本地降级
    return _save_to_local(image_data, task_id, step, category)


def _save_to_local(image_data: bytes, task_id: str, step: int, category: str) -> str | None:
    """OSS 降级时把图片落地到 nginx 静态目录"""
    local_dir = _get_local_fallback_dir()
    if local_dir is None:
        logger.error("NGINX_UPLOADS_ROOT 未配置，无法本地降级存储")
        return None
    local_dir.mkdir(parents=True, exist_ok=True)
    md5_prefix = hashlib.md5(image_data).hexdigest()[:8]
    safe_category = _category_to_filename_safe(category)
    filename = f"{task_id}_{step}_{safe_category}_{md5_prefix}.jpg"
    local_path = local_dir / filename
    if not local_path.exists():
        local_path.write_bytes(image_data)
    url = f"{_get_local_fallback_url_prefix()}/{filename}"
    logger.info("OSS 降级：模特图已存本地: %s", url)
    return url


async def _download_image(url: str) -> bytes | None:
    """下载图片

    支持 Java 侧存储的相对路径（如 /uploads/model-images/xxx.jpg）：
    检测到相对路径时，拼接 settings.nginx_external_base_url 形成完整 URL。

    注意：必须用 trust_env=False 禁用系统代理，否则 Windows 系统代理
    （如 Clash 127.0.0.1:7897）会拦截 localhost 请求导致 502。
    """
    if not url:
        return None
    # 相对路径拼接：Java item-service 存的是 /uploads/xxx.jpg，Python 需补全 host
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


def _should_post_process(state: DirectorState) -> str:
    """条件边：评估后判断是否走后处理分支

    Returns:
        "upload" - 直接上传（pass）
        "post_process" - 走后处理（post_process，限 1 轮）
    """
    decision = state.get("director_decision", "pass")
    round_num = state.get("post_process_round", 0)
    actions = state.get("post_process_actions") or []

    if (decision == "post_process"
            and round_num < MAX_POST_PROCESS_ROUNDS
            and actions):
        return "post_process"
    return "upload"


def build_model_director_graph():
    """构建 AI 模特多 Agent 决策主图（v3 增强版）

    拓扑：
      entry → director_plan → vton_execute → director_review → [条件分支]
                                                         ├─ post_process → director_review（重评，限 1 轮）
                                                         └─ oss_upload → END

    v3 多候选路径与单候选路径统一在同一拓扑中：
    - vton_execute 内部根据 vton_order_candidates 长度选择单/多候选执行
    - director_review 内部根据 candidates_final_images 长度选择单/多候选评估
    - 重评阶段（post_process_round > 0）强制走单候选路径评估后处理效果

    Returns:
        编译后的 LangGraph 可执行图
    """
    workflow = StateGraph(DirectorState)

    # 注册节点
    workflow.add_node(NODE_PLAN, director_plan_node)
    workflow.add_node(NODE_VTON, vton_execute_node)
    workflow.add_node(NODE_REVIEW, director_review_node)
    workflow.add_node(NODE_POST_PROCESS, post_process_node)
    workflow.add_node(NODE_OSS_UPLOAD, oss_upload_node)

    # 边：plan → vton → review
    workflow.set_entry_point(NODE_PLAN)
    workflow.add_edge(NODE_PLAN, NODE_VTON)
    workflow.add_edge(NODE_VTON, NODE_REVIEW)

    # 条件边：review 后判断是否走后处理
    workflow.add_conditional_edges(
        NODE_REVIEW,
        _should_post_process,
        {
            "post_process": NODE_POST_PROCESS,
            "upload": NODE_OSS_UPLOAD,
        },
    )

    # 后处理后回到 review 重评（限 1 轮，由 _should_post_process 控制）
    workflow.add_edge(NODE_POST_PROCESS, NODE_REVIEW)

    # 上传后结束
    workflow.add_edge(NODE_OSS_UPLOAD, END)

    compiled = workflow.compile()
    logger.info("LangGraph AI 模特多 Agent 主图已编译: v3 增强版（多候选并行 + 投票）")
    return compiled


# 编译一次，全局复用
_compiled_graph = None
_compile_lock = asyncio.Lock()


async def get_compiled_model_director_graph():
    """获取编译后的图单例（asyncio.Lock 保护）"""
    global _compiled_graph
    if _compiled_graph is None:
        async with _compile_lock:
            if _compiled_graph is None:
                _compiled_graph = build_model_director_graph()
    return _compiled_graph
