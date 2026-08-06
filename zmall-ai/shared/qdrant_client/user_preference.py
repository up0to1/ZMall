"""
用户偏好持久化（Qdrant user_preference collection）

跨会话记忆用户偏好：
- dislike_colors: 不喜欢的颜色（累积）
- dislike_styles: 不喜欢的风格（累积）
- like_styles: 喜欢的风格（accept 时累积）
- preferred_price_range: 常买价格区间 [min, max]

设计：
- 用 user_id 作为 point_id（唯一）
- 向量用 user_id 哈希占位（P2 可换成行为向量）
- payload 存偏好字段
- 读写都容错：失败不阻塞主流程

upsert_preference 用 Redis 分布式锁串行化同一用户的偏好更新，
避免并发反馈"读-改-写"导致先写的偏好被后写覆盖。
"""
import asyncio
import hashlib
import logging
from datetime import datetime

from qdrant_client.http.models import PointStruct, VectorParams, Distance

from shared.qdrant_client.client import QdrantClientWrapper

logger = logging.getLogger(__name__)

COLLECTION_USER_PREFERENCE = "zmall_user_preference"

# 占位向量维度（与 item_style 一致，jina-clip-v2 原生 1024 维）
_PREFERENCE_VECTOR_DIM = 1024

# 偏好更新分布式锁 Key 前缀
_PREF_LOCK_PREFIX = "lock:user_preference:"


def _user_id_to_vector(user_id: int) -> list[float]:
    """user_id 哈希为占位向量（P2 可换成行为向量）"""
    h = hashlib.md5(f"user:{user_id}".encode()).digest()
    # 重复哈希字节填满 1024 维
    vec = []
    for i in range(_PREFERENCE_VECTOR_DIM):
        vec.append((h[i % 16] / 255.0) * 2 - 1)  # 归一化到 [-1, 1]
    return vec


