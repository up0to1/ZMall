import unittest
import asyncio
from types import SimpleNamespace

from app.services.agent_service import AgentService
from app.services.profile_service import ProfileService
from shared.memory_policy import should_persist_preference
from shared.qdrant_client.user_behavior import UserBehaviorIndexer
from shared.qdrant_client.user_episode import UserEpisodeStore
from shared.qdrant_client.user_preference import UserPreferenceReader, UserPreferenceUpdater


class _FakeQdrant:
    def __init__(self):
        self.points = {}
        self.last_upsert = None
        self.payload_updates = []

    def retrieve(self, collection_name, ids, with_payload, with_vectors):
        point = self.points.get(str(ids[0]))
        return [point] if point else []

    def upsert(self, collection_name, points):
        self.last_upsert = points[0]
        self.points[str(points[0].id)] = SimpleNamespace(
            id=points[0].id,
            payload=points[0].payload,
            vector=points[0].vector,
        )

    def scroll(self, collection_name, scroll_filter=None, limit=100,
               offset=None, with_payload=True, with_vectors=False):
        return list(self.points.values())[:limit], None

    def set_payload(self, collection_name, payload, points):
        self.payload_updates.append((collection_name, payload, points))
        for point_id in points:
            point = self.points[str(point_id)]
            point.payload.update(payload)

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name="zmall_user_behavior")])


class _FakeWrapper:
    def __init__(self, client):
        self.client = client

    def get_client(self):
        return self.client


