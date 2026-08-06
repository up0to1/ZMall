"""
LangGraph StateGraph 编排（v3 两阶段架构）

阶段一候选推荐图（stage="recommend"，OUTFIT_RECOMMEND 2 credits）：
  entry → intent_understanding → qdrant_search → outfit_combination
        → reflection_check → oss_upload（跳过 vton_generation）→ END
  - 输出 Top3 候选搭配（resultUrl 用商品图，前端展示供用户选定）
  - 用户选定后前端调 POST /select 触发阶段二

阶段二 VTON 生成图（stage="vton"，OUTFIT_VTON 5×N credits）：
  entry → vton_generation → oss_upload → END
  - 仅对 selected_outfit_indexes 执行 VTON
  - 输出最终效果图（resultUrl 是 VTON 生成图上传 OSS 后的 URL）
  - 用户满意后前端调 POST /accept 入库 ai_outfit_record

设计要点：
- 阶段一用 conditional edge 在 reflection_check 后判断 stage：
  - stage="recommend" → 跳过 vton 直接进 oss_upload（推荐轮）
  - 其他（如旧版单阶段或反馈轮完整流程）→ 走 vton_generation
- 阶段二是独立的 vton_only_graph，仅 2 个节点
- 超时控制由调用方（AgentService）用 asyncio.wait_for 包裹
- LangGraph 自动管理状态合并，每个节点只返回需要更新的字段
- 多轮反馈不依赖 LangGraph interrupt/checkpointer，而是由 AgentService.feedback
  构造新一轮 initial_state（带 feedback_parsed/keep_categories/seen_item_ids 等）
  重新 ainvoke 阶段一图。各节点根据 state 中的反馈字段自适应行为：
    - 节点1: adjust_style 时合并新风格重新编码向量；其他反馈轮复用旧向量
    - 节点2: keep_categories 非空时只检索要替换的品类，保留其他品类的候选
    - 节点3: seen_item_ids 过滤已推荐过的组合
    - 节点3.5 Reflection: 自检颜色协调性/风格一致性/季节匹配，不合格从 Top10 池替换
"""
import asyncio
import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.schemas.agent_state import AgentState
from app.tools.nodes import (
    intent_understanding,
    qdrant_search,
    outfit_combination,
    reflection_check,
    vton_generation,
    oss_upload,
    build_wardrobe_outfit,
)

logger = logging.getLogger(__name__)

# 节点名称常量（便于日志和调试）
NODE_INTENT = "intent_understanding"
NODE_SEARCH = "qdrant_search"
NODE_COMBINE = "outfit_combination"
NODE_REFLECT = "reflection_check"
NODE_VTON = "vton_generation"
NODE_OSS = "oss_upload"
NODE_WARDROBE_OUTFIT = "build_wardrobe_outfit"


def _should_skip_vton(state: AgentState) -> str:
    """条件边：reflection_check 后判断是否跳过 vton_generation

    v3 两阶段架构：
    - stage="recommend"（阶段一候选推荐）：跳过 VTON，直接进 oss_upload
      （用商品图作为 resultUrl，前端展示供用户选定，VTON 延迟到阶段二）
    - stage 缺失或非 "recommend"：走原完整流程（vton_generation → oss_upload）
      （兼容旧版单阶段模式和多轮反馈轮完整流程）

    Returns:
        "vton" 或 "oss"
    """
    stage = state.get("stage")
    if stage == "recommend":
        return "oss"
    return "vton"


def _route_after_intent(state: AgentState) -> str:
    """条件边：intent_understanding 后判断走哪条路径

    ⑥ 用户选定模式（stage="user_picked"）：
      跳过 Qdrant 检索（节点2）和组合决策（节点3），直接走 build_wardrobe_outfit → vton
      用户已选定全部单品，无需 LLM 决策搭配组合

    ④ 风格驱动模式（stage != "user_picked"）：
      正常走 Qdrant 检索 → 组合决策 → 反思自检

    Returns:
        "wardrobe_outfit" 或 "qdrant"
    """
    stage = state.get("stage")
    wardrobe_item_ids = state.get("wardrobe_item_ids") or []
    if stage == "user_picked" and wardrobe_item_ids:
        return "wardrobe_outfit"
    return "qdrant"


