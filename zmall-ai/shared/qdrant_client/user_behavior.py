"""
用户行为向量索引器（Phase 2.5，Qdrant zmall_user_behavior collection）

将用户行为事件（ITEM_VIEW/CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT）写入 Qdrant，
用于画像聚合服务（profile_service.py）的个性化推荐增强。

Collection 设计：
  - 向量维度：1024（jina-clip-v2 商品图向量）
  - 距离度量：Cosine
  - point_id：ub_{userId}_{itemId}_{timestamp}（唯一标识一次行为）

Payload 结构：
  {
    "user_id": 123,
    "item_id": 10001,
    "type": "ITEM_VIEW",         # 4 类事件枚举
    "timestamp": "2026-07-28T10:00:00",
    "category": "上衣",           # 中文品类（与商品库一致）
    "color": "black",
    "price": 199.00,
    "shop_id": 200,
    "style_tags": ["通勤", "简约"],
    "is_cross_gender": false     # 是否跨性别浏览/购买
  }

性别对齐检查（§2.10.3）：
  - 商品 target_gender 与用户性别冲突时，不写入向量，仅写入 payload（is_cross_gender=true）
  - 此类记录仅用于 family_buy_profile 判断，不参与主推荐画像的 style_vector 聚合
"""
import hashlib
import logging
from datetime import datetime

from qdrant_client.http.models import PointStruct, VectorParams, Distance

from shared.qdrant_client.client import QdrantClientWrapper

logger = logging.getLogger(__name__)

COLLECTION_USER_BEHAVIOR = "zmall_user_behavior"
_BEHAVIOR_VECTOR_DIM = 1024  # jina-clip-v2 原生维度


class UserBehaviorIndexer:
    """用户行为向量索引器（写入 Qdrant user_behavior collection）

    线程安全：同步 Qdrant HTTP 客户端，可在 MQ Consumer 线程中使用。
    """

    def __init__(self, client_wrapper: QdrantClientWrapper):
        self.client = client_wrapper.get_client()

    def ensure_collection(self):
        """启动时确保 user_behavior collection 存在"""
        try:
            collections = {c.name for c in self.client.get_collections().collections}
            if COLLECTION_USER_BEHAVIOR not in collections:
                self.client.create_collection(
                    collection_name=COLLECTION_USER_BEHAVIOR,
                    vectors_config=VectorParams(
                        size=_BEHAVIOR_VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Qdrant Collection 已创建: %s", COLLECTION_USER_BEHAVIOR)
        except Exception as e:
            logger.warning("创建 user_behavior collection 失败: %s", e)

    def index_behavior(
        self,
        user_id: int,
        item_id: int,
        behavior_type: str,
        timestamp: str,
        category: str | None = None,
        color: str | None = None,
        price: float | None = None,
        shop_id: int | None = None,
        style_tags: list[str] | None = None,
        item_gender: str | None = None,
        user_gender: str | None = None,
        vector: list[float] | None = None,
    ) -> bool:
        """写入一条用户行为记录到 Qdrant

        Args:
            user_id: 用户 ID
            item_id: 商品 ID
            behavior_type: 行为类型（ITEM_VIEW/CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT）
            timestamp: ISO 格式时间戳
            category: 商品品类（中文，如"上衣"）
            color: 商品颜色
            price: 商品价格
            shop_id: 店铺 ID
            style_tags: 风格标签列表
            item_gender: 商品性别（male/female/unisex）
            user_gender: 用户性别（male/female）
            vector: 商品图 CLIP 向量（1024 维）。None 时不写入向量。

        Returns:
            True 成功，False 失败（不抛异常）
        """
        try:
            # 性别对齐检查
            is_cross_gender = self._check_gender_alignment(item_gender, user_gender)

            # 跨性别且非 unisex：不写入向量（仅提取中性属性）
            actual_vector = vector if not is_cross_gender else None

            # 生成唯一 point_id
            point_id = f"ub_{user_id}_{item_id}_{behavior_type}_{timestamp.replace(':', '-').replace('.', '-')}"

            payload = {
                "user_id": user_id,
                "item_id": item_id,
                "type": behavior_type,
                "timestamp": timestamp,
                "category": category,
                "color": color,
                "price": price,
                "shop_id": shop_id,
                "style_tags": style_tags or [],
                "is_cross_gender": is_cross_gender,
            }

            # 如果没有向量（跨性别或未编码），用占位向量（Qdrant 要求 vector 或 sparse_vector 至少一个）
            # 实际上 Qdrant 支持 point 不带 vector（仅 payload），但需要 collection 配置允许多向量
            # 简化处理：跨性别时用零向量，聚合时按 is_cross_gender 过滤
            if actual_vector is None:
                actual_vector = [0.0] * _BEHAVIOR_VECTOR_DIM

            self.client.upsert(
                collection_name=COLLECTION_USER_BEHAVIOR,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=actual_vector,
                        payload=payload,
                    )
                ],
            )
            logger.info(
                "用户行为已索引: userId=%s, itemId=%s, type=%s, crossGender=%s",
                user_id, item_id, behavior_type, is_cross_gender,
            )
            return True
        except Exception as e:
            logger.warning(
                "索引用户行为失败（不阻塞主流程）: userId=%s, itemId=%s, type=%s, error=%s",
                user_id, item_id, behavior_type, e,
            )
            return False

    @staticmethod
    def _check_gender_alignment(item_gender: str | None, user_gender: str | None) -> bool:
        """检查商品性别与用户性别是否对齐

        Returns:
            True 表示跨性别（不对齐），False 表示对齐
        """
        if not item_gender or not user_gender:
            return False  # 信息不全时不标记
        if item_gender == "unisex":
            return False  # 中性款始终对齐
        return item_gender != user_gender
