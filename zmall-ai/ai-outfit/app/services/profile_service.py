"""
用户画像聚合服务

从 3 个数据源聚合用户画像，用于 AI 随心搭个性化推荐增强：
  ① Qdrant zmall_user_behavior collection（CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT 行为向量）
  ② Qdrant zmall_user_preference collection（dislike_colors/like_styles 显式偏好）
  ③ MySQL user_browse_history 表（ITEM_VIEW 浏览统计）

产出字段：
  - top_styles: Top3 风格标签
  - top_colors: Top3 颜色
  - price_distribution: {min, median, max}
  - style_vector: 1024 维加权平均风格向量
  - profile_confidence: 0-1 画像置信度

缓存策略（§2.11.4）：
  - Redis Key: ai:profile:user:{userId}
  - TTL: 24h（86400s）
  - 懒加载：用户首次进入 AI 随心搭时触发聚合
  - 主动失效：用户调 accept 接口时 DEL

降级策略：
  - 画像聚合失败时返回空画像（profile_confidence=0），推荐工作流按原逻辑执行
  - Qdrant user_behavior collection 不存在时跳过向量聚合

信号权重表（§3.25.1）：
  OUTFIT_ACCEPT=3.0, ORDER_PLACE=2.0, CART_ADD=1.5, ITEM_VIEW=1.0

时间衰减（§3.25.2）：
  - 浏览信号 30 天后丢弃
  - 购买/加购/采纳信号 90 天后丢弃
"""
import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta

from shared.db_client import DbClient
from shared.qdrant_client.client import QdrantClientWrapper
from shared.qdrant_client.user_preference import UserPreferenceReader

logger = logging.getLogger(__name__)

# Qdrant user_behavior collection 名（与 user_behavior_indexer.py 对齐）
COLLECTION_USER_BEHAVIOR = "zmall_user_behavior"

# 画像缓存 Redis Key 前缀和 TTL
PROFILE_KEY_PREFIX = "ai:profile:user:"
PROFILE_TTL = 86400  # 24h

# 信号权重表（§3.25.1）
SIGNAL_WEIGHTS = {
    "OUTFIT_ACCEPT": 3.0,
    "ORDER_PLACE": 2.0,
    "CART_ADD": 1.5,
    "ITEM_VIEW": 1.0,
}

# 时间衰减阈值（天）
VIEW_DECAY_DAYS = 30        # 浏览信号 30 天后丢弃
PURCHASE_DECAY_DAYS = 90    # 购买/加购/采纳信号 90 天后丢弃


