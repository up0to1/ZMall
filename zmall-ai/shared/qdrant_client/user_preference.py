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
import uuid
from datetime import datetime
from typing import Any

from qdrant_client.http.models import PointStruct, VectorParams, Distance

from shared.qdrant_client.client import QdrantClientWrapper

logger = logging.getLogger(__name__)

COLLECTION_USER_PREFERENCE = "zmall_user_preference"

# 占位向量维度（与 item_style 的 DashScope text-embedding-v4 1024 维配置一致）
_PREFERENCE_VECTOR_DIM = 1024

# 偏好更新分布式锁 Key 前缀
_PREF_LOCK_PREFIX = "lock:user_preference:"
_PROFILE_CACHE_PREFIX = "ai:profile:user:"

MEMORY_STATUS_ACTIVE = "active"
MEMORY_STATUS_SUPERSEDED = "superseded"


def _new_memory(
    kind: str,
    value: Any,
    source: str,
    confidence: float = 1.0,
    supersedes: str | None = None,
) -> dict:
    """创建一条可审计的显式偏好记忆。"""
    memory = {
        "memory_id": f"pref_{uuid.uuid4().hex}",
        "kind": kind,
        "value": value,
        "source": source,
        "timestamp": datetime.now().isoformat(),
        "confidence": float(confidence),
        "status": MEMORY_STATUS_ACTIVE,
    }
    if supersedes:
        memory["supersedes"] = supersedes
    return memory


def _legacy_memory_records(payload: dict) -> list[dict]:
    """把旧版按数组保存的偏好转换成内存中的记忆记录。"""
    timestamp = payload.get("last_updated") or datetime.now().isoformat()
    records: list[dict] = []
    for field, kind in (
        ("dislike_colors", "dislike_color"),
        ("dislike_styles", "dislike_style"),
        ("like_styles", "like_style"),
    ):
        for index, value in enumerate(payload.get(field) or []):
            records.append({
                "memory_id": f"legacy_{kind}_{index}",
                "kind": kind,
                "value": value,
                "source": "legacy_migration",
                "timestamp": timestamp,
                "confidence": 0.5,
                "status": MEMORY_STATUS_ACTIVE,
            })
    price_range = payload.get("preferred_price_range")
    if price_range:
        records.append({
            "memory_id": "legacy_preferred_price_range",
            "kind": "preferred_price_range",
            "value": price_range,
            "source": "legacy_migration",
            "timestamp": timestamp,
            "confidence": 0.5,
            "status": MEMORY_STATUS_ACTIVE,
        })
    return records


def _memory_records(payload: dict) -> list[dict]:
    records = payload.get("memory_records")
    if not isinstance(records, list):
        records = _legacy_memory_records(payload)
    return [dict(record) for record in records if isinstance(record, dict)]


def _active_memory_records(records: list[dict]) -> list[dict]:
    active = []
    for record in records:
        if record.get("status", MEMORY_STATUS_ACTIVE) != MEMORY_STATUS_ACTIVE:
            continue
        try:
            if float(record.get("confidence", 1.0)) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        active.append(record)
    return active


