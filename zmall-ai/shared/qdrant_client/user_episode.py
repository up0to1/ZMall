"""
用户搭配事件存储（EpisodicMemory，O3 优化）

跨会话记忆用户每次搭配会话的事件：
- accept 时写入：记录用户采纳的搭配（itemId 列表 + 风格 + 场景 + 时间）
- 下次进入"AI 随心搭"时读取最近 N 条事件，作为"上次推荐回顾"输入到 LLM prompt
- 业务价值：提升复购率（"基于您上次偏好，这次为您推荐..."）

设计：
- Collection 名：zmall_user_episode（一个用户多条记录，按时间序列）
- point_id：uuid（每次 accept 一个新 point，不覆盖）
- 向量：用 style_tags 文本编码向量（支持"相似风格"检索，P2 可扩展）
- payload：user_id + accepted_items + style_tags + scene_desc + season + task_id + timestamp
- 查询：按 user_id scroll + 按 timestamp 降序，取最近 5 条
"""
import logging
import uuid
from datetime import datetime

from qdrant_client.http.models import (
    PointStruct, VectorParams, Distance, Filter, FieldCondition, MatchValue,
)

from shared.qdrant_client.client import QdrantClientWrapper

logger = logging.getLogger(__name__)

COLLECTION_USER_EPISODE = "zmall_user_episode"

# 占位向量维度（与 item_style 的 DashScope text-embedding-v4 1024 维配置一致）
_EPISODE_VECTOR_DIM = 1024

# 读取最近 N 条搭配事件（避免一次拉太多）
MAX_EPISODES_TO_READ = 5


def _episode_to_vector() -> list[float]:
    """占位向量（P2 可换成 style_tags 文本编码向量做相似风格检索）

    当前用零向量：episode 主要按 user_id + timestamp 查询，不依赖向量相似度。
    """
    return [0.0] * _EPISODE_VECTOR_DIM


