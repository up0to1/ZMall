import unittest
from unittest.mock import AsyncMock, Mock, patch

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from app.tools.nodes import (
    _enforce_explicit_color_selection,
    _filter_candidates_by_inventory,
    _run_intent_agent,
)
from shared.qdrant_client.searcher import QdrantSearcher


class _Wrapper:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


class _IntentLLM:
    def __init__(self, result):
        self.result = result

    async def react_intent(self, **kwargs):
        return self.result


class _EmbedClient:
    async def encode_text(self, text):
        return [0.0] * 1024


class IntentColorPreferenceTests(unittest.IsolatedAsyncioTestCase):
    async def _run_intent(self, explicit_color, llm_color):
        result = {
            "query_text": "休闲 日常 黑色 白色",
            "style_tags": ["休闲"],
            "color": llm_color,
            "scene_desc": "日常",
            "season": "autumn",
        }
        state = {
            "style_tags": ["休闲"],
            "scene_desc": "日常",
            "color": explicit_color,
            "categories": ["tops"],
            "user_id": 7,
            "task_id": "color-preference-test",
        }
        with patch("app.tools.nodes.get_llm_client", new=AsyncMock(return_value=_IntentLLM(result))), \
             patch("app.tools.nodes.get_embed_client", new=AsyncMock(return_value=_EmbedClient())):
            return await _run_intent_agent(state)

    async def test_explicit_form_colors_are_not_overwritten_by_llm(self):
        result = await self._run_intent(["黑色", "白色"], ["black"])
        self.assertEqual(result["color"], ["黑色", "白色"])

    async def test_llm_color_aliases_are_normalized_to_catalog_colors(self):
        result = await self._run_intent(None, ["black", "white"])
        self.assertEqual(result["color"], ["黑色", "白色"])


class QdrantColorPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.client = QdrantClient(":memory:")
        self.client.create_collection(
            collection_name="item_style",
            vectors_config=VectorParams(size=2, distance=Distance.COSINE),
        )
        self.searcher = QdrantSearcher(_Wrapper(self.client))

    def tearDown(self):
        self.client.close()

    def _insert(self, point_id, vector, color):
        self.client.upsert(
            collection_name="item_style",
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "item_id": point_id,
                    "shop_id": 1,
                    "category": "tops",
                    "color": color,
                    "season": "autumn",
                    "is_active": True,
                    "stock": 10,
                    "target_gender": "male",
                },
            )],
        )

    def test_color_preference_does_not_exclude_when_no_matching_color_exists(self):
        self._insert(1, [1.0, 0.0], "红色")

        results = self.searcher.search_complementary_items(
            query_vector=[1.0, 0.0],
            category="tops",
            color=["黑色"],
            target_gender="male",
            limit=5,
            score_threshold=0.0,
        )

        self.assertEqual([item["item_id"] for item in results], [1])

    def test_color_preference_boosts_matching_items_without_dropping_alternatives(self):
        self._insert(1, [1.0, 0.02], "红色")
        self._insert(2, [1.0, 0.0], "黑色")

        results = self.searcher.search_complementary_items(
            query_vector=[1.0, 0.0],
            category="tops",
            color=["黑色"],
            target_gender="male",
            limit=2,
            score_threshold=0.0,
        )

        self.assertEqual({item["item_id"] for item in results}, {1, 2})
        self.assertEqual(results[0]["item_id"], 2)

    def test_explicit_color_can_be_hard_filtered(self):
        self._insert(1, [1.0, 0.0], "红色")
        self._insert(2, [0.99, 0.01], "黑色")

        results = self.searcher.search_complementary_items(
            query_vector=[1.0, 0.0],
            category="tops",
            color=["黑色"],
            target_gender="male",
            limit=5,
            score_threshold=0.0,
            strict_color=True,
        )

        self.assertEqual([item["item_id"] for item in results], [2])


class DeterministicRecommendationGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_llm_color_mismatch_is_replaced_by_matching_candidate(self):
        candidates = [
            {"items": [{"item_id": 1, "color": "卡其色"}], "score": 0.9},
            {"items": [{"item_id": 2, "color": "黑色"}], "score": 0.8},
        ]
        selected = _enforce_explicit_color_selection(
            [{"outfit_idx": 0, "reason": "llm"}], candidates, ["黑色"],
        )
        self.assertEqual(selected[0]["outfit_idx"], 1)

    async def test_inventory_failure_marks_candidates_unknown(self):
        candidates = {"下装": [{"item_id": 11, "color": "黑色"}]}
        with patch("app.tools.nodes.get_java_client", new=AsyncMock(return_value=object())), \
             patch("app.tools.nodes.get_redis", new=AsyncMock(return_value=object())), \
             patch("app.tools.nodes.batch_query_stock", new=Mock(return_value={})), \
             patch("app.tools.nodes.call_with_check", new=AsyncMock(return_value=None)):
            result = await _filter_candidates_by_inventory(candidates, set(), "inventory-test")

        self.assertTrue(result["下装"][0]["inventory_unknown"])

    async def test_partial_inventory_response_removes_out_of_stock_and_marks_unknown(self):
        candidates = {"下装": [
            {"item_id": 11, "color": "黑色"},
            {"item_id": 12, "color": "白色"},
            {"item_id": 13, "color": "蓝色"},
        ]}
        with patch("app.tools.nodes.get_java_client", new=AsyncMock(return_value=object())), \
             patch("app.tools.nodes.get_redis", new=AsyncMock(return_value=object())), \
             patch("app.tools.nodes.batch_query_stock", new=Mock(return_value={11: 0, 12: 5})), \
             patch("app.tools.nodes.call_with_check", new=AsyncMock(return_value={11: 0, 12: 5})):
            result = await _filter_candidates_by_inventory(candidates, set(), "inventory-partial")

        self.assertEqual([item["item_id"] for item in result["下装"]], [12, 13])
        self.assertTrue(result["下装"][1]["inventory_unknown"])


if __name__ == "__main__":
    unittest.main()