def build_outfit_graph():
    """构建阶段一候选推荐 LangGraph 工作流（v3 + ⑥ 用户选定模式）

    v3 改造：reflection_check 后加条件边
    - stage="recommend" → 跳过 vton_generation 直接到 oss_upload
    - 其他（旧版/反馈轮）→ 走 vton_generation → oss_upload

    ⑥ 用户选定模式：intent_understanding 后加条件边
    - stage="user_picked" → 跳过 Qdrant 检索和组合决策，直接 build_wardrobe_outfit → vton

    Returns:
        编译后的 LangGraph 可执行图（支持 ainvoke 异步调用）
    """
    workflow = StateGraph(AgentState)

    # 注册 7 个节点
    workflow.add_node(NODE_INTENT, intent_understanding)
    workflow.add_node(NODE_SEARCH, qdrant_search)
    workflow.add_node(NODE_COMBINE, outfit_combination)
    workflow.add_node(NODE_REFLECT, reflection_check)
    workflow.add_node(NODE_VTON, vton_generation)
    workflow.add_node(NODE_OSS, oss_upload)
    workflow.add_node(NODE_WARDROBE_OUTFIT, build_wardrobe_outfit)

    # 边：entry → 1 → (条件路由)
    workflow.set_entry_point(NODE_INTENT)

    # ⑥ 用户选定模式条件边：intent_understanding 后判断路径
    # - stage="user_picked" → build_wardrobe_outfit → vton_generation → oss_upload
    # - 其他 → qdrant_search（正常流程）
    workflow.add_conditional_edges(
        NODE_INTENT,
        _route_after_intent,
        {
            "wardrobe_outfit": NODE_WARDROBE_OUTFIT,
            "qdrant": NODE_SEARCH,
        },
    )

    # ⑥ 用户选定模式路径：build_wardrobe_outfit → vton → oss
    workflow.add_edge(NODE_WARDROBE_OUTFIT, NODE_VTON)

    # ④ 风格驱动模式路径：1 → 2 → 3 → 3.5(reflection)
    workflow.add_edge(NODE_SEARCH, NODE_COMBINE)
    workflow.add_edge(NODE_COMBINE, NODE_REFLECT)

    # v3 条件边：reflection_check 后按 stage 判断
    # - stage="recommend" → 跳过 VTON 直接进 oss_upload（阶段一候选推荐）
    # - 其他 → 走 vton_generation（旧版单阶段/反馈轮完整流程）
    workflow.add_conditional_edges(
        NODE_REFLECT,
        _should_skip_vton,
        {
            "vton": NODE_VTON,
            "oss": NODE_OSS,
        },
    )
    workflow.add_edge(NODE_VTON, NODE_OSS)
    workflow.add_edge(NODE_OSS, END)

    compiled = workflow.compile()
    logger.info("LangGraph 工作流已编译: v3 两阶段架构 + ⑥ 用户选定模式")
    return compiled


def build_vton_only_graph():
    """构建阶段二 VTON 生成 LangGraph 工作流

    仅 2 个节点：
      entry → vton_generation → oss_upload → END

    阶段二仅对 state.selected_outfit_indexes 中的搭配执行 VTON 生成，
    不再走节点1/2/3（候选已在阶段一生成）。

    Returns:
        编译后的 LangGraph 可执行图（支持 ainvoke 异步调用）
    """
    workflow = StateGraph(AgentState)

    workflow.add_node(NODE_VTON, vton_generation)
    workflow.add_node(NODE_OSS, oss_upload)

    workflow.set_entry_point(NODE_VTON)
    workflow.add_edge(NODE_VTON, NODE_OSS)
    workflow.add_edge(NODE_OSS, END)

    compiled = workflow.compile()
    logger.info("LangGraph 阶段二 VTON-only 工作流已编译: 2 节点线性流程")
    return compiled


# 编译一次，全局复用（LangGraph 编译后的图是线程安全的）
_compiled_graph = None
# 延迟初始化 Lock，避免模块级创建 asyncio.Lock() 在无事件循环时报错
_compile_lock: asyncio.Lock | None = None

# 阶段二 VTON-only 图单例
_compiled_vton_only_graph = None
_vton_only_compile_lock: asyncio.Lock | None = None


async def _get_compiled_graph():
    """获取编译后的图单例（asyncio.Lock 保护，避免并发重复编译）"""
    global _compiled_graph, _compile_lock
    if _compiled_graph is None:
        if _compile_lock is None:
            _compile_lock = asyncio.Lock()
        async with _compile_lock:
            if _compiled_graph is None:
                _compiled_graph = build_outfit_graph()
    return _compiled_graph


