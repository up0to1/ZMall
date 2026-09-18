import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.task_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    build_task_checkpoint,
    hydrate_task_checkpoint,
)
from app.services.agent_service import AgentService, STATE_SNAPSHOT_PREFIX


class TaskCheckpointTests(unittest.TestCase):
    def test_checkpoint_keeps_recoverable_context_and_drops_runtime_fields(self):
        state = {
            "task_id": "task-1",
            "user_id": 7,
            "round": 2,
            "style_tags": ["休闲"],
            "color_is_explicit": True,
            "scene_desc": "日常出门",
            "category_constraints": ["上衣", "下装", "鞋"],
            "outfit_candidates": [{"items": [{"itemId": 11}]}],
            "final_outfits": [
                {"resultUrl": "https://oss.example/outfit.jpg"},
                {"resultUrl": "data:image/jpeg;base64," + ("A" * 1024)},
            ],
            "history_outfits": [],
            "seen_item_ids": {11, 12},
            "feedback_parsed": {"action": "replace"},
            "keep_categories": ["上衣", "鞋"],
            "candidate_items_by_category": {"下装": [{"item_id": 12}]},
            "query_vector": [0.1, 0.2],
            "user_profile": {"profile_confidence": 0.8},
            "recent_episodes": [{"task_id": "old-task"}],
            "weather_info": {"season": "summer"},
            "user_photo": b"photo-bytes",
            "generated_images": [b"generated-bytes"],
            "_main_item_bytes": b"main-item-bytes",
        }

        checkpoint = build_task_checkpoint(state, version=3)

        self.assertEqual(checkpoint["checkpoint_schema_version"], CHECKPOINT_SCHEMA_VERSION)
        self.assertEqual(checkpoint["checkpoint_version"], 3)
        self.assertEqual(checkpoint["seen_item_ids"], [11, 12])
        self.assertEqual(checkpoint["candidate_items_by_category"], {"下装": [{"item_id": 12}]})
        self.assertEqual(
            checkpoint["final_outfits"][0],
            {"resultUrl": "https://oss.example/outfit.jpg"},
        )
        self.assertIsNone(checkpoint["final_outfits"][1]["resultUrl"])
        self.assertEqual(checkpoint["query_vector"], [0.1, 0.2])
        self.assertTrue(checkpoint["color_is_explicit"])
        self.assertNotIn("user_profile", checkpoint)
        self.assertNotIn("recent_episodes", checkpoint)
        self.assertNotIn("weather_info", checkpoint)
        self.assertNotIn("user_photo", checkpoint)
        self.assertNotIn("generated_images", checkpoint)
        self.assertNotIn("_main_item_bytes", checkpoint)

    def test_hydrate_checkpoint_restores_seen_ids_and_defaults_version(self):
        state = hydrate_task_checkpoint({
            "task_id": "task-1",
            "seen_item_ids": [11, 12],
        })

        self.assertEqual(state["seen_item_ids"], {11, 12})
        self.assertEqual(state["checkpoint_version"], 0)


class _FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, _script, _num_keys, key, expected_version, payload, _ttl):
        current = self.values.get(key)
        current_version = 0
        if current:
            current_version = json.loads(current).get("checkpoint_version", 0)
        if int(current_version) != int(expected_version):
            return 0
        self.values[key] = payload
        return 1


class AgentServiceCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_runtime_reloads_profile_instead_of_persisting_it(self):
        redis = _FakeRedis()
        service = AgentService(redis)
        profile_service = SimpleNamespace(
            get_or_load_profile=AsyncMock(return_value={"profile_confidence": 0.8})
        )

        with patch(
            "app.services.profile_service.get_profile_service",
            new=AsyncMock(return_value=profile_service),
        ):
            state = await service._restore_feedback_runtime(
                {"task_id": "task-1", "user_id": 7}, user_id=7
            )

        self.assertEqual(state["user_profile"], {"profile_confidence": 0.8})
        profile_service.get_or_load_profile.assert_awaited_once_with(7)

    async def test_save_state_writes_compact_versioned_checkpoint(self):
        redis = _FakeRedis()
        service = AgentService(redis)

        saved = await service._save_state("task-1", {
            "task_id": "task-1",
            "user_id": 7,
            "round": 1,
            "seen_item_ids": {11},
            "outfit_candidates": [],
            "user_profile": {"profile_confidence": 1.0},
        })

        self.assertTrue(saved)
        stored = json.loads(redis.values[f"{STATE_SNAPSHOT_PREFIX}task-1"])
        self.assertEqual(stored["checkpoint_version"], 1)
        self.assertNotIn("user_profile", stored)
        self.assertEqual(stored["seen_item_ids"], [11])

    async def test_stale_checkpoint_write_is_rejected(self):
        redis = _FakeRedis()
        service = AgentService(redis)
        first = {"task_id": "task-1", "user_id": 7, "round": 1}
        second = {"task_id": "task-1", "user_id": 7, "round": 2}
        stale = {"task_id": "task-1", "user_id": 7, "round": 99, "checkpoint_version": 1}

        self.assertTrue(await service._save_state("task-1", first))
        self.assertTrue(await service._save_state("task-1", {**second, "checkpoint_version": 1}))
        self.assertFalse(await service._save_state("task-1", stale))
        stored = json.loads(redis.values[f"{STATE_SNAPSHOT_PREFIX}task-1"])
        self.assertEqual(stored["round"], 2)
        self.assertEqual(stored["checkpoint_version"], 2)


if __name__ == "__main__":
    unittest.main()
