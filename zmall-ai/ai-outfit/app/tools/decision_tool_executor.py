"""
搭配决策子 Agent 的 ReAct Tool 执行器（场景 1）

LlmClient.react_decision 调用本模块的 DecisionToolExecutor 执行 LLM 自主选择的 Tool：
  - re_search: 用新 query 重新检索 Qdrant（Reflection 发现候选池不足时调用）
  - get_item_details: 批量查询 Java 商品详情
  - call_price_balance: 调用价格平衡工具
  - call_trending_styles: 调用流行趋势工具

设计要点（与 agent_tools.ToolExecutor 保持一致）：
- DecisionToolExecutor 持有 task_id / user_id / query_vector 等上下文
- 所有 Tool 执行失败返回 {"error": ...}，不抛异常（避免中断 ReAct 循环）
- LLM 根据 Reflection 结果自主决定调用哪些工具
  例：候选池不足时调 re_search；需要价格约束时调 call_price_balance
"""
import logging

from app.api.deps import get_embed_client, get_java_client, get_qdrant_searcher
from shared.qdrant_client.category_mapping import to_en, to_cn

logger = logging.getLogger(__name__)


class DecisionToolExecutor:
    """搭配决策子 Agent 的 ReAct Tool 执行器

    每次搭配决策子 Agent 运行创建一个实例，持有 task_id / query_vector 等上下文。
    LLM 通过 react_decision 调用 executor.execute(tool_name, action_input)。
    """

    def __init__(
        self,
        task_id: str | None = None,
        user_id: int | None = None,
        query_vector: list[float] | None = None,
        shop_ids: list[int] | None = None,
        season: str | None = None,
        target_gender: str | None = None,
        user_city: str | None = None,
        user_country: str | None = None,
        style_tags: list[str] | None = None,
        scene_desc: str | None = None,
    ):
        self.task_id = task_id
        self.user_id = user_id
        self.query_vector = query_vector
        self.shop_ids = shop_ids
        self.season = season
        # 性别与服装匹配：re_search 工具需透传 target_gender
        # 确保 DecisionAgent 重新检索时也走 Qdrant 硬过滤，不返回跨性别商品
        self.target_gender = target_gender
        # 时尚潮流搜索用：search_fashion_trend 工具需 city/country 做地区路由
        self.user_city = user_city
        self.user_country = user_country
        self.style_tags = style_tags or []
        self.scene_desc = scene_desc

    async def execute(self, tool_name: str, action_input: dict) -> dict:
        """执行 Tool

        Args:
            tool_name: re_search / get_item_details / call_price_balance /
                       call_trending_styles / search_fashion_trend
            action_input: Tool 参数 dict
        Returns:
            Tool 执行结果 dict；失败时返回 {"error": "..."}
        """
        try:
            if tool_name == "re_search":
                return await self._re_search(action_input)
            if tool_name == "get_item_details":
                return await self._get_item_details(action_input)
            if tool_name == "call_price_balance":
                return await self._call_price_balance(action_input)
            if tool_name == "call_trending_styles":
                return await self._call_trending_styles(action_input)
            if tool_name == "search_fashion_trend":
                return await self._search_fashion_trend(action_input)
            return {"error": f"未知 Tool: {tool_name}"}
        except Exception as e:
            logger.warning("[DecisionAgent] Tool %s 执行异常: %s", tool_name, e)
            return {"error": f"Tool {tool_name} 执行失败: {e}"}

    # ------------------------------------------------------------------
    # Tool 1: re_search - 重新检索 Qdrant
    # ------------------------------------------------------------------
    async def _re_search(self, action_input: dict) -> dict:
        """用新 query 重新检索 Qdrant（Reflection 发现候选池不足时调用）

        LLM 在 Reflection 发现所有候选都偏正式，需要休闲风时调用此工具。
        用新的 style_tags 重新编码向量并检索。
        """
        style_tags = list(action_input.get("style_tags") or [])
        category_cn = action_input.get("category")  # 中文品类，可选
        dislike_colors = list(action_input.get("dislike_colors") or [])

        if not style_tags:
            return {"error": "style_tags 为空，无法重新检索"}

        # 用新 style_tags 重新编码向量
        query_text = " ".join(style_tags)
        embed_client = await get_embed_client()
        new_vector = await embed_client.encode_text(query_text)
        if not new_vector:
            return {"error": "向量编码失败"}

        # 品类中文 → 英文
        category_en = to_en(category_cn) if category_cn else None

        # 调 Qdrant 检索
        searcher = await get_qdrant_searcher()
        results = await searcher.search_complementary_items(
            query_vector=new_vector,
            shop_ids=self.shop_ids,
            category=category_en,
            color=None,  # color 由 dislike_colors 反向过滤
            season=self.season,
            dislike_colors=dislike_colors or None,
            target_gender=self.target_gender,  # 性别与服装匹配
            limit=5,
            score_threshold=0.3,
        )

        # 精简返回（避免 token 浪费）
        simplified = []
        for r in results[:5]:
            simplified.append({
                "itemId": r.get("item_id"),
                "category": to_cn(r.get("category")) if r.get("category") else None,
                "color": r.get("color"),
                "price": r.get("price"),
                "shopId": r.get("shop_id"),
                "score": r.get("score"),
            })
        logger.info("[DecisionAgent] re_search: style=%s, category=%s → %d items",
                     style_tags, category_cn, len(simplified))
        return {"items": simplified}

    # ------------------------------------------------------------------
    # Tool 2: get_item_details - 批量查询 Java 商品详情
    # ------------------------------------------------------------------
    async def _get_item_details(self, action_input: dict) -> dict:
        """批量查询 Java 商品详情

        LLM 在需要确认商品细节（如具体价格、颜色、图片）时调用。
        """
        item_ids = list(action_input.get("item_ids") or [])
        if not item_ids:
            return {"items": []}

        try:
            item_ids = [int(i) for i in item_ids]
        except (ValueError, TypeError):
            return {"error": "item_ids 必须是整数列表"}

        java_client = await get_java_client()
        details = await java_client.get_items_by_ids(item_ids)
        simplified = []
        for d in details:
            if d and d.get("id"):
                simplified.append({
                    "itemId": d.get("id"),
                    "name": d.get("name"),
                    "price": d.get("price"),
                    "category": d.get("category"),
                    "color": d.get("color"),
                    "image": d.get("image"),
                })
        logger.info("[DecisionAgent] get_item_details: ids=%s → %d items",
                     item_ids, len(simplified))
        return {"items": simplified}

    # ------------------------------------------------------------------
    # Tool 3: call_price_balance - 价格平衡分析
    # ------------------------------------------------------------------
    async def _call_price_balance(self, action_input: dict) -> dict:
        """调用价格平衡工具

        LLM 在 Reflection 发现价格不协调（如 100 元上装配 5000 元下装）时调用。
        """
        # 延迟导入避免循环依赖
        from app.core.config import settings
        from shared.external_services.price_service import analyze_price_balance

        if not settings.price_tool_enabled:
            return {"error": "price_tool_enabled=False，价格工具未开启"}

        items = list(action_input.get("items") or [])
        if not items:
            return {"error": "items 为空"}

        # 提取价格列表
        prices = []
        for it in items:
            price = it.get("price")
            if price is not None:
                try:
                    prices.append(float(price))
                except (ValueError, TypeError):
                    continue

        if not prices:
            return {"error": "无有效价格"}

        ratio_max = settings.price_balance_ratio_max
        result = analyze_price_balance(prices, ratio_max=ratio_max)
        logger.info("[DecisionAgent] call_price_balance: prices=%s → %s",
                     prices, result.get("balance_score"))
        return result

    # ------------------------------------------------------------------
    # Tool 4: call_trending_styles - 流行趋势分析
    # ------------------------------------------------------------------
    async def _call_trending_styles(self, action_input: dict) -> dict:
        """调用流行趋势工具

        LLM 在 Reflection 发现搭配不够时尚，需要参考流行趋势时调用。
        """
        # 延迟导入避免循环依赖
        from app.core.config import settings
        from shared.external_services.trend_service import get_trending_styles

        if not settings.trend_tool_enabled:
            return {"error": "trend_tool_enabled=False，趋势工具未开启"}

        category = action_input.get("category")  # 可选品类过滤
        java_client = await get_java_client()
        embed_client = await get_embed_client()

        result = await get_trending_styles(
            java_client=java_client,
            embed_client=embed_client,
            category=category,
            top_k=settings.trend_top_k,
            cluster_k=settings.trend_cluster_k,
        )
        logger.info("[DecisionAgent] call_trending_styles: category=%s → %s",
                     category, result.get("trending_styles"))
        return result

    # ------------------------------------------------------------------
    # Tool 5: search_fashion_trend - 时尚潮流搜索（AnySearch API）
    # ------------------------------------------------------------------
    async def _search_fashion_trend(self, action_input: dict) -> dict:
        """搜索地区时尚潮流信息（AnySearch API）

        LLM 在 Reflection 发现搭配不够时尚/需要参考当地潮流时调用。
        使用 social_media.social_media + general.general 两个 tag 并行搜索，
        根据用户 city/country 自动路由该地区的搜索关键词。

        action_input 可选字段：
            - query: 自定义搜索关键词（覆盖默认的 scene+style_tags）
            - scene: 场景描述（覆盖构造函数的 scene_desc）
            - style_tags: 风格标签列表（覆盖构造函数的 style_tags）
        """
        # 延迟导入避免循环依赖
        from app.core.config import settings
        from shared.external_services.fashion_trend_service import get_fashion_trends

        if not settings.fashion_trend_tool_enabled:
            return {"error": "fashion_trend_tool_enabled=False，时尚潮流工具未开启"}

        # 优先用 action_input 传入的参数，兜底用构造函数的上下文
        custom_query = action_input.get("query", "")
        scene = action_input.get("scene") or self.scene_desc or ""
        style_tags = action_input.get("style_tags") or self.style_tags or []

        # 如果 LLM 显式传了 query，则只用 query 不拼地区关键词（LLM 自主决策）
        # 否则用 scene + style_tags + 地区关键词构造（默认行为）
        if custom_query:
            # LLM 自定义 query 模式：直接用 LLM 的 query，但仍走地区路由的 language/zone
            from shared.external_services.fashion_trend_service import (
                infer_country, REGIONAL_FASHION_STRATEGY, _DEFAULT_STRATEGY,
                _build_query, _call_anysearch, _merge_results,
            )
            country_code = infer_country(self.user_city or "", self.user_country or "")
            strategy = REGIONAL_FASHION_STRATEGY.get(country_code, _DEFAULT_STRATEGY)
            social_query = custom_query
            general_query = custom_query
            import asyncio as _asyncio
            social_task = _call_anysearch(
                settings.anysearch_api_url, settings.anysearch_api_key,
                social_query, "social_media.social_media",
                strategy["language"], strategy["zone"],
                max_results=settings.anysearch_max_results,
                proxy_url=settings.proxy_url,
            )
            general_task = _call_anysearch(
                settings.anysearch_api_url, settings.anysearch_api_key,
                general_query, "general.general",
                strategy["language"], strategy["zone"],
                max_results=settings.anysearch_max_results,
                proxy_url=settings.proxy_url,
            )
            social_results, general_results = await _asyncio.gather(
                social_task, general_task, return_exceptions=True,
            )
            if isinstance(social_results, Exception):
                social_results = []
            if isinstance(general_results, Exception):
                general_results = []
            merged = _merge_results(social_results, general_results)
            result = {
                "city": self.user_city or "",
                "country": country_code,
                "region_label": strategy["region_label"],
                "query_base": custom_query,
                "social_results": social_results,
                "general_results": general_results,
                "merged_results": merged,
                "total": len(merged),
                "data_source": "anysearch_api",
            }
        else:
            # 默认模式：用 city/country/scene/style_tags 走标准地区路由
            result = await get_fashion_trends(
                city=self.user_city or "",
                country=self.user_country or "",
                scene=scene,
                style_tags=style_tags,
                api_key=settings.anysearch_api_key,
                api_url=settings.anysearch_api_url,
                proxy_url=settings.proxy_url,
            )

        logger.info("[DecisionAgent] search_fashion_trend: city=%s, country=%s → %d 条结果",
                    self.user_city, self.user_country, result.get("total", 0))
        return result
