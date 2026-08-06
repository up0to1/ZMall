"""
LangGraph 工作流 5 个节点实现

节点1 意图理解 → 节点2 Qdrant 检索 → 节点3 组合决策 → 节点4 换装生成 → 节点5 OSS 上传

每个节点接收完整 AgentState，返回需要更新的部分字段（LangGraph 自动合并）。
"""
import asyncio
import base64
import functools
import itertools
import json
import logging
import time
from datetime import datetime

import httpx

from app.api.deps import (
    get_embed_client, get_gen_client, get_java_client, get_llm_client, get_oss_uploader,
    get_qdrant_searcher, get_redis, get_vton_client,
)
from app.core.config import settings
from app.schemas.agent_state import AgentState
from shared.metrics import record_agent_workflow_node
from shared.qdrant_client.category_mapping import (
    DEFAULT_CATEGORIES_CN, to_cn, to_en,
)
# 共享模块：PIL 多件合成 + 辅助品类区域映射 + SSRF 防护（与 ai-models 商品驱动模式共用）
from shared.outfit_common import (
    AUX_CATEGORY_REGION,
    compose_full_outfit_image,
    is_safe_image_url,
    filter_conflicting_categories,
    estimate_vton_timeout,
    count_vton_categories,
)
# 工具拓展：统一工具调用入口
from shared.tools import call_with_check
from shared.external_services.price_service import (
    analyze_price_balance, format_price_hint_for_llm,
)
from shared.external_services.inventory_service import (
    filter_instock_items,
)
from shared.external_services.trend_service import (
    get_trending_styles, format_trend_hint_for_llm,
)
from shared.external_services.fashion_trend_service import (
    get_fashion_trends, format_fashion_trend_hint_for_llm,
)
from shared.external_services.weather_service import (
    get_weather, format_weather_hint_for_llm,
)

logger = logging.getLogger(__name__)