class UserPreferenceReader:
    """用户偏好读取器（首轮推荐时调用）"""

    def __init__(self, client_wrapper: QdrantClientWrapper):
        self.client = client_wrapper.get_client()

    def get_preference(self, user_id: int) -> dict | None:
        """读取用户偏好，失败返回 None（不抛异常）

        Returns:
            {dislike_colors, dislike_styles, like_styles, preferred_price_range, last_updated}
            或 None（无记录或读取失败）
        """
        try:
            # 用 user_id 作 point_id 直接 retrieve
            try:
                points = self.client.retrieve(
                    collection_name=COLLECTION_USER_PREFERENCE,
                    ids=[str(user_id)],
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception:
                # retrieve 失败时尝试 scroll + payload 过滤兜底
                from qdrant_client.http.models import Filter, FieldCondition, MatchValue
                points = self.client.scroll(
                    collection_name=COLLECTION_USER_PREFERENCE,
                    scroll_filter=Filter(must=[
                        FieldCondition(key="user_id", match=MatchValue(value=user_id))
                    ]),
                    limit=1,
                    with_payload=True,
                    with_vectors=False,
                )[0]

            if not points:
                return None

            payload = points[0].payload or {}
            return {
                "dislike_colors": payload.get("dislike_colors", []),
                "dislike_styles": payload.get("dislike_styles", []),
                "like_styles": payload.get("like_styles", []),
                "preferred_price_range": payload.get("preferred_price_range"),
                "last_updated": payload.get("last_updated"),
            }
        except Exception as e:
            logger.warning("读取用户偏好失败（不影响主流程）: userId=%s, error=%s", user_id, e)
            return None


class UserPreferenceUpdater:
    """用户偏好写入器（feedback 接口异步调用）"""

    def __init__(self, client_wrapper: QdrantClientWrapper, redis=None):
        """
        Args:
            client_wrapper: Qdrant 客户端封装
            redis: Redis 连接（可选，用于分布式锁保证 upsert 原子性）
        """
        self.client = client_wrapper.get_client()
        self._redis = redis

    def ensure_collection(self):
        """启动时确保 user_preference collection 及 user_id 索引存在

        Qdrant Cloud 要求 scroll filter 涉及的字段必须有索引，
        retrieve 失败兜底走 scroll 时会按 user_id(integer) 过滤。
        """
        try:
            collections = {c.name for c in self.client.get_collections().collections}
            if COLLECTION_USER_PREFERENCE not in collections:
                self.client.create_collection(
                    collection_name=COLLECTION_USER_PREFERENCE,
                    vectors_config=VectorParams(
                        size=_PREFERENCE_VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Qdrant Collection 已创建: %s", COLLECTION_USER_PREFERENCE)
            # 幂等补建 user_id 索引（兜底 scroll 按 user_id integer 过滤）
            try:
                self.client.create_payload_index(
                    collection_name=COLLECTION_USER_PREFERENCE,
                    field_name="user_id",
                    field_schema="integer",
                )
            except Exception as e:
                if "already" not in str(e).lower():
                    logger.debug("user_preference user_id 索引已存在或跳过: %s", e)
        except Exception as e:
            logger.warning("创建 user_preference collection 失败: %s", e)

    async def upsert_preference(
        self,
        user_id: int,
        dislike_colors: list[str] | None = None,
        dislike_styles: list[str] | None = None,
        like_styles: list[str] | None = None,
        preferred_price_range: list | None = None,
    ) -> bool:
        """合并 upsert 用户偏好（与已有记录合并去重）

        改为 async 方法，用 Redis 分布式锁串行化同一用户的偏好更新，
        避免"读-改-写"竞态导致先写的偏好被后写覆盖。
        redis 未注入时降级为非原子逻辑（向后兼容）。

        Returns:
            True 成功，False 失败（不抛异常）
        """
        # redis 可用时用分布式锁保证原子性
        if self._redis is not None:
            return await self._upsert_with_lock(
                user_id, dislike_colors, dislike_styles,
                like_styles, preferred_price_range,
            )
        # 降级：无 redis 时走原同步逻辑（非原子，向后兼容）
        return await asyncio.to_thread(
            self._upsert_inner,
            user_id, dislike_colors, dislike_styles,
            like_styles, preferred_price_range,
        )

    async def _upsert_with_lock(
        self, user_id, dislike_colors, dislike_styles,
        like_styles, preferred_price_range,
    ) -> bool:
        """带分布式锁的 upsert"""
        from shared.distributed_lock import DistributedLock
        lock_key = f"{_PREF_LOCK_PREFIX}{user_id}"
        try:
            async with DistributedLock(self._redis, lock_key, wait_timeout=3, lease_timeout=10):
                return await asyncio.to_thread(
                    self._upsert_inner,
                    user_id, dislike_colors, dislike_styles,
                    like_styles, preferred_price_range,
                )
        except Exception as e:
            logger.warning("upsert 用户偏好获取锁失败（降级直写）: userId=%s, error=%s", user_id, e)
            return await asyncio.to_thread(
                self._upsert_inner,
                user_id, dislike_colors, dislike_styles,
                like_styles, preferred_price_range,
            )

    def _upsert_inner(
        self,
        user_id: int,
        dislike_colors: list[str] | None,
        dislike_styles: list[str] | None,
        like_styles: list[str] | None,
        preferred_price_range: list | None,
    ) -> bool:
        """实际的读-改-写逻辑（同步，在线程池中执行）"""
        try:
            # 1. 读取现有偏好
            existing = self._read_existing(user_id)
            merged_dislike_colors = self._merge_unique(
                existing.get("dislike_colors", []), dislike_colors
            )
            merged_dislike_styles = self._merge_unique(
                existing.get("dislike_styles", []), dislike_styles
            )
            merged_like_styles = self._merge_unique(
                existing.get("like_styles", []), like_styles
            )
            # 价格区间：取交集（更窄），无交集时取新值
            merged_price_range = self._merge_price_range(
                existing.get("preferred_price_range"), preferred_price_range
            )

            # 2. upsert
            payload = {
                "user_id": user_id,
                "dislike_colors": merged_dislike_colors,
                "dislike_styles": merged_dislike_styles,
                "like_styles": merged_like_styles,
                "preferred_price_range": merged_price_range,
                "last_updated": datetime.now().isoformat(),
            }
            self.client.upsert(
                collection_name=COLLECTION_USER_PREFERENCE,
                points=[
                    PointStruct(
                        id=str(user_id),  # 用 user_id 作 point_id（字符串）
                        vector=_user_id_to_vector(user_id),
                        payload=payload,
                    )
                ],
            )
            logger.info(
                "用户偏好已 upsert: userId=%s, dislikeColors=%s, dislikeStyles=%s, "
                "likeStyles=%s, priceRange=%s",
                user_id, merged_dislike_colors, merged_dislike_styles,
                merged_like_styles, merged_price_range,
            )
            return True
        except Exception as e:
            logger.warning("upsert 用户偏好失败（不阻塞主流程）: userId=%s, error=%s", user_id, e)
            return False

    def _read_existing(self, user_id: int) -> dict:
        """读取现有偏好（内部用，失败返回空 dict）"""
        try:
            points = self.client.retrieve(
                collection_name=COLLECTION_USER_PREFERENCE,
                ids=[str(user_id)],
                with_payload=True,
                with_vectors=False,
            )
            if points:
                return points[0].payload or {}
        except Exception as e:
            logger.debug("读取现有偏好失败（可能首次写入）: userId=%s, error=%s", user_id, e)
        return {}

    @staticmethod
    def _merge_unique(existing: list[str], new: list[str] | None) -> list[str]:
        """合并两个列表，去重保序"""
        if not new:
            return existing or []
        merged = list(dict.fromkeys((existing or []) + new))
        return merged

    @staticmethod
    def _merge_price_range(
        existing: list | None, new: list | None
    ) -> list | None:
        """合并价格区间：取交集（更窄），无交集时取新值"""
        if not new:
            return existing
        if not existing:
            return new
        # 取交集：max(min) ~ min(max)
        new_min = max(existing[0], new[0])
        new_max = min(existing[1], new[1])
        if new_min <= new_max:
            return [new_min, new_max]
        return new  # 无交集，取新值
