"""
LangGraph AgentState 定义

统一工作流状态（商品驱动 + 风格驱动）：
  节点1 意图理解 → 节点2 Qdrant 检索 → 节点3 组合决策 → 节点3.5 反思自检 → 节点4 换装生成 → 节点5 OSS 上传

两种模式通过 mode 字段区分：
  - mode="product"：商品驱动（主商品已锁定，单套生成，不支持多轮反馈）
  - mode="agent"：风格驱动（风格描述检索，3 套生成，支持多轮反馈）

注意：LangGraph 节点返回的 dict 会被合并到 state，因此每个节点只需返回它更新的字段。
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    """LangGraph 工作流状态（total=False 表示所有字段可选，便于节点返回部分更新）"""

    # ===== 模式标识（U1 统一架构）=====
    # "product"=商品驱动模式，"agent"=风格驱动模式
    mode: str

    # ===== v3 两阶段交互架构（AI 随心搭·风格驱动）=====
    # stage="recommend"=阶段一候选推荐（OUTFIT_RECOMMEND，2 credits）
    # stage="vton"=阶段二 VTON 生成（OUTFIT_VTON，5×N credits）
    # 默认 "recommend"，向后兼容旧版单阶段流程
    stage: str
    # 阶段二用户选定的搭配索引列表（阶段一 Top3 中的 0/1/2 子集）
    # 阶段二仅对这些索引执行 VTON 生成
    selected_outfit_indexes: list[int]
    # 阶段二关联的阶段一 taskId（用于读取阶段一 state 快照中的 outfit_candidates）
    parent_task_id: str
    # 阶段二 VTON 部分失败的搭配索引（用于部分失败不退还规则审计）
    partial_failures: list[int]
    # 阶段二每套 VTON 消耗的 credits 数（默认 5，审计用）
    vton_credits_per_outfit: int

    # ===== 输入（init 时填充）=====
    task_id: str
    user_id: int
    style_tags: list[str]              # 风格标签（可选，与其他字段任一非空即可）
    scene_desc: str | None             # 场景描述
    photo_session_key: str | None
    # 结构化输入字段
    shop_ids: list[int]               # 指定店铺内检索（支持多选），None/空则全平台
    color: list[str] | None             # 偏好色调列表（中文，如 ['白色','蓝色']）
    color_is_explicit: bool             # 是否来自用户结构化选择；明确选择时首轮硬过滤，候选不足再放宽
    # 注解对齐实际行为。categories 缺省/None 时节点2 走默认品类组合，
    # state.get("categories") 返回 None，故注解需显式允许 None
    categories: list[str] | None       # 用户指定品类组合（中文），None/空则默认 [上衣, 下装, 鞋]
    note: str | None                   # 自然语言备注补充，节点1 调 LlmClient 解析后合并到上述字段
    budget_max: float | None           # 预算上限，节点3 按总价过滤
    # 季节感知（节点1 注入）
    # 节点2 用 state.get("season")，缺失时返回 None 且不过滤；
    # QdrantSearcher.search_complementary_items 形参 season 也是 str | None，注解需对齐
    season: str | None                 # 当前季节（spring/summer/autumn/winter），None 则不按季节过滤
    # 用户所在地信息（2026-07-31 新增，时尚潮流搜索用）
    # 前端 IP 定位获取，节点1 透传到节点3 用于 fashion_trend 地区路由
    # user_city 支持中文（"北京"）和英文（"Tokyo"）；user_country 是 ISO 国家代码（"CN"/"JP"）
    user_city: str | None
    user_country: str | None
    # 我的衣橱/购物车/订单挑选的衣物
    wardrobe_item_ids: list[int]

    # ===== 商品驱动模式专用输入（U1 统一架构）=====
    # 主商品 ID 列表（商品驱动模式必填，风格驱动为空）
    # 非空时触发商品驱动分支：按主商品图编码向量 + 按主商品品类推导互补品类
    main_item_ids: list[int]

    # ===== 节点1 输出：意图理解 =====
    query_text: str                  # 风格标签 + 场景描述拼接的检索文本
    query_vector: list[float] | None # 文本向量（DashScope text-embedding-v4，1024 维）
    category_constraints: list[str]  # 品类约束，如 ["上衣", "下装", "鞋"]
    user_photo: bytes | None         # 用户真人照片（可选，场景 B 非空，场景 A 为 None）
    # 场景 B 专用：LLM 图像理解模型分析用户照片得到的视觉特征
    # 节点1 调 LlmClient.analyze_user_photo 得到，节点3 LLM 搭配决策参考
    # 结构：{gender, skin_tone, body_type, age_range, style_cue, preferred_colors}
    # 场景 A（无照片）或分析失败时为 None
    user_visual_profile: dict | None
    # 场景标识：True=用户未上传照片，节点4 用 default_model_image_url 兜底 VTON
    # False=用户已上传照片，节点4 用 user_photo 正常 VTON
    use_default_model: bool

    # ===== 用户身体信息档案（尺码推荐用）=====
    # 用户在 AI 搭配页选中的身体信息档案 ID（前端传入，可选）
    # 节点1 拉取档案详情到 user_body_profile，节点3 LLM 决策时参考
    # 用户未选中时为 None，LLM 不考虑身材因素
    user_body_profile_id: int
    # 身体信息详情：{gender, height, weight, shoulderWidth, bust, waist, hip,
    #               footLength, footWidth, headCircumference, ageRange, bodyType}
    # 节点1 调 JavaClient.get_body_profile 拉取，节点3 LLM 搭配决策参考
    # 搭配结果返回前端后，前端用此字段调 /items/size-chart/recommend-by-item?itemId=X
    # 或 /items/size-chart/recommend-batch 获取每件单品推荐尺码（按商品三级回退查询店铺尺码表）
    user_body_profile: dict | None

    # ===== 性别与服装匹配（2026-07-27 新增）=====
    # 用户选定的系统模特图 ID（前端传入，可选）
    # 用户在 AI 搭配页选了"使用系统模特"时传入，节点1 据此下载模特图作为 VTON base，
    # 并用 system_model_gender 作为 target_gender 进行 Qdrant 性别过滤
    system_model_id: int
    # 系统模特图 URL（前端从模特列表选中后传入，避免 Python 再调 Java 查询）
    # 节点1 下载此 URL 作为 user_photo 替代 Redis 会话级照片
    # 优先级：system_model_image_url > photo_session_key（用户自拍）
    system_model_image_url: str
    # 系统模特性别（male/female，前端从模特列表选中后传入）
    # 节点1 直接用作 target_gender，无需再调 LLM 分析照片
    system_model_gender: str
    # 最终确定的搭配目标性别（male/female），节点1 综合以下来源按优先级确定：
    #   1. system_model_gender（用户选定系统模特时）
    #   2. user_visual_profile.gender（用户上传自拍照时 LLM 分析结果）
    #   3. user_body_profile.gender（用户登记身体档案时）
    #   4. None（以上均无，跳过性别过滤，向后兼容）
    # 节点2 据此过滤 Qdrant：target_gender IN (target_gender, "unisex")
    # 节点3 LLM prompt 也会注入此字段作为双保险
    target_gender: str
    # target_gender 的来源标识（审计/调试用）：
    #   "system_model" | "user_photo" | "body_profile" | None
    gender_source: str

    # ===== 节点2 输出：Qdrant 检索 =====
    candidate_items_by_category: dict[str, list[dict]]  # {category: [items]}

    # ===== 节点3 输出：组合决策 =====
    outfit_candidates: list[dict]    # 候选搭配（风格驱动 3 套，商品驱动 1 套），每套含 items + score
    # Top10 候选池（节点3 输出，供 Reflection 节点修正时复用，避免重新检索 Qdrant）
    top_candidates_pool: list[dict]

    # ===== 节点4 输出：换装生成 =====
    generated_images: list[bytes | None]  # 与 outfit_candidates 一一对应
    # VTON 生成图与所选商品的一致性检查结果（与 outfit_candidates 一一对应）
    vton_quality_reports: list[dict | None]

    # ===== 节点5 输出：OSS 上传 =====
    final_outfits: list[dict]        # 最终结果，含 resultUrl

    # ===== 错误跟踪 =====
    error: str | None

    # ===== 多轮反馈字段（仅风格驱动模式使用）=====
    # 当前轮次（首轮=1，每次反馈后 +1，上限 3）
    round: int
    # 用户反馈原文（如"不喜欢这个颜色"）
    feedback: str | None
    # 反馈解析结果（AgentService.feedback 调用 LlmClient 输出，节点1/2/3 读取）
    #   {action: "replace"|"regenerate_all"|"adjust_style"|"accept",
    #    target_category: str|None,    # action=replace 时要替换的品类
    #    reason: str|None,             # 用户反馈原因
    #    new_style_tags: list[str]|None}  # action=adjust_style 时的新风格
    feedback_parsed: dict | None
    # 本轮保留不重新检索的品类（action=replace 时使用）
    # 例如用户说"换下装"，则 keep_categories=["上衣","鞋"]，节点2 只检索"下装"
    keep_categories: list[str]
    # 历史轮次的搭配结果（最多 3 轮），用于节点3 去重，避免重复推荐
    # 结构：[[outfit1_round1, outfit2_round1, ...], [outfit1_round2, ...], ...]
    history_outfits: list[list[dict]]
    # 已推荐过的商品 ID 集合（跨轮次累积，节点3 过滤用）
    seen_item_ids: set[int]
    # 工作流是否已完成（accept 或轮次超限时置 True）
    finished: bool

    # Redis task checkpoint 的乐观并发版本；只用于持久化 CAS，不参与模型决策
    checkpoint_version: int

    # ===== 用户偏好字段（US-AT-21/22，P0 同会话累积）=====
    # 同会话累积的不喜欢颜色（跨轮次持续生效，会话结束 Redis TTL 30min 后自然清除）
    user_dislike_colors: list[str]
    # 本轮不喜欢的商品 ID（不累积，下轮自动失效，节点2 后置过滤）
    dislike_item_ids: list[int]
    # 本轮 VTON 效果差的商品 ID（商品本身 OK，仅重新换装不换商品，不累积）
    retry_vton_item_ids: list[int]
    # 本轮想要的新增风格（合并到 style_tags 重新编码向量检索）
    want_style_tags: list[str]

    # ===== O3 优化：EpisodicMemory（跨会话搭配事件）=====
    # 用户最近采纳的搭配事件列表（首轮从 Qdrant 加载，节点3 LLM 决策参考）
    # 结构：[{task_id, accepted_items, style_tags, scene_desc, season, timestamp}, ...]
    # 业务价值：下次进入随心搭时，LLM 可参考"上次推荐"做差异化推荐，提升复购率
    recent_episodes: list[dict]

    # ===== 个性化推荐画像 =====
    # 用户画像（ProfileService 聚合，Redis 缓存 24h，accept 时主动失效）
    # 数据源：Qdrant user_behavior（行为向量）+ user_preference（显式偏好）+ MySQL user_browse_history
    # 结构：{
    #   top_styles: list[str],            # Top3 风格标签（行为 + 显式偏好聚合）
    #   top_colors: list[str],            # Top3 颜色（行为聚合）
    #   price_distribution: {min, median, max},  # 价格分布
    #   style_vector: list[float],        # 1024 维加权平均风格向量（无数据时为空列表）
    #   profile_confidence: float,        # 0-1 画像置信度
    #   dislike_colors: list[str],        # 显式不喜欢的颜色（来自 user_preference）
    #   like_styles: list[str],           # 显式喜欢的风格（来自 user_preference）
    # }
    # 消费点：
    #   - 节点1 intent_understanding：style_vector 融合 query_vector（提升召回相关性）
    #   - 节点3 outfit_combination：top_colors 颜色偏好加权（提升偏好颜色组合评分）
    #   - agent_service._run_agent_workflow：top_styles 合并到 style_tags（增强召回）
    # profile_confidence=0 时节点1/3 自动降级为原逻辑
    user_profile: dict

    # ===== 反馈轮 ReAct + Tool Calling =====
    # feedback 接口的自然语言备注补充（非空时触发 ReAct 模式）
    feedback_note: str | None

    # ===== 内部字段（不持久化，节点间传递用）=====
    # 节点1 记录本轮使用的 style_tags，反馈轮判断是否复用旧向量
    _prev_style_tags_for_query: list[str]
    # 商品驱动模式：主商品图 bytes（节点1 下载，节点4 用作 VTON garment_image）
    _main_item_bytes: bytes
    # 商品驱动模式：主商品详情（节点1 拉取，节点5 用作 outfitItems 输出）
    _main_item_info: dict
