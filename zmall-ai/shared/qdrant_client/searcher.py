"""
Qdrant 向量检索（搭配检索）

P1 优化：filter 加 stock>0 条件，避免召回缺货商品。
性别过滤扩展：filter 加 target_gender IN (user_gender, "unisex")，
避免跨性别推荐（男用户不推女款，女用户不推男款，中性款男女都可）。
"""
import logging
from qdrant_client.http.models import Filter, FieldCondition, MatchAny, MatchValue, Range

from shared.qdrant_client.client import COLLECTION_ITEM_STYLE, QdrantClientWrapper
from shared.qdrant_client.color_mapping import normalize_color_values

logger = logging.getLogger(__name__)

# score_threshold 参数化默认值
# CLIP v2 实测相似度分布通常在 0.2-0.4，原硬编码 0.5 偏严导致召回不足。
# 此处仅作为函数签名的兜底默认值；调用方未传时，优先读 settings.qdrant_score_threshold。
_DEFAULT_SCORE_THRESHOLD = 0.3


def _resolve_score_threshold(score_threshold: float | None) -> float:
    """解析最终的 score_threshold：显式传参 > settings 配置 > 兜底默认值 0.3"""
    if score_threshold is not None:
        return score_threshold
    try:
        from app.core.config import settings
        return getattr(settings, "qdrant_score_threshold", _DEFAULT_SCORE_THRESHOLD)
    except Exception:
        return _DEFAULT_SCORE_THRESHOLD


class QdrantSearcher:
    """商品向量检索器"""

    def __init__(self, client: QdrantClientWrapper):
        # 复用 wrapper 内部单例 QdrantClient，与 indexer/user_preference 等保持一致
        self.client = client.get_client()

    def search_complementary_items(
        self,
        query_vector: list[float],
        shop_ids: list[int] | None = None,
        category: str | None = None,
        color: list[str] | None = None,
        season: str | None = None,
        dislike_colors: list[str] | None = None,
        target_gender: str | None = None,
        limit: int = 5,
        score_threshold: float | None = None,
        strict_color: bool = False,
    ) -> list[dict]:
        """向量检索互补商品

        Args:
            query_vector: 查询向量（CLIP 1024维）
            shop_ids: 限定店铺列表（支持多选），None/空 则全平台
            category: 限定品类（英文枚举，如 tops/bottoms/shoes）
            color: 偏好色调列表（中文，如 ['白色','蓝色']）。默认用于扩大候选池后的软重排；
                   strict_color=True 时作为硬过滤。None/空 则不限
            season: 限定季节（spring/summer/autumn/winter），
                    匹配 payload.season IN (season, "all")，None 则不限
            dislike_colors: 不喜欢的颜色列表（Qdrant must_not 过滤），
                            命中这些颜色的商品会被排除。None 或空则不限
            target_gender: 用户/模特适用性别（male/female），用于硬过滤商品 target_gender。
                           匹配规则：payload.target_gender IN (target_gender, "unisex")，
                           即男用户推男款+中性款，女用户推女款+中性款。
                           None 时不过滤（向后兼容旧数据/未标注商品）。
            limit: 返回数量
            score_threshold: 相似度阈值。None 时读 settings.qdrant_score_threshold（默认 0.3），
                             避免原硬编码 0.5 偏严导致召回不足
            strict_color: 是否将用户明确选择的颜色作为硬过滤。默认 False，
                          画像推断颜色仍走软重排；候选不足时由上层显式降级为 False。
        Returns:
            商品列表 [{item_id, score, shop_id, category, color, season, style_tags,
                      price, stock, target_gender}, ...]
            cross_shop 字段由调用方（节点2）在跨店 fallback 时打标，本方法不设置。

        P1 优化：filter 加 stock>0 条件，避免召回缺货商品。
        旧数据无 stock 字段时 range 不命中（视为无库存），需全量入库脚本回填。

        性别过滤扩展：
        - target_gender 非空时硬过滤，确保不出现跨性别推荐
        - payload 无 target_gender 字段的旧数据会被排除（视为未标注，不参与推荐）
          → 需通过 reconcile_mysql_qdrant --fix-inconsistent 回填字段
        """
        must_conditions = [
            FieldCondition(key="is_active", match=MatchValue(value=True)),
            # P1 优化：库存大于 0 才推荐（避免推荐缺货商品）
            FieldCondition(key="stock", range=Range(gt=0)),
        ]
        if shop_ids:
            must_conditions.append(FieldCondition(key="shop_id", match=MatchAny(any=list(shop_ids))))
        if category is not None:
            must_conditions.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if season is not None:
            # 季节匹配：当前季节 或 全季可推（season="all"）
            must_conditions.append(FieldCondition(
                key="season",
                match=MatchAny(any=[season, "all"]),
            ))
        if target_gender is not None:
            # 性别过滤扩展：
            # 男用户 → 推 male + unisex；女用户 → 推 female + unisex
            # 避免男用户被推荐女款连衣裙、女用户被推荐男款西装等跨性别场景
            must_conditions.append(FieldCondition(
                key="target_gender",
                match=MatchAny(any=[target_gender, "unisex"]),
            ))

        preferred_colors = set(normalize_color_values(color))
        if strict_color and preferred_colors:
            # 明确勾选的颜色先作为硬约束，避免“黑/白”被语义相似度带偏到卡其、灰色。
            # 候选不足时由节点2再次以 strict_color=False 检索，保留可解释的放宽路径。
            must_conditions.append(FieldCondition(
                key="color",
                match=MatchAny(any=list(preferred_colors)),
            ))

        # 不喜欢的颜色 → must_not 排除
        must_not_conditions: list[FieldCondition] = []
        if dislike_colors:
            must_not_conditions.append(FieldCondition(
                key="color",
                match=MatchAny(any=list(dislike_colors)),
            ))

        # 颜色是软偏好而非硬条件。先取更大的语义候选池，再对命中偏好色的商品
        # 做稳定重排，避免 should 过滤在无同色商品时把整类结果清空。
        candidate_limit = max(limit * 5, 25) if preferred_colors else limit
        results = self.client.search(
            collection_name=COLLECTION_ITEM_STYLE,
            query_vector=query_vector,
            query_filter=Filter(must=must_conditions, must_not=must_not_conditions),
            limit=candidate_limit,
            score_threshold=_resolve_score_threshold(score_threshold),
        )
        items = [
            {
                "item_id": hit.payload.get("item_id"),
                "score": hit.score,
                "shop_id": hit.payload.get("shop_id"),
                "category": hit.payload.get("category"),
                "color": hit.payload.get("color"),
                "season": hit.payload.get("season"),
                "style_tags": hit.payload.get("style_tags", []),
                "price": hit.payload.get("price"),
                "stock": hit.payload.get("stock", 0),
                "target_gender": hit.payload.get("target_gender"),
            }
            for hit in results
        ]
        if preferred_colors:
            def rerank_score(item: dict) -> float:
                matched = preferred_colors.intersection(normalize_color_values(item.get("color")))
                semantic_score = float(item.get("score") or 0.0)
                return semantic_score + (0.05 if matched else 0.0)

            items.sort(
                key=rerank_score,
                reverse=True,
            )
        return items[:limit]
