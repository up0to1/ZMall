import io
import unittest

from PIL import Image

from app.services.vton_quality_service import (
    VTON_QUALITY_WARNING,
    crop_garment_to_canvas,
    normalize_vton_review,
)


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class GarmentReferenceCropTests(unittest.TestCase):
    def test_crop_uses_detected_garment_box_and_pads_on_white_canvas(self):
        source = Image.new("RGB", (100, 200), "white")
        for y in range(0, 80):
            for x in range(20, 80):
                source.putpixel((x, y), (20, 60, 180))  # unrelated blue top
        for y in range(80, 180):
            for x in range(20, 80):
                source.putpixel((x, y), (190, 160, 90))  # khaki trousers
        for y in range(180, 200):
            for x in range(20, 80):
                source.putpixel((x, y), (220, 30, 30))  # unrelated shoes

        result = Image.open(io.BytesIO(crop_garment_to_canvas(
            _png_bytes(source), [0.2, 0.4, 0.8, 0.9]
        )))

        self.assertEqual(result.size, (768, 1024))
        self.assertEqual(result.getpixel((384, 512)), (190, 160, 90))
        self.assertEqual(result.getpixel((0, 0)), (255, 255, 255))

    def test_crop_rejects_invalid_or_degenerate_boxes(self):
        source = _png_bytes(Image.new("RGB", (100, 100), "white"))

        for bbox in ([0.8, 0.2, 0.2, 0.9], [-0.1, 0.2, 0.8, 0.9], [0, 0, 0, 0]):
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                crop_garment_to_canvas(source, bbox)


class VtonReviewNormalizationTests(unittest.TestCase):
    def test_confident_mismatch_becomes_user_visible_warning(self):
        result = normalize_vton_review({
            "consistent": False,
            "confidence": 0.91,
            "issues": ["商品为卡其色长裤，效果图下装仍为黑色"],
        })

        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["warning"], VTON_QUALITY_WARNING)
        self.assertEqual(result["issues"], ["商品为卡其色长裤，效果图下装仍为黑色"])

    def test_low_confidence_review_is_unverified_not_a_false_alarm(self):
        result = normalize_vton_review({
            "consistent": False,
            "confidence": 0.4,
            "issues": ["uncertain color"],
        })

        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["warning"])

    def test_confident_match_does_not_warn(self):
        result = normalize_vton_review({
            "consistent": True,
            "confidence": 0.88,
            "issues": [],
        })

        self.assertEqual(result["status"], "passed")
        self.assertIsNone(result["warning"])

    def test_unknown_consistency_value_never_becomes_a_confident_mismatch(self):
        result = normalize_vton_review({
            "consistent": "model was unsure",
            "confidence": 0.99,
            "issues": [],
        })

        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["warning"])


class VtonQualityServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.services.vton_quality_service import VtonQualityService

        self.service = VtonQualityService()

    async def asyncTearDown(self):
        await self.service.close()

    async def test_unconfigured_vision_service_keeps_original_garment_and_skips_warning(self):
        original = b"original-product-image"
        prepared, crop_report = await self.service.prepare_garment_reference(
            original, {"category": "下装", "color": "卡其色"}
        )
        review = await self.service.review_result(
            b"generated-image",
            [{"category": "下装", "color": "卡其色"}],
            [{"category": "下装", "image_bytes": original}],
        )

        self.assertEqual(prepared, original)
        self.assertFalse(crop_report["cropped"])
        self.assertEqual(review["status"], "unverified")
        self.assertIsNone(review["warning"])


if __name__ == "__main__":
    unittest.main()
