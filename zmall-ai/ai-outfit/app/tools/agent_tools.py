"""
ReAct Tool Calling 工具定义和执行器

反馈轮 note 非空时，LlmClient.react_feedback 调用本模块的 ToolExecutor
执行 LLM 自主选择的 Tool：
  - update_user_preference: 异步 upsert 用户偏好到 Qdrant
  - get_item_details: 批量查询 Java 商品详情
  - search_items: Qdrant 预检索（仅用于 LLM 决策参考，正式检索由节点2 完成）

设计要点：
- ToolExecutor 持有 user_id / redis 等上下文，避免每次 Tool 调用都传参
- 所有 Tool 执行失败返回 {"error": ...}，不抛异常（避免中断 ReAct 循环）
- update_user_preference 为 fire-and-forget（异步 upsert，失败仅记日志）
"""
import asyncio
import logging

from app.api.deps import (
    get_java_client, get_qdrant_searcher, get_user_preference_updater,
)
from shared.qdrant_client.category_mapping import to_en

logger = logging.getLogger(__name__)


class ToolExecutor:
    """ReAct Tool 执行器

    每个 feedback 请求创建一个实例，持有 user_id 等上下文。
    LLM 通过 react_feedback 调用 executor.execute(tool_name, action_input)。
    """

    def __init__(self, user_id: int):
        self.user_id = user_id

    async def execute(self, tool_name: str, action_input: dict) -> dict:
        """执行 Tool

        Args:
            tool_name: update_user_preference / get_item_details / search_items
            action_input: Tool 参数 dict
        Returns:
            Tool 执行结果 dict；失败时返回 {"error": "..."}
        """
        try:
            if tool_name == "update_user_preference":
                return await self._update_user_preference(action_input)
            if tool_name == "get_item_details":
                return await self._get_item_details(action_input)
            if tool_name == "search_items":
                return await self._search_items(action_input)
            return {"error": f"未知 Tool: {tool_name}"}
        except Exception as e:
            logger.warning("Tool %s 执行异常: %s", tool_name, e)
            return {"error": f"Tool {tool_name} 执行失败: {e}"}

    async def _update_user_preference(self, action_input: dict) -> dict:
        """更新用户偏好到 Qdrant（fire-and-forget，失败仅记日志）

        LLM 在用户明确表示"不喜欢X色""喜欢X风"时调用。
        US-AT-24：补齐 dislike_styles 和 preferred_price_range 字段采集。
        """
        dislike_colors = list(action_input.get("dislike_colors") or [])
        like_styles = list(action_input.get("like_styles") or [])
        dislike_styles = list(action_input.get("dislike_styles") or [])
        preferred_price_range = action_input.get("preferred_price_range") or None

        if not dislike_colors and not like_styles and not dislike_styles and not preferred_price_range:
            return {"success": True, "msg": "无偏好需更新"}

        # preferred_price_range 校验：必须是 [min, max] 形式
        if preferred_price_range is not None:
            if not (isinstance(preferred_price_range, list) and len(preferred_price_range) == 2):
                preferred_price_range = None

        updater = await get_user_preference_updater()
        # upsert_preference 为 async（内部用分布式锁保证原子性）
        await updater.upsert_preference(
            self.user_id,
            dislike_colors or None,
            dislike_styles or None,
            like_styles or None,
            preferred_price_range,
        )
        logger.info("[ReAct Tool] update_user_preference: userId=%s, dislikeColors=%s, dislikeStyles=%s, likeStyles=%s, priceRange=%s",
                     self.user_id, dislike_colors, dislike_styles, like_styles, preferred_price_range)
        return {"success": True}

    async def _get_item_details(self, action_input: dict) -> dict:
        """批量查询 Java 商品详情

        LLM 在用户提到具体商品但需要确认细节时调用。
        """
        item_ids = list(action_input.get("item_ids") or [])
        if not item_ids:
            return {"items": []}

        # 转 int（LLM 可能输出 str）
        try:
            item_ids = [int(i) for i in item_ids]
        except (ValueError, TypeError):
            return {"error": "item_ids 必须是整数列表"}

        java_client = await get_java_client()
        details = await java_client.get_items_by_ids(item_ids)
        # 精简返回（避免 token 浪费）
        simplified = []
        for d in details:
            if d and d.get("id"):
                simplified.append({
                    "itemId": d.get("id"),
                    "name": d.get("name"),
                    "price": d.get("price"),
                    "category": d.get("category"),
                    "color": d.get("color"),
                })
        logger.info("[ReAct Tool] get_item_details: ids=%s → %d items",
                     item_ids, len(simplified))
        return {"items": simplified}

    async def _search_items(self, action_input: dict) -> dict:
        """Qdrant 预检索（仅用于 LLM 决策参考）

        正式检索仍由节点2 完成，此处只返回简要信息帮助 LLM 理解商品池。
        """
        style_tags = list(action_input.get("style_tags") or [])
        dislike_colors = list(action_input.get("dislike_colors") or [])
        category_cn = action_input.get("category")
        # 兼容 shop_id（旧字段，单个 int）和 shop_ids（新字段，list[int]）
        shop_ids_raw = action_input.get("shop_ids")
        if shop_ids_raw is None:
            shop_id_legacy = action_input.get("shop_id")
            shop_ids_list = [int(shop_id_legacy)] if shop_id_legacy and int(shop_id_legacy) > 0 else None
        else:
            shop_ids_list = [int(sid) for sid in shop_ids_raw if sid and int(sid) > 0] or None

        # 品类中文 → 英文
        category_en = to_en(category_cn) if category_cn else None

        # 需要 query_vector，但 ReAct 阶段没有向量编码
        # 简化：用零向量 + payload 过滤（Qdrant 支持纯 payload 过滤检索）
        # 这里用 1024 维零向量（与 item_style collection 对齐），相似度无意义，仅靠 payload 过滤返回商品
        dummy_vector = [0.0] * 1024

        searcher = await get_qdrant_searcher()
        results = await asyncio.to_thread(
            searcher.search_complementary_items,
            dummy_vector,
            shop_ids_list,  # list[int] | None，对应形参 shop_ids（MatchAny 多店过滤）
            category_en,
            None,  # color 由 dislike_colors 反向过滤，不正向限定
            None,  # season 由节点2 处理，ReAct 阶段不限定
            dislike_colors or None,
            5,   # limit
            0.0, # score_threshold=0，零向量相似度为 0
        )
        # 精简返回
        simplified = []
        for r in results[:5]:
            simplified.append({
                "itemId": r.get("item_id"),
                "category": r.get("category"),
                "color": r.get("color"),
                "price": r.get("price"),
                "shopId": r.get("shop_id"),
            })
        logger.info("[ReAct Tool] search_items: style=%s, category=%s → %d items",
                     style_tags, category_cn, len(simplified))
        return {"items": simplified}
