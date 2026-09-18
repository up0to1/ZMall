import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tools import nodes


class VtonQualityPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_vton_receives_prepared_single_garment_reference(self):
        quality_service = SimpleNamespace(
            prepare_garment_reference=AsyncMock(
                return_value=(b"cropped-trousers", {"cropped": True})
            )
        )
        vton_client = SimpleNamespace(
            try_on_chain=AsyncMock(return_value=b"try-on-result")
        )
        references = []
        outfit = {"items": [{
            "category": "下装",
            "name": "卡其色休闲工装裤 男士",
            "color": "卡其色",
            "image": "https://shop.example/trousers.jpg",
        }]}

        with patch.object(nodes, "get_vton_quality_service", new=AsyncMock(return_value=quality_service)), \
             patch.object(nodes, "_download_image", new=AsyncMock(return_value=b"original-lifestyle-photo")):
            result = await nodes._generate_single_outfit(
                0, outfit, b"person-photo", vton_client, references
            )

        self.assertEqual(result, b"try-on-result")
        self.assertEqual(vton_client.try_on_chain.await_args.args[1], [b"cropped-trousers"])
        self.assertEqual(references[0]["image_bytes"], b"cropped-trousers")
        self.assertEqual(references[0]["color"], "卡其色")

    async def test_review_report_is_aligned_to_its_outfit_index(self):
        report = {
            "status": "warning",
            "warning": "效果图可能未准确还原所选商品，请以商品图和商品信息为准。",
            "issues": ["卡其色下装疑似未还原"],
            "confidence": 0.9,
        }
        quality_service = SimpleNamespace(review_result=AsyncMock(return_value=report))
        outfits = [{"items": [{"category": "下装", "color": "卡其色"}]}, {"items": []}]
        images = [b"result-1", None]
        references = [[{"category": "下装", "image_bytes": b"pants-reference"}], []]

        with patch.object(nodes, "get_vton_quality_service", new=AsyncMock(return_value=quality_service)):
            reports = await nodes._review_vton_outputs(outfits, images, references, "task-1")

        self.assertEqual(reports, [report, None])
        quality_service.review_result.assert_awaited_once_with(
            b"result-1", outfits[0]["items"], references[0]
        )

    async def test_oss_result_exposes_quality_warning_to_frontend(self):
        uploader = SimpleNamespace(upload_image=lambda *_args: "https://cdn.example/result.jpg")
        state = {
            "task_id": "task-1",
            "outfit_candidates": [{"items": [], "score": 0.8, "reason": "休闲约会"}],
            "generated_images": [b"result-image"],
            "vton_quality_reports": [{
                "status": "warning",
                "warning": "效果图可能未准确还原所选商品，请以商品图和商品信息为准。",
                "issues": ["所选下装与结果图颜色不一致"],
            }],
        }

        with patch.object(nodes, "get_oss_uploader", new=AsyncMock(return_value=uploader)):
            result = await nodes.oss_upload(state)

        outfit = result["final_outfits"][0]
        self.assertEqual(outfit["vtonQualityStatus"], "warning")
        self.assertEqual(outfit["vtonWarning"], state["vton_quality_reports"][0]["warning"])
        self.assertEqual(outfit["vtonQualityIssues"], ["所选下装与结果图颜色不一致"])


if __name__ == "__main__":
    unittest.main()
