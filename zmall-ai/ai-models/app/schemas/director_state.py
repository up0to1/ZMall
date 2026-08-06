"""
AI 模特多 Agent 决策架构 State 定义（v4 多换装增强版）

v3 修订要点（增强版）：
- 新增 vton_order_candidates: 多 VTON 顺序候选（多 Agent 并行投票用）
- 新增 candidates_review: 多候选评估结果
- 新增 selected_candidate_idx: 投票选中的候选索引
- 新增 decision_reason_cn / issues_summary: 决策可解释性
- 新增 prev_overall_score: 后处理回归校验用
- 新增 react_enabled: ReAct 反思机制开关
- stylist_dual_plan 为主，eu/asia 为前端兼容拆分
- 评估阶段新增 is_fallback 标记，区分 LLM 调用失败和真实评分

v4 多换装增强（multi_outfit 模式）：
- 新增 generation_mode: "single" | "multi_outfit"
- 新增 outfit_combinations: 多套商品 ID 组合（如 [[101,201],[101,202]]）
- 新增 scene_results: 每个场景的独立结果（final_image/vton_results/评估/后处理）
- 多换装模式下，每个场景独立执行 VTON → 评估 → 后处理
"""
from typing import TypedDict


class DirectorState(TypedDict, total=False):
    """AI 模特多 Agent 主图 State（LangGraph 全局状态）

    total=False：所有字段可选，便于各节点只返回需更新的字段（LangGraph 自动合并）。
    """

    # ===== 任务上下文 =====
    task_id: str
    shop_id: int
    user_id: int
    item_ids: list[int]
    items: list[dict]
    model_image_candidates: list[dict]
    uploaded_model_url: str | None

    # ===== v4 多换装模式 =====
    generation_mode: str                   # "single" | "multi_outfit" | "multi_pose"
    outfit_combinations: list[list[int]]   # 多套商品 ID 组合（如 [[101,201],[101,202]]）
    combination_reasons: list[str]         # 每套组合的推荐理由（LLM 搭配推荐）
    scene_results: list[dict]              # 每个场景的独立结果（含 final_image/评估/后处理）

    # ===== v5 多姿势模式（multi_pose）=====
    # 同脸同妆造同服装 + 不同姿势：VTON 一次生成基准图，O1 图生图生成 N 个姿势变体
    pose_count: int                        # 姿势数量（默认 3，最大 4）
    pose_prompts: list[dict]               # LLM 推荐的姿势 prompt 列表 [{name, prompt, intent_cn}]
    pose_results: list[dict]               # 每个姿势的独立结果（含 final_image/评估）

    # ===== 策划阶段输出 =====
    stylist_dual_plan: dict | None         # 双视角衣品审美策划（合并 EU+Asia）
    # 向后兼容字段（导演节点从 stylist_dual_plan 拆分填充）
    stylist_eu_plan: dict | None           # 兼容前端：EU 风格特征
    stylist_asia_plan: dict | None         # 兼容前端：Asia 风格特征
    photographer_plan: dict | None
    # 多 VTON 顺序候选
    vton_order_candidates: list[list[str]]  # 1-3 个候选顺序
    vton_order: list[str]                   # 主候选（第 1 个，单候选执行时用）
    vton_order_reason: str
    selected_model_image: dict
    style_features: str
    style_features_divergence: str
    style_conflicts_summary: list[str]

    # ===== VTON 执行输出 =====
    # 单候选模式（向后兼容）
    vton_results: list[bytes]
    final_image: bytes
    item_categories: list[str]
    # 多候选模式
    candidates_vton_results: list[list[bytes]]   # 每个候选的中间图列表
    candidates_final_images: list[bytes]          # 每个候选的最终图
    candidates_item_categories: list[list[str]]   # 每个候选的品类标签

    # ===== 评估阶段输出（v3：带 is_fallback 标记）=====
    stylist_eu_review: dict | None         # 兼容前端：从 dual_review 拆分
    stylist_asia_review: dict | None
    stylist_dual_review: dict | None       # v3 新增：双视角合并评估结果
    lighting_review: dict | None
    makeup_review: dict | None
    photographer_review: dict | None
    # v3 新增：多候选评估结果
    candidates_reviews: list[dict]          # 每个候选的 5 维度评估
    selected_candidate_idx: int             # 投票选中的候选索引

    # ===== 导演决策（v3：可解释性）=====
    director_decision: str                 # "pass" | "post_process"
    overall_score: float
    star_rating: int
    post_process_actions: list[dict]
    post_process_round: int
    # v3 新增：可解释性
    decision_reason_cn: str                # 决策理由（中文，供商家查看）
    issues_summary: list[str]              # 问题清单（中文）
    # v3 新增：后处理回归校验
    prev_overall_score: float              # 后处理前的评分（用于回归校验，new < prev - 0.1 时回退）

    # ===== 后处理输出 =====
    post_processed_image: bytes | None

    # ===== 最终输出 =====
    result_urls: list[str]
    post_processed_image_url: str | None

    # ===== 错误兜底 =====
    error: str | None