def _preference_fields(records: list[dict]) -> dict:
    fields = {
        "dislike_colors": [],
        "dislike_styles": [],
        "like_styles": [],
        "preferred_price_range": None,
    }
    for record in _active_memory_records(records):
        kind = record.get("kind")
        value = record.get("value")
        if kind == "dislike_color" and value not in fields["dislike_colors"]:
            fields["dislike_colors"].append(value)
        elif kind == "dislike_style" and value not in fields["dislike_styles"]:
            fields["dislike_styles"].append(value)
        elif kind == "like_style" and value not in fields["like_styles"]:
            fields["like_styles"].append(value)
        elif kind == "preferred_price_range":
            fields["preferred_price_range"] = value
    return fields


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
            records = _memory_records(payload)
            return {
                **_preference_fields(records),
                "memory_records": _active_memory_records(records),
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
            success = await self._upsert_with_lock(
                user_id, dislike_colors, dislike_styles,
                like_styles, preferred_price_range,
            )
        else:
            # 降级：无 redis 时走原同步逻辑（非原子，向后兼容）
            success = await asyncio.to_thread(
                self._upsert_inner,
                user_id, dislike_colors, dislike_styles,
                like_styles, preferred_price_range,
            )
        if success:
            await self._invalidate_profile_cache(user_id)
        return success

    async def correct_preference(
        self,
        user_id: int,
        memory_id: str,
        replacement: dict | None = None,
        reason: str | None = None,
    ) -> bool:
        """弃用旧偏好并可选写入一条替代偏好。

        旧记录不物理删除，召回端只读取 active 记录，便于审计和回溯。
        replacement 形如 {"kind": "dislike_color", "value": "黑色"}。
        """
        if self._redis is not None:
            success = await self._correct_with_lock(
                user_id, memory_id, replacement, reason,
            )
        else:
            success = await asyncio.to_thread(
                self._correct_inner,
                user_id, memory_id, replacement, reason,
            )
        if success:
            await self._invalidate_profile_cache(user_id)
        return success

    async def correct_preference_by_value(
        self,
        user_id: int,
        kind: str,
        old_value: Any,
        replacement: dict | None = None,
        reason: str | None = None,
    ) -> bool:
        """按旧记忆内容纠错，供自然语言反馈无法拿到 memory_id 时使用。"""
        if self._redis is not None:
            success = await self._correct_by_value_with_lock(
                user_id, kind, old_value, replacement, reason,
            )
        else:
            success = await asyncio.to_thread(
                self._correct_by_value_inner,
                user_id, kind, old_value, replacement, reason,
            )
        if success:
            await self._invalidate_profile_cache(user_id)
        return success

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

    async def _correct_with_lock(
        self, user_id: int, memory_id: str,
        replacement: dict | None, reason: str | None,
    ) -> bool:
        """带分布式锁的偏好纠错。"""
        from shared.distributed_lock import DistributedLock
        lock_key = f"{_PREF_LOCK_PREFIX}{user_id}"
        try:
            async with DistributedLock(self._redis, lock_key, wait_timeout=3, lease_timeout=10):
                return await asyncio.to_thread(
                    self._correct_inner, user_id, memory_id, replacement, reason,
                )
        except Exception as e:
            logger.warning("correct_preference 获取锁失败: userId=%s, error=%s", user_id, e)
            return await asyncio.to_thread(
                self._correct_inner, user_id, memory_id, replacement, reason,
            )

    async def _correct_by_value_with_lock(
        self, user_id: int, kind: str, old_value: Any,
        replacement: dict | None, reason: str | None,
    ) -> bool:
        from shared.distributed_lock import DistributedLock
        lock_key = f"{_PREF_LOCK_PREFIX}{user_id}"
        try:
            async with DistributedLock(self._redis, lock_key, wait_timeout=3, lease_timeout=10):
                return await asyncio.to_thread(
                    self._correct_by_value_inner,
                    user_id, kind, old_value, replacement, reason,
                )
        except Exception as e:
            logger.warning("按值纠正用户偏好获取锁失败: userId=%s, error=%s", user_id, e)
            return await asyncio.to_thread(
                self._correct_by_value_inner,
                user_id, kind, old_value, replacement, reason,
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
            existing = self._read_existing(user_id)
            records = _memory_records(existing)
            active = _active_memory_records(records)

            for value in dislike_colors or []:
                self._append_if_new(records, active, "dislike_color", value)
            for value in dislike_styles or []:
                self._append_if_new(records, active, "dislike_style", value)
            for value in like_styles or []:
                self._append_if_new(records, active, "like_style", value)

            if preferred_price_range:
                current = _preference_fields(records).get("preferred_price_range")
                merged = self._merge_price_range(current, preferred_price_range)
                # 价格偏好是单值事实，新值覆盖旧值但保留旧记录审计链。
                for record in records:
                    if (record.get("kind") == "preferred_price_range"
                            and record.get("status", MEMORY_STATUS_ACTIVE) == MEMORY_STATUS_ACTIVE):
                        self._supersede_record(record, "price preference updated")
                records.append(_new_memory(
                    "preferred_price_range", merged, "explicit_feedback",
                ))

            self._write_records(user_id, records)
            fields = _preference_fields(records)
            logger.info(
                "用户偏好已 upsert: userId=%s, dislikeColors=%s, dislikeStyles=%s, "
                "likeStyles=%s, priceRange=%s",
                user_id, fields["dislike_colors"], fields["dislike_styles"],
                fields["like_styles"], fields["preferred_price_range"],
            )
            return True
        except Exception as e:
            logger.warning("upsert 用户偏好失败（不阻塞主流程）: userId=%s, error=%s", user_id, e)
            return False

    def _correct_inner(
        self,
        user_id: int,
        memory_id: str,
        replacement: dict | None,
        reason: str | None,
    ) -> bool:
        """同步执行偏好纠错，供 async 外层在线程池中调用。"""
        try:
            existing = self._read_existing(user_id)
            records = _memory_records(existing)
            target = next(
                (
                    record for record in records
                    if record.get("memory_id") == memory_id
                    and record.get("status", MEMORY_STATUS_ACTIVE) == MEMORY_STATUS_ACTIVE
                ),
                None,
            )
            if target is None:
                return False

            replacement_data = self._validate_replacement(replacement)
            if replacement is not None and replacement_data is None:
                return False

            self._supersede_record(target, reason or "corrected by user")
            if replacement_data is not None:
                kind, value, confidence = replacement_data
                records.append(_new_memory(
                    kind,
                    value,
                    "user_correction",
                    confidence=confidence,
                    supersedes=memory_id,
                ))
            self._write_records(user_id, records)
            return True
        except Exception as e:
            logger.warning(
                "纠正用户偏好失败（不阻塞主流程）: userId=%s, memoryId=%s, error=%s",
                user_id, memory_id, e,
            )
            return False

    def _correct_by_value_inner(
        self,
        user_id: int,
        kind: str,
        old_value: Any,
        replacement: dict | None,
        reason: str | None,
    ) -> bool:
        try:
            existing = self._read_existing(user_id)
            records = _memory_records(existing)
            target = next(
                (
                    record for record in reversed(records)
                    if record.get("kind") == kind
                    and record.get("value") == old_value
                    and record.get("status", MEMORY_STATUS_ACTIVE) == MEMORY_STATUS_ACTIVE
                ),
                None,
            )
            if target is None:
                return False
            memory_id = target.get("memory_id")

            replacement_data = self._validate_replacement(replacement)
            if replacement is not None and replacement_data is None:
                return False

            self._supersede_record(target, reason or "corrected by user")
            if replacement_data is not None:
                replacement_kind, value, confidence = replacement_data
                records.append(_new_memory(
                    replacement_kind,
                    value,
                    "user_correction",
                    confidence=confidence,
                    supersedes=memory_id,
                ))
            self._write_records(user_id, records)
            return True
        except Exception as e:
            logger.warning(
                "按值纠正用户偏好失败: userId=%s, kind=%s, error=%s",
                user_id, kind, e,
            )
            return False

    @staticmethod
    def _append_if_new(records: list[dict], active: list[dict], kind: str, value: Any) -> None:
        if any(record.get("kind") == kind and record.get("value") == value for record in active):
            return
        records.append(_new_memory(kind, value, "explicit_feedback"))
        active.append(records[-1])

    @staticmethod
    def _supersede_record(record: dict, reason: str) -> None:
        record["status"] = MEMORY_STATUS_SUPERSEDED
        record["superseded_at"] = datetime.now().isoformat()
        record["superseded_reason"] = reason

    @staticmethod
    def _validate_replacement(replacement: dict | None) -> tuple[str, Any, float] | None:
        """校验替代记忆，确保校验失败不会先修改旧记忆状态。"""
        if replacement is None:
            return None
        if not isinstance(replacement, dict):
            return None
        kind = replacement.get("kind")
        if not kind or "value" not in replacement:
            return None
        try:
            confidence = float(replacement.get("confidence", 1.0))
        except (TypeError, ValueError):
            return None
        if confidence <= 0:
            return None
        return str(kind), replacement["value"], confidence

    def _write_records(self, user_id: int, records: list[dict]) -> None:
        fields = _preference_fields(records)
        payload = {
            "user_id": user_id,
            **fields,
            "memory_records": records,
            "last_updated": datetime.now().isoformat(),
        }
        self.client.upsert(
            collection_name=COLLECTION_USER_PREFERENCE,
            points=[
                PointStruct(
                    id=str(user_id),
                    vector=_user_id_to_vector(user_id),
                    payload=payload,
                )
            ],
        )

    async def _invalidate_profile_cache(self, user_id: int) -> None:
        """偏好变化后主动失效派生画像，下一次推荐懒加载重算。"""
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"{_PROFILE_CACHE_PREFIX}{user_id}")
        except Exception as e:
            logger.warning("失效用户画像缓存失败: userId=%s, error=%s", user_id, e)

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