class LongTermMemoryMetadataTests(unittest.TestCase):
    def test_task_scoped_feedback_does_not_become_long_term_preference(self):
        self.assertFalse(should_persist_preference("这次不要红色"))
        self.assertTrue(should_persist_preference("以后都不要红色"))
        self.assertTrue(should_persist_preference("任意文本", explicit_user_field=True))

    def test_event_recall_filters_irrelevant_history(self):
        episodes = [
            {
                "task_id": "old-formal",
                "style_tags": ["正式"],
                "scene_desc": "商务通勤",
                "season": "winter",
                "accepted_items": [{"category": "上衣"}],
            },
            {
                "task_id": "relevant-casual",
                "style_tags": ["休闲"],
                "scene_desc": "日常出门",
                "season": "summer",
                "accepted_items": [{"category": "下装"}],
            },
        ]

        result = AgentService._filter_relevant_episodes(
            episodes,
            style_tags=["休闲"],
            scene_desc="日常出门",
            season="summer",
            categories=["下装"],
        )

        self.assertEqual([item["task_id"] for item in result], ["relevant-casual"])

    def test_behavior_memory_has_auditable_metadata(self):
        client = _FakeQdrant()
        indexer = UserBehaviorIndexer(_FakeWrapper(client))

        self.assertTrue(indexer.index_behavior(
            user_id=7,
            item_id=11,
            behavior_type="CART_ADD",
            timestamp="2026-09-18T10:00:00",
            category="下装",
            vector=[0.1, 0.2],
        ))

        payload = client.last_upsert.payload
        self.assertEqual(payload["memory_id"], client.last_upsert.id)
        self.assertEqual(payload["source"], "mq:user_behavior")
        self.assertEqual(payload["confidence"], 1.0)
        self.assertEqual(payload["status"], "active")

        self.assertTrue(indexer.supersede_memory(7, client.last_upsert.id, "用户否认该行为"))
        self.assertEqual(client.last_upsert.payload["status"], "superseded")

    def test_behavior_memories_can_be_superseded_by_item(self):
        client = _FakeQdrant()
        indexer = UserBehaviorIndexer(_FakeWrapper(client))
        client.points["behavior-1"] = SimpleNamespace(
            id="behavior-1",
            payload={"user_id": 7, "item_id": 11, "status": "active"},
            vector=[0.0],
        )

        self.assertEqual(indexer.supersede_by_item(7, 11, "用户不喜欢该商品"), 1)
        self.assertEqual(client.points["behavior-1"].payload["status"], "superseded")

    def test_superseded_preference_is_not_recalled_and_replacement_is_active(self):
        client = _FakeQdrant()
        updater = UserPreferenceUpdater(_FakeWrapper(client))
        reader = UserPreferenceReader(_FakeWrapper(client))

        self.assertTrue(updater._upsert_inner(7, ["红色"], None, None, None))
        old_memory = client.last_upsert.payload["memory_records"][0]

        self.assertTrue(
            updater._correct_inner(
                7,
                old_memory["memory_id"],
                {"kind": "dislike_color", "value": "黑色"},
                "user correction",
            )
        )

        active_payload = client.last_upsert.payload
        old = next(m for m in active_payload["memory_records"]
                   if m["memory_id"] == old_memory["memory_id"])
        replacement = next(m for m in active_payload["memory_records"]
                           if m.get("supersedes") == old_memory["memory_id"])
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(replacement["status"], "active")
        self.assertEqual(reader.get_preference(7)["dislike_colors"], ["黑色"])

    def test_preference_can_be_corrected_by_old_value_without_memory_id(self):
        client = _FakeQdrant()
        updater = UserPreferenceUpdater(_FakeWrapper(client))
        reader = UserPreferenceReader(_FakeWrapper(client))

        self.assertTrue(updater._upsert_inner(7, ["红色"], None, None, None))
        self.assertTrue(asyncio.run(updater.correct_preference_by_value(
            7,
            "dislike_color",
            "红色",
            {"kind": "like_style", "value": "简约"},
            "用户更正偏好",
        )))

        preference = reader.get_preference(7)
        self.assertEqual(preference["dislike_colors"], [])
        self.assertEqual(preference["like_styles"], ["简约"])

    def test_invalid_preference_replacement_does_not_supersede_old_memory(self):
        client = _FakeQdrant()
        updater = UserPreferenceUpdater(_FakeWrapper(client))
        reader = UserPreferenceReader(_FakeWrapper(client))

        self.assertTrue(updater._upsert_inner(7, ["红色"], None, None, None))
        old_memory = client.last_upsert.payload["memory_records"][0]

        self.assertFalse(updater._correct_inner(
            7,
            old_memory["memory_id"],
            {"kind": "dislike_color"},
            "invalid replacement",
        ))

        active = reader.get_preference(7)
        self.assertEqual(active["dislike_colors"], ["红色"])
        old = next(m for m in client.last_upsert.payload["memory_records"]
                   if m["memory_id"] == old_memory["memory_id"])
        self.assertEqual(old["status"], "active")

    def test_invalid_value_replacement_does_not_supersede_old_memory(self):
        client = _FakeQdrant()
        updater = UserPreferenceUpdater(_FakeWrapper(client))
        reader = UserPreferenceReader(_FakeWrapper(client))

        self.assertTrue(updater._upsert_inner(7, ["红色"], None, None, None))
        self.assertFalse(asyncio.run(updater.correct_preference_by_value(
            7,
            "dislike_color",
            "红色",
            {"kind": "dislike_color"},
            "invalid replacement",
        )))

        self.assertEqual(reader.get_preference(7)["dislike_colors"], ["红色"])

    def test_explicit_dislike_color_is_removed_from_profile_top_colors(self):
        client = _FakeQdrant()
        client.points["active"] = SimpleNamespace(
            id="active",
            payload={
                "user_id": 7, "type": "CART_ADD", "timestamp": "2026-09-18T10:00:00",
                "style_tags": ["休闲"], "color": "黑色", "price": 100,
                "status": "active", "confidence": 1.0, "is_cross_gender": False,
            },
            vector=[1.0, 0.0],
        )
        client.points["7"] = SimpleNamespace(
            id="7",
            payload={
                "user_id": 7,
                "memory_records": [{
                    "memory_id": "pref-black",
                    "kind": "dislike_color",
                    "value": "黑色",
                    "status": "active",
                    "confidence": 1.0,
                }],
                "last_updated": "2026-09-18T10:00:00",
            },
            vector=[0.0],
        )
        service = ProfileService(_FakeWrapper(client), _FakeWrapper(client))

        result = service._aggregate_profile(7)

        self.assertNotIn("黑色", result["top_colors"])

    def test_profile_aggregation_ignores_superseded_behavior(self):
        client = _FakeQdrant()
        client.points["active"] = SimpleNamespace(
            id="active",
            payload={
                "user_id": 7, "type": "CART_ADD", "timestamp": "2026-09-18T10:00:00",
                "style_tags": ["休闲"], "color": "黑色", "price": 100,
                "status": "active", "confidence": 1.0, "is_cross_gender": False,
            },
            vector=[1.0, 0.0],
        )
        client.points["old"] = SimpleNamespace(
            id="old",
            payload={
                "user_id": 7, "type": "CART_ADD", "timestamp": "2026-09-18T10:00:00",
                "style_tags": ["正式"], "color": "红色", "price": 999,
                "status": "superseded", "confidence": 1.0, "is_cross_gender": False,
            },
            vector=[0.0, 1.0],
        )
        service = ProfileService(_FakeWrapper(client), _FakeWrapper(client))

        result = service._aggregate_from_qdrant_behavior(7)

        self.assertEqual(result["signal_count"], 1)
        self.assertEqual(result["color_counter"]["黑色"], 1.5)
        self.assertNotIn("红色", result["color_counter"])

    def test_episode_recall_ignores_superseded_memory(self):
        client = _FakeQdrant()
        store = UserEpisodeStore(_FakeWrapper(client))
        client.points["active"] = SimpleNamespace(
            id="active",
            payload={
                "user_id": 7, "task_id": "task-new", "accepted_items": [],
                "style_tags": ["休闲"], "timestamp": "2026-09-18T10:00:00",
                "source": "user_accept", "confidence": 1.0, "status": "active",
            },
            vector=[0.0],
        )
        client.points["old"] = SimpleNamespace(
            id="old",
            payload={
                "user_id": 7, "task_id": "task-old", "accepted_items": [],
                "style_tags": ["正式"], "timestamp": "2026-09-17T10:00:00",
                "source": "user_accept", "confidence": 1.0, "status": "superseded",
            },
            vector=[0.0],
        )

        episodes = store.get_recent_episodes(7)

        self.assertEqual([e["task_id"] for e in episodes], ["task-new"])

    def test_episode_memory_can_be_superseded_without_delete(self):
        client = _FakeQdrant()
        store = UserEpisodeStore(_FakeWrapper(client))

        self.assertTrue(store.add_episode(7, "task-1", [], ["休闲"], None, None))
        memory_id = client.last_upsert.id
        self.assertTrue(store.supersede_memory(7, memory_id, "用户撤回采纳"))
        self.assertEqual(client.points[str(memory_id)].payload["status"], "superseded")

    def test_episode_memory_can_be_superseded_by_task(self):
        client = _FakeQdrant()
        store = UserEpisodeStore(_FakeWrapper(client))

        self.assertTrue(store.add_episode(7, "task-1", [], ["休闲"], None, None))
        self.assertTrue(store.supersede_by_task(7, "task-1", "用户撤回采纳"))
        memory_id = client.last_upsert.id
        self.assertEqual(client.points[str(memory_id)].payload["status"], "superseded")


if __name__ == "__main__":
    unittest.main()