class UserEpisodeStore:
    """用户搭配事件存储器（跨会话长期记忆）"""

    def __init__(self, client_wrapper: QdrantClientWrapper):
        self.client = client_wrapper.get_client()

    def ensure_collection(self):
        """启动时确保 user_episode collection 及 user_id 索引存在

        Qdrant Cloud 要求 scroll filter 涉及的字段必须有索引，
        因此无论 collection 是否新建，都幂等补建 user_id 索引。
        """
        try:
            collections = {c.name for c in self.client.get_collections().collections}
            if COLLECTION_USER_EPISODE not in collections:
                self.client.create_collection(
                    collection_name=COLLECTION_USER_EPISODE,
                    vectors_config=VectorParams(
                        size=_EPISODE_VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Qdrant Collection 已创建: %s", COLLECTION_USER_EPISODE)
            # 幂等补建 user_id 索引（collection 已存在但缺索引时也需补建）
            # Qdrant 要求 integer 类型索引（filter value 是 int）
            try:
                self.client.create_payload_index(
                    collection_name=COLLECTION_USER_EPISODE,
                    field_name="user_id",
                    field_schema="integer",
                )
            except Exception as e:
                if "already" not in str(e).lower():
                    logger.debug("user_episode user_id 索引已存在或跳过: %s", e)
            try:
                self.client.create_payload_index(
                    collection_name=COLLECTION_USER_EPISODE,
                    field_name="task_id",
                    field_schema="keyword",
                )
            except Exception as e:
                if "already" not in str(e).lower():
                    logger.debug("user_episode task_id 索引已存在或跳过: %s", e)
        except Exception as e:
            logger.warning("创建 user_episode collection 失败: %s", e)

    def add_episode(
        self,
        user_id: int,
        task_id: str,
        accepted_items: list[dict],
        style_tags: list[str] | None = None,
        scene_desc: str | None = None,
        season: str | None = None,
    ) -> bool:
        """记录一次用户采纳搭配的事件

        Args:
            user_id: 用户 ID
            task_id: 任务 ID
            accepted_items: 用户采纳的搭配商品列表，每项含 {itemId, name, category, color, price}
            style_tags: 本次推荐使用的风格标签
            scene_desc: 场景描述
            season: 季节

        Returns:
            True 成功，False 失败（不抛异常）
        """
        try:
            # 精简 item 信息（只保留关键字段，节省存储）
            compact_items = []
            for it in accepted_items:
                compact_items.append({
                    "itemId": it.get("itemId") or it.get("item_id"),
                    "name": it.get("name"),
                    "category": it.get("category"),
                    "color": it.get("color"),
                    "price": it.get("price"),
                })

            point_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            payload = {
                "user_id": user_id,
                "task_id": task_id,
                "accepted_items": compact_items,
                "style_tags": list(style_tags) if style_tags else [],
                "scene_desc": scene_desc,
                "season": season,
                "timestamp": now,
                "memory_id": point_id,
                "source": "user_accept",
                "created_at": now,
                "confidence": 1.0,
                "status": "active",
            }
            self.client.upsert(
                collection_name=COLLECTION_USER_EPISODE,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=_episode_to_vector(),
                        payload=payload,
                    )
                ],
            )
            logger.info("[EpisodicMemory] 已记录搭配事件: userId=%s, taskId=%s, items=%d",
                         user_id, task_id, len(compact_items))
            return True
        except Exception as e:
            logger.warning("[EpisodicMemory] 记录搭配事件失败（不影响主流程）: %s", e)
            return False

    def supersede_memory(self, user_id: int, memory_id: str, reason: str | None = None) -> bool:
        """将一条事件记忆标记为已弃用，保留原事件用于审计。"""
        try:
            points = self.client.retrieve(
                collection_name=COLLECTION_USER_EPISODE,
                ids=[memory_id],
                with_payload=True,
                with_vectors=False,
            )
            if not points or (points[0].payload or {}).get("user_id") != user_id:
                return False
            self.client.set_payload(
                collection_name=COLLECTION_USER_EPISODE,
                payload={
                    "status": "superseded",
                    "superseded_at": datetime.now().isoformat(),
                    "superseded_reason": reason,
                },
                points=[memory_id],
            )
            return True
        except Exception as e:
            logger.warning(
                "弃用用户事件记忆失败: userId=%s, memoryId=%s, error=%s",
                user_id, memory_id, e,
            )
            return False

    def supersede_by_task(self, user_id: int, task_id: str, reason: str | None = None) -> bool:
        """按用户和任务弃用事件，供用户撤回某次采纳时使用。"""
        try:
            results, _ = self.client.scroll(
                collection_name=COLLECTION_USER_EPISODE,
                scroll_filter=Filter(must=[
                    FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                    FieldCondition(key="task_id", match=MatchValue(value=task_id)),
                ]),
                limit=100,
                with_payload=True,
                with_vectors=False,
            )
            memory_ids = [
                point.id for point in results
                if (point.payload or {}).get("status", "active") == "active"
            ]
            if not memory_ids:
                return False
            self.client.set_payload(
                collection_name=COLLECTION_USER_EPISODE,
                payload={
                    "status": "superseded",
                    "superseded_at": datetime.now().isoformat(),
                    "superseded_reason": reason or "corrected by user",
                },
                points=memory_ids,
            )
            return True
        except Exception as e:
            logger.warning(
                "按 task 弃用用户事件记忆失败: userId=%s, taskId=%s, error=%s",
                user_id, task_id, e,
            )
            return False

    def get_recent_episodes(self, user_id: int, limit: int = MAX_EPISODES_TO_READ) -> list[dict]:
        """读取用户最近的搭配事件（按时间降序）

        用于下次进入"AI 随心搭"时，作为"上次推荐"上下文输入 LLM。

        Args:
            user_id: 用户 ID
            limit: 最多读取条数（默认 5）

        Returns:
            [{accepted_items, style_tags, scene_desc, season, timestamp}, ...]
            按时间降序（最新在前），失败返回空列表
        """
        try:
            # scroll 按 user_id 过滤，拿最近 limit*3 条（可能含多次反馈，取最新 limit 条不同 task）
            results, _ = self.client.scroll(
                collection_name=COLLECTION_USER_EPISODE,
                scroll_filter=Filter(
                    must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
                ),
                limit=limit * 3,  # 多拉一些，前端按 task_id 去重
                with_payload=True,
                with_vectors=False,
            )
            if not results:
                return []

            episodes = []
            seen_tasks: set[str] = set()
            for point in results:
                payload = point.payload or {}
                if payload.get("status", "active") != "active":
                    continue
                try:
                    if float(payload.get("confidence", 1.0)) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
                task_id = payload.get("task_id")
                # 同一 task 只保留最新一条（避免一次会话多次 accept 污染）
                if task_id and task_id in seen_tasks:
                    continue
                seen_tasks.add(task_id)
                episodes.append({
                    "memory_id": payload.get("memory_id") or str(point.id),
                    "task_id": task_id,
                    "accepted_items": payload.get("accepted_items", []),
                    "style_tags": payload.get("style_tags", []),
                    "scene_desc": payload.get("scene_desc"),
                    "season": payload.get("season"),
                    "timestamp": payload.get("timestamp"),
                })
                if len(episodes) >= limit:
                    break

            # 按时间降序（最新在前）
            episodes.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
            logger.info("[EpisodicMemory] 读取搭配事件: userId=%s, count=%d", user_id, len(episodes))
            return episodes
        except Exception as e:
            logger.warning("[EpisodicMemory] 读取搭配事件失败（不影响主流程）: %s", e)
            return []