async def _get_compiled_vton_only_graph():
    """获取编译后的阶段二 VTON-only 图单例"""
    global _compiled_vton_only_graph, _vton_only_compile_lock
    if _compiled_vton_only_graph is None:
        if _vton_only_compile_lock is None:
            _vton_only_compile_lock = asyncio.Lock()
        async with _vton_only_compile_lock:
            if _compiled_vton_only_graph is None:
                _compiled_vton_only_graph = build_vton_only_graph()
    return _compiled_vton_only_graph


class OutfitGraphRunner:
    """LangGraph 工作流运行器

    封装初始状态构造和异步执行，供 AgentService 调用。
    v3 两阶段架构：
    - run()：阶段一候选推荐图（含多轮反馈）
    - run_vton_only()：阶段二 VTON 生成图（仅 vton_generation + oss_upload）
    """

    @staticmethod
    async def run(
        task_id: str,
        user_id: int,
        style_tags: list[str],
        scene_desc: str | None,
        photo_session_key: str | None,
        initial_state: AgentState | None = None,
    ) -> dict[str, Any]:
        """执行阶段一候选推荐工作流

        Args:
            initial_state: 反馈轮时传入完整 initial_state（含 feedback_parsed/
                keep_categories/seen_item_ids/history_outfits/round 等字段）。
                首轮不传，由本方法构造。
        Returns:
            最终 state（含 final_outfits / error 等字段）
        """
        if initial_state is None:
            # 首轮：构造初始 state（v3 默认 stage="recommend"，跳过 VTON）
            initial_state = {
                "task_id": task_id,
                "user_id": user_id,
                "style_tags": style_tags,
                "scene_desc": scene_desc,
                "photo_session_key": photo_session_key,
                "stage": "recommend",  # v3：阶段一候选推荐
                "round": 1,
                "error": None,
            }
        else:
            # 反馈轮：确保关键字段存在
            initial_state.setdefault("task_id", task_id)
            initial_state.setdefault("user_id", user_id)
            initial_state.setdefault("error", None)
            # v3：反馈轮也走阶段一图（stage="recommend"），跳过 VTON
            initial_state.setdefault("stage", "recommend")

        graph = await _get_compiled_graph()
        # LangGraph 异步执行
        final_state = await graph.ainvoke(initial_state)
        logger.info(
            "LangGraph 阶段一执行完成: taskId=%s, round=%s, stage=%s, outfits=%d, error=%s",
            task_id,
            final_state.get("round", 1),
            final_state.get("stage"),
            len(final_state.get("final_outfits", [])),
            final_state.get("error"),
        )
        return final_state

    @staticmethod
    async def run_vton_only(initial_state: AgentState) -> dict[str, Any]:
        """执行阶段二 VTON-only 工作流

        阶段二仅对 initial_state.selected_outfit_indexes 中的搭配执行 VTON 生成，
        不再走节点1/2/3（候选已在阶段一生成）。

        Args:
            initial_state: 阶段二完整 state，必须包含：
                - task_id: 阶段二新 taskId
                - user_id: 用户 ID
                - parent_task_id: 阶段一 taskId（用于日志关联）
                - selected_outfit_indexes: 用户选定的搭配索引列表
                - outfit_candidates: 阶段一 Top3 候选（从 parent state 加载）
                - photo_session_key: 用户照片会话 Key（场景 B VTON 用）
                - user_photo: 用户照片 bytes（场景 B，从 Redis 加载）
                - use_default_model: 是否使用默认模特图（场景 A）
                - style_tags/scene_desc/color: 用于 AI 文生图 prompt（场景 A 兜底）
                - vton_credits_per_outfit: 每套 VTON 消耗的 credits 数（审计用）

        Returns:
            最终 state（含 final_outfits / partial_failures / error 等字段）
        """
        initial_state.setdefault("stage", "vton")
        initial_state.setdefault("error", None)
        initial_state.setdefault("partial_failures", [])

        graph = await _get_compiled_vton_only_graph()
        final_state = await graph.ainvoke(initial_state)
        logger.info(
            "LangGraph 阶段二 VTON 执行完成: taskId=%s, parentTaskId=%s, selected=%s, "
            "outfits=%d, partialFailures=%s, error=%s",
            final_state.get("task_id"),
            final_state.get("parent_task_id"),
            final_state.get("selected_outfit_indexes"),
            len(final_state.get("final_outfits", [])),
            final_state.get("partial_failures"),
            final_state.get("error"),
        )
        return final_state