class ProfileService:
    """用户画像聚合服务（懒加载 + Redis 缓存）

    用法：
        profile = await profile_service.get_or_load_profile(user_id)
        if profile["profile_confidence"] > 0:
            # 注入到推荐 state
            state["user_profile"] = profile
    """

    def __init__(
        self,
        redis,
        qdrant_wrapper: QdrantClientWrapper,
        db_client: DbClient | None = None,
    ):
        self._redis = redis
        self._qdrant = qdrant_wrapper.get_client()
        self._qdrant_wrapper = qdrant_wrapper
        self._db = db_client or DbClient()
        self._pref_reader = UserPreferenceReader(qdrant_wrapper)

    async def get_or_load_profile(self, user_id: int) -> dict:
        """获取用户画像（懒加载，优先读 Redis 缓存）

        Returns:
            画像 dict，结构：
            {
                "top_styles": ["通勤", "简约"],
                "top_colors": ["black", "white"],
                "price_distribution": {"min": 99, "median": 199, "max": 499},
                "style_vector": [0.1, ...],  # 1024 维，无数据时为空列表
                "profile_confidence": 0.72,
                "dislike_colors": ["red"],   # 来自 user_preference
                "like_styles": ["通勤"],      # 来自 user_preference
            }
            画像聚合失败时返回 profile_confidence=0 的空画像。
        """
        cache_key = f"{PROFILE_KEY_PREFIX}{user_id}"
        try:
            cached = await self._redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("读取画像缓存失败（继续聚合）: userId=%s, error=%s", user_id, e)

        # 缓存未命中，执行聚合（放线程池避免阻塞事件循环）
        try:
            profile = await asyncio.to_thread(self._aggregate_profile, user_id)
        except Exception as e:
            logger.error("画像聚合失败，返回空画像: userId=%s, error=%s", user_id, e, exc_info=True)
            profile = self._empty_profile()

        # 写入缓存（即使空画像也缓存，避免频繁聚合失败）
        try:
            await self._redis.setex(cache_key, PROFILE_TTL, json.dumps(profile, ensure_ascii=False))
        except Exception as e:
            logger.warning("写入画像缓存失败（不影响主流程）: userId=%s, error=%s", user_id, e)

        return profile

    async def invalidate_profile(self, user_id: int):
        """主动失效画像缓存（accept 接口调用时触发）"""
        cache_key = f"{PROFILE_KEY_PREFIX}{user_id}"
        try:
            await self._redis.delete(cache_key)
            logger.info("画像缓存已失效: userId=%s", user_id)
        except Exception as e:
            logger.warning("失效画像缓存失败: userId=%s, error=%s", user_id, e)

    def _aggregate_profile(self, user_id: int) -> dict:
        """同步聚合画像（从 3 个数据源）

        在线程池中执行，不阻塞事件循环。
        """
        # 数据源 ① Qdrant user_behavior（行为向量 + 信号统计）
        behavior_data = self._aggregate_from_qdrant_behavior(user_id)

        # 数据源 ② Qdrant user_preference（显式偏好）
        preference_data = self._read_user_preference(user_id)

        # 数据源 ③ MySQL user_browse_history（浏览统计补充）
        browse_data = self._aggregate_from_browse_history(user_id)

        # 合并三个数据源
        return self._merge_profile_sources(behavior_data, preference_data, browse_data)

    def _aggregate_from_qdrant_behavior(self, user_id: int) -> dict:
        """从 Qdrant user_behavior collection 聚合行为信号

        Returns:
            {
                "style_counter": Counter({"通勤": 5.5, "简约": 3.0}),
                "color_counter": Counter({"black": 4.0, "white": 2.5}),
                "prices": [199, 299, 99],
                "vectors": [(vector, weight), ...],  # 加权向量列表
                "total_weight": 12.0,
                "signal_count": 8,
                "signal_types": set(["CART_ADD", "ORDER_PLACE"]),
            }
            collection 不存在或无数据时返回空结构。
        """
        result = {
            "style_counter": Counter(),
            "color_counter": Counter(),
            "prices": [],
            "vectors": [],
            "total_weight": 0.0,
            "signal_count": 0,
            "signal_types": set(),
        }

        try:
            # 检查 collection 是否存在
            collections = {c.name for c in self._qdrant.get_collections().collections}
            if COLLECTION_USER_BEHAVIOR not in collections:
                logger.debug("user_behavior collection 不存在，跳过向量聚合: userId=%s", user_id)
                return result

            # 按时间过滤 + 滚动检索用户行为记录
            now = datetime.now()
            view_cutoff = now - timedelta(days=VIEW_DECAY_DAYS)
            purchase_cutoff = now - timedelta(days=PURCHASE_DECAY_DAYS)

            from qdrant_client.http.models import Filter, FieldCondition, MatchValue, ScrollRequest

            scroll_filter = Filter(must=[
                FieldCondition(key="user_id", match=MatchValue(value=user_id))
            ])

            offset = None
            limit = 100
            while True:
                points, offset = self._qdrant.scroll(
                    collection_name=COLLECTION_USER_BEHAVIOR,
                    scroll_filter=scroll_filter,
                    limit=limit,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                if not points:
                    break

                for point in points:
                    payload = point.payload or {}
                    signal_type = payload.get("type", "ITEM_VIEW")
                    timestamp_str = payload.get("timestamp", "")

                    # 时间衰减检查
                    try:
                        ts = datetime.fromisoformat(timestamp_str) if timestamp_str else now
                    except Exception:
                        ts = now

                    if signal_type == "ITEM_VIEW":
                        if ts < view_cutoff:
                            continue
                    else:
                        if ts < purchase_cutoff:
                            continue

                    # 信号权重
                    weight = SIGNAL_WEIGHTS.get(signal_type, 1.0)

                    # 聚合风格标签
                    styles = payload.get("style_tags", [])
                    if isinstance(styles, list):
                        for s in styles:
                            self._add_weighted(result["style_counter"], s, weight)

                    # 聚合颜色
                    color = payload.get("color")
                    if color:
                        self._add_weighted(result["color_counter"], color, weight)

                    # 聚合价格
                    price = payload.get("price")
                    if price and isinstance(price, (int, float)) and price > 0:
                        result["prices"].append(float(price))

                    # 聚合向量（仅对齐性别的记录参与 style_vector 聚合）
                    # 跨性别记录（is_cross_gender=true）写入的是零向量（见 user_behavior.py
                    # 第 130 行），加入加权平均会拉低 style_vector 模长，按文档约定不参与向量聚合。
                    # 其 color/price/style_tags 等中性属性仍可参与聚合（已在上文处理）。
                    # 同时过滤 embed 失败时写入的零向量（非空 list 但全为 0.0）
                    is_cross_gender = payload.get("is_cross_gender", False)
                    vector = point.vector
                    if vector and not is_cross_gender and any(abs(v) > 1e-9 for v in vector):
                        result["vectors"].append((vector, weight))

                    result["total_weight"] += weight
                    result["signal_count"] += 1
                    result["signal_types"].add(signal_type)

                if offset is None:
                    break

        except Exception as e:
            logger.warning("从 Qdrant user_behavior 聚合失败（降级为空）: userId=%s, error=%s", user_id, e)

        return result

    def _read_user_preference(self, user_id: int) -> dict:
        """从 Qdrant user_preference collection 读取显式偏好"""
        try:
            pref = self._pref_reader.get_preference(user_id)
            if pref:
                return pref
        except Exception as e:
            logger.warning("读取用户偏好失败（降级为空）: userId=%s, error=%s", user_id, e)
        return {}

    def _aggregate_from_browse_history(self, user_id: int) -> dict:
        """从 MySQL user_browse_history 聚合浏览统计（ITEM_VIEW 信号补充）

        仅统计 30 天内的浏览记录，且 view_count >= 2（排除误点击）。
        """
        result = {
            "category_counter": Counter(),
            "browse_count": 0,
        }
        try:
            cutoff = (datetime.now() - timedelta(days=VIEW_DECAY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            rows = self._db.execute(
                """
                SELECT category, SUM(view_count) as total_views, COUNT(*) as record_count
                FROM user_browse_history
                WHERE user_id = :user_id
                  AND last_viewed_at >= :cutoff
                  AND view_count >= 2
                GROUP BY category
                """,
                {"user_id": user_id, "cutoff": cutoff},
            )
            for row in rows:
                cat = row.category if hasattr(row, "category") else row[0]
                views = row.total_views if hasattr(row, "total_views") else row[1]
                if cat:
                    # 浏览权重 = 1.0 × 浏览次数（与 SIGNAL_WEIGHTS["ITEM_VIEW"] 一致）
                    self._add_weighted(result["category_counter"], cat, float(views))
                    result["browse_count"] += int(views or 0)
        except Exception as e:
            logger.warning("从 MySQL user_browse_history 聚合失败（降级为空）: userId=%s, error=%s", user_id, e)
        return result

    def _merge_profile_sources(
        self,
        behavior_data: dict,
        preference_data: dict,
        browse_data: dict,
    ) -> dict:
        """合并三个数据源产出最终画像"""
        # 1. top_styles（行为信号 + 显式偏好合并）
        style_counter: Counter = behavior_data["style_counter"].copy()
        # 显式 like_styles 加权 2.0（用户明确表达的偏好权重更高）
        for style in preference_data.get("like_styles", []):
            self._add_weighted(style_counter, style, 2.0)
        # 浏览历史的 category 不直接作为 style，但可作为风格推断的辅助
        top_styles = [s for s, _ in style_counter.most_common(3)]

        # 2. top_colors
        color_counter: Counter = behavior_data["color_counter"].copy()
        top_colors = [c for c, _ in color_counter.most_common(3)]

        # 3. price_distribution
        prices = behavior_data["prices"]
        if prices:
            prices_sorted = sorted(prices)
            n = len(prices_sorted)
            median = prices_sorted[n // 2] if n % 2 == 1 else (prices_sorted[n // 2 - 1] + prices_sorted[n // 2]) / 2
            price_distribution = {
                "min": int(prices_sorted[0]),
                "median": int(median),
                "max": int(prices_sorted[-1]),
            }
        else:
            # 兜底用 user_preference 的 preferred_price_range
            pr = preference_data.get("preferred_price_range")
            if pr and len(pr) == 2:
                price_distribution = {"min": int(pr[0]), "median": int((pr[0] + pr[1]) / 2), "max": int(pr[1])}
            else:
                price_distribution = {"min": 0, "median": 0, "max": 0}

        # 4. style_vector（加权平均向量 + L2 归一化）
        # CLIP 向量本身 L2 归一化（模长=1），但加权平均后模长 ≤1，
        # 不归一化会导致节点1 融合时 style_vector 实际贡献权重 < 设计预期（1-α=0.3）
        vectors = behavior_data["vectors"]
        if vectors:
            total_weight = sum(w for _, w in vectors)
            if total_weight > 0:
                vec_dim = len(vectors[0][0])
                style_vector = [0.0] * vec_dim
                for vec, weight in vectors:
                    for i in range(vec_dim):
                        style_vector[i] += vec[i] * (weight / total_weight)
                # L2 归一化，使加权平均向量模长恢复为 1，匹配 Qdrant Cosine 距离
                norm = sum(x * x for x in style_vector) ** 0.5
                if norm > 0:
                    style_vector = [x / norm for x in style_vector]
            else:
                style_vector = []
        else:
            style_vector = []

        # 5. profile_confidence（§3.25.6）
        signal_count = behavior_data["signal_count"] + browse_data["browse_count"]
        signal_types = behavior_data["signal_types"]
        # 加入显式偏好作为信号类型
        if preference_data.get("dislike_colors") or preference_data.get("like_styles"):
            signal_types = signal_types | {"EXPLICIT_PREFERENCE"}
        confidence = min(1.0, (signal_count / 20) * 0.5 + (len(signal_types) / 4) * 0.5)

        # 6. dislike_colors / like_styles（透传显式偏好）
        dislike_colors = preference_data.get("dislike_colors", [])
        like_styles = preference_data.get("like_styles", [])

        return {
            "top_styles": top_styles,
            "top_colors": top_colors,
            "price_distribution": price_distribution,
            "style_vector": style_vector,
            "profile_confidence": round(confidence, 4),
            "dislike_colors": dislike_colors,
            "like_styles": like_styles,
        }

    @staticmethod
    def _add_weighted(counter: Counter, key: str, weight: float):
        """向 Counter 加权累加"""
        counter[key] = counter.get(key, 0) + weight

    @staticmethod
    def _empty_profile() -> dict:
        """空画像（聚合失败时返回，推荐工作流按原逻辑执行）"""
        return {
            "top_styles": [],
            "top_colors": [],
            "price_distribution": {"min": 0, "median": 0, "max": 0},
            "style_vector": [],
            "profile_confidence": 0.0,
            "dislike_colors": [],
            "like_styles": [],
        }


# ===== 单例管理（与 deps.py 风格一致）=====
_profile_service: ProfileService | None = None
_profile_lock = asyncio.Lock()


async def get_profile_service() -> ProfileService:
    """获取 ProfileService 单例

    依赖：Redis + QdrantClientWrapper（复用 get_qdrant_searcher 的 wrapper）
    """
    global _profile_service
    if _profile_service is None:
        async with _profile_lock:
            if _profile_service is None:
                from app.api.deps import get_redis, get_qdrant_searcher
                redis = await get_redis()
                # 确保 qdrant_wrapper 已初始化
                await get_qdrant_searcher()
                # 复用 deps 中的 _qdrant_wrapper
                from app.api.deps import _qdrant_wrapper
                _profile_service = ProfileService(redis, _qdrant_wrapper)
    return _profile_service
