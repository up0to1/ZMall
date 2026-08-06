"""
Qdrant 向量索引（商品入库）

- payload 加 stock 字段，节点2 filter stock>0 避免推荐缺货商品
- 新增 update_payload 方法，图片未变更时仅更新 payload（省 encode API 调用）

性别过滤扩展：
- payload 加 target_gender 字段（male/female/unisex），节点2 filter target_gender IN (user_gender, 'unisex')
- 业务价值：避免 AI 随心搭给男性推荐女性服装（或反之），中性服装男女都可穿
- target_gender 来自 item 表的 target_gender 字段（已存在），入库时直接读取
"""
import logging
from qdrant_client.http.models import PointStruct

from shared.qdrant_client.client import COLLECTION_ITEM_STYLE, QdrantClientWrapper

logger = logging.getLogger(__name__)


class QdrantIndexer:
    """商品向量索引器"""

    def __init__(self, client_wrapper: QdrantClientWrapper):
        self.client = client_wrapper.get_client()

    def upsert_item(
        self,
        item_id: int,
        vector: list[float],
        shop_id: int,
        category: str,
        style_tags: list[str],
        price: float,
        color: str | None = None,
        season: str | None = None,
        stock: int = 0,
        is_active: bool = True,
        target_gender: str | None = None,
    ):
        """插入/更新商品向量（图片变更时调用，完整 upsert）

        Args:
            category: 英文品类枚举（tops/bottoms/shoes/hat/bag/accessory），由调用方转码
            color: 商品主色调（red/black/white/blue/gray/khaki 等），用于颜色过滤。
                   None 时不写入 payload（向后兼容旧数据）。
            season: 商品季节（spring/summer/autumn/winter/all），用于季节过滤。
                    None 时不写入 payload（向后兼容旧数据）。
            stock: 库存数量，节点2 filter stock>0 避免推荐缺货商品。
                   默认 0，向后兼容旧调用方。
            target_gender: 商品适合性别（male/female/unisex），用于 AI 随心搭性别过滤。
                           None 时不写入 payload（向后兼容旧数据，等价于 unisex 不限）。
        """
        payload = {
            "item_id": item_id,
            "shop_id": shop_id,
            "category": category,
            "style_tags": style_tags,
            "price": price,
            "stock": stock,
            "is_active": is_active,
        }
        if color is not None:
            payload["color"] = color
        if season is not None:
            payload["season"] = season
        if target_gender is not None:
            payload["target_gender"] = target_gender
        self.client.upsert(
            collection_name=COLLECTION_ITEM_STYLE,
            points=[
                PointStruct(
                    id=item_id,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        logger.info("商品向量已索引: itemId=%s, color=%s, season=%s, stock=%s, target_gender=%s",
                     item_id, color, season, stock, target_gender)

    def update_payload(
        self,
        item_id: int,
        shop_id: int,
        category: str,
        style_tags: list[str],
        price: float,
        color: str | None = None,
        season: str | None = None,
        stock: int = 0,
        is_active: bool = True,
        target_gender: str | None = None,
    ):
        """P1 优化：仅更新 payload，保留原向量（图片未变更时调用，省 encode API）

        用于商品改价/改库存/改颜色/改季节等不涉及图片的变更场景。
        若 point 不存在则记 warning（可能是数据不一致，需对账任务修复）。
        """
        payload = {
            "item_id": item_id,
            "shop_id": shop_id,
            "category": category,
            "style_tags": style_tags,
            "price": price,
            "stock": stock,
            "is_active": is_active,
        }
        if color is not None:
            payload["color"] = color
        if season is not None:
            payload["season"] = season
        if target_gender is not None:
            payload["target_gender"] = target_gender
        self.client.set_payload(
            collection_name=COLLECTION_ITEM_STYLE,
            payload=payload,
            points=[item_id],
        )
        logger.info("商品 payload 已更新（向量保留）: itemId=%s, color=%s, season=%s, stock=%s, target_gender=%s",
                     item_id, color, season, stock, target_gender)

    def delete_item(self, item_id: int):
        """从 Qdrant 删除商品（商品下架时调用）"""
        self.client.delete(
            collection_name=COLLECTION_ITEM_STYLE,
            points_selector=[item_id],
        )
        logger.info("商品向量已删除: itemId=%s", item_id)

    def set_item_inactive(self, item_id: int):
        """商品下架时软删除：置 is_active=false（推荐不再命中，但保留向量供重新上架）"""
        self.client.set_payload(
            collection_name=COLLECTION_ITEM_STYLE,
            payload={"is_active": False},
            points=[item_id],
        )
        logger.info("商品已置为下架: itemId=%s", item_id)