def _trace_node(node_name: str):
    """节点级埋点装饰器：记录节点耗时日志 + Prometheus 指标（SUCCESS/FAILED）

    用于测试可观测性：单点/JMeter 测试时可通过日志和 /metrics 端点定位哪个节点慢或失败。
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state: AgentState) -> dict:
            task_id = state.get("task_id", "unknown")
            start = time.monotonic()
            try:
                result = await func(state)
                elapsed = time.monotonic() - start
                logger.info(
                    "[节点埋点] %s SUCCESS: taskId=%s, duration_ms=%d",
                    node_name, task_id, int(elapsed * 1000),
                )
                record_agent_workflow_node(
                    node=node_name, status="SUCCESS", duration_seconds=elapsed,
                )
                return result
            except Exception as e:
                elapsed = time.monotonic() - start
                logger.error(
                    "[节点埋点] %s FAILED: taskId=%s, duration_ms=%d, error=%s",
                    node_name, task_id, int(elapsed * 1000), e,
                    exc_info=True,
                )
                record_agent_workflow_node(
                    node=node_name, status="FAILED", duration_seconds=elapsed,
                )
                raise
        return wrapper
    return decorator


# MVP 默认品类约束（上衣 → 下装 → 鞋），用户未指定 categories 时用
DEFAULT_CATEGORIES = DEFAULT_CATEGORIES_CN  # 中文，前端/API 用

# 模型 API 重试参数（指数退避 2s/4s/8s）
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

# 兜底默认模特照片（空 bytes，VTON API 用默认模特）
DEFAULT_USER_PHOTO = b""

# 节点2 缺货跨店降级时，每个品类最少期望的候选数
MIN_CANDIDATES_PER_CATEGORY = 3

# 月份 → 季节映射
# 3-5 春 / 6-8 夏 / 9-11 秋 / 12-2 冬
_MONTH_TO_SEASON: dict[int, str] = {}
for m in (3, 4, 5):
    _MONTH_TO_SEASON[m] = "spring"
for m in (6, 7, 8):
    _MONTH_TO_SEASON[m] = "summer"
for m in (9, 10, 11):
    _MONTH_TO_SEASON[m] = "autumn"
for m in (12, 1, 2):
    _MONTH_TO_SEASON[m] = "winter"

# 季节 → 默认风格标签（用户未填 styleTags 时注入）
_SEASON_DEFAULT_STYLE: dict[str, list[str]] = {
    "spring": ["清新", "轻薄"],
    "summer": ["清爽", "透气"],
    "autumn": ["层次", "复古"],
    "winter": ["保暖", "厚重"],
}


def _build_season_gender_hint(season: str | None, target_gender: str | None) -> str:
    """根据季节+性别构造品类偏好 hint，注入 LLM 搭配决策上下文

    业务需求：
    - 夏季女性：多推裙装（长裙/短裙）和裤装（长裤/短裤），短裤优先短款
    - 男性四季：推长裤和短裤，夏季侧重短裤
    - 女性短裤长度问题：VTON(aitryon-plus) 不支持 prompt 参数控制裤长，
      此处通过 LLM 商品选择引导，优先选名称带"短款/热裤"的商品，
      避免 VTON 渲染时裤长过长

    Returns:
        hint 文本；无偏好时返回空字符串
    """
    if not season or not target_gender:
        return ""

    hints: list[str] = []

    if target_gender == "female":
        if season == "summer":
            hints.append(
                "夏季女性搭配偏好：多推荐裙装（长裙、短裙）和裤装（长裤、短裤）。"
                "下装品类中裙装和短裤的优先级应高于长裤。"
                "女性短裤特别注意：优先选择名称或描述中带有\"短款\"\"热裤\"\"短裤\""
                "等明确标注为短款的商品，避免选择中裤或五分裤，"
                "以避免虚拟试衣时裤长渲染过长影响美观。"
            )
        elif season in ("spring", "autumn"):
            hints.append(
                "春秋季女性搭配偏好：可推荐裙装（长裙、短裙）和裤装（长裤、短裤），"
                "裙装与裤装均衡推荐。"
            )
        elif season == "winter":
            hints.append(
                "冬季女性搭配偏好：优先推荐长裤、长裙等保暖下装，"
                "短裤可与打底裤搭配。"
            )

    elif target_gender == "male":
        if season == "summer":
            hints.append(
                "夏季男性搭配偏好：多推荐短裤，短裤与长裤的推荐比例建议 2:1。"
                "长裤和短裤都是四季通用品类，夏季侧重短裤。"
            )
        else:
            hints.append(
                f"{'春秋' if season in ('spring', 'autumn') else '冬'}季男性搭配偏好："
                "推荐长裤和短裤，长裤为主、短裤为辅。"
            )

    return "\n".join(hints)


def _get_current_season() -> str:
    """获取当前季节（基于 Asia/Shanghai 时区的月份）"""
    month = datetime.now().month
    return _MONTH_TO_SEASON.get(month, "summer")


async def _retry_async(coro_factory, retries: int = MAX_RETRIES, backoff: list[int] = None):
    """异步重试包装（指数退避）"""
    backoff = backoff or RETRY_BACKOFF
    last_exc = None
    for i in range(retries):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            if i < retries - 1:
                wait = backoff[i] if i < len(backoff) else backoff[-1]
                logger.warning("第 %d 次重试失败，%ds 后重试: %s", i + 1, wait, e)
                await asyncio.sleep(wait)
    raise last_exc


# ============================================================
# 节点1：意图理解
# ============================================================
@_trace_node("intent")
async def intent_understanding(state: AgentState) -> dict:
    """解析结构化输入 + note 备注 → 检索文本 + 向量 + 品类约束 + 用户照片

    U1 统一架构后支持双模式：
    - mode="product"（商品驱动）：main_item_ids 非空时触发，按主商品图编码向量 +
      按主商品品类推导互补品类；不支持多轮反馈，跳过 note 解析/季节注入
    - mode="agent"（风格驱动）：按 style_tags + scene_desc 编码文本向量

    多轮反馈支持（仅风格驱动）：
    - action=adjust_style：合并 feedback_parsed.new_style_tags 到 style_tags，重新编码向量
    - 其他反馈轮：若 state 已有 query_vector 且 style_tags 未变，复用旧向量避免重复调用 embed API
    - 首轮：正常解析

    结构化输入支持（仅风格驱动）：
    - styleTags/color/sceneDesc/note 任一非空即可（必填校验放宽）
    - note 非空时调 LlmClient.parse_note 解析，合并到 style_tags/color/categories/scene_desc
    - shop_id/categories 直接透传到 state 供节点2 使用
    """
    # ===== 用户身体信息档案拉取（尺码推荐用）=====
    # 用户在 AI 搭配页选中身体信息档案时，前端传入 user_body_profile_id
    # 节点1 拉取档案详情，节点3 LLM 决策参考，搭配结果返回前端用于尺码推荐
    body_profile_id = state.get("user_body_profile_id")
    user_body_profile = None
    if body_profile_id:
        try:
            java_client = await get_java_client()
            user_body_profile = await java_client.get_body_profile(body_profile_id)
            if user_body_profile:
                logger.info("[节点1] 拉取身体信息档案: profileId=%s, gender=%s, height=%s",
                             body_profile_id, user_body_profile.get("gender"),
                             user_body_profile.get("height"))
        except Exception as e:
            logger.warning("[节点1] 拉取身体信息档案失败，不阻塞主流程: profileId=%s, error=%s",
                            body_profile_id, e)
    # 缓存到局部变量，供三个分支返回时统一带上
    _body_profile_cache = user_body_profile

    # ===== U1 统一架构：商品驱动分支 =====
    # main_item_ids 非空 → 商品驱动模式：拉主商品 + encode_text + 推导互补品类
    # 商品驱动模式不支持多轮反馈，无需处理 feedback_parsed/season 等风格驱动专属逻辑
    main_item_ids = state.get("main_item_ids") or []
    if main_item_ids:
        result = await _intent_understanding_product(state, main_item_ids)
        if _body_profile_cache is not None:
            result["user_body_profile"] = _body_profile_cache
        return result

    # ===== ⑥ 用户选定模式分支（从衣橱/购物车/订单挑选）=====
    # wardrobe_item_ids 非空且 stage="user_picked" → 用户已选定全部单品，直接 VTON
    # 跳过向量编码/风格解析/Qdrant 检索/组合决策，仅加载用户照片
    wardrobe_item_ids = state.get("wardrobe_item_ids") or []
    if wardrobe_item_ids and state.get("stage") == "user_picked":
        result = await _intent_understanding_user_picked(state, wardrobe_item_ids)
        if _body_profile_cache is not None:
            result["user_body_profile"] = _body_profile_cache
        return result

    # ===== 风格驱动分支=====
    style_tags = list(state.get("style_tags", []))
    scene_desc = state.get("scene_desc")
    color = state.get("color")
    categories = state.get("categories") or []
    shop_ids = state.get("shop_ids")
    note = state.get("note")
    photo_session_key = state.get("photo_session_key")
    user_id = state.get("user_id")
    feedback_parsed = state.get("feedback_parsed")
    prev_query_vector = state.get("query_vector")
    prev_style_tags = state.get("_prev_style_tags_for_query", [])
    round_num = state.get("round", 1)
    task_id = state.get("task_id")

    # ===== 意图理解子 Agent（场景 2）=====
    # 已固定启用（原 intent_agent_enabled 开关已移除）
    # 首轮 + 非反馈轮 → 走 ReAct 子 Agent，让 LLM 自主决定调用哪些意图理解工具
    # 反馈轮 → 走原节点1 硬编码顺序
    if (round_num == 1
            and not feedback_parsed):
        try:
            agent_result = await _run_intent_agent(state)
            if agent_result is not None:
                return agent_result
            # 子 Agent 返回 None → 降级走原逻辑
            logger.warning("[节点1] 意图理解子 Agent 返回 None，降级走原逻辑: taskId=%s", task_id)
        except Exception as e:
            logger.warning("[节点1] 意图理解子 Agent 异常，降级走原逻辑: taskId=%s, error=%s",
                            task_id, e)

    # ----- note 备注 LLM 解析合并（仅在首轮且有 note 时执行） -----
    # 反馈轮不走 note 解析（feedback_parsed 已有结构化信息）
    if note and round_num == 1 and not feedback_parsed:
        try:
            llm_client = await get_llm_client()
            note_parsed = await llm_client.parse_note(note)
            logger.info("[节点1] note 解析合并: taskId=%s, note=%s → %s",
                         task_id, note[:50], note_parsed)
            # 合并：note 解析结果补充到结构化字段（用户已填的字段优先，note 只补空字段）
            if not style_tags and note_parsed.get("style_tags"):
                style_tags = note_parsed["style_tags"]
            if not color and note_parsed.get("color"):
                # note 解析的 color 可能是 str 或 list，统一转为 list
                note_color = note_parsed["color"]
                color = [note_color] if isinstance(note_color, str) else note_color
            if not categories and note_parsed.get("categories"):
                categories = note_parsed["categories"]
            if not scene_desc and note_parsed.get("scene"):
                scene_desc = note_parsed["scene"]
            # shop_name 暂不解析为 shop_id（需调 Java 店铺搜索接口，留 P1 优化）
            if note_parsed.get("shop_name"):
                logger.info("[节点1] note 提及店铺 %s，需前端改用 shopId 字段或 P1 实现店铺名解析",
                             note_parsed["shop_name"])
        except Exception as e:
            logger.warning("[节点1] note 解析失败（忽略，继续走结构化字段）: %s", e)

    # ----- 必填校验：style_tags/color/scene_desc/note 任一非空即可 -----
    if not style_tags and not color and not scene_desc and not note:
        return {
            "error": "输入不可全空：styleTags/color/sceneDesc/note 至少填一项",
            "category_constraints": categories or DEFAULT_CATEGORIES,
        }

    # ----- 反馈轮 adjust_style：替换风格标签（与 LLM prompt 契约一致） -----
    # REACT_FEEDBACK_PROMPT 明确告诉 LLM new_style_tags 是"替换原 style_tags"，
    # 采用真正的替换语义；"追加"语义由 want_style_tags 字段承担（见下方）。
    style_changed = False
    if feedback_parsed and feedback_parsed.get("action") == "adjust_style":
        new_tags = feedback_parsed.get("new_style_tags") or []
        if new_tags:
            logger.info("[节点1] 反馈轮 adjust_style: 替换风格 %s → %s",
                         style_tags, new_tags)
            style_tags = list(new_tags)  # 替换，非合并
            style_changed = True

    # ----- 反馈轮 want_style_tags：追加风格（与 adjust_style 区别：
    # adjust_style 是"替换"风格，want_style_tags 是"追加"风格，不替换原 style_tags） -----
    want_tags = state.get("want_style_tags") or []
    if want_tags:
        merged = list(dict.fromkeys(style_tags + want_tags))
        if merged != style_tags:
            logger.info("[节点1] 反馈轮 want_style_tags: 追加风格 %s → %s", want_tags, merged)
            style_tags = merged
            style_changed = True

    logger.info("[节点1] 意图理解: taskId=%s, round=%d, styleTags=%s, color=%s, "
                 "categories=%s, shopIds=%s, sceneDesc=%s",
                 task_id, round_num, style_tags, color, categories, shop_ids, scene_desc)

    # ----- 拼接检索文本（style_tags + scene_desc + color） -----
    parts = list(style_tags)
    if scene_desc:
        parts.append(scene_desc)
    if color:
        parts.extend(color)  # 颜色加入检索文本辅助向量召回（should 加权由节点2 控制）
    query_text = " ".join(parts) if parts else "休闲 日常"

    # ----- HyDE 查询改写（仅首轮，LLM 把模糊输入改写为"假想完美搭配描述"）-----
    # 业务价值：用户输入"下周面试"→ 改写为"商务通勤黑色西装外套白色衬衫正装皮鞋"，
    # 向量召回质量显著提升，直接提升加购率。
    # 降级：LLM 未配置/调用失败时走原 query_text，不影响主流程
    if round_num == 1 and not feedback_parsed:
        try:
            llm_client = await get_llm_client()
            hyde_text = await llm_client.rewrite_query_hyde(
                style_tags=style_tags, scene_desc=scene_desc, color=color,
            )
            if hyde_text:
                logger.info("[节点1] HyDE 改写: taskId=%s, original=%s → hyde=%s",
                             task_id, query_text, hyde_text)
                query_text = hyde_text  # 用改写后的文本编码向量
        except Exception as e:
            logger.warning("[节点1] HyDE 改写失败（走原 query_text）: %s", e)

    # ----- 编码为向量 -----
    # - 首轮：必须编码
    # - 反馈轮 style 未变且已有向量：复用旧向量，节省 embed API 调用
    # - 反馈轮 style 变了（adjust_style）：重新编码
    query_vector = None
    if (
        not style_changed
        and prev_query_vector is not None
        and prev_style_tags == style_tags
        and round_num > 1
    ):
        query_vector = prev_query_vector
        logger.info("[节点1] 反馈轮复用旧向量: taskId=%s, dim=%d", task_id, len(query_vector))
    else:
        try:
            embed_client = await get_embed_client()
            query_vector = await _retry_async(lambda: embed_client.encode_text(query_text))
        except Exception as e:
            logger.warning("[节点1] 文本向量编码失败（后续走兜底）: %s", e)

    # ----- 获取用户照片（系统模特图 > 用户自拍 Redis 会话级）-----
    # 性别与服装匹配：
    # - 用户选定系统模特时，前端传 system_model_image_url，节点1 下载作为 VTON base
    # - 优先级：system_model_image_url > photo_session_key（用户自拍 Redis）
    # - 系统模特图下载后用作 VTON base，user_visual_profile 不再分析（系统模特已带 gender）
    system_model_image_url = state.get("system_model_image_url")
    system_model_gender = state.get("system_model_gender")
    user_photo = None
    if system_model_image_url:
        # 用户选定系统模特，下载图片作为 VTON base
        try:
            user_photo = await _download_image(system_model_image_url)
            if user_photo:
                logger.info("[节点1] 已加载系统模特图: imageUrl=%s, bytes=%d, gender=%s",
                             system_model_image_url[:80], len(user_photo), system_model_gender)
            else:
                logger.warning("[节点1] 系统模特图下载失败，降级走用户自拍/默认模特: imageUrl=%s",
                                system_model_image_url[:80])
        except Exception as e:
            logger.warning("[节点1] 系统模特图下载异常，降级走用户自拍/默认模特: %s", e)

    # 系统模特图下载失败 或 用户未选系统模特 → 走原 Redis 会话级照片加载
    if user_photo is None and photo_session_key and user_id is not None:
        try:
            redis = await get_redis()
            photo_base64 = await redis.get(f"ai:photo:session:{photo_session_key}")
            if photo_base64:
                user_photo = base64.b64decode(photo_base64)
                logger.info("[节点1] 已加载用户自拍照片: userId=%s, bytes=%d", user_id, len(user_photo))
        except Exception as e:
            logger.warning("[节点1] 加载用户自拍照片失败: %s", e)

    # ----- 场景 B：用户照片 LLM 图像理解（提取视觉特征供节点3 搭配决策参考）-----
    # 场景 A（无照片）：跳过 LLM 分析，节点4 用 default_model_image_url 兜底 VTON
    # 场景 B（有照片）：调 LlmClient.analyze_user_photo 提取性别/肤色/风格倾向
    # 系统模特图场景：跳过 LLM 分析（系统模特已带 gender/skinTone 等元数据，无需再分析）
    user_visual_profile = None
    use_default_model = False
    skip_photo_analysis = system_model_image_url is not None and user_photo is not None
    if user_photo and not skip_photo_analysis:
        try:
            llm_client = await get_llm_client()
            user_visual_profile = await llm_client.analyze_user_photo(user_photo)
            if user_visual_profile:
                logger.info("[节点1] 用户视觉特征分析: taskId=%s, profile=%s",
                             task_id, user_visual_profile)
            else:
                logger.info("[节点1] LLM 未配置或分析失败，user_visual_profile=None: taskId=%s", task_id)
        except Exception as e:
            logger.warning("[节点1] 用户照片 LLM 分析失败（不阻塞主流程）: %s", e)
    elif user_photo and skip_photo_analysis:
        logger.info("[节点1] 使用系统模特图，跳过 LLM 视觉分析: taskId=%s, gender=%s",
                     task_id, system_model_gender)
    else:
        use_default_model = True
        logger.info("[节点1] 用户未上传照片且未选系统模特，标记使用默认模特图: taskId=%s", task_id)

    # ----- 性别与服装匹配：确定 target_gender-----
    # 优先级：system_model_gender > user_visual_profile.gender > user_body_profile.gender
    # 来源决定后，节点2 据此过滤 Qdrant payload.target_gender IN (target_gender, "unisex")
    target_gender = None
    gender_source = None
    if system_model_gender in ("male", "female"):
        target_gender = system_model_gender
        gender_source = "system_model"
        logger.info("[节点1] target_gender 来自系统模特: gender=%s, modelId=%s",
                     target_gender, state.get("system_model_id"))
    elif user_visual_profile and user_visual_profile.get("gender") in ("male", "female"):
        target_gender = user_visual_profile["gender"]
        gender_source = "user_photo"
        logger.info("[节点1] target_gender 来自用户自拍分析: gender=%s, taskId=%s",
                     target_gender, task_id)
    elif _body_profile_cache and _body_profile_cache.get("gender") in ("male", "female"):
        target_gender = _body_profile_cache["gender"]
        gender_source = "body_profile"
        logger.info("[节点1] target_gender 来自身体信息档案: gender=%s, profileId=%s",
                     target_gender, body_profile_id)
    else:
        logger.info("[节点1] 未确定 target_gender，跳过性别过滤（向后兼容）: taskId=%s", task_id)

    # 品类约束：用户指定则用，未指定则默认 [上衣, 下装, 鞋]
    final_categories = categories if categories else DEFAULT_CATEGORIES

    # ----- 季节感知注入（天气工具拓展）-----
    # 优先调用天气工具获取实时季节（基于温度），降级走月份推断
    weather_info = None
    if settings.weather_tool_enabled:
        try:
            redis_client = await get_redis()
            weather_info = await call_with_check(
                "weather",
                get_weather(
                    city=state.get("user_city", "") or settings.weather_default_city,
                    api_key=settings.weather_api_key,
                    api_url=settings.weather_api_url,
                    redis=redis_client,
                ),
                fallback=None,
                timeout=5.0,
            )
            if weather_info and weather_info.get("season"):
                current_season = weather_info["season"]
                logger.info("[节点1] 天气工具推导季节: taskId=%s, city=%s, temp=%s, season=%s, source=%s",
                             task_id, weather_info.get("city"), weather_info.get("temp"),
                             current_season, weather_info.get("source"))
            else:
                current_season = _get_current_season()
        except Exception as e:
            logger.warning("[节点1] 天气工具调用异常，降级月份推断: %s", e)
            current_season = _get_current_season()
    else:
        # 根据当前月份判断季节，节点2 会用此字段过滤 Qdrant payload.season
        current_season = _get_current_season()
    # 用户未填 styleTags 时，注入季节默认风格（不覆盖用户意图）
    if not style_tags:
        season_style = _SEASON_DEFAULT_STYLE.get(current_season, [])
        if season_style:
            style_tags = season_style
            logger.info("[节点1] 季节默认风格注入: taskId=%s, season=%s, styleTags=%s",
                         task_id, current_season, style_tags)
            # style_tags 变了，需要重新拼接 query_text 和编码向量
            parts = list(style_tags)
            if scene_desc:
                parts.append(scene_desc)
            if color:
                parts.extend(color)
            query_text = " ".join(parts) if parts else "休闲 日常"
            style_changed = True

    logger.info("[节点1] 季节感知: taskId=%s, season=%s, month=%s",
                 task_id, current_season, datetime.now().month)

    # 季节变更后若 style_changed 已置 True，需重新编码向量（前面已设 style_changed=True）
    # 若 style_changed 在 adjust_style 时已置 True 但向量还没编，这里统一处理
    if style_changed and prev_query_vector is not None and round_num > 1:
        # 反馈轮 adjust_style 已处理，这里跳过
        pass
    elif style_changed and round_num == 1:
        # 首轮因季节注入导致 style_changed，需重新编码
        try:
            embed_client = await get_embed_client()
            query_vector = await _retry_async(lambda: embed_client.encode_text(query_text))
        except Exception as e:
            logger.warning("[节点1] 季节注入后向量编码失败: %s", e)

    # ----- Phase 2.5 个性化推荐画像：融合 style_vector 提升 query_vector 召回相关性 -----
    # 策略：加权融合 α*query_vector + (1-α)*style_vector，用户当前意图优先（α=0.7），
    #       画像风格向量作为辅助增强（1-α=0.3），融合后 L2 归一化匹配 Qdrant Cosine 距离。
    # 条件：profile_confidence > 0.3 且 style_vector 维度与 query_vector 一致时才融合，
    #       否则保持原 query_vector 不变（降级为原逻辑）。
    user_profile = state.get("user_profile") or {}
    if query_vector and user_profile.get("profile_confidence", 0) > 0.3:
        style_vector = user_profile.get("style_vector") or []
        if style_vector and len(style_vector) == len(query_vector):
            alpha = 0.7  # 用户当前意图权重
            fused = [
                alpha * q + (1 - alpha) * s
                for q, s in zip(query_vector, style_vector)
            ]
            # L2 归一化（Cosine 距离要求向量归一化效果最佳）
            norm = sum(x * x for x in fused) ** 0.5
            if norm > 0:
                query_vector = [x / norm for x in fused]
            logger.info(
                "[节点1] Phase 2.5 画像向量融合: taskId=%s, confidence=%s, alpha=%s, dim=%d",
                task_id, user_profile.get("profile_confidence"), alpha, len(query_vector),
            )
        else:
            logger.debug(
                "[节点1] 画像 style_vector 维度不匹配或为空，跳过融合: taskId=%s, "
                "queryDim=%s, styleVecDim=%s",
                task_id, len(query_vector), len(style_vector),
            )

    return {
        "query_text": query_text,
        "query_vector": query_vector,
        "style_tags": style_tags,           # 合并后的 style_tags（含 note 解析 + 季节注入）
        "color": color,                     # 合并后的 color
        "shop_ids": shop_ids,               # 透传给节点2（支持多店铺）
        "season": current_season,           # 透传给节点2 做 Qdrant season 过滤
        "category_constraints": final_categories,  # 中文品类，节点2 内部转英文查 Qdrant
        "user_photo": user_photo,
        "user_visual_profile": user_visual_profile,  # 场景 B：LLM 分析的用户视觉特征
        "use_default_model": use_default_model,      # 场景 A：是否使用默认模特图
        # 天气工具拓展：透传天气信息供下游节点（如 LLM 搭配决策）使用
        "weather_info": weather_info,
        # 用户身体信息档案（节点3 LLM 决策参考 + 前端尺码推荐）
        "user_body_profile": user_body_profile,
        # 性别与服装匹配：节点2 据此过滤 Qdrant，节点3 LLM prompt 双保险
        "target_gender": target_gender,
        "gender_source": gender_source,
        # 记录本轮使用的 style_tags，供下一轮判断是否复用向量
        "_prev_style_tags_for_query": style_tags,
    }


def _build_main_item_text(item_info: dict, category_cn: str | None = None) -> str:
    """从主商品信息拼接文本用于向量编码（纯文本向量模式）

    与 index_items.py 的 build_item_text 逻辑一致：
    拼接 name + category + color + season + styleTags

    Args:
        item_info: Java item-service 返回的商品字典
        category_cn: 已转码的中文类目（可选，避免重复转码）
    Returns:
        拼接后的文本字符串
    """
    parts = []

    name = item_info.get("name")
    if name:
        parts.append(str(name).strip())

    cat = category_cn or item_info.get("category")
    if cat:
        parts.append(str(cat).strip())

    color = item_info.get("color")
    if color:
        parts.append(str(color).strip())

    season = item_info.get("season")
    if season:
        parts.append(str(season).strip())

    raw_style = item_info.get("styleTags") or item_info.get("style_tags")
    if raw_style:
        try:
            if isinstance(raw_style, str):
                parsed = json.loads(raw_style)
                if isinstance(parsed, list):
                    style_tags = [str(s) for s in parsed if s]
                else:
                    style_tags = [str(parsed)]
            elif isinstance(raw_style, list):
                style_tags = [str(s) for s in raw_style if s]
            else:
                style_tags = []
            if style_tags:
                parts.extend(style_tags)
        except (ValueError, TypeError):
            pass

    if not parts:
        return f"商品{item_info.get('id', '')}"
    return " ".join(parts)


async def _intent_understanding_product(state: AgentState, main_item_ids: list[int]) -> dict:
    """U1 统一架构：商品驱动模式意图理解

    流程（对齐 ai-models 原 outfit_service._do_generate 主商品处理逻辑）：
    1. 调 JavaClient.get_items_by_ids 拉主商品详情 → _main_item_info
    2. 下载主商品图 → _main_item_bytes（节点4 VTON garment_image 复用，避免重复下载）
    3. EmbedClient.encode_text(主商品文本) → query_vector（纯文本向量模式，拼接 name+category+color+season+styleTags）
    4. 主商品品类 → 推导互补品类 → category_constraints（替代 DEFAULT_CATEGORIES 硬编码）
    5. 主商品 creater → shop_id（同店优先检索，缺货时节点2 自动跨店降级）
    6. 加载用户照片（与风格驱动共用 Redis 会话级存储）

    与风格驱动的差异：
    - 跳过 note LLM 解析（商品驱动输入是确定的 itemId，无自然语言备注）
    - 跳过季节注入（主商品本身已携带季节信息，无需额外注入默认风格）
    - 跳过 feedback_parsed 处理（商品驱动不支持多轮反馈）
    - mode 字段透传 "product" 供下游节点分支判断

    商品驱动模式接入多轮反馈。
    - 反馈轮（round > 1）：复用 prev_state 中的 _main_item_info / query_vector /
      category_constraints（主商品不变，无需重新拉详情/编码向量）
    - 重新下载主商品图（_main_item_bytes 是 bytes 不可持久化，每轮重新下载）
    - 重新加载用户照片（user_photo 是 bytes 不可持久化，每轮重新加载）
    - 透传 keep_categories / seen_item_ids / dislike_item_ids / feedback_parsed 等反馈字段
    """
    task_id = state.get("task_id")
    user_id = state.get("user_id")
    photo_session_key = state.get("photo_session_key")
    round_num = state.get("round", 1)
    is_feedback_round = round_num > 1

    logger.info("[节点1-商品驱动] 意图理解: taskId=%s, userId=%s, mainItemIds=%s, round=%d",
                 task_id, user_id, main_item_ids, round_num)

    # ===== 反馈轮：复用 prev_state 中的主商品信息 =====
    if is_feedback_round:
        prev_main_info = state.get("_main_item_info") or {}
        if prev_main_info.get("id") is not None:
            main_item_info = prev_main_info
            main_item_id = main_item_info.get("id")
            main_item_image = main_item_info.get("image", "")
            shop_id_raw = main_item_info.get("creater")
            shop_ids = [shop_id_raw] if shop_id_raw is not None else None
            main_category_cn = to_cn(main_item_info.get("category"))
            query_vector = state.get("query_vector")  # 复用首轮编码的向量
            category_constraints = state.get("category_constraints") or []

            logger.info("[节点1-商品驱动][反馈轮] 复用主商品信息: taskId=%s, mainId=%s, "
                         "category=%s, vectorDim=%s",
                         task_id, main_item_id, main_category_cn,
                         len(query_vector) if query_vector else None)
        else:
            # 兜底：prev_state 中无主商品信息（异常情况），降级走首轮逻辑
            logger.warning("[节点1-商品驱动][反馈轮] prev_state 无主商品信息，降级走首轮逻辑: taskId=%s",
                            task_id)
            is_feedback_round = False  # 走首轮逻辑

    # ===== 首轮：拉主商品详情 + 编码向量 + 推导互补品类 =====
    if not is_feedback_round:
        # 1. 拉主商品详情（取第一件作为换装基准，与 ai-models 行为一致）
        try:
            java_client = await get_java_client()
            main_items = await java_client.get_items_by_ids(list(main_item_ids))
        except Exception as e:
            logger.error("[节点1-商品驱动] 拉主商品详情失败: taskId=%s, error=%s", task_id, e)
            return {"error": f"主商品详情拉取失败: {e}", "category_constraints": []}

        if not main_items:
            logger.error("[节点1-商品驱动] 主商品不存在: taskId=%s, mainItemIds=%s", task_id, main_item_ids)
            return {"error": "主商品不存在", "category_constraints": []}

        main_item_info = main_items[0]
        main_item_id = main_item_info.get("id")
        main_item_image = main_item_info.get("image", "")
        # creater 字段对齐 ai-models 用法（商品创建者=店铺 ID），转为 shop_ids 列表
        shop_id_raw = main_item_info.get("creater")
        shop_ids = [shop_id_raw] if shop_id_raw is not None else None
        main_category_cn = to_cn(main_item_info.get("category"))
        logger.info("[节点1-商品驱动] 主商品: id=%s, category=%s, shopIds=%s, image=%s",
                     main_item_id, main_category_cn, shop_ids,
                     (main_item_image or "")[:80])

        # 2. 下载主商品图（节点4 VTON 会复用 _main_item_bytes，避免重复下载）
        main_item_bytes = await _download_image(main_item_image)
        if main_item_bytes is None:
            logger.error("[节点1-商品驱动] 主商品图下载失败: taskId=%s, imageUrl=%s",
                          task_id, main_item_image)
            return {"error": "主商品图片下载失败", "category_constraints": []}

        # 3. 编码主商品文本为向量（纯文本向量模式，替代原 encode_image）
        # 拼接 name + category + color + season + styleTags，与 index_items.py 入库逻辑一致
        main_item_text = _build_main_item_text(main_item_info, main_category_cn)
        query_vector = None
        try:
            embed_client = await get_embed_client()
            query_vector = await _retry_async(lambda: embed_client.encode_text(main_item_text))
        except Exception as e:
            logger.warning("[节点1-商品驱动] 文本向量编码失败（后续走兜底）: %s, text=%s", e, main_item_text[:80])

        # 4. 推导互补品类：默认 [上衣, 下装, 鞋] 中排除主商品品类
        # 主商品是上衣 → 互补 [下装, 鞋]
        # 主商品是下装 → 互补 [上衣, 鞋]
        # 主商品是鞋 → 互补 [上衣, 下装]
        # 主商品是全身套装（连衣裙/旗袍）→ 互补 [鞋]（全身套装本身已覆盖上衣+下装）
        if main_category_cn == "全身套装":
            category_constraints = ["鞋"]
            logger.info("[节点1-商品驱动] 主商品是全身套装，互补品类简化为 [鞋]: taskId=%s", task_id)
        elif main_category_cn:
            category_constraints = [c for c in DEFAULT_CATEGORIES_CN if c != main_category_cn]
        else:
            logger.warning("[节点1-商品驱动] 主商品 category 为空，使用默认品类: taskId=%s", task_id)
            category_constraints = list(DEFAULT_CATEGORIES_CN)
    else:
        # 反馈轮：主商品图重新下载（bytes 不可持久化，每轮重新加载）
        main_item_bytes = await _download_image(main_item_image)
        if main_item_bytes is None:
            logger.error("[节点1-商品驱动][反馈轮] 主商品图下载失败: taskId=%s, imageUrl=%s",
                          task_id, main_item_image)
            return {"error": "主商品图片下载失败", "category_constraints": []}

    # 5. 加载用户照片（系统模特图 > 用户自拍 Redis 会话级，与风格驱动一致）
    # 性别与服装匹配：商品驱动也支持选定系统模特作 VTON base
    system_model_image_url = state.get("system_model_image_url")
    system_model_gender = state.get("system_model_gender")
    user_photo = None
    if system_model_image_url:
        try:
            user_photo = await _download_image(system_model_image_url)
            if user_photo:
                logger.info("[节点1-商品驱动] 已加载系统模特图: imageUrl=%s, bytes=%d, gender=%s",
                             system_model_image_url[:80], len(user_photo), system_model_gender)
            else:
                logger.warning("[节点1-商品驱动] 系统模特图下载失败，降级走用户自拍/默认模特: imageUrl=%s",
                                system_model_image_url[:80])
        except Exception as e:
            logger.warning("[节点1-商品驱动] 系统模特图下载异常，降级走用户自拍/默认模特: %s", e)

    if user_photo is None and photo_session_key and user_id is not None:
        try:
            redis = await get_redis()
            photo_base64 = await redis.get(f"ai:photo:session:{photo_session_key}")
            if photo_base64:
                user_photo = base64.b64decode(photo_base64)
                logger.info("[节点1-商品驱动] 已加载用户自拍照片: userId=%s, bytes=%d",
                             user_id, len(user_photo))
        except Exception as e:
            logger.warning("[节点1-商品驱动] 加载用户自拍照片失败: %s", e)

    # 6. 场景 B：用户照片 LLM 图像理解（与风格驱动共用 LlmClient.analyze_user_photo）
    # 系统模特图场景跳过 LLM 分析（系统模特已带 gender/skinTone 等元数据）
    user_visual_profile = None
    use_default_model = False
    skip_photo_analysis = system_model_image_url is not None and user_photo is not None
    if user_photo and not skip_photo_analysis:
        try:
            llm_client = await get_llm_client()
            user_visual_profile = await llm_client.analyze_user_photo(user_photo)
            if user_visual_profile:
                logger.info("[节点1-商品驱动] 用户视觉特征分析: taskId=%s, profile=%s",
                             task_id, user_visual_profile)
        except Exception as e:
            logger.warning("[节点1-商品驱动] 用户照片 LLM 分析失败（不阻塞）: %s", e)
    elif user_photo and skip_photo_analysis:
        logger.info("[节点1-商品驱动] 使用系统模特图，跳过 LLM 视觉分析: taskId=%s, gender=%s",
                     task_id, system_model_gender)
    else:
        use_default_model = True
        logger.info("[节点1-商品驱动] 用户未上传照片且未选系统模特，标记使用默认模特图: taskId=%s", task_id)

    # 性别与服装匹配：确定 target_gender
    # 优先级：system_model_gender > user_visual_profile.gender
    # 商品驱动模式不读 user_body_profile（主商品已选定，性别仅用于过滤互补商品）
    target_gender = None
    gender_source = None
    if system_model_gender in ("male", "female"):
        target_gender = system_model_gender
        gender_source = "system_model"
        logger.info("[节点1-商品驱动] target_gender 来自系统模特: gender=%s, modelId=%s",
                     target_gender, state.get("system_model_id"))
    elif user_visual_profile and user_visual_profile.get("gender") in ("male", "female"):
        target_gender = user_visual_profile["gender"]
        gender_source = "user_photo"
        logger.info("[节点1-商品驱动] target_gender 来自用户自拍分析: gender=%s, taskId=%s",
                     target_gender, task_id)
    else:
        logger.info("[节点1-商品驱动] 未确定 target_gender，跳过性别过滤（向后兼容）: taskId=%s", task_id)

    logger.info("[节点1-商品驱动] 完成: taskId=%s, round=%d, mainCategory=%s, complementary=%s, "
                 "shopIds=%s, vectorDim=%s, targetGender=%s",
                 task_id, round_num, main_category_cn, category_constraints, shop_ids,
                 len(query_vector) if query_vector else None, target_gender)

    return {
        "mode": "product",
        "query_vector": query_vector,
        "query_text": f"商品驱动:mainItemId={main_item_id}",  # 仅用于日志/调试
        "style_tags": [],                  # 商品驱动不依赖 style_tags
        "color": None,                     # 商品驱动不做颜色过滤（主商品已是用户选定）
        "shop_ids": shop_ids,              # 同店优先检索，节点2 缺货时自动跨店降级
        "season": None,                    # 商品驱动不做季节过滤
        "category_constraints": category_constraints,  # 排除主商品品类
        "user_photo": user_photo,
        "user_visual_profile": user_visual_profile,  # 场景 B：LLM 分析的用户视觉特征
        "use_default_model": use_default_model,      # 场景 A：是否使用默认模特图
        # 性别与服装匹配：节点2 据此过滤 Qdrant
        "target_gender": target_gender,
        "gender_source": gender_source,
        # 内部字段（不持久化，节点4/5 复用）
        "_main_item_bytes": main_item_bytes,
        "_main_item_info": main_item_info,
    }


# ============================================================
# 意图理解子 Agent（场景 2）
# ============================================================
# 季节关键词识别表（用于从 scene_desc/note 提取 season_hint）
_SEASON_KEYWORDS = {
    "spring": ["春", "春天", "春季", "初春", "暮春"],
    "summer": ["夏", "夏天", "夏季", "初夏", "盛夏", "夏日"],
    "autumn": ["秋", "秋天", "秋季", "初秋", "深秋"],
    "winter": ["冬", "冬天", "冬季", "初冬", "寒冬"],
}


def _extract_season_hint(scene_desc: str | None, note: str | None) -> str | None:
    """从场景描述和备注中提取季节线索"""
    text = f"{scene_desc or ''} {note or ''}"
    for season, keywords in _SEASON_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return season
    return None


async def _run_intent_agent(state: AgentState) -> dict | None:
    """意图理解子 Agent 入口：用 ReAct 模式让 LLM 自主决定调用哪些意图理解工具

    LLM 根据用户输入语义自主决定调用顺序和次数：
    - note 非空 → 调 parse_note
    - 场景明确 → 调 rewrite_query_hyde
    - 有照片 → 调 analyze_user_photo
    - 含季节线索 → 调 get_weather_season
    - 最终必须调 encode_query_vector 生成向量

    Returns:
        节点1 state 更新 dict（与原节点1 返回字段一致）；失败返回 None 降级走原逻辑
    """
    from app.tools.intent_tool_executor import IntentToolExecutor

    style_tags = list(state.get("style_tags", []))
    scene_desc = state.get("scene_desc")
    color = state.get("color")
    categories = state.get("categories") or []
    shop_ids = state.get("shop_ids")
    note = state.get("note")
    photo_session_key = state.get("photo_session_key")
    user_id = state.get("user_id")
    task_id = state.get("task_id")
    # 用户是否从衣橱/购物车/订单选定了部分商品参与搭配
    # True 时商品本身已隐含季节属性，IntentAgent 不需要调 get_weather_season 推导季节
    wardrobe_item_ids = state.get("wardrobe_item_ids") or []
    has_picked_items = bool(wardrobe_item_ids)

    # 提取季节线索
    season_hint = _extract_season_hint(scene_desc, note)

    # 构造 LLM 输入
    user_input = {
        "style_tags": style_tags,
        "scene_desc": scene_desc,
        "color": color,
        "note": note,
        "has_photo": bool(photo_session_key and user_id is not None),
        "photo_session_key": photo_session_key,
        "season_hint": season_hint,
        "has_picked_items": has_picked_items,
        "user_id": user_id,
    }

    # 创建 ToolExecutor
    tool_executor = IntentToolExecutor(
        user_id=user_id,
        photo_session_key=photo_session_key,
    )

    llm_client = await get_llm_client()
    max_rounds = settings.intent_agent_max_rounds
    logger.info("[意图Agent] 启动: taskId=%s, maxRounds=%d, userInput=%s",
                 task_id, max_rounds, {k: v for k, v in user_input.items() if k != "photo_session_key"})

    # 调用 ReAct 子 Agent
    result = await llm_client.react_intent(
        user_input=user_input,
        tool_executor=tool_executor,
        max_rounds=max_rounds,
    )

    if not result:
        return None

    # ===== 处理子 Agent 返回结果 =====
    # 1. 提取 LLM 返回的各字段
    final_query_text = result.get("query_text") or ""
    final_style_tags = list(result.get("style_tags") or style_tags)
    # color 统一为 list[str]：
    # LLM 可能返回 str、list 或嵌套 list（如 [['黑色', '白色']]）
    # 扁平化处理避免后续 join 报错 "expected str instance, list found"
    _raw_color = result.get("color") or color
    if isinstance(_raw_color, str):
        final_color = [_raw_color]
    elif isinstance(_raw_color, list):
        flat: list[str] = []
        for c in _raw_color:
            if isinstance(c, list):
                flat.extend(str(x) for x in c if x)
            elif c:
                flat.append(str(c))
        final_color = flat
    else:
        final_color = None
    final_scene_desc = result.get("scene_desc") or scene_desc
    final_season = result.get("season") or "auto"
    user_visual_profile = result.get("user_visual_profile")

    # 2. 处理 query_text：若 LLM 未生成，按原逻辑拼接
    if not final_query_text:
        parts = final_style_tags + ([final_scene_desc] if final_scene_desc else []) + \
                (list(final_color) if final_color else [])
        final_query_text = " ".join(p for p in parts if p) if parts else "休闲 日常"

    # 3. 处理 query_vector：子 Agent 的 LLM 通过 encode_query_vector 工具生成向量，
    #    但向量在 observation 中，final_answer 不直接返回。
    #    这里根据 final_query_text 重新编码一次（与原节点1 逻辑一致）
    query_vector = None
    try:
        embed_client = await get_embed_client()
        query_vector = await embed_client.encode_text(final_query_text)
    except Exception as e:
        logger.warning("[意图Agent] 向量编码失败: %s", e)

    # 4. 处理 season：auto → 按月份推断（子 Agent 未调 get_weather_season 或调用失败）
    current_season = final_season
    if current_season == "auto":
        current_season = _get_current_season()

    # 5. 处理 user_photo（优先级：system_model_image_url > photo_session_key > 默认模特）
    user_photo = None
    use_default_model = True

    # 5.1 优先下载用户选定的系统模特图
    system_model_image_url = state.get("system_model_image_url")
    system_model_gender = state.get("system_model_gender")
    if system_model_image_url:
        try:
            user_photo = await _download_image(system_model_image_url)
            if user_photo:
                use_default_model = False
                logger.info("[意图Agent] 已加载系统模特图: imageUrl=%s, bytes=%d, gender=%s",
                            system_model_image_url[:80], len(user_photo), system_model_gender)
            else:
                logger.warning("[意图Agent] 系统模特图下载失败，降级走用户自拍/默认模特: imageUrl=%s",
                               system_model_image_url[:80])
        except Exception as e:
            logger.warning("[意图Agent] 系统模特图下载异常，降级走用户自拍/默认模特: %s", e)

    # 5.2 系统模特图未加载 → 回退到 Redis 会话级自拍
    if user_photo is None and photo_session_key and user_id is not None:
        try:
            redis = await get_redis()
            photo_b64 = await redis.get(f"ai:photo:session:{photo_session_key}")
            if photo_b64:
                user_photo = base64.b64decode(photo_b64)
                use_default_model = False
        except Exception as e:
            logger.warning("[意图Agent] 加载用户照片失败: %s", e)

    # 5.3 确定 target_gender（系统模特性别优先级最高）
    target_gender = None
    gender_source = None
    if system_model_gender in ("male", "female"):
        target_gender = system_model_gender
        gender_source = "system_model"
    elif user_visual_profile and user_visual_profile.get("gender") in ("male", "female"):
        target_gender = user_visual_profile["gender"]
        gender_source = "user_photo"

    # 6. 季节默认风格注入（style_tags 为空时）
    if not final_style_tags and current_season in _SEASON_DEFAULT_STYLE:
        final_style_tags = list(_SEASON_DEFAULT_STYLE[current_season])
        # 重新拼 query_text 并重新编码
        parts = final_style_tags + ([final_scene_desc] if final_scene_desc else []) + \
                (list(final_color) if final_color else [])
        final_query_text = " ".join(p for p in parts if p) if parts else "休闲 日常"
        try:
            embed_client = await get_embed_client()
            query_vector = await embed_client.encode_text(final_query_text)
        except Exception as e:
            logger.warning("[意图Agent] 季节注入后向量编码失败: %s", e)

    # 7. 品类约束
    final_categories = categories if categories else DEFAULT_CATEGORIES

    logger.info("[意图Agent] 完成: taskId=%s, queryText=%s, season=%s, styleTags=%s, "
                 "hasVector=%s, hasPhoto=%s, targetGender=%s, genderSource=%s",
                 task_id, final_query_text[:50], current_season, final_style_tags,
                 query_vector is not None, user_photo is not None,
                 target_gender, gender_source)

    # 返回与原节点1 一致的 state 字段
    return {
        "query_text": final_query_text,
        "query_vector": query_vector,
        "style_tags": final_style_tags,
        "color": final_color,
        "shop_ids": shop_ids,
        "season": current_season,
        "category_constraints": final_categories,
        "user_photo": user_photo,
        "user_visual_profile": user_visual_profile,
        "use_default_model": use_default_model,
        "weather_info": result.get("weather_info"),
        "target_gender": target_gender,
        "gender_source": gender_source,
        "_prev_style_tags_for_query": final_style_tags,
    }


async def _run_decision_agent(
    state: AgentState,
    outfit_candidates: list[dict],
    reflection_results: list[dict],
    failed_indices: list[int],
) -> dict | None:
    """搭配决策子 Agent 入口：基于 Reflection 结果让 LLM 自主决定下一步动作

    LLM 根据 Reflection 结果自主决定：
    - accept=true → 保留原结果（返回 {} 不更新 state）
    - accept=false → 用 re_search 重新检索或 get_item_details 找替代品，返回新 outfit_candidates

    Returns:
        节点3.5 state 更新 dict（含 outfit_candidates）；失败返回 None 降级走原 pool 替换
    """
    from app.tools.decision_tool_executor import DecisionToolExecutor

    task_id = state.get("task_id")
    user_id = state.get("user_id")
    query_vector = state.get("query_vector")
    shop_ids = state.get("shop_ids")
    season = state.get("season")
    style_tags = list(state.get("style_tags", []))
    color = state.get("color")
    scene_desc = state.get("scene_desc")
    note = state.get("note")

    # 构造 user_intent
    user_intent = {
        "style_tags": style_tags,
        "color": color,
        "scene_desc": scene_desc,
        "note": note,
        "season": season,
        # 性别与服装匹配：注入 target_gender 让 LLM 双保险生效
        "target_gender": state.get("target_gender"),
    }

    # 创建 ToolExecutor
    tool_executor = DecisionToolExecutor(
        task_id=task_id,
        user_id=user_id,
        query_vector=query_vector,
        shop_ids=shop_ids,
        season=season,
        # 性别与服装匹配：传递 target_gender 给 re_search 工具
        target_gender=state.get("target_gender"),
        # 时尚潮流搜索：传递 city/country/style/scene 给 search_fashion_trend 工具
        user_city=state.get("user_city"),
        user_country=state.get("user_country"),
        style_tags=list(state.get("style_tags", [])),
        scene_desc=state.get("scene_desc"),
    )

    llm_client = await get_llm_client()
    max_rounds = 3  # Reflection 最大循环轮次（固定值，原 decision_agent_max_rounds 已移除）
    logger.info("[决策Agent] 启动: taskId=%s, maxRounds=%d, failedIdx=%s",
                 task_id, max_rounds, failed_indices)

    # 调用 ReAct 子 Agent
    result = await llm_client.react_decision(
        outfits=outfit_candidates,
        user_intent=user_intent,
        reflection_results=reflection_results,
        tool_executor=tool_executor,
        max_rounds=max_rounds,
    )

    if not result:
        return None

    # ===== 处理子 Agent 返回结果 =====
    accept = bool(result.get("accept", True))
    new_items_by_outfit = result.get("new_items_by_outfit") or {}
    reason = result.get("reason", "")

    if accept:
        # 接受原结果，不更新 state
        logger.info("[决策Agent] 接受原结果: taskId=%s, reason=%s", task_id, reason)
        return {}

    # 有替换项 → 应用替换
    if not new_items_by_outfit:
        logger.info("[决策Agent] accept=false 但无替换项，保留原结果: taskId=%s", task_id)
        return {}

    new_outfits = list(outfit_candidates)
    is_product_mode = state.get("mode") == "product"
    replaced = 0

    for idx_str, new_items in new_items_by_outfit.items():
        try:
            idx = int(idx_str)
        except (ValueError, TypeError):
            continue
        if idx < 0 or idx >= len(new_outfits):
            continue
        if not new_items:
            continue

        if is_product_mode:
            # 商品驱动模式保留主商品（isMain=True），只替换互补商品
            old_main = next((it for it in new_outfits[idx].get("items", [])
                              if it.get("isMain")), None)
            # new_items 中排除 isMain（LLM 可能返回了新主商品，但商品驱动主商品不可替换）
            filtered_items = [it for it in new_items if not it.get("isMain")]
            if old_main:
                final_items = [old_main] + filtered_items
            else:
                final_items = filtered_items
        else:
            final_items = new_items

        new_outfits[idx] = {
            "items": final_items,
            "score": new_outfits[idx].get("score", 0),
            "reason": f"决策 Agent 替换：{reason[:30]}",
        }
        replaced += 1

    logger.info("[决策Agent] 完成: taskId=%s, replaced=%d/%d, reason=%s",
                 task_id, replaced, len(new_items_by_outfit), reason)

    if replaced == 0:
        return {}

    return {"outfit_candidates": new_outfits}


async def _intent_understanding_user_picked(
    state: AgentState, wardrobe_item_ids: list[int]
) -> dict:
    """⑥ 用户选定模式意图理解（从衣橱/购物车/订单挑选）

    用户已选定全部搭配单品，直接走 VTON，无需向量编码/风格解析/Qdrant 检索。
    本节点仅负责加载用户照片 + LLM 视觉特征分析（与风格驱动共用 Redis 会话级存储）。

    流程：
    1. 加载用户照片（场景 A=默认模特，场景 B=用户上传）
    2. 场景 B：LLM 图像理解提取性别/肤色/风格倾向（不阻塞主流程）
    3. 透传 wardrobe_item_ids 供 build_wardrobe_outfit 节点使用

    与风格驱动的差异：
    - 跳过 note LLM 解析 / 季节注入 / HyDE 改写 / 向量编码
    - 跳过 style_tags / color / categories 等风格字段
    - mode="user_picked" 透传到下游节点
    """
    task_id = state.get("task_id")
    user_id = state.get("user_id")
    photo_session_key = state.get("photo_session_key")
    system_model_image_url = state.get("system_model_image_url")
    system_model_gender = state.get("system_model_gender")

    logger.info("[节点1-用户选定] 意图理解: taskId=%s, userId=%s, wardrobeItemIds=%d",
                 task_id, user_id, len(wardrobe_item_ids))

    # 加载用户照片（优先级：system_model_image_url > photo_session_key > 默认模特）
    user_photo = None

    # 1. 优先下载用户选定的系统模特图
    if system_model_image_url:
        try:
            user_photo = await _download_image(system_model_image_url)
            if user_photo:
                logger.info("[节点1-用户选定] 已加载系统模特图: imageUrl=%s, bytes=%d, gender=%s",
                            str(system_model_image_url)[:80], len(user_photo),
                            system_model_gender)
        except Exception as e:
            logger.warning("[节点1-用户选定] 系统模特图下载失败: %s", e)

    # 2. 系统模特图未加载 → 回退到 Redis 会话级自拍
    if not user_photo and photo_session_key and user_id is not None:
        try:
            redis = await get_redis()
            photo_base64 = await redis.get(f"ai:photo:session:{photo_session_key}")
            if photo_base64:
                user_photo = base64.b64decode(photo_base64)
                logger.info("[节点1-用户选定] 已加载用户照片: userId=%s, bytes=%d",
                             user_id, len(user_photo))
        except Exception as e:
            logger.warning("[节点1-用户选定] 加载用户照片失败: %s", e)

    # 确定 target_gender（系统模特性别优先级最高，与风格驱动一致）
    target_gender = system_model_gender or None
    gender_source = "system_model" if system_model_gender else None

    # 场景 B：用户照片 LLM 图像理解
    user_visual_profile = None
    use_default_model = False
    skip_photo_analysis = system_model_image_url is not None and user_photo is not None
    if user_photo and not skip_photo_analysis:
        try:
            llm_client = await get_llm_client()
            user_visual_profile = await llm_client.analyze_user_photo(user_photo)
            if user_visual_profile:
                logger.info("[节点1-用户选定] 用户视觉特征分析: taskId=%s, profile=%s",
                             task_id, user_visual_profile)
                # 系统模特性别未提供时，从 LLM 分析结果补充
                if not target_gender and user_visual_profile.get("gender"):
                    target_gender = user_visual_profile.get("gender")
                    gender_source = "user_photo"
        except Exception as e:
            logger.warning("[节点1-用户选定] 用户照片 LLM 分析失败（不阻塞）: %s", e)
    elif not user_photo:
        use_default_model = True
        logger.info("[节点1-用户选定] 用户未上传照片，标记使用默认模特图: taskId=%s", task_id)

    return {
        "mode": "user_picked",
        "user_photo": user_photo,
        "user_visual_profile": user_visual_profile,
        "use_default_model": use_default_model,
        "target_gender": target_gender,
        "gender_source": gender_source,
        # wardrobe_item_ids 已在 state 中，无需重复设置
    }


# ============================================================
# 节点 1.5：用户选定模式搭配构建（⑥ 专属，跳过 Qdrant 检索 + 组合决策）
# ============================================================
@_trace_node("wardrobe")
async def build_wardrobe_outfit(state: AgentState) -> dict:
    """⑥ 用户选定模式：从衣橱/购物车/订单挑选的商品直接构建搭配

    用户已选定全部单品，无需 LLM 决策搭配组合，直接构造 outfit_candidates：
    1. 调 JavaClient.get_items_by_ids 拉取用户选定商品详情
    2. 构造单套搭配（包含所有用户选定商品）
    3. 返回 outfit_candidates 供 vton_generation 节点使用

    与风格驱动的差异：
    - 跳过 Qdrant 向量检索（节点2）
    - 跳过 LLM 组合决策（节点3）
    - 跳过 Reflection 自检（节点3.5）
    - 直接输出 1 套搭配（用户选定，无需 Top3 候选）
    """
    wardrobe_item_ids = state.get("wardrobe_item_ids") or []
    task_id = state.get("task_id")

    logger.info("[节点1.5-用户选定] 构建搭配: taskId=%s, wardrobeItemIds=%s",
                 task_id, wardrobe_item_ids)

    if not wardrobe_item_ids:
        return {"outfit_candidates": [], "error": "用户未选定任何商品"}

    # 拉取商品详情
    try:
        java_client = await get_java_client()
        items = await java_client.get_items_by_ids(list(wardrobe_item_ids))
    except Exception as e:
        logger.error("[节点1.5-用户选定] 拉取商品详情失败: taskId=%s, error=%s", task_id, e)
        return {"outfit_candidates": [], "error": f"商品详情拉取失败: {e}"}

    if not items:
        logger.error("[节点1.5-用户选定] 商品不存在: taskId=%s, itemIds=%s",
                      task_id, wardrobe_item_ids)
        return {"outfit_candidates": [], "error": "选定的商品不存在"}

    # 构造 outfit_items（与 outfit_combination 节点输出格式一致，字段名统一 camelCase）
    # 单品来源：item_sources 映射（item_id → wardrobe/cart/order/search），
    # 映射缺失时兜底 wardrobe（旧链路无来源信息）
    item_sources = state.get("wardrobe_item_sources") or {}
    outfit_items = []
    for it in items:
        if not it or not it.get("id"):
            continue
        try:
            item_id_int = int(it["id"])
        except (TypeError, ValueError):
            continue
        outfit_items.append({
            "itemId": item_id_int,
            "name": it.get("name", ""),
            "image": it.get("image", ""),
            "category": to_cn(it.get("category")) or "",
            "color": it.get("color"),
            "price": it.get("price"),
            "shopId": it.get("shopId") or it.get("shop_id"),
            "isWardrobePicked": True,  # 标记用户选定
            "source": item_sources.get(item_id_int, "wardrobe"),  # 来源：wardrobe/cart/order/search
        })

    if not outfit_items:
        return {"outfit_candidates": [], "error": "选定的商品无效"}

    # 构造单套搭配（与 outfit_combination 输出格式一致）
    outfit_candidate = {
        "items": outfit_items,
        "score": 1.0,
        "reason": "用户选定搭配",
    }

    logger.info("[节点1.5-用户选定] 搭配构建完成: taskId=%s, items=%d",
                 task_id, len(outfit_items))

    return {
        "outfit_candidates": [outfit_candidate],
        "top_candidates_pool": [outfit_candidate],
    }


# ============================================================
# 节点2：Qdrant 向量检索
# ============================================================
@_trace_node("search")
async def qdrant_search(state: AgentState) -> dict:
    """按品类约束在 Qdrant 中检索互补商品

    多轮反馈支持：
    - keep_categories 非空时，只检索不在 keep_categories 中的品类（要替换的品类）
    - 保留上一轮 keep_categories 中已选定的商品，直接复用

    结构化输入支持：
    - shop_ids 非空时限定店铺内检索；指定店铺某品类检索为空（或不足 3 件）时自动 fallback 全平台
      并在结果 item 上打标 cross_shop=true
    - color 非空时 Qdrant payload 精确过滤
    - categories 为空时默认 [上衣, 下装, 鞋]
    - season 非空时 Qdrant payload 过滤 season IN (season, "all")

    品类转码：
    - state.category_constraints 存中文，检索时转英文查 Qdrant
    - 返回的 candidate_items_by_category 用中文 key（保持前端友好）

    衣橱功能：
    - state.wardrobe_item_ids 非空时，先调 JavaClient.get_items_by_ids 拉商品详情
    - 这些商品按 category 分桶塞入 candidate_items_by_category，标记 _wardrobe_picked=True
    - 被衣橱覆盖的品类跳过 Qdrant 检索（衣橱商品是该品类的唯一候选）
    - 衣橱商品不受 dislike_item_ids 过滤（用户本轮明确选定）
    - 节点3 通过 _wardrobe_picked 标记强制保留这些商品（不参与 seen_item_ids 过滤）
    """
    query_vector = state.get("query_vector")
    categories = state.get("category_constraints") or DEFAULT_CATEGORIES
    keep_categories = state.get("keep_categories") or []
    prev_candidates = state.get("candidate_items_by_category", {})
    shop_ids = state.get("shop_ids")
    color = state.get("color")
    season = state.get("season")
    # 性别与服装匹配：节点1 已确定 target_gender
    target_gender = state.get("target_gender")
    # 用户偏好：同会话累积的不喜欢颜色（Qdrant must_not 过滤）+ 本轮不喜欢的商品 ID（后置过滤）
    user_dislike_colors = state.get("user_dislike_colors") or []
    dislike_item_ids = set(state.get("dislike_item_ids") or [])
    wardrobe_item_ids = state.get("wardrobe_item_ids") or []
    task_id = state.get("task_id")

    # ===== 衣橱商品注入=====
    # 拉取衣橱商品详情，按 category 分桶塞入候选池；
    # 被覆盖的品类跳过 Qdrant 检索；衣橱商品不受 dislike_item_ids 过滤
    # 性别过滤扩展：衣橱商品也检查 target_gender，避免跨性别
    wardrobe_candidates_by_cat: dict[str, list[dict]] = {}
    if wardrobe_item_ids:
        try:
            java_client = await get_java_client()
            wardrobe_items = await java_client.get_items_by_ids(list(wardrobe_item_ids))
            for it in wardrobe_items:
                if not it or not it.get("id"):
                    continue
                # ItemDTO.category 可能是英文或中文，统一转中文
                item_category = to_cn(it.get("category"))
                if not item_category:
                    logger.warning("[节点2] 衣橱商品 %s 无 category 字段，跳过", it.get("id"))
                    continue
                # 性别过滤扩展：衣橱商品也检查 target_gender，避免用户选了跨性别商品
                # 例如男用户选了女款连衣裙，应跳过（用户可能误选）
                item_gender = it.get("targetGender") or it.get("target_gender")
                if (target_gender in ("male", "female")
                        and item_gender in ("male", "female")
                        and item_gender != target_gender):
                    logger.warning("[节点2] 衣橱商品 %s 性别不匹配（用户性别=%s, 商品性别=%s），跳过",
                                    it.get("id"), target_gender, item_gender)
                    continue
                # 构造与 Qdrant 结果一致的 candidate 格式
                try:
                    item_id_int = int(it["id"])
                except (TypeError, ValueError):
                    continue
                candidate = {
                    "item_id": item_id_int,
                    "category": item_category,
                    "color": it.get("color"),
                    "shop_id": it.get("shopId") or it.get("shop_id"),
                    "price": it.get("price"),
                    "score": 1.0,  # 用户选定，分数最高（节点3 优先选）
                    "cross_shop": False,
                    "target_gender": item_gender,
                    # 标记：节点3 强制保留不参与 seen_item_ids 过滤、不参与反馈替换
                    "_wardrobe_picked": True,
                }
                wardrobe_candidates_by_cat.setdefault(item_category, []).append(candidate)
            logger.info("[节点2] 衣橱商品注入: taskId=%s, wardrobeItemIds=%d, fetched=%d, "
                         "coveredCategories=%s, targetGender=%s",
                         task_id, len(wardrobe_item_ids), len(wardrobe_items),
                         list(wardrobe_candidates_by_cat.keys()), target_gender)
        except Exception as e:
            logger.warning("[节点2] 衣橱商品注入失败（不阻塞 Qdrant 检索）: %s", e)

    wardrobe_covered_categories = set(wardrobe_candidates_by_cat.keys())

    # 计算本轮需要检索的品类（排除保留的品类 + 衣橱覆盖的品类）
    if keep_categories:
        search_categories = [c for c in categories
                             if c not in keep_categories
                             and c not in wardrobe_covered_categories]
        logger.info("[节点2] Qdrant 检索（反馈轮）: taskId=%s, all=%s, keep=%s, "
                     "wardrobeCovered=%s, search=%s, "
                     "shopIds=%s, color=%s, season=%s, targetGender=%s, "
                     "dislikeColors=%s, dislikeItems=%d",
                     task_id, categories, keep_categories,
                     list(wardrobe_covered_categories), search_categories,
                     shop_ids, color, season, target_gender,
                     user_dislike_colors, len(dislike_item_ids))
    else:
        search_categories = [c for c in categories
                             if c not in wardrobe_covered_categories]
        logger.info("[节点2] Qdrant 检索（首轮）: taskId=%s, categories=%s, "
                     "wardrobeCovered=%s, search=%s, shopIds=%s, color=%s, "
                     "season=%s, targetGender=%s, dislikeColors=%s, dislikeItems=%d",
                     task_id, categories,
                     list(wardrobe_covered_categories), search_categories,
                     shop_ids, color, season, target_gender,
                     user_dislike_colors, len(dislike_item_ids))

    candidate_items_by_category: dict[str, list[dict]] = {}

    # ① 注入衣橱商品（被覆盖的品类，唯一候选，不受 dislike_item_ids 过滤）
    for cat, items in wardrobe_candidates_by_cat.items():
        candidate_items_by_category[cat] = list(items)
        logger.info("[节点2] 衣橱商品注入品类 %s: %d 件", cat, len(items))

    # ② 保留上一轮已选定的品类商品（用户未要求替换的，且未被衣橱覆盖）
    for cat in keep_categories:
        if cat in prev_candidates and cat not in candidate_items_by_category:
            candidate_items_by_category[cat] = prev_candidates[cat]
            logger.info("[节点2] 保留上轮 %s 候选: %d 件", cat, len(prev_candidates[cat]))

    if query_vector is None:
        logger.warning("[节点2] 无查询向量，跳过 Qdrant 检索（返回已有候选）")
        return {"candidate_items_by_category": candidate_items_by_category,
                "error": "向量编码失败" if not candidate_items_by_category else None}

    searcher = await get_qdrant_searcher()

    # ③ 串行检索每个需替换的品类（Qdrant 同步客户端，避免并发阻塞事件循环）
    for category in search_categories:
        # 品类中→英转码（Qdrant payload.category 存英文）
        category_en = to_en(category)
        results = await _search_with_fallback(
            searcher, query_vector, category_en, color, season,
            user_dislike_colors, target_gender, shop_ids, task_id,
        )
        # 后置过滤：排除用户不喜欢的商品 ID（dislike_item_ids）
        if dislike_item_ids:
            before = len(results)
            results = [r for r in results if r.get("item_id") not in dislike_item_ids]
            if before != len(results):
                logger.info("[节点2] 品类 %s 后置过滤 dislike_item_ids: %d → %d",
                             category, before, len(results))
        # 结果 item 的 category 字段转回中文，保持前端友好
        for r in results:
            r["category"] = to_cn(r.get("category"))
        candidate_items_by_category[category] = results
        logger.info("[节点2] 品类 %s 最终候选: %d 件（targetGender=%s）",
                     category, len(results), target_gender)

    # ===== 工具拓展：实时库存过滤 =====
    # 调用 item-service 批量查询实时库存，过滤掉缺货商品
    # 失败时降级为不过滤（原候选保留）
    if settings.inventory_tool_enabled:
        candidate_items_by_category = await _filter_candidates_by_inventory(
            candidate_items_by_category, wardrobe_covered_categories, task_id,
        )

    return {"candidate_items_by_category": candidate_items_by_category}


async def _filter_candidates_by_inventory(
    candidate_items_by_category: dict[str, list[dict]],
    wardrobe_covered_categories: set,
    task_id: str,
) -> dict[str, list[dict]]:
    """库存工具：批量查询候选商品实时库存，过滤缺货商品

    策略：
    1. 收集所有候选 item_id（除衣橱商品外），调 item-service 批量查库存
    2. 过滤掉 stock <= threshold 的商品
    3. 衣橱商品（_wardrobe_picked）不参与库存过滤（用户已选定）
    4. 某品类过滤后为空 → 触发跨店补全（这里只标记，由后续逻辑处理）
    """
    try:
        java_client = await get_java_client()
    except Exception as e:
        logger.warning("[节点2] 库存过滤跳过：JavaClient 不可用: %s", e)
        return candidate_items_by_category

    # 收集所有候选 item_id（衣橱商品跳过）
    all_item_ids: set[int] = set()
    for cat, items in candidate_items_by_category.items():
        for it in items:
            if not it.get("_wardrobe_picked") and it.get("item_id"):
                all_item_ids.add(it["item_id"])

    if not all_item_ids:
        return candidate_items_by_category

    # 调用库存工具（统一熔断 + 超时 + 降级）
    instock_ids, outstock_ids, stock_map = await call_with_check(
        "inventory",
        filter_instock_items(
            java_client, list(all_item_ids),
            threshold=settings.inventory_threshold,
        ),
        fallback=(list(all_item_ids), [], {}),  # 降级：全部保留，不过滤
        timeout=3.0,
    )

    if not outstock_ids:
        # 没有缺货商品或降级返回，原样返回
        logger.info("[节点2] 库存过滤：无缺货商品（候选共 %d 件）", len(all_item_ids))
        return candidate_items_by_category

    logger.info("[节点2] 库存过滤：缺货 %d 件，将过滤: %s",
                len(outstock_ids), outstock_ids[:10])
    outstock_set = set(outstock_ids)

    # 执行过滤
    filtered_by_cat: dict[str, list[dict]] = {}
    for cat, items in candidate_items_by_category.items():
        kept = []
        for it in items:
            if it.get("_wardrobe_picked"):
                # 衣橱商品强制保留
                kept.append(it)
                continue
            iid = it.get("item_id")
            if iid in outstock_set:
                logger.info("[节点2] 库存过滤：剔除品类 %s 的缺货商品 %s", cat, iid)
                continue
            kept.append(it)
        filtered_by_cat[cat] = kept
        if len(kept) < len(items):
            logger.info("[节点2] 品类 %s 库存过滤: %d → %d", cat, len(items), len(kept))

    return filtered_by_cat


async def _search_with_fallback(
    searcher,
    query_vector: list[float],
    category_en: str,
    color: list[str] | None,
    season: str | None,
    dislike_colors: list[str] | None,
    target_gender: str | None,
    shop_ids: list[int] | None,
    task_id: str,
) -> list[dict]:
    """单品类检索 + 缺货跨店降级补全 + 稀缺品类放宽兜底

    策略：
    1. shop_ids 非空时先在指定店铺内检索（Filter: shop_ids + color + season + category + target_gender）
    2. 指定店铺检索为空或不足 MIN_CANDIDATES_PER_CATEGORY 件 → fallback 全平台检索补全
       并在跨店结果 item 上打标 cross_shop=true
    3. 全平台仍不足 → 放宽条件兜底检索（去掉 season + 降低 score_threshold），
       缓解品类数据稀缺导致"检索为 0"（如全身套装全平台仅 3 件，夏季+女模过滤后不足 3 件，
       再被 0.3 相似度阈值过滤直接为 0）

    Args:
        category_en: 英文品类枚举（tops/bottoms/shoes 等），已由调用方转码
        dislike_colors: 同会话累积的不喜欢颜色（Qdrant must_not 过滤）
        target_gender: 用户/模特适用性别（male/female），Qdrant payload.target_gender IN (target_gender, "unisex")。
                       None 时不过滤（向后兼容未标注商品）。
        shop_ids: 指定店铺 ID 列表（支持多选），None/空则全平台
    """
    # 稀缺品类兜底阈值：原 0.3 相似度阈值会把仅有的候选全部过滤掉
    RELAX_SCORE_THRESHOLD = 0.1

    async def _do_search(
        shop_ids_: list[int] | None, ssn: str | None, thr: float,
    ) -> list[dict]:
        return await asyncio.to_thread(
            searcher.search_complementary_items,
            query_vector=query_vector,
            shop_ids=shop_ids_,
            category=category_en,
            color=color,
            season=ssn,
            dislike_colors=dislike_colors,
            target_gender=target_gender,
            limit=5,
            score_threshold=thr,
        )

    try:
        # ① 指定店铺内检索（shop_ids 非空时）
        if shop_ids:
            results = await _do_search(shop_ids, season, 0.3)
            if len(results) >= MIN_CANDIDATES_PER_CATEGORY:
                return results
            logger.info("[节点2] 店铺 %s 品类 %s 仅 %d 件（<%d），fallback 全平台补全（targetGender=%s）",
                         shop_ids, category_en, len(results), MIN_CANDIDATES_PER_CATEGORY, target_gender)
            # ② 跨店 fallback 补全
            cross_results = await _do_search(None, season, 0.3)
            # 打标 cross_shop=true（前端展示"此件来自其他店铺"）
            for r in cross_results:
                r["cross_shop"] = True
            # 合并去重（按 item_id），店铺内结果优先
            seen_ids = {r.get("item_id") for r in results}
            for r in cross_results:
                if r.get("item_id") not in seen_ids:
                    results.append(r)
                    seen_ids.add(r.get("item_id"))
            logger.info("[节点2] 品类 %s 跨店补全后共 %d 件", category_en, len(results))
            if len(results) >= MIN_CANDIDATES_PER_CATEGORY:
                return results
            # ③ 放宽兜底：去 season + 降阈值（店铺内数据更稀缺，直接全平台放宽重试）
            relaxed = await _do_search(None, None, RELAX_SCORE_THRESHOLD)
            if relaxed:
                logger.info("[节点2] 品类 %s 放宽兜底（去season+阈值0.1）: 补 %d 件", category_en, len(relaxed))
                for r in relaxed:
                    if r.get("item_id") not in seen_ids:
                        r["cross_shop"] = True
                        results.append(r)
                        seen_ids.add(r.get("item_id"))
            return results

        # ④ 全平台检索（shop_ids 为空时直接全平台）
        results = await _do_search(None, season, 0.3)
        if len(results) < MIN_CANDIDATES_PER_CATEGORY:
            # ⑤ 放宽兜底：去 season + 降阈值（缓解品类数据稀缺）
            relaxed = await _do_search(None, None, RELAX_SCORE_THRESHOLD)
            if len(relaxed) > len(results):
                logger.info("[节点2] 品类 %s 放宽兜底（去season+阈值0.1）: %d → %d 件",
                             category_en, len(results), len(relaxed))
                results = relaxed
        return results
    except Exception as e:
        logger.warning("[节点2] 品类 %s 检索失败: %s", category_en, e)
        return []


# ============================================================
# 节点3：组合决策
# ============================================================
@_trace_node("outfit")
async def outfit_combination(state: AgentState) -> dict:
    """从候选商品中组合出 3 套搭配，并补全商品详情

    U1 统一架构：商品驱动模式（mode="product"）只生成 1 套搭配，
    把主商品加入搭配 items（标记 isMain=true），跳过 LLM Top3 决策和 seen_item_ids 过滤。

    多轮反馈支持（仅风格驱动）：
    - 基于 seen_item_ids 过滤已推荐过的商品，避免重复
    - 已推荐组合完全相同（所有 itemId 一致）则跳过
    - action=replace_single（点哪换哪）：
      prev_candidates 中其他品类只有 1 件"保留单品"，待替换品类有 N 件候选
      笛卡尔积 = 待替换品类候选 × 其他品类唯一保留单品 = N 套搭配
      其他单品不变，只有待替换品类变

    品类组合支持：
    - 按 state.category_constraints 动态笛卡尔积，不再固定"上衣→下装→鞋"三件
    - 支持用户自定义品类组合（如 [上衣, 下装] 或 [帽子]）

    预算约束：
    - state.budget_max 非空时，按组合总价过滤 ≤ budget_max

    衣橱功能：
    - 候选池中带 _wardrobe_picked=True 的商品为"用户选定商品"
    - 这些商品从笛卡尔积候选中剥离，强制追加到每套搭配末尾
    - 不参与 seen_item_ids 过滤（用户本轮明确选定，不应被去重过滤掉）
    - 不参与反馈替换（即使 action=replace_single 也保留）
    - 输出 front_items 时打标 isWardrobePicked=true 供前端展示
    """
    # ===== U1 统一架构：商品驱动分支 =====
    if state.get("mode") == "product":
        return await _outfit_combination_product(state)

    # ===== 风格驱动分支=====
    candidates_by_cat = state.get("candidate_items_by_category", {})
    seen_item_ids = set(state.get("seen_item_ids") or set())
    task_id = state.get("task_id")
    round_num = state.get("round", 1)
    categories = state.get("category_constraints") or DEFAULT_CATEGORIES
    # 搭配来源：指定店铺（shop_ids 非空）或全平台（为空）
    shop_ids = state.get("shop_ids") or []
    # 兜底：反馈轮 LLM 解析后的 categories 可能含冲突（全身套装 + 上衣/下装），
    # 自动剔除冲突品类（先到先得），避免后续笛卡尔积产生非法组合
    filtered = filter_conflicting_categories(categories)
    if len(filtered) != len(categories):
        logger.warning(
            "[节点3] 品类兜底过滤: 原=%s → 过滤后=%s, taskId=%s",
            categories, filtered, task_id,
        )
    categories = filtered
    budget_max = state.get("budget_max")
    feedback_parsed = state.get("feedback_parsed")
    is_replace_single = (
        feedback_parsed and feedback_parsed.get("action") == "replace_single"
    )

    # ===== 衣橱商品剥离 =====
    # wardrobe_picked_items：所有 _wardrobe_picked=True 的商品（强制追加到每套搭配）
    # regular_candidates_by_cat：剔除衣橱商品后的常规候选（参与笛卡尔积）
    wardrobe_picked_items: list[dict] = []
    regular_candidates_by_cat: dict[str, list[dict]] = {}
    for cat, items in candidates_by_cat.items():
        regular = []
        for it in items:
            if it.get("_wardrobe_picked"):
                wardrobe_picked_items.append(it)
            else:
                regular.append(it)
        if regular:
            regular_candidates_by_cat[cat] = regular

    logger.info("[节点3] 组合决策: taskId=%s, round=%d, categories=%s, seenItems=%d, "
                 "budgetMax=%s, replaceSingle=%s, wardrobePicked=%d",
                 task_id, round_num, categories, len(seen_item_ids), budget_max,
                 is_replace_single, len(wardrobe_picked_items))

    # 收集每个品类的非空常规候选（保持 categories 顺序）
    cat_lists = [regular_candidates_by_cat[c] for c in categories
                  if c in regular_candidates_by_cat and regular_candidates_by_cat[c]]

    # 笛卡尔积生成组合（上限 15 个，避免品类多时爆炸）
    # 衣橱商品不参与笛卡尔积，强制追加到每套搭配末尾
    if cat_lists:
        combos = list(itertools.product(*cat_lists))[:15]
        # Phase 2.5 个性化推荐画像：提取 top_colors 用于颜色偏好加权
        # 业务价值：用户历史偏好颜色的组合评分提升，更易进入 Top10 喂给 LLM 决策
        user_profile = state.get("user_profile") or {}
        profile_top_colors = set(user_profile.get("top_colors") or [])
        profile_confidence = user_profile.get("profile_confidence", 0)
        scored = []
        for combo in combos:
            items = list(combo) + list(wardrobe_picked_items)  # 追加衣橱商品
            # 综合分 = 平均相似度（衣橱商品 score=1.0，会拉高均分）
            base_score = sum(it.get("score", 0) for it in items) / len(items) if items else 0
            # Phase 2.5：偏好颜色商品加权（仅当画像置信度 > 0 时生效）
            # color_bonus = 命中比例 × 0.1 × confidence，最多 +0.1*confidence，避免主导评分
            color_bonus = 0.0
            if profile_top_colors and profile_confidence > 0 and items:
                matched = sum(1 for it in items if it.get("color") in profile_top_colors)
                color_bonus = (matched / len(items)) * 0.1 * profile_confidence
            score = base_score + color_bonus
            scored.append((items, score))
    elif wardrobe_picked_items:
        # 无常规候选但有衣橱商品 → 单套搭配（仅衣橱商品）
        logger.info("[节点3] 仅衣橱商品无常规候选，生成单套搭配: %d 件",
                     len(wardrobe_picked_items))
        items = list(wardrobe_picked_items)
        score = sum(it.get("score", 0) for it in items) / len(items) if items else 0
        scored = [(items, score)]
    else:
        logger.warning("[节点3] 无候选商品，返回空搭配")
        return {"outfit_candidates": [], "error": "未检索到匹配商品"}

    # 按分数排序
    scored.sort(key=lambda x: x[1], reverse=True)

    # 预算过滤（budget_max 非空时）— 衣橱商品价格计入总价
    if budget_max is not None and budget_max > 0:
        budget_filtered = []
        for items, score in scored:
            total_price = sum(
                (it.get("price") or 0) for it in items if it.get("price")
            )
            if total_price <= budget_max:
                budget_filtered.append((items, score))
        if budget_filtered:
            scored = budget_filtered
            logger.info("[节点3] 预算过滤后剩余 %d 套（budgetMax=%s）", len(scored), budget_max)
        else:
            logger.warning("[节点3] 预算过滤后无组合，降级保留原排序（不强制预算）")

    # 过滤已推荐过的组合：组合内所有"非衣橱"itemId 都在 seen_item_ids 中则跳过
    # 衣橱商品不受 seen_item_ids 影响（用户本轮明确选定，不应被去重过滤掉）
    # 点哪换哪场景特殊：保留单品不应被 seen_item_ids 误过滤，
    # 只要待替换品类的商品是新商品即可（is_replace_single 时放宽过滤条件）
    fresh_scored = []
    for items, score in scored:
        # 仅检查非衣橱商品是否在 seen_item_ids 中
        non_wardrobe_ids = {it.get("item_id") for it in items
                             if it.get("item_id") and not it.get("_wardrobe_picked")}
        if not non_wardrobe_ids:
            # 全是衣橱商品 → 永远保留（不应被去重）
            fresh_scored.append((items, score))
            continue
        if is_replace_single:
            # 点哪换哪：只要有 1 件新商品即可（待替换品类的那件）
            if not non_wardrobe_ids.issubset(seen_item_ids):
                fresh_scored.append((items, score))
        else:
            # 标准模式：组合中至少有一个新商品才保留
            if not non_wardrobe_ids.issubset(seen_item_ids):
                fresh_scored.append((items, score))

    if fresh_scored:
        top_candidates = fresh_scored[:10]  # 取 Top10 喂给 LLM
    else:
        logger.warning("[节点3] 所有组合均已推荐过，降级为不去重取 Top10")
        top_candidates = scored[:10]

    # ----- 批量补全商品详情（name / image / price）-----
    # Top10 的所有 item_id 都查详情（LLM 决策需要 name/color/price 上下文）
    all_item_ids = list({it["item_id"] for items, _ in top_candidates
                          for it in items if it.get("item_id")})
    item_details: dict[int, dict] = {}
    if all_item_ids:
        try:
            java_client = await get_java_client()
            details_list = await java_client.get_items_by_ids(all_item_ids)
            for d in details_list:
                if d and d.get("id"):
                    item_details[int(d["id"])] = d
        except Exception as e:
            logger.warning("[节点3] 批量查询商品详情失败: %s", e)

    # 构造 LLM 输入：Top10 候选（含 name/color/price 等字段）
    # 透传 _wardrobe_picked 标记，让 LLM 知道哪些是用户选定商品（影响搭配理由生成）
    llm_candidates = []
    for items, score in top_candidates:
        enriched_items = []
        for it in items:
            item_id = it.get("item_id")
            detail = item_details.get(item_id, {})
            enriched_items.append({
                "item_id": item_id,
                "name": detail.get("name"),
                "image": detail.get("image"),
                "price": detail.get("price") or it.get("price"),
                "category": it.get("category"),
                "color": it.get("color"),
                "shop_id": it.get("shop_id"),
                "cross_shop": it.get("cross_shop", False),
                "score": it.get("score"),
                "_wardrobe_picked": it.get("_wardrobe_picked", False),
            })
        llm_candidates.append({"items": enriched_items, "score": round(score, 4)})

    # ----- LLM 搭配决策：从 Top10 选 Top3 + reason -----
    user_intent = {
        "style_tags": state.get("style_tags", []),
        "color": state.get("color"),
        "scene_desc": state.get("scene_desc"),
        "note": state.get("note"),
        "season": state.get("season"),
        # 场景 B：用户视觉特征（节点1 LLM 图像理解输出）
        # 让 LLM 在搭配决策时参考用户性别/肤色/风格倾向
        "user_visual_profile": state.get("user_visual_profile"),
        # 用户身体信息：让 LLM 考虑用户身高/体重/三围
        # 避免 recommend 超出用户身材范围的版型（如瘦小用户推oversized款）
        "user_body_profile": state.get("user_body_profile"),
        # 性别与服装匹配：注入 target_gender 让 LLM 双保险生效
        "target_gender": state.get("target_gender"),
    }
    history_outfits = state.get("history_outfits") or []
    dislike_colors = state.get("user_dislike_colors") or []
    dislike_styles = state.get("user_dislike_styles") or []
    # O3 优化：EpisodicMemory - 跨会话搭配事件传给 LLM
    # 业务价值：LLM 看到"用户上次采纳了黑灰通勤搭配"，本轮可推荐差异化方向或同方向延伸款
    recent_episodes = state.get("recent_episodes") or []

    # ===== 工具拓展：价格平衡 + 流行趋势 + 天气 hint 注入 =====
    # 把工具结果格式化为 LLM 可读文本，作为搭配决策的参考上下文
    extra_hints: list[str] = []

    # 1. 天气 hint（来自节点1 透传的 weather_info）
    if state.get("weather_info"):
        weather_hint = format_weather_hint_for_llm(state["weather_info"])
        if weather_hint:
            extra_hints.append(weather_hint)

    # 2. 价格平衡 hint（本地计算，分析所有候选商品价格分布）
    if settings.price_tool_enabled:
        try:
            all_candidate_items = [
                it for outfit in llm_candidates for it in outfit.get("items", [])
                if it.get("price")
            ]
            if all_candidate_items:
                price_balance = await call_with_check(
                    "price_balance",
                    analyze_price_balance(
                        all_candidate_items,
                        ratio_max=settings.price_balance_ratio_max,
                    ),
                    fallback={"balance_score": 0.5, "suggestion": ""},
                    timeout=1.0,
                )
                price_hint = format_price_hint_for_llm(price_balance)
                if price_hint:
                    extra_hints.append(price_hint)
                    logger.info("[节点3] 价格平衡工具: score=%.2f, ratio=%s",
                                price_balance.get("balance_score", 0),
                                price_balance.get("ratio"))
        except Exception as e:
            logger.warning("[节点3] 价格平衡工具调用失败: %s", e)

    # 3. 时尚潮流 hint（HTTP 调 AnySearch API，社媒+通用搜索）
    # 数据源：social_media.social_media + general.general 两个 tag 并行搜索
    # 根据用户 city/country 路由不同地区的搜索关键词（中国搜小红书、日本搜原宿風等）
    if settings.fashion_trend_tool_enabled:
        try:
            # 从 state 读取用户所在地信息（前端 IP 定位获取，节点1 透传）
            user_city = state.get("user_city", "") or settings.weather_default_city
            user_country = state.get("user_country", "") or ""
            # scene_desc 和 style_tags 用于构造搜索 query
            scene_desc = state.get("scene_desc") or ""
            style_tags_for_trend = list(state.get("style_tags", []))

            fashion_trend_data = await call_with_check(
                "fashion_trend",
                get_fashion_trends(
                    city=user_city,
                    country=user_country,
                    scene=scene_desc,
                    style_tags=style_tags_for_trend,
                    api_key=settings.anysearch_api_key,
                    api_url=settings.anysearch_api_url,
                    proxy_url=settings.proxy_url,
                ),
                fallback={"merged_results": [], "error": "disabled", "data_source": "anysearch_api"},
                timeout=12.0,
            )
            fashion_trend_hint = format_fashion_trend_hint_for_llm(fashion_trend_data)
            if fashion_trend_hint:
                extra_hints.append(fashion_trend_hint)
                logger.info("[节点3] 时尚潮流工具: %s 地区, 合并 %d 条结果",
                            fashion_trend_data.get("region_label", "全球"),
                            fashion_trend_data.get("total", 0))
        except Exception as e:
            logger.warning("[节点3] 时尚潮流工具调用失败: %s", e)

    # 3.1 旧版流行趋势 hint（基于平台销量，默认关闭，保留向后兼容）
    # trend_tool_enabled=False 时跳过；若需启用旧版平台销量趋势，可设 trend_tool_enabled=true
    # 但不建议同时开启 fashion_trend 和 trending_styles（重复 hint 增加 LLM 上下文成本）
    if settings.trend_tool_enabled:
        try:
            java_client = await get_java_client()
            embed_client = await get_embed_client()
            main_category = categories[0] if categories else ""
            trend_data = await call_with_check(
                "trending_styles",
                get_trending_styles(
                    java_client=java_client,
                    embed_client=embed_client,
                    category=main_category,
                    top_k=settings.trend_top_k,
                    cluster_k=settings.trend_cluster_k,
                    days=settings.trend_lookback_days,
                ),
                fallback={"trending_styles": [], "error": "disabled"},
                timeout=10.0,
            )
            trend_hint = format_trend_hint_for_llm(trend_data)
            if trend_hint:
                extra_hints.append(trend_hint)
                logger.info("[节点3] 旧版流行趋势工具: %d 个风格簇",
                            len(trend_data.get("trending_styles", [])))
        except Exception as e:
            logger.warning("[节点3] 旧版流行趋势工具调用失败: %s", e)

    # ===== 季节+性别品类偏好 hint 注入 =====
    # 根据季节和性别引导 LLM 在搭配决策时倾向特定品类
    # 注意：VTON(aitryon-plus) 不支持 prompt 参数，短裤长度无法通过 VTON 控制，
    # 此处通过 LLM 商品选择引导（优先选名称带"短款/热裤"的商品）
    season_gender_hint = _build_season_gender_hint(
        season=state.get("season"),
        target_gender=state.get("target_gender"),
    )
    if season_gender_hint:
        extra_hints.append(season_gender_hint)
        logger.info("[节点3] 季节+性别品类偏好 hint: season=%s, gender=%s",
                     state.get("season"), state.get("target_gender"))

    try:
        llm_client = await get_llm_client()
        selected = await llm_client.select_top_outfits(
            candidates=llm_candidates,
            user_intent=user_intent,
            history_outfits=history_outfits,
            dislike_colors=dislike_colors,
            recent_episodes=recent_episodes,
            extra_hints=extra_hints,  # 工具拓展 hint
            dislike_styles=dislike_styles,
        )
    except Exception as e:
        logger.warning("[节点3] LLM 搭配选择调用失败，降级取前3: %s", e)
        selected = [
            {"outfit_idx": i, "reason": ""}
            for i in range(min(3, len(llm_candidates)))
        ]

    # 补全单品店铺名（来源标签展示）：按候选商品 shopId 批量查店铺名
    # 店铺名接口：social-service GET /merchant/profile/shop-name?userId={shopId}
    # 失败不阻塞主流程（来源标签退化为"全平台/店铺"文本）
    all_shop_ids = set()
    for _o in llm_candidates:
        for _it in _o.get("items", []):
            if _it.get("shop_id") is not None:
                all_shop_ids.add(_it["shop_id"])
    shop_name_map: dict[int, str] = {}
    if all_shop_ids:
        try:
            java_client = await get_java_client()
            for sid in all_shop_ids:
                name = await java_client.get_shop_name(sid)
                if name:
                    shop_name_map[sid] = name
        except Exception as e:
            logger.warning("[节点3] 查询店铺名失败（不影响主流程）: %s", e)
    logger.info("[节点3] 店铺名补全: 候选店铺数=%d, 命中=%d", len(all_shop_ids), len(shop_name_map))

    # 根据 LLM 选择结果构造 outfit_candidates
    outfit_candidates = []
    new_seen = set(seen_item_ids)
    for sel in selected[:3]:
        idx = sel.get("outfit_idx", 0)
        if idx < 0 or idx >= len(llm_candidates):
            logger.warning("[节点3] LLM 选出的 idx=%s 越界，跳过", idx)
            continue
        outfit = llm_candidates[idx]
        # 累积已推荐商品 ID
        for it in outfit["items"]:
            if it.get("item_id") is not None:
                new_seen.add(it["item_id"])
        # 输出字段对齐前端（itemId 而非 item_id，crossShop 而非 cross_shop）
        # 单品来源：衣橱商品 → wardrobe；风格驱动常规商品 → 指定店铺 shop / 全平台 platform
        front_items = []
        for it in outfit["items"]:
            front_items.append({
                "itemId": it.get("item_id"),
                "name": it.get("name"),
                "image": it.get("image"),
                "price": it.get("price"),
                "category": it.get("category"),
                "color": it.get("color"),
                "shopId": it.get("shop_id"),
                "shopName": shop_name_map.get(it.get("shop_id")) or "",
                "crossShop": it.get("cross_shop", False),
                "score": it.get("score"),
                "isWardrobePicked": it.get("_wardrobe_picked", False),
                "source": ("wardrobe" if it.get("_wardrobe_picked")
                           else ("shop" if shop_ids else "platform")),
                # 补全 styleTags 和 itemGender，供 OUTFIT_ACCEPT 事件使用
                "styleTags": it.get("style_tags") or [],
                "itemGender": it.get("target_gender"),
            })
        outfit_candidates.append({
            "items": front_items,
            "score": outfit["score"],
            "reason": sel.get("reason", ""),  # 可解释性
        })

    # 兜底：LLM 全部越界导致 outfit_candidates 为空 → 取前 3 个
    if not outfit_candidates and llm_candidates:
        logger.warning("[节点3] LLM 选择结果全空，降级取前 3 个候选")
        for outfit in llm_candidates[:3]:
            front_items = []
            for it in outfit["items"]:
                if it.get("item_id") is not None:
                    new_seen.add(it["item_id"])
                front_items.append({
                    "itemId": it.get("item_id"),
                    "name": it.get("name"),
                    "image": it.get("image"),
                    "price": it.get("price"),
                    "category": it.get("category"),
                    "color": it.get("color"),
                    "shopId": it.get("shop_id"),
                    "shopName": shop_name_map.get(it.get("shop_id")) or "",
                    "crossShop": it.get("cross_shop", False),
                    "score": it.get("score"),
                    "isWardrobePicked": it.get("_wardrobe_picked", False),
                    "source": ("wardrobe" if it.get("_wardrobe_picked")
                               else ("shop" if shop_ids else "platform")),
                })
            outfit_candidates.append({
                "items": front_items,
                "score": outfit["score"],
                "reason": "",
            })

    logger.info("[节点3] 已生成 %d 套搭配（LLM 决策）, 累积已推荐商品数=%d",
                 len(outfit_candidates), len(new_seen))
    # top_candidates_pool 存 camelCase 版本（与 outfit_candidates 一致），
    # 避免 Reflection 节点替换时再转字段名
    top_candidates_pool = []
    for outfit in llm_candidates:
        pool_items = []
        for it in outfit["items"]:
            pool_items.append({
                "itemId": it.get("item_id"),
                "name": it.get("name"),
                "image": it.get("image"),
                "price": it.get("price"),
                "category": it.get("category"),
                "color": it.get("color"),
                "shopId": it.get("shop_id"),
                "shopName": shop_name_map.get(it.get("shop_id")) or "",
                "crossShop": it.get("cross_shop", False),
                "score": it.get("score"),
                "isWardrobePicked": it.get("_wardrobe_picked", False),
                "source": ("wardrobe" if it.get("_wardrobe_picked")
                           else ("shop" if shop_ids else "platform")),
            })
        top_candidates_pool.append({
            "items": pool_items,
            "score": outfit["score"],
        })
    return {
        "outfit_candidates": outfit_candidates,
        "seen_item_ids": new_seen,
        "top_candidates_pool": top_candidates_pool,  # Top10 候选池（camelCase，与 outfit_candidates 一致）
    }


async def _outfit_combination_product(state: AgentState) -> dict:
    """U1 统一架构：商品驱动模式组合决策（全量对齐风格驱动）

    与风格驱动的差异：
    - 主商品作为搭配的 isMain=true item 加入 items（风格驱动无主商品概念）
    - 跳过 budget_max 过滤（用户已选定主商品，预算约束不适用）
    - seen_item_ids 仅过滤互补商品（主商品 isMain=True 不参与去重）

    多轮反馈支持：
    - keep_categories 非空时，保留品类复用 prev_candidates 的"保留单品"，
      其他品类重新笛卡尔积
    - seen_item_ids 过滤互补商品避免重复推荐（主商品 isMain=True 不受影响）
    - dislike_item_ids 已在节点2 后置过滤，本节点无需重复处理
    - 反馈轮 LLM 决策时传入 history_outfits（历史搭配） + dislike_colors（如有）

    outfit items 顺序：主商品 + 各互补品类候选商品
    """
    candidates_by_cat = state.get("candidate_items_by_category", {})
    task_id = state.get("task_id")
    round_num = state.get("round", 1)
    main_item_info = state.get("_main_item_info") or {}
    categories = state.get("category_constraints") or DEFAULT_CATEGORIES
    seen_item_ids = set(state.get("seen_item_ids") or [])
    keep_categories = state.get("keep_categories") or []
    feedback_parsed = state.get("feedback_parsed")
    is_replace_single = (
        feedback_parsed and feedback_parsed.get("action") == "replace_single"
    )

    logger.info("[节点3-商品驱动] 组合决策: taskId=%s, round=%d, categories=%s, "
                 "candidatesCats=%s, seenItems=%d, keep=%s, replaceSingle=%s",
                 task_id, round_num, categories, list(candidates_by_cat.keys()),
                 len(seen_item_ids), keep_categories, is_replace_single)

    # 主商品作为 isMain=true 的第一件 item
    main_item_id = main_item_info.get("id")
    try:
        main_item_id_int = int(main_item_id) if main_item_id is not None else None
    except (TypeError, ValueError):
        main_item_id_int = None
    main_category_cn = to_cn(main_item_info.get("category"))

    main_item_dict = {
        "itemId": main_item_id_int,
        "name": main_item_info.get("name"),
        "image": main_item_info.get("image"),
        "price": main_item_info.get("price"),
        "category": main_category_cn,
        "color": main_item_info.get("color"),
        "shopId": main_item_info.get("creater"),
        "crossShop": False,
        "score": 1.0,
        "isMain": True,  # 商品驱动主商品标记
    }

    # 收集各品类 Top5 候选商品，构造笛卡尔积（与风格驱动一致）
    # 反馈轮 keep_categories 中的"保留单品"（_kept_from_prev=True）作为该品类唯一候选
    cat_lists: list[list[dict]] = []
    for cat in categories:
        candidates = candidates_by_cat.get(cat) or []
        if not candidates:
            logger.info("[节点3-商品驱动] 品类 %s 无候选商品，跳过", cat)
            continue
        # 取 Top5 候选（与风格驱动一致）
        top5 = candidates[:5]
        cat_list = []
        for c in top5:
            try:
                cid = int(c.get("item_id")) if c.get("item_id") is not None else None
            except (TypeError, ValueError):
                cid = None
            cat_list.append({
                "itemId": cid,
                "name": None,
                "image": None,
                "price": c.get("price"),
                "category": cat,
                "color": c.get("color"),
                "shopId": c.get("shop_id"),
                "crossShop": c.get("cross_shop", False),
                "score": c.get("score", 0.0),
                "isMain": False,
                "_kept_from_prev": bool(c.get("_kept_from_prev")),
            })
        cat_lists.append(cat_list)

    # 笛卡尔积组合（与风格驱动一致）
    if not cat_lists:
        # 无互补候选，只返回主商品 1 套
        logger.warning("[节点3-商品驱动] 无任何互补候选，仅返回主商品 1 套: taskId=%s", task_id)
        return {
            "outfit_candidates": [{"items": [main_item_dict], "score": 1.0,
                                    "reason": "暂无互补商品可搭配"}],
            "seen_item_ids": set(),
            "top_candidates_pool": [],
        }

    # 限制组合数上限（与风格驱动一致，上限 15）
    combos = list(itertools.product(*cat_lists))[:15]
    logger.info("[节点3-商品驱动] 笛卡尔积组合数: %d", len(combos))

    # 构造候选搭配（主商品 + 各品类候选）
    all_candidates = []
    for combo in combos:
        items = [main_item_dict] + list(combo)
        # 综合分 = 平均相似度（主商品 score=1.0 拉高均分）
        scores = [it.get("score", 0.0) for it in items]
        avg_score = sum(scores) / len(scores) if scores else 0
        all_candidates.append({
            "items": items,
            "score": round(avg_score, 4),
            "reason": "基于您选的商品搭配的互补单品",
        })

    # 反馈轮 seen_item_ids 过滤（仅过滤互补商品，主商品 isMain=True 不参与去重）
    # 点哪换哪场景放宽：保留品类（_kept_from_prev=True）的商品视为"已选定"，
    # 只需待替换品类有新商品即可
    if seen_item_ids and round_num > 1:
        fresh_candidates = []
        for cand in all_candidates:
            # 仅检查非主商品且非保留单品是否在 seen_item_ids 中
            new_comp_ids = {
                it.get("itemId") for it in cand["items"]
                if it.get("itemId") is not None
                and not it.get("isMain")
                and not it.get("_kept_from_prev")
            }
            if not new_comp_ids:
                # 无新互补商品 → 永远保留（不应被去重）
                fresh_candidates.append(cand)
                continue
            if is_replace_single:
                # 点哪换哪：只要有 1 件新互补商品即可
                if not new_comp_ids.issubset(seen_item_ids):
                    fresh_candidates.append(cand)
            else:
                # 标准模式：组合中至少有一个新互补商品才保留
                if not new_comp_ids.issubset(seen_item_ids):
                    fresh_candidates.append(cand)
        if fresh_candidates:
            all_candidates = fresh_candidates
            logger.info("[节点3-商品驱动][反馈轮] seen_item_ids 过滤后剩余 %d 套",
                         len(all_candidates))
        else:
            logger.warning("[节点3-商品驱动][反馈轮] 所有组合均已推荐过，降级为不去重")

    # 批量补全所有候选的商品详情（name/image/price）
    all_comp_ids = set()
    for cand in all_candidates:
        for it in cand["items"]:
            if it.get("isMain") or it.get("itemId") is None:
                continue
            all_comp_ids.add(it["itemId"])
    if all_comp_ids:
        try:
            java_client = await get_java_client()
            details_list = await java_client.get_items_by_ids(list(all_comp_ids))
            details_map = {int(d["id"]): d for d in details_list if d and d.get("id")}
            for cand in all_candidates:
                for it in cand["items"]:
                    if it.get("isMain") or it.get("itemId") is None:
                        continue
                    d = details_map.get(it["itemId"], {})
                    if d:
                        it["name"] = d.get("name")
                        it["image"] = d.get("image")
                        it["price"] = d.get("price") or it.get("price")
        except Exception as e:
            logger.warning("[节点3-商品驱动] 互补商品详情查询失败: %s", e)

    # LLM Top3 决策（与风格驱动一致）
    # 输入 Top10 候选 + 主商品信息，LLM 选出最优 3 套并给理由
    # 反馈轮传入 history_outfits / dislike_colors 让 LLM 避开历史方向
    top10 = all_candidates[:10]
    try:
        llm_client = await get_llm_client()
        user_intent = {
            "main_item": {
                "name": main_item_info.get("name"),
                "category": main_category_cn,
                "color": main_item_info.get("color"),
            },
            # 反馈轮传入用户视觉特征（与风格驱动一致）
            "user_visual_profile": state.get("user_visual_profile"),
            # 用户身体信息：商品驱动也考虑用户身材
            "user_body_profile": state.get("user_body_profile"),
            # 性别与服装匹配：注入 target_gender 让 LLM 双保险生效
            "target_gender": state.get("target_gender"),
        }
        top3_with_reason = await llm_client.select_top_outfits(
            candidates=top10,
            user_intent=user_intent,
            history_outfits=state.get("history_outfits") or [],
            dislike_colors=state.get("user_dislike_colors") or [],
            recent_episodes=state.get("recent_episodes") or [],
            dislike_styles=state.get("user_dislike_styles") or [],
        )
        if top3_with_reason and len(top3_with_reason) > 0:
            # 按 LLM 返回的 idx 取对应候选
            outfit_candidates = []
            for sel in top3_with_reason:
                idx = sel.get("outfit_idx")
                if idx is None or idx >= len(top10):
                    continue
                cand = top10[idx]
                cand["reason"] = sel.get("reason") or cand.get("reason")
                outfit_candidates.append(cand)
            # LLM 返回不足 3 套时用原 Top3 补
            while len(outfit_candidates) < 3 and len(outfit_candidates) < len(top10):
                outfit_candidates.append(top10[len(outfit_candidates)])
        else:
            outfit_candidates = top10[:3]
    except Exception as e:
        logger.warning("[节点3-商品驱动] LLM Top3 决策失败，降级取前 3 套: %s", e)
        outfit_candidates = top10[:3]

    logger.info("[节点3-商品驱动] 已生成 %d 套搭配: taskId=%s",
                 len(outfit_candidates), task_id)

    # 累积本轮推荐的新互补商品 ID 到 seen_item_ids（主商品 isMain=True 不加入）
    new_seen = set(seen_item_ids)
    for cand in outfit_candidates:
        for it in cand.get("items", []):
            iid = it.get("itemId")
            if iid is not None and not it.get("isMain"):
                new_seen.add(iid)

    return {
        "outfit_candidates": outfit_candidates,
        # 保留 Top10 候选池供 Reflection 替换
        "top_candidates_pool": [
            {
                "items": [{"itemId": it["itemId"], "name": it.get("name"),
                            "image": it.get("image"), "price": it.get("price"),
                            "category": it.get("category"), "color": it.get("color"),
                            "shopId": it.get("shopId"), "crossShop": it.get("crossShop"),
                            "score": it.get("score"), "isMain": it.get("isMain")}
                           for it in cand["items"]],
                "score": cand["score"],
                "reason": cand.get("reason"),
            }
            for cand in top10
        ],
        "seen_item_ids": new_seen,
    }


# ============================================================
# 节点3.5：Reflection 自检
# ============================================================
@_trace_node("reflection")
async def reflection_check(state: AgentState) -> dict:
    """对节点3 输出的 3 套搭配做质检：颜色协调性/风格一致性/季节匹配

    自检策略（§3.13 ㉚-㉛）：
    - LLM 自检 3 项维度，输出每套 pass/fail + issues
    - 不合格的搭配从 top_candidates_pool 重新选（避开不合格方向）
    - 最多 1 次修正机会；修正失败 → 保留原结果（不阻塞主流程）

    商品驱动模式（mode="product"）也接入 Reflection 自检，
    替换的是互补商品（主商品 isMain=True 不替换）。

    Returns:
        更新 outfit_candidates（可能不变，也可能部分替换）
    """
    # 商品驱动模式不再跳过 Reflection
    # 生成 3 套候选，Reflection 有对比意义，且替换时跳过 isMain 商品。

    outfit_candidates = state.get("outfit_candidates") or []
    top_pool = state.get("top_candidates_pool") or []
    task_id = state.get("task_id")
    season = state.get("season")

    # 无候选或无候选池 → 跳过自检
    if not outfit_candidates:
        return {}
    if not top_pool:
        logger.info("[节点3.5] 无 top_candidates_pool，跳过 Reflection", )
        return {}

    user_intent = {
        "style_tags": state.get("style_tags", []),
        "color": state.get("color"),
        "scene_desc": state.get("scene_desc"),
        "note": state.get("note"),
    }

    try:
        llm_client = await get_llm_client()
        results = await llm_client.reflect_outfits(
            outfits=outfit_candidates,
            user_intent=user_intent,
            season=season,
        )
    except Exception as e:
        logger.warning("[节点3.5] Reflection 调用失败（不阻塞）: %s", e)
        return {}

    # 找出不合格的搭配索引
    failed_indices = [r["outfit_idx"] for r in results if not r.get("pass")]
    if not failed_indices:
        logger.info("[节点3.5] Reflection 自检全部通过: taskId=%s", task_id)
        return {}

    logger.info("[节点3.5] Reflection 自检不合格: taskId=%s, failedIdx=%s, issues=%s, suggestedFix=%s",
                 task_id, failed_indices,
                 {r["outfit_idx"]: r.get("issues") for r in results if not r.get("pass")},
                 {r["outfit_idx"]: r.get("suggested_fix", "")[:80] for r in results if not r.get("pass")})

    # ===== 搭配决策子 Agent（场景 1）=====
    # LLM 决策作为默认主路径：始终尝试 LLM 决策，
    # 仅在 LLM 异常或返回 None 时降级到分数排序兜底。
    try:
        agent_result = await _run_decision_agent(
            state=state,
            outfit_candidates=outfit_candidates,
            reflection_results=results,
            failed_indices=failed_indices,
        )
        if agent_result is not None:
            return agent_result
        logger.warning("[节点3.5] 决策子 Agent 返回 None，降级走原 pool 替换: taskId=%s", task_id)
    except Exception as e:
        logger.warning("[节点3.5] 决策子 Agent 异常，降级走原 pool 替换: taskId=%s, error=%s",
                        task_id, e)

    # ----- 修正：从 top_candidates_pool 重新选 -----
    # 策略：把不合格搭配的 reason 喂给 LLM，让它从 pool 中重新选
    # 简化：直接从 pool 中按分数排序，选未在当前 outfit_candidates 中出现的候选替换
    # pool 已是 camelCase，无需再转字段名
    current_item_ids = {
        it.get("itemId")
        for outfit in outfit_candidates
        for it in outfit.get("items", [])
        if it.get("itemId") is not None
    }

    # 从 pool 中找未使用的候选（按 score 降序）
    # 商品驱动模式保留主商品（isMain=True），只替换互补商品
    is_product_mode = state.get("mode") == "product"
    unused_pool = [
        c for c in top_pool
        if not any(
            it.get("itemId") in current_item_ids
            for it in c.get("items", [])
            if it.get("itemId") is not None
        )
    ]
    # pool 中的 score 字段已是数值
    unused_pool.sort(key=lambda x: x.get("score", 0), reverse=True)

    if not unused_pool:
        logger.warning("[节点3.5] 无可替换候选（pool 已用尽），保留原结果: taskId=%s", task_id)
        return {}

    # 替换不合格的搭配（按 unused_pool 顺序填）
    # pool 中的 items 已是 camelCase 格式，直接使用
    new_outfits = list(outfit_candidates)
    replaced = 0
    pool_iter = iter(unused_pool)
    for idx in failed_indices:
        try:
            replacement = next(pool_iter)
        except StopIteration:
            logger.warning("[节点3.5] 候选池不足以替换所有不合格搭配，剩余保留原结果", )
            break
        if is_product_mode:
            # 商品驱动模式保留主商品（isMain=True），只替换互补商品
            old_main = next((it for it in new_outfits[idx].get("items", [])
                              if it.get("isMain")), None)
            new_items = [it for it in replacement.get("items", [])
                         if not it.get("isMain")]
            if old_main:
                new_items = [old_main] + new_items
            new_outfits[idx] = {
                "items": new_items,
                "score": replacement.get("score", 0),
                "reason": replacement.get("reason") or "Reflection 替换后的搭配",
            }
        else:
            new_outfits[idx] = {
                "items": replacement.get("items", []),
            "score": replacement.get("score", 0),
            "reason": f"Reflection 修正：原搭配质检不合格已替换",
        }
        replaced += 1

    logger.info("[节点3.5] Reflection 修正完成: taskId=%s, replaced=%d/%d",
                 task_id, replaced, len(failed_indices))
    return {"outfit_candidates": new_outfits}


# ============================================================
# 节点4：换装图生成（B5 全件换装）
# ============================================================
# PIL 多件合成函数和区域映射已下沉到 shared.outfit_common（与 ai-models 共用）
# 节点4 调用 compose_full_outfit_image(..., log_prefix="[节点4]") 即可


async def _download_image(url: str) -> bytes | None:
    """下载图片（复用 _retry_async 增加重试机制）

    最多 3 次重试（指数退避 1/2/4s），重试耗尽才返回 None。
    """
    if not url:
        return None
    # 相对路径 → 拼接 nginx_external_base_url（Java 返回的模特图/商品图可能是相对路径）
    if url.startswith("/"):
        base = settings.nginx_external_base_url.rstrip("/")
        url = f"{base}{url}"
    # SSRF 防护：拦截非法协议和元数据地址
    if not is_safe_image_url(url):
        logger.warning("SSRF 拦截: 非法图片 URL 已拒绝: %s", url[:120])
        return None

    async def _once():
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                return resp.content
            # 非 200 抛异常触发重试（4xx 也重试，避免临时 429/403 误降级）
            raise httpx.HTTPStatusError(
                f"status={resp.status_code}", request=resp.request, response=resp
            )

    try:
        return await _retry_async(_once, retries=3, backoff=[1, 2, 4])
    except Exception as e:
        logger.warning("图片下载重试耗尽: url=%s, error=%s", url, e)
        return None


# VTON 支持的品类（千问 aitryon-plus 仅支持服装类虚拟换装）
# 2026-08-06 调整：鞋/帽子从 VTON 移出（aitryon-plus 仅支持衣物换装，
# top_garment_url 是"上装"语义，把鞋/帽子塞进去接口虽返回成功但生成图中不含该单品）
# → 改走 wan2.7-image 图生图穿戴；下装（裤子/裙子）原生支持 bottom_garment_url，保留 VTON
VTON_CATEGORIES = ["上衣", "下装", "全身套装"]
# wan2.7-image 穿戴的品类（VTON 不支持配饰/包/鞋/帽子的虚拟穿戴，直接走 wan2.7-image 节省 VTON credits）
WAN_ACCESSORY_CATEGORIES = ["鞋", "包", "帽子", "配饰"]


async def _get_prev_vton_bytes_for_items(
    history_outfits: list,
    retry_item_ids: set[int],
    task_id: str,
) -> bytes | None:
    """从历史搭配中找出包含 retry_vton 商品的 outfit，下载其 VTON 效果图

    用于 retry_vton 场景：商品 OK 但 VTON 效果差，需要获取上一轮效果图做二次精修。

    Args:
        history_outfits: 历史搭配列表（最后一个元素为上一轮 outfit_candidates）
        retry_item_ids: 需要重新换装的商品 ID 集合
        task_id: 任务ID（日志用）
    Returns:
        上一轮 VTON 效果图二进制，找不到或下载失败返回 None
    """
    if not history_outfits or not retry_item_ids:
        return None

    # history_outfits 最后一个元素是上一轮的 outfit_candidates
    prev_outfits = history_outfits[-1] if history_outfits else []
    if not isinstance(prev_outfits, list):
        return None

    # 找出包含 retry_vton 商品的 outfit
    for outfit in prev_outfits:
        if not isinstance(outfit, dict):
            continue
        items = outfit.get("items", [])
        outfit_item_ids = {
            it.get("itemId") or it.get("item_id")
            for it in items if isinstance(it, dict)
        }
        if outfit_item_ids & retry_item_ids:
            # 找到包含 retry_vton 商品的 outfit，下载其 resultUrl
            result_url = outfit.get("resultUrl")
            if not result_url or result_url.startswith("data:"):
                # base64 内联图或无 URL，跳过
                logger.warning("[节点4-retryVTON] 上一轮 resultUrl 不可下载: taskId=%s", task_id)
                return None
            logger.info("[节点4-retryVTON] 找到上一轮效果图，下载用于精修: taskId=%s, url=%s",
                        task_id, str(result_url)[:80])
            return await _download_image(result_url)

    logger.info("[节点4-retryVTON] 历史搭配中未找到包含 retry_vton 商品的 outfit: taskId=%s", task_id)
    return None


async def _refine_outfit_with_prev_vton(
    new_vton_bytes: bytes | None,
    prev_vton_bytes: bytes | None,
    outfit_items: list[dict],
    user_photo: bytes,
    gender: str,
    task_id: str,
    idx: int,
) -> bytes | None:
    """retry_vton 场景：对 outfit 尝试用 refiner 二次精修提升还原度

    优先级：
    1. prev_vton_bytes 可得 → 调用 refine_vton_result 精修 prev_vton_bytes
    2. 精修失败 → 用 new_vton_bytes（重新 VTON 的结果）
    3. new_vton_bytes 也失败 → 用 prev_vton_bytes（虽然效果差但总比 None 好）

    Args:
        new_vton_bytes: 重新 VTON 生成的效果图（可能为 None）
        prev_vton_bytes: 上一轮的 VTON 效果图（用于精修输入）
        outfit_items: 搭配单品列表（refiner 提取 top/bottom garment）
        user_photo: 原始用户照片
        gender: 模特性别
        task_id: 任务ID
        idx: 搭配索引（日志用）
    Returns:
        精修后的效果图二进制，全部失败返回 None
    """
    if prev_vton_bytes:
        refined = await refine_vton_result(
            user_photo=user_photo,
            prev_vton_bytes=prev_vton_bytes,
            outfit_items=outfit_items,
            gender=gender,
            task_id=task_id,
        )
        if refined is not None:
            logger.info("[节点4-retryVTON] 第%d套精修成功，用精修结果替换", idx + 1)
            return refined
        logger.warning("[节点4-retryVTON] 第%d套精修失败，降级用重新 VTON 结果", idx + 1)

    # 精修失败或无 prev_vton_bytes → 用重新 VTON 的结果
    if new_vton_bytes is not None:
        return new_vton_bytes

    # 重新 VTON 也失败 → 用上一轮结果兜底（虽然效果差但总比 None 好）
    if prev_vton_bytes:
        logger.warning("[节点4-retryVTON] 第%d套重新 VTON 也失败，用上一轮效果图兜底", idx + 1)
        return prev_vton_bytes

    return None


async def _generate_single_outfit(
    idx: int,
    outfit: dict,
    user_photo: bytes,
    vton_client,
) -> bytes | None:
    """单套搭配的全身换装生成（链式VTON + wan2.7-image 配饰穿戴）

    策略（千问 aitryon-plus 不支持配饰/包类）：
    1. 按品类分组，配饰/包类走 wan2.7-image，其余走 VTON
       - VTON 顺序：上衣→下装→全身套装→帽→鞋
       - wan2.7-image：包、配饰（VTON 后链式穿戴）
       - 全身套装特殊处理：
         · 仅有全身套装（无上衣/下装）：全身套装一次 VTON 完成全身换装（等价于上衣+下装）
         · 同时有上衣+全身套装：先上衣 → 再全身套装（全身套装覆盖上衣，符合"连衣裙套在上衣外"的搭配）
         · 同时有下装+全身套装：先下装 → 再全身套装（全身套装覆盖下装）
         · 同时有上衣+下装+全身套装：按顺序上衣→下装→全身套装（全身套装覆盖前两者）
    2. 依次链式调用VTON，每次用上一步结果作为新人图
       - 单件失败不中断，用上一步结果继续
    3. VTON 完成后，对包/配饰依次调用 wan2.7-image 穿戴（单件失败不中断）
    4. 链式VTON全部失败 → 降级用首件商品图作为 base（PIL 兜底，含包/配饰）

    全身套装说明：
    - "全身套装" = 连衣裙/旗袍等连体款（一次 VTON 覆盖全身）
    - 半身裙归为"下装"，走下装逻辑
    """
    items = outfit.get("items", [])

    # 按品类分组（VTON 品类 + wan2.7-image 品类分开）
    vton_grouped: dict[str, list] = {cat: [] for cat in VTON_CATEGORIES}
    accessory_items: list[dict] = []  # 下装/鞋/包/配饰 → wan2.7-image
    for it in items:
        cat = it.get("category")
        if cat in vton_grouped:
            vton_grouped[cat].append(it)
        elif cat in WAN_ACCESSORY_CATEGORIES:
            accessory_items.append(it)

    has_dress = bool(vton_grouped["全身套装"])
    has_top_or_bottom = bool(vton_grouped["上衣"]) or bool(vton_grouped["下装"])

    if has_dress and not has_top_or_bottom:
        # 仅有全身套装（无上衣/下装）：全身套装一次 VTON 完成全身换装
        # （鞋/帽子/包/配饰走 wan2.7-image，不在此列）
        ordered_items = [vton_grouped["全身套装"][0]]
    else:
        # 通用顺序：上衣→下装→全身套装（鞋/帽子/包/配饰走 wan2.7-image 穿戴）
        # 同时有上衣+全身套装时，先上衣→再全身套装，让全身套装（连衣裙/旗袍）覆盖上衣
        ordered_items = []
        for cat in VTON_CATEGORIES:
            if vton_grouped[cat]:
                ordered_items.append(vton_grouped[cat][0])

    if not ordered_items:
        # 无 VTON 品类（如仅下装+鞋）：直接用用户照片作 base 走 wan2.7-image 穿戴
        if accessory_items:
            result = await _wear_accessories_chain(user_photo, accessory_items, idx)
            return result
        return None

    # 下载 VTON 商品图（并行）
    download_tasks = [_download_image(it.get("image")) for it in ordered_items]
    downloaded = await asyncio.gather(*download_tasks, return_exceptions=False)

    garment_bytes_list: list[bytes] = []
    garment_categories: list[str] = []
    for it, b in zip(ordered_items, downloaded):
        if b is not None:
            garment_bytes_list.append(b)
            garment_categories.append(it.get("category"))
        else:
            logger.warning("[节点4] 第%d套 商品图下载失败: category=%s, image=%s",
                           idx + 1, it.get("category"), str(it.get("image"))[:80])

    if not garment_bytes_list:
        logger.warning("[节点4] 第%d套 所有商品图下载失败，跳过换装", idx + 1)
        return None

    # 链式VTON调用（仅服装类：上衣/下装/全身套装；鞋/帽子/包/配饰走 wan2.7-image）
    # 传入 categories 供 vton_client 智能分流（向后兼容，下装已不走此通道）
    result = await vton_client.try_on_chain(
        user_photo, garment_bytes_list, categories=garment_categories)

    if result is not None:
        logger.info("[节点4] 第%d套链式VTON成功: 件数=%d, bytes=%d",
                     idx + 1, len(garment_bytes_list), len(result))
        # VTON 成功后，对包/配饰调用 wan2.7-image 穿戴
        if accessory_items:
            result = await _wear_accessories_chain(result, accessory_items, idx)
        return result

    # 链式VTON全部失败 → 降级：用户照片作为 base + 其余PIL贴图（含包/配饰）
    # H7 修复：PIL 贴图区域（AUX_CATEGORY_REGION）按人体部位设计，
    # 必须用人物照片作为 base；用商品图作为 base 会导致下装/鞋/帽子贴在商品图上错位
    logger.warning("[节点4] 第%d套链式VTON失败，降级PIL贴图（base=user_photo）", idx + 1)
    base_image = user_photo
    aux_items = []
    for it, b in zip(ordered_items, garment_bytes_list):
        cat = it.get("category")
        if cat in AUX_CATEGORY_REGION:
            aux_items.append({"category": cat, "image_bytes": b})
    # 包/配饰也加入 PIL 贴图（VTON 失败时最后兜底）
    for it in accessory_items:
        cat = it.get("category")
        if cat in AUX_CATEGORY_REGION:
            img_bytes = await _download_image(it.get("image"))
            if img_bytes is not None:
                aux_items.append({"category": cat, "image_bytes": img_bytes})

    if aux_items:
        composed = await asyncio.to_thread(
            compose_full_outfit_image, base_image, aux_items, "[节点4]",
        )
        if composed is not None:
            logger.info("[节点4] 第%d套PIL降级合成成功: aux=%d",
                         idx + 1, len(aux_items))
            return composed

    return base_image


async def _wear_accessories_chain(
    base_image: bytes,
    accessory_items: list[dict],
    idx: int,
) -> bytes:
    """对鞋/包/配饰依次调用 wan2.7-image 虚拟穿戴（链式，单件失败不中断）

    VTON（aitryon-plus）不支持配饰/包/鞋类虚拟穿戴，统一用 wan2.7-image 图生图实现。
    每件穿戴结果作为下一件的输入，形成链式穿戴。

    穿戴顺序：鞋 → 包 → 配饰（先穿鞋，再包，最后配饰点缀）

    Args:
        base_image: VTON 输出的人物图（已穿上服装）
        accessory_items: 鞋/包/配饰 商品列表
        idx: 搭配索引（日志用）
    Returns:
        穿戴后的人物图；wan2.7-image 失败时返回原 base_image（不阻塞主流程）
    """
    if not accessory_items:
        return base_image

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
        img_url = it.get("image")
        if not img_url:
            continue

        accessory_bytes = await _download_image(img_url)
        if accessory_bytes is None:
            logger.warning("[节点4] 第%d套 单品图下载失败: category=%s", idx + 1, cat)
            continue

        worn = await gen_client.wear_accessory(current_image, accessory_bytes, cat)
        if worn is not None:
            current_image = worn
            success_count += 1
            logger.info("[节点4] 第%d套 wan2.7-image 穿戴成功: category=%s",
                         idx + 1, cat)
        else:
            logger.warning("[节点4] 第%d套 wan2.7-image 穿戴失败，跳过: category=%s",
                            idx + 1, cat)

    logger.info("[节点4] 第%d套单品穿戴完成: 总数=%d, 成功=%d",
                 idx + 1, len(accessory_items), success_count)
    return current_image


async def _vton_generation_product(
    state: AgentState, outfit: dict, user_photo: bytes, task_id: str,
) -> dict:
    """U1 统一架构：商品驱动模式换装生成（链式VTON + wan2.7-image 配饰穿戴）

    流程（千问 aitryon-plus 不支持配饰/包类）：
    1. 主商品图复用 state._main_item_bytes（节点1 已下载，避免重复下载）
    2. 用户照片为空 → 跳过 VTON，直接用主商品图作为 base
    3. 用户照片非空 → 按品类顺序链式 VTON（主商品 + 互补商品，仅服装类）
       - 包/配饰不走 VTON，VTON 后用 wan2.7-image 穿戴
       - 链式全部失败 → 降级用主商品图作为 base + PIL 贴图
    """
    main_item_bytes = state.get("_main_item_bytes")
    if main_item_bytes is None:
        logger.error("[节点4-商品驱动] _main_item_bytes 缺失: taskId=%s", task_id)
        return {"generated_images": [None]}

    vton_client = await get_vton_client()

    # 1. 用户照片为空 → 跳过 VTON 直接用主商品图
    # H7 修复：无用户照片时不能走 PIL 贴图（AUX_CATEGORY_REGION 按人体部位设计，
    # 贴在商品图上会错位），直接返回主商品图
    if not user_photo:
        logger.info("[节点4-商品驱动] 用户照片为空，跳过 VTON 直接用主商品图: taskId=%s", task_id)
        return {"generated_images": [main_item_bytes]}
    else:
        # 2. 按品类顺序链式 VTON（主商品 + 互补商品，仅服装类）
        items = outfit.get("items", [])
        vton_grouped: dict[str, list] = {cat: [] for cat in VTON_CATEGORIES}
        accessory_items: list[dict] = []  # 下装/鞋/包/配饰 → wan2.7-image
        for it in items:
            cat = it.get("category")
            if cat in vton_grouped:
                vton_grouped[cat].append(it)
            elif cat in WAN_ACCESSORY_CATEGORIES:
                accessory_items.append(it)

        # 确定链式调用顺序（主商品在前，互补商品按品类顺序追加）
        # 全身套装特殊处理：
        # - 仅有全身套装（无上衣/下装）：全身套装一次 VTON 完成全身换装
        # - 同时有上衣+全身套装：先上衣 → 再全身套装（全身套装覆盖上衣，符合"连衣裙套在上衣外"的搭配）
        has_dress = bool(vton_grouped["全身套装"])
        has_top_or_bottom = bool(vton_grouped["上衣"]) or bool(vton_grouped["下装"])

        if has_dress and not has_top_or_bottom:
            # 仅有全身套装（无上衣/下装）：全身套装一次 VTON 完成全身换装
            # （鞋/帽子/包/配饰走 wan2.7-image，不在此列）
            ordered_items = [vton_grouped["全身套装"][0]]
        else:
            ordered_items = []
            for cat in VTON_CATEGORIES:
                if vton_grouped[cat]:
                    ordered_items.append(vton_grouped[cat][0])

        if not ordered_items:
            # 无 VTON 品类（如主商品为下装/鞋/包/配饰且无服装类互补）
            # 有用户照片 → 直接用照片作 base 走 wan2.7-image 穿戴
            if accessory_items:
                logger.info("[节点4-商品驱动] 无 VTON 品类，直接用用户照片走 wan2.7-image 穿戴: taskId=%s",
                            task_id)
                result = await _wear_accessories_chain(user_photo, accessory_items, 0)
                if result is not None:
                    return {"generated_images": [result]}
            base_image = main_item_bytes
        else:
            # 下载互补商品图（主商品图已下载，跳过 isMain）
            # 构建 garment_bytes_list + garment_categories（主商品在前，互补商品按品类顺序追加）
            main_item_info = state.get("_main_item_info") or {}
            main_cat = main_item_info.get("category")
            # 主商品若为 wan2.7 品类（下装/鞋/包/配饰），不进 VTON 链（已在 accessory_items 分组）
            if main_cat in WAN_ACCESSORY_CATEGORIES:
                garment_bytes_list: list[bytes] = []
                garment_categories: list[str] = []
            else:
                garment_bytes_list = [main_item_bytes]  # 主商品图已在列表首位
                garment_categories = [main_cat]  # 主商品品类
            for it in ordered_items:
                if it.get("isMain"):
                    continue  # 主商品已加入（或走 accessory 分支）
                img_url = it.get("image")
                if img_url:
                    img_bytes = await _download_image(img_url)
                    if img_bytes is not None:
                        garment_bytes_list.append(img_bytes)
                        garment_categories.append(it.get("category"))

            # 链式VTON调用（仅服装类：上衣/下装/全身套装；鞋/帽子/包/配饰走 wan2.7-image）
            # 传入 categories 供 vton_client 智能分流（向后兼容，下装已不走此通道）
            result = await vton_client.try_on_chain(
                user_photo, garment_bytes_list, categories=garment_categories)
            if result is not None:
                logger.info("[节点4-商品驱动] 链式VTON成功: taskId=%s, 件数=%d, bytes=%d",
                             task_id, len(garment_bytes_list), len(result))
                # VTON 成功后，对包/配饰调用 wan2.7-image 穿戴
                if accessory_items:
                    result = await _wear_accessories_chain(result, accessory_items, 0)
                return {"generated_images": [result]}

            # 链式VTON失败 → 降级用用户照片作为 base + PIL 贴图
            # H7 修复：PIL 贴图区域按人体部位设计，必须用人物照片作为 base，避免错位
            logger.warning("[节点4-商品驱动] 链式VTON失败，降级PIL贴图（base=user_photo）: taskId=%s", task_id)
            base_image = user_photo

    # 3. 降级：PIL 贴图合成（互补商品，含包/配饰）
    items = outfit.get("items", [])
    aux_items: list[dict] = []
    for it in items:
        if it.get("isMain"):
            continue
        category = it.get("category")
        if category in AUX_CATEGORY_REGION:
            img_url = it.get("image")
            if img_url:
                aux_items.append({"category": category, "image_url": img_url})

    if aux_items:
        aux_download_tasks = [_download_image(a["image_url"]) for a in aux_items]
        aux_bytes_list = await asyncio.gather(*aux_download_tasks, return_exceptions=False)
        aux_ready = []
        for a, b in zip(aux_items, aux_bytes_list):
            if b is not None:
                aux_ready.append({"category": a["category"], "image_bytes": b})

        if aux_ready:
            composed = await asyncio.to_thread(
                compose_full_outfit_image, base_image, aux_ready, "[节点4-商品驱动]",
            )
            if composed is not None:
                logger.info("[节点4-商品驱动] PIL降级合成成功: aux=%d, bytes=%d",
                             len(aux_ready), len(composed))
                return {"generated_images": [composed]}
            logger.warning("[节点4-商品驱动] PIL 合成失败，仅用 base 图")

    return {"generated_images": [base_image]}


async def refine_vton_result(
    user_photo: bytes,
    prev_vton_bytes: bytes,
    outfit_items: list[dict],
    gender: str = "woman",
    task_id: str = "",
) -> bytes | None:
    """VTON 结果精修（千问 aitryon-refiner）

    业务场景（设计文档 §3.19）：用户对 VTON 整体效果不满意但喜欢那套衣服单品时，
    用 person_image + coarse_image + 服饰图做二次精修，提升还原度。

    Args:
        user_photo: 原始用户照片（与 VTON 输入同一张，refiner 必需）
        prev_vton_bytes: 上一轮 VTON 生成的效果图（作为 coarse_image）
        outfit_items: 搭配单品列表，用于提取 top_garment / bottom_garment 图
        gender: 模特性别（woman | man，refiner 必填）
        task_id: 任务ID（日志用）
    Returns:
        精修后的效果图二进制，失败返回 None（调用方降级用原 VTON 图）
    """
    _refine_start = time.monotonic()
    from app.api.deps import get_refiner_client

    if not user_photo or not prev_vton_bytes:
        logger.warning("[精修] 输入参数为空，跳过: taskId=%s", task_id)
        return None

    if not settings.qwen_refiner_enabled:
        logger.info("[精修] qwen_refiner_enabled=False，跳过精修: taskId=%s", task_id)
        return None

    # 从 outfit_items 提取上装/下装图（按品类优先级）
    # 全身套装优先作为 top_garment（refiner 的 top_garment 接受连衣裙/套装）
    top_item = None
    bottom_item = None
    for it in outfit_items:
        cat = it.get("category")
        if cat in ("上衣", "全身套装") and top_item is None:
            top_item = it
        elif cat == "下装" and bottom_item is None:
            bottom_item = it

    if top_item is None and bottom_item is None:
        logger.warning("[精修] outfit_items 无上装/下装/套装，跳过: taskId=%s", task_id)
        return None

    # 下载服饰图
    top_bytes: bytes | None = None
    bottom_bytes: bytes | None = None
    if top_item:
        top_url = top_item.get("image") or top_item.get("imageUrl")
        if top_url:
            top_bytes = await _download_image(top_url)
            if top_bytes is None:
                logger.warning("[精修] 上装图下载失败: taskId=%s, url=%s",
                               task_id, str(top_url)[:80])
    if bottom_item:
        bottom_url = bottom_item.get("image") or bottom_item.get("imageUrl")
        if bottom_url:
            bottom_bytes = await _download_image(bottom_url)
            if bottom_bytes is None:
                logger.warning("[精修] 下装图下载失败: taskId=%s, url=%s",
                               task_id, str(bottom_url)[:80])

    if top_bytes is None and bottom_bytes is None:
        logger.warning("[精修] 服饰图全部下载失败，跳过: taskId=%s", task_id)
        return None

    # gender 规范化（refiner 只接受 woman | man）
    if gender in ("male", "man", "男", "男性"):
        gender = "man"
    elif gender in ("female", "woman", "女", "女性"):
        gender = "woman"
    else:
        gender = "woman"  # 默认女性

    refiner_client = await get_refiner_client()
    try:
        refined = await refiner_client.refine(
            person_image=user_photo,
            coarse_image=prev_vton_bytes,
            top_garment_image=top_bytes,
            bottom_garment_image=bottom_bytes,
            gender=gender,
        )
    except Exception as e:
        _elapsed = time.monotonic() - _refine_start
        logger.error("[精修] RefinerClient 异常，降级用原 VTON 图: taskId=%s, duration_ms=%d, error=%s",
                     task_id, int(_elapsed * 1000), e, exc_info=True)
        record_agent_workflow_node(node="refine", status="FAILED", duration_seconds=_elapsed)
        return None

    if refined is not None:
        _elapsed = time.monotonic() - _refine_start
        logger.info("[精修] 成功: taskId=%s, duration_ms=%d, prev=%d bytes, refined=%d bytes",
                    task_id, int(_elapsed * 1000), len(prev_vton_bytes), len(refined))
        record_agent_workflow_node(node="refine", status="SUCCESS", duration_seconds=_elapsed)
    else:
        _elapsed = time.monotonic() - _refine_start
        logger.warning("[精修] RefinerClient 返回 None，降级用原 VTON 图: taskId=%s, duration_ms=%d",
                        task_id, int(_elapsed * 1000))
        record_agent_workflow_node(node="refine", status="FAILED", duration_seconds=_elapsed)
    return refined


async def _load_default_model_image(task_id: str, state: AgentState | None = None) -> bytes | None:
    """加载系统默认模特图（场景 A：用户未上传自拍照时 VTON 兜底）

    统一系统模特图池兜底链路（按优先级降序）：
    0. 用户选定的系统模特图（state.system_model_image_url）→ 直接下载（最高优先级）
    1. 调 Java item-service GET /items/admin/ai-model/system-images/random-default
       查全平台共用的系统模特图池 → 拿到 imageUrl（相对路径或完整 URL）→ 下载
    2. 系统池为空 → 调 AI 大模型文生图（千问 wan2.7-image）生成模特图
       prompt 基于搭配上下文（style_tags/scene_desc/color/categories）构造，保证模特契合穿搭
    3. AI 生成失败 → 兜底用 settings.default_model_image_url 直接下载（向后兼容）
    4. 全部失败 → 返回 None，调用方走 PIL 商品图堆叠降级

    Args:
        task_id: 任务ID（日志用）
        state: AgentState（用于提取 style_tags/scene_desc/color/categories 构造 AI 生成 prompt）
               None 时跳过 AI 生成，仅走系统池 + default_model_image_url 兜底
    Returns:
        模特图二进制，失败返回 None
    """
    # ===== Step 0：用户选定的系统模特图（最高优先级）=====
    # 防止 vton_generation 的回捞逻辑因故未执行时，这里再次兜底
    if state:
        system_model_image_url = state.get("system_model_image_url")
        if system_model_image_url:
            try:
                image_bytes = await _download_image_bytes(
                    system_model_image_url, task_id, source="user_selected_system_model"
                )
                if image_bytes:
                    logger.info("[节点4] 用户选定系统模特图加载成功: taskId=%s, url=%s, bytes=%d",
                                task_id, str(system_model_image_url)[:120], len(image_bytes))
                    return image_bytes
                logger.warning("[节点4] 用户选定系统模特图下载失败（bytes 为空），走兜底链路: taskId=%s", task_id)
            except Exception as e:
                logger.warning("[节点4] 用户选定系统模特图下载异常，走兜底链路: taskId=%s, error=%s",
                               task_id, e)

    # ===== Step 1：查 Java 系统模特图池 =====
    # 注意：随机池不支持 gender 过滤，若用户已选定 target_gender，需校验返回模特性别一致性
    try:
        java_client = await get_java_client()
        user_id = state.get("user_id") if state else None
        model_image_dto = await java_client.get_random_default_model_image(user_id=user_id)
        if model_image_dto:
            # 性别一致性校验：用户选定 male 时，跳过女性模特图（避免覆盖用户选择）
            target_gender = (state or {}).get("target_gender")
            pool_gender = model_image_dto.get("gender")
            if target_gender and pool_gender and target_gender != pool_gender:
                logger.info("[节点4] 系统池随机模特性别不匹配（期望 %s, 实际 %s），跳过走 AI 生成: taskId=%s",
                            target_gender, pool_gender, task_id)
            else:
                image_url = model_image_dto.get("imageUrl", "")
                resolved_url = _resolve_model_image_url(image_url)
                if resolved_url:
                    image_bytes = await _download_image_bytes(resolved_url, task_id, source="system_pool")
                    if image_bytes:
                        logger.info("[节点4] 系统模特图池命中: taskId=%s, modelImageId=%s, url=%s, gender=%s",
                                    task_id, model_image_dto.get("id"), resolved_url[:120], pool_gender)
                        return image_bytes
        else:
            logger.info("[节点4] 系统模特图池为空，尝试 AI 生成兜底: taskId=%s", task_id)
    except Exception as e:
        logger.warning("[节点4] 查询系统模特图池异常，尝试 AI 生成兜底: taskId=%s, error=%s",
                       task_id, e)

    # ===== Step 2：AI 文生图兜底（系统池为空或不可用）=====
    if state is not None:
        try:
            image_bytes = await _generate_model_image_via_ai(task_id, state)
            if image_bytes:
                logger.info("[节点4] AI 文生图模特图生成成功: taskId=%s, bytes=%d",
                            task_id, len(image_bytes))
                return image_bytes
            logger.warning("[节点4] AI 文生图模特图生成失败: taskId=%s", task_id)
        except Exception as e:
            logger.warning("[节点4] AI 文生图模特图生成异常: taskId=%s, error=%s", task_id, e)

    # ===== Step 3：default_model_image_url 直接下载（向后兼容兜底）=====
    if settings.default_model_image_url:
        try:
            image_bytes = await _download_image_bytes(
                settings.default_model_image_url, task_id, source="legacy_default"
            )
            if image_bytes:
                logger.info("[节点4] 兜底 default_model_image_url 加载成功: taskId=%s", task_id)
                return image_bytes
        except Exception as e:
            logger.warning("[节点4] default_model_image_url 加载异常: taskId=%s, error=%s",
                           task_id, e)

    logger.error("[节点4] 所有默认模特图兜底链路均失败: taskId=%s", task_id)
    return None


def _resolve_model_image_url(image_url: str) -> str:
    """将 Java 返回的 imageUrl 解析为可下载的完整 URL

    Java FileStorageStrategy 两种模式返回值：
    - OSS 模式：完整 URL（如 https://zmall-ai.oss-cn-xxx.aliyuncs.com/model-images/xxx.jpg）→ 直接返回
    - 本地模式：相对路径（如 /uploads/model-images/xxx.jpg）→ 拼 nginx_external_base_url 前缀

    Args:
        image_url: Java 返回的 imageUrl
    Returns:
        完整可下载 URL，无法解析时返回空字符串
    """
    if not image_url:
        return ""
    # 完整 URL（http/https/oss）直接返回
    if image_url.startswith(("http://", "https://")):
        return image_url
    # 相对路径 → 拼 nginx base url
    if settings.nginx_external_base_url:
        base = settings.nginx_external_base_url.rstrip("/")
        return f"{base}{image_url if image_url.startswith('/') else '/' + image_url}"
    # nginx base url 未配置 → 用 item-service 自身 URL 拼接（仅适合同机部署）
    logger.warning("[节点4] nginx_external_base_url 未配置，相对路径无法解析: %s", image_url)
    return ""


async def _download_image_bytes(url: str, task_id: str, source: str = "") -> bytes | None:
    """下载图片二进制（统一封装，含超时和错误日志）"""
    # A2 SSRF 防护：拦截内网/回环/元数据地址
    if not is_safe_image_url(url):
        logger.warning("[节点4] SSRF 拦截: 非法图片 URL 已拒绝: taskId=%s, source=%s, url=%s",
                       task_id, source, url[:120])
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                logger.info("[节点4] 模特图下载成功: taskId=%s, source=%s, bytes=%d",
                            task_id, source, len(resp.content))
                return resp.content
            logger.error("[节点4] 模特图下载失败: source=%s, status=%s, url=%s",
                         source, resp.status_code, url[:120])
            return None
    except Exception as e:
        logger.error("[节点4] 模特图下载异常: source=%s, taskId=%s, error=%s",
                     source, task_id, e)
        return None


async def _generate_model_image_via_ai(task_id: str, state: AgentState) -> bytes | None:
    """AI 文生图生成模特图（系统池为空时的兜底）

    根据搭配上下文（style_tags/scene_desc/color/categories）构造中文 prompt，
    调千问 wan2.7-image 文生图模型生成模特白底全身照，供 VTON 后续使用。

    prompt 设计原则：
    - 强调全身 + 站立姿势 + 纯白背景（VTON 输入要求）
    - 融入 style_tags（如"商务""清新"）+ scene_desc（如"通勤"）匹配穿搭风格
    - 默认模特为成年女性中等肤色（避免与搭配风格冲突；性别由 style_tags 启发式判断）
    """
    from app.api.deps import get_gen_client

    style_tags = state.get("style_tags") or []
    scene_desc = state.get("scene_desc") or ""
    color = state.get("color") or []
    categories = state.get("category_constraints") or []

    # 性别确定（优先级：target_gender > 风格启发式 > 默认女性）
    target_gender = (state or {}).get("target_gender")
    if target_gender == "male":
        gender_cn = "男性"
    elif target_gender == "female":
        gender_cn = "女性"
    else:
        # 启发式性别推断：风格标签含"商务/正装/工装/运动/街头"倾向男性，含"清新/甜美/优雅/浪漫"倾向女性
        male_hints = {"商务", "正装", "工装", "运动", "街头", "硬朗", "粗犷"}
        female_hints = {"清新", "甜美", "优雅", "浪漫", "少女", "可爱", "温柔"}
        style_set = {s for s in style_tags if isinstance(s, str)}
        if style_set & male_hints and not (style_set & female_hints):
            gender_cn = "男性"
        elif style_set & female_hints and not (style_set & male_hints):
            gender_cn = "女性"
        else:
            gender_cn = "女性"  # 默认女性（服装电商常见默认）

    # 风格描述拼接
    style_str = "、".join(style_tags) if style_tags else "日常休闲"
    scene_str = scene_desc if scene_desc else "影棚"
    color_str = f"，主色调{'/'.join(color)}" if color else ""

    # 品类上下文（让 AI 知道这套搭配是大致什么样的）
    categories_str = "、".join(categories) if categories else "时尚穿搭"

    prompt = (
        f"一位专业时装模特，全身照，站立姿势，正面朝向镜头，"
        f"纯白影棚背景，柔和灯光，"
        f"{gender_cn}，中等肤色，自然妆容，"
        f"风格：{style_str}，场景：{scene_str}{color_str}，"
        f"穿着{categories_str}，"
        f"高级时尚摄影，超高清，逼真写实"
    )

    logger.info("[节点4] AI 文生图 prompt: taskId=%s, prompt=%s", task_id, prompt[:200])

    gen_client = await get_gen_client()
    return await gen_client.generate_text_only_model_image(prompt)


@_trace_node("vton")
async def vton_generation(state: AgentState) -> dict:
    """为每套搭配并行生成换装图（3 套并发，避免 30s 超时）

    U1 统一架构：商品驱动模式（mode="product"）只生成 1 套，
    主商品图复用 _main_item_bytes 避免重复下载。

    两阶段架构：
    - stage="recommend"（阶段一候选推荐）：在条件边处已跳过本节点，不会执行
    - stage="vton"（阶段二 VTON 生成）：仅对 state.selected_outfit_indexes 执行 VTON，
      未选定的搭配 generated_image 为 None（oss_upload 节点用商品图兜底）
    - stage 缺失（单阶段/反馈轮完整流程）：对全部 outfit_candidates 执行 VTON

    场景 A（无自拍照）兜底链路：
    1. 调 Java 系统模特图池 → 命中即用
    2. 系统池空 → AI 文生图生成（千问 wan2.7-image，基于搭配上下文 prompt）
    3. AI 失败 → settings.default_model_image_url 直接下载（向后兼容）
    4. 全部失败 → 降级为商品图 PIL 堆叠
    场景 B（有自拍照）：用用户照片正常 VTON。
    """
    outfit_candidates = state.get("outfit_candidates") or []
    user_photo = state.get("user_photo")
    use_default_model = state.get("use_default_model", False)
    task_id = state.get("task_id")
    mode = state.get("mode")
    stage = state.get("stage")
    selected_indexes = state.get("selected_outfit_indexes") or []
    # retry_vton_item_ids：商品 OK 但 VTON 效果差的商品 ID（用户点"不还原"）
    # 与 dislike_item_ids 的差异：dislike 在节点2 后置过滤换商品，retry_vton 在节点4 仅重换装/精修
    retry_vton_item_ids = set(state.get("retry_vton_item_ids") or [])

    if not outfit_candidates:
        return {"generated_images": []}

    # ===== 阶段二：仅对 selected_outfit_indexes 执行 VTON =====
    # 未选定的搭配 generated_image 为 None，oss_upload 节点用商品图兜底
    if stage == "vton" and selected_indexes:
        return await _vton_generation_selected(
            state, outfit_candidates, selected_indexes, user_photo, task_id,
        )

    # ===== 场景 A：用户未上传自拍照 → 加载默认模特图兜底 VTON =====
    if not user_photo:
        # 优先回捞用户选定的系统模特图（vton_only 阶段不跑节点1，user_photo 可能未透传）
        system_model_image_url = state.get("system_model_image_url")
        if system_model_image_url:
            logger.info("[节点4] user_photo 为空，回捞系统模特图: taskId=%s, url=%s",
                        task_id, str(system_model_image_url)[:80])
            try:
                user_photo = await _download_image(system_model_image_url)
            except Exception as e:
                logger.warning("[节点4] 回捞系统模特图失败: taskId=%s, error=%s", task_id, e)
                user_photo = None

    if not user_photo:
        logger.info("[节点4] 用户照片为空，加载默认模特图: taskId=%s, use_default_model=%s",
                     task_id, use_default_model)
        # v2：传入 state 用于 AI 生成 prompt 构造（系统池为空时启用 AI 兜底）
        user_photo = await _load_default_model_image(task_id, state)
        if not user_photo:
            # 默认模特图也未配置/加载失败 → 用空 bytes 触发降级逻辑
            # H7 修复：_vton_generation_product 检测到空 user_photo 时直接返回主商品图，不再走 PIL 贴图
            logger.error("[节点4] 默认模特图加载失败，降级返回主商品图: taskId=%s", task_id)
            user_photo = DEFAULT_USER_PHOTO  # b""，触发 _vton_generation_product 的跳过 VTON 分支
        else:
            # 默认模特图加载成功，标记为非空，正常走 VTON
            # use_default_model 仍保持 True 用于日志/统计
            logger.info("[节点4] 默认模特图就绪，开始 VTON: taskId=%s", task_id)

    # ===== U1 统一架构：商品驱动分支 =====
    if mode == "product":
        result = await _vton_generation_product(state, outfit_candidates[0], user_photo, task_id)
        # 商品驱动模式也支持 retry_vton 精修
        if retry_vton_item_ids and result.get("generated_images"):
            history_outfits = state.get("history_outfits") or []
            target_gender = state.get("target_gender") or state.get("system_model_gender") or "woman"
            prev_vton_bytes = await _get_prev_vton_bytes_for_items(
                history_outfits, retry_vton_item_ids, task_id,
            )
            if prev_vton_bytes:
                logger.info("[节点4-retryVTON-商品驱动] 获取到上一轮效果图，开始精修: taskId=%s", task_id)
                outfit_items = outfit_candidates[0].get("items", [])
                outfit_item_ids = {
                    it.get("itemId") or it.get("item_id")
                    for it in outfit_items if isinstance(it, dict)
                }
                if outfit_item_ids & retry_vton_item_ids:
                    result["generated_images"][0] = await _refine_outfit_with_prev_vton(
                        new_vton_bytes=result["generated_images"][0],
                        prev_vton_bytes=prev_vton_bytes,
                        outfit_items=outfit_items,
                        user_photo=user_photo,
                        gender=target_gender,
                        task_id=task_id,
                        idx=0,
                    )
            else:
                logger.info("[节点4-retryVTON-商品驱动] 未获取到上一轮效果图，跳过精修: taskId=%s", task_id)
        return result

    # ===== 风格驱动分支（单阶段/反馈轮完整流程）=====
    logger.info("[节点4] 换装生成: taskId=%s, stage=%s, outfits=%d, use_default_model=%s, "
                 "retryVtonItems=%s",
                 task_id, stage, len(outfit_candidates), use_default_model,
                 list(retry_vton_item_ids) if retry_vton_item_ids else None)

    vton_client = await get_vton_client()

    # 并行生成 3 套搭配的换装图（asyncio.gather 同时执行）
    # return_exceptions=True 防止单套 VTON 异常拖垮全部 3 套。
    # 节点5 已有 `if gen_image is not None` 判断，异常对象在此统一降级为 None。
    tasks = [
        _generate_single_outfit(idx, outfit, user_photo, vton_client)
        for idx, outfit in enumerate(outfit_candidates)
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    generated_images: list[bytes | None] = []
    for idx, r in enumerate(raw_results):
        if isinstance(r, Exception):
            logger.warning("[节点4] 第 %d 套 VTON 生成异常（降级为 None，不阻塞其他套）: %s",
                           idx + 1, r)
            generated_images.append(None)
        else:
            generated_images.append(r)

    # ===== retry_vton 精修：对包含 retry_vton 商品的 outfit 做二次精修提升还原度 =====
    # 场景：用户点"不还原"表示商品 OK 但 VTON 效果差，通过 refiner 二次精修提升还原度
    if retry_vton_item_ids:
        history_outfits = state.get("history_outfits") or []
        target_gender = state.get("target_gender") or state.get("system_model_gender") or "woman"
        # 从历史搭配下载上一轮 VTON 效果图（用于 refiner 的 coarse_image 输入）
        prev_vton_bytes = await _get_prev_vton_bytes_for_items(
            history_outfits, retry_vton_item_ids, task_id,
        )
        if prev_vton_bytes:
            logger.info("[节点4-retryVTON] 获取到上一轮效果图，开始精修: taskId=%s", task_id)
            for idx, outfit in enumerate(outfit_candidates):
                if idx >= len(generated_images):
                    break
                items = outfit.get("items", [])
                outfit_item_ids = {
                    it.get("itemId") or it.get("item_id")
                    for it in items if isinstance(it, dict)
                }
                if outfit_item_ids & retry_vton_item_ids:
                    # 该 outfit 包含 retry_vton 商品，做精修
                    generated_images[idx] = await _refine_outfit_with_prev_vton(
                        new_vton_bytes=generated_images[idx],
                        prev_vton_bytes=prev_vton_bytes,
                        outfit_items=items,
                        user_photo=user_photo,
                        gender=target_gender,
                        task_id=task_id,
                        idx=idx,
                    )
        else:
            logger.info("[节点4-retryVTON] 未获取到上一轮效果图，跳过精修（用重新 VTON 结果）: "
                        "taskId=%s", task_id)

    return {"generated_images": generated_images}


async def _vton_generation_selected(
    state: AgentState,
    outfit_candidates: list[dict],
    selected_indexes: list[int],
    user_photo: bytes | None,
    task_id: str,
) -> dict:
    """阶段二：仅对 selected_outfit_indexes 执行 VTON 生成

    策略：
    - 仅对用户选定的搭配（如 [0, 2]）调用 VTON
    - 未选定的搭配 generated_image 为 None（oss_upload 用商品图兜底）
    - 单套 VTON 异常不阻塞其他套（return_exceptions=True）
    - 全部失败时记录 partial_failures，调用方按规则处理 credits 退还

    失败规则：
    - 全部失败 → 调用方走 _on_failure（全额 rollback）
    - 部分失败 → 调用方走 _on_success（部分失败不退还 credits）
    - VTON API 故障 → 调用方走 _on_failure（全额 rollback）

    场景 A 兜底（用户未上传自拍照）：
    - 加载默认模特图（系统池 → AI 文生图 → legacy default）
    - 全部失败时该套标记为失败（partial_failures）
    """
    # 场景 A：用户未上传自拍照 → 加载默认模特图兜底
    if not user_photo:
        logger.info("[节点4-阶段二] 用户照片为空，加载默认模特图: taskId=%s", task_id)
        user_photo = await _load_default_model_image(task_id, state)
        if not user_photo:
            logger.error("[节点4-阶段二] 默认模特图加载失败，全部 VTON 失败: taskId=%s", task_id)
            # 全部失败：所有 selected 都加入 partial_failures
            return {
                "generated_images": [None] * len(outfit_candidates),
                "partial_failures": list(selected_indexes),
            }
        logger.info("[节点4-阶段二] 默认模特图就绪，开始 VTON: taskId=%s", task_id)

    logger.info("[节点4-阶段二] VTON 生成: taskId=%s, selectedIndexes=%s, outfits=%d",
                 task_id, selected_indexes, len(outfit_candidates))

    vton_client = await get_vton_client()

    # 仅对选定的搭配执行 VTON（并行）
    # 分离有效/无效索引，避免 raw_results 与 selected_indexes 索引错位导致 IndexError
    valid_indexes = [idx for idx in selected_indexes if 0 <= idx < len(outfit_candidates)]
    invalid_indexes = [idx for idx in selected_indexes if not (0 <= idx < len(outfit_candidates))]

    selected_tasks = [
        _generate_single_outfit(idx, outfit_candidates[idx], user_photo, vton_client)
        for idx in valid_indexes
    ]
    raw_results = await asyncio.gather(*selected_tasks, return_exceptions=True)

    # 构造完整 generated_images（未选定的为 None）
    generated_images: list[bytes | None] = [None] * len(outfit_candidates)
    # 越界索引直接记为部分失败
    partial_failures: list[int] = list(invalid_indexes)
    success_count = 0

    for i, idx in enumerate(valid_indexes):
        r = raw_results[i]
        if isinstance(r, Exception):
            logger.warning("[节点4-阶段二] 第 %d 套 VTON 异常（降级为 None）: %s",
                            idx + 1, r)
            generated_images[idx] = None
            partial_failures.append(idx)
        elif r is None:
            logger.warning("[节点4-阶段二] 第 %d 套 VTON 失败（返回 None）", idx + 1)
            generated_images[idx] = None
            partial_failures.append(idx)
        else:
            generated_images[idx] = r
            success_count += 1
            logger.info("[节点4-阶段二] 第 %d 套 VTON 成功: bytes=%d",
                         idx + 1, len(r))

    # 越界索引日志警告
    for idx in invalid_indexes:
        logger.warning("[节点4-阶段二] 选定索引 %s 越界（outfits=%d），跳过",
                        idx, len(outfit_candidates))

    logger.info("[节点4-阶段二] VTON 完成: taskId=%s, selected=%d, success=%d, failed=%d",
                 task_id, len(selected_indexes), success_count, len(partial_failures))

    return {
        "generated_images": generated_images,
        "partial_failures": partial_failures,
    }


# ============================================================
# 节点5：OSS 上传
# ============================================================
@_trace_node("upload")
async def oss_upload(state: AgentState) -> dict:
    """上传换装图到 OSS，组装最终搭配结果

    两阶段架构：
    - stage="recommend"（阶段一候选推荐）：generated_images 不存在，所有 resultUrl
      用商品图兜底，isVtonGenerated=False（前端展示候选图供用户选定）
    - stage="vton"（阶段二 VTON 生成）：仅 selected_outfit_indexes 中的搭配上传 OSS，
      未选定的搭配 resultUrl=None（前端过滤展示）
    - stage 缺失（单阶段/反馈轮完整流程）：完整执行所有流程

    final_outfits 字段说明：
    - isVtonGenerated: bool — True=VTON 生成的效果图，False=商品图兜底
    - isSelected: bool — 阶段二时是否为用户选定的搭配（阶段一全部为 True）
    - isPartialFailure: bool — 阶段二时该套 VTON 是否失败（部分失败不退还规则审计用）
    """
    outfit_candidates = state.get("outfit_candidates") or []
    generated_images = state.get("generated_images") or []
    task_id = state.get("task_id")
    stage = state.get("stage")
    selected_indexes = set(state.get("selected_outfit_indexes") or [])
    partial_failures = set(state.get("partial_failures") or [])

    if not outfit_candidates:
        return {"final_outfits": []}

    logger.info("[节点5] OSS 上传: taskId=%s, stage=%s, outfits=%d, selected=%s",
                 task_id, stage, len(outfit_candidates), list(selected_indexes))

    oss_uploader = await get_oss_uploader()
    final_outfits: list[dict] = []

    for idx, outfit in enumerate(outfit_candidates):
        items = outfit.get("items", [])
        gen_image = generated_images[idx] if idx < len(generated_images) else None
        result_url: str | None = None
        is_vton_generated = False

        # 阶段二：未选定的搭配 resultUrl=None，跳过上传
        if stage == "vton" and idx not in selected_indexes:
            final_outfits.append({
                "items": items,
                "resultUrl": None,
                "isVtonGenerated": False,
                "isSelected": False,
                "isPartialFailure": False,
                "score": outfit.get("score", 0.0),
                "reason": outfit.get("reason", ""),
            })
            continue

        # 上传 VTON 生成图（如果有）
        if gen_image is not None:
            try:
                result_url = await asyncio.to_thread(
                    oss_uploader.upload_image,
                    gen_image,
                    "outfit-results",
                    "jpg",
                )
                is_vton_generated = True
            except Exception as e:
                logger.warning("[节点5] 第 %d 套 OSS 上传失败: %s", idx + 1, e)

        # 降级策略
        if result_url is None:
            if gen_image is not None:
                # OSS/本地存储均失败 → base64 内联（开发环境兜底）
                result_url = f"data:image/jpeg;base64,{base64.b64encode(gen_image).decode()}"
                is_vton_generated = True
            else:
                # VTON 生成失败 → 不用商品图冒充，返回 None 由前端展示"生成失败"
                result_url = None
                is_vton_generated = False

        final_outfits.append({
            "items": items,
            "resultUrl": result_url,
            "isVtonGenerated": is_vton_generated,
            # isSelected：阶段一全部为 True（候选可选）；阶段二此处仅选定搭配进入，
            # 未选定的已通过上方 continue 跳过，所以这里恒为 True
            "isSelected": True,
            "isPartialFailure": idx in partial_failures,
            "score": outfit.get("score", 0.0),
            "reason": outfit.get("reason", ""),  # 透传 LLM 推荐理由
        })

    vton_count = sum(1 for f in final_outfits if f.get("isVtonGenerated"))
    logger.info("[节点5] 已组装 %d 套最终搭配: stage=%s, vtonGenerated=%d",
                 len(final_outfits), stage, vton_count)
    return {"final_outfits": final_outfits}
