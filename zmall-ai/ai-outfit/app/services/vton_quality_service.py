"""Prepare garment references and audit VTON image fidelity.

The quality checks are deliberately best-effort: an unavailable vision model must
never turn a successful try-on into a failed recommendation task.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
from typing import Any

import httpx
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

VTON_QUALITY_WARNING = "效果图可能未准确还原所选商品，请以商品图和商品信息为准。"
_REVIEW_CONFIDENCE_THRESHOLD = 0.78
_CROP_CONFIDENCE_THRESHOLD = 0.58
_CANVAS_SIZE = (768, 1024)


def crop_garment_to_canvas(
    image_bytes: bytes,
    bbox: list[float] | tuple[float, float, float, float],
    canvas_size: tuple[int, int] = _CANVAS_SIZE,
) -> bytes:
    """Crop a normalized xyxy box and center it on a white VTON-friendly canvas."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("bbox must contain normalized x1, y1, x2, y2")
    try:
        x1, y1, x2, y2 = (float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox coordinates must be numbers") from exc
    if not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
        raise ValueError("bbox coordinates must be between 0 and 1")
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox must have positive width and height")

    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            width, height = source.size
            left = max(0, min(width - 1, round(x1 * width)))
            top = max(0, min(height - 1, round(y1 * height)))
            right = max(left + 1, min(width, round(x2 * width)))
            bottom = max(top + 1, min(height, round(y2 * height)))
            garment = source.crop((left, top, right, bottom))

        canvas = Image.new("RGB", canvas_size, (255, 255, 255))
        target_width = max(1, int(canvas_size[0] * 0.88))
        target_height = max(1, int(canvas_size[1] * 0.90))
        scale = min(target_width / garment.width, target_height / garment.height)
        resized = garment.resize(
            (max(1, round(garment.width * scale)), max(1, round(garment.height * scale))),
            Image.Resampling.LANCZOS,
        )
        offset = ((canvas_size[0] - resized.width) // 2,
                  (canvas_size[1] - resized.height) // 2)
        canvas.paste(resized, offset)

        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("invalid garment image") from exc


def normalize_vton_review(review: dict[str, Any] | None) -> dict[str, Any]:
    """Convert a vision model response into a conservative UI-safe quality report."""
    if not isinstance(review, dict):
        return {"status": "unverified", "warning": None, "issues": [], "confidence": 0.0}

    raw_confidence = review.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
        if not math.isfinite(confidence):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    consistent = review.get("consistent")
    if isinstance(consistent, str):
        normalized = consistent.strip().lower()
        if normalized in {"true", "yes", "是", "一致"}:
            consistent = True
        elif normalized in {"false", "no", "否", "不一致"}:
            consistent = False
        else:
            consistent = None
    if not isinstance(consistent, bool):
        consistent = None

    raw_issues = review.get("issues", [])
    if isinstance(raw_issues, str):
        raw_issues = [raw_issues]
    issues = [str(issue).strip()[:120] for issue in raw_issues
              if str(issue).strip()][:5] if isinstance(raw_issues, list) else []

    if consistent is False and confidence >= _REVIEW_CONFIDENCE_THRESHOLD:
        status, warning = "warning", VTON_QUALITY_WARNING
    elif consistent is True and confidence >= 0.60:
        status, warning = "passed", None
    else:
        status, warning = "unverified", None
    return {"status": status, "warning": warning, "issues": issues,
            "confidence": round(confidence, 3)}


class VtonQualityService:
    """Best-effort garment crop and generated-image consistency checker."""

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        vision_model: str = "qwen3.5-flash",
        proxy_url: str = "",
        timeout: float = 15.0,
    ) -> None:
        base = (api_url or "").rstrip("/")
        self.api_url = base if not base or base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.api_key = api_key
        self.vision_model = vision_model
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        self._client = httpx.AsyncClient(**client_kwargs)

    async def close(self) -> None:
        await self._client.aclose()

    async def prepare_garment_reference(
        self, image_bytes: bytes, item: dict[str, Any]
    ) -> tuple[bytes, dict[str, Any]]:
        """Ask the vision model to locate one garment; return original bytes on any uncertainty."""
        if not image_bytes or not self.api_url or not self.api_key:
            return image_bytes, {"cropped": False, "reason": "vision_unavailable"}

        category = str(item.get("category") or "服装")
        name = str(item.get("name") or item.get("title") or "")[:100]
        color = str(item.get("color") or "")[:40]
        prompt = (
            "请在商品参考图中定位指定的单件服装，并返回该服装主体的紧致矩形框。"
            "不要框入其他衣物、鞋或无关人物；如果图片中商品穿在模特身上，只框指定品类对应的衣物区域。"
            "坐标为相对图片宽高的 0 到 1 归一化值，格式严格为 JSON："
            '{"bbox":[x1,y1,x2,y2],"confidence":0到1的数字,"found":true或false}。'
            f"目标品类：{category}；商品名称：{name or '未知'}；商品颜色：{color or '未知'}。"
            "若无法可靠区分目标衣物，found=false。"
        )
        try:
            result = await self._vision_json(prompt, [("商品参考图", image_bytes)])
            bbox = result.get("bbox")
            confidence = float(result.get("confidence", 0.0))
            if (result.get("found") is False or not math.isfinite(confidence)
                    or confidence < _CROP_CONFIDENCE_THRESHOLD):
                return image_bytes, {"cropped": False, "reason": "low_localization_confidence"}
            cropped = crop_garment_to_canvas(image_bytes, bbox)
            return cropped, {"cropped": True, "bbox": bbox, "confidence": confidence}
        except Exception as exc:
            logger.info("VTON 商品图裁剪不可用，保留原图: category=%s error=%s", category, exc)
            return image_bytes, {"cropped": False, "reason": "crop_failed"}

    async def review_result(
        self,
        result_image: bytes,
        items: list[dict[str, Any]],
        garment_references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compare final VTON output with selected item references and metadata."""
        if not result_image or not garment_references or not self.api_url or not self.api_key:
            return normalize_vton_review(None)

        expected = []
        for item in items:
            if not isinstance(item, dict):
                continue
            expected.append({
                "category": item.get("category"),
                "name": str(item.get("name") or item.get("title") or "")[:100],
                "color": item.get("color"),
            })
        prompt = (
            "你是虚拟试穿结果质检器。先看商品参考图及商品信息，再看最终试穿图。"
            "只核对可见服装的品类是否对应、主色是否明显冲突；人物姿势、背景、轻微色差不算失败。"
            "如果试穿图仍保留原衣物（例如参考裤子为卡其色但人物仍穿黑裤），判为不一致。"
            "仅在证据明确时判不一致；看不清或被遮挡就降低 confidence。严格输出 JSON："
            '{"consistent":true或false,"confidence":0到1的数字,"issues":["简短中文原因"]}。'
            f"本套选定商品元信息：{json.dumps(expected, ensure_ascii=False)}。"
            "后续图片会先按顺序给出商品参考图，最后一张是试穿结果图。"
        )
        image_parts = [
            (f"商品参考图：{ref.get('category') or '服装'} {ref.get('name') or ''} {ref.get('color') or ''}",
             ref.get("image_bytes", b""))
            for ref in garment_references if ref.get("image_bytes")
        ]
        image_parts.append(("最终试穿结果图", result_image))
        try:
            response = await self._vision_json(prompt, image_parts)
            return normalize_vton_review(response)
        except Exception as exc:
            logger.info("VTON 结果一致性审核不可用，按未审核放行: %s", exc)
            return normalize_vton_review(None)

    async def _vision_json(
        self, prompt: str, images: list[tuple[str, bytes]]
    ) -> dict[str, Any]:
        if not self.api_url or not self.api_key:
            raise RuntimeError("vision model is not configured")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for label, image_bytes in images:
            encoded = base64.b64encode(_to_model_jpeg(image_bytes)).decode("ascii")
            content.append({"type": "text", "text": label})
            content.append({"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{encoded}"
            }})
        response = await self._client.post(
            self.api_url,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.vision_model,
                  "messages": [{"role": "user", "content": content}],
                  "temperature": 0.0,
                  "response_format": {"type": "json_object"}},
        )
        response.raise_for_status()
        payload = response.json()
        raw_content = payload["choices"][0]["message"]["content"]
        if isinstance(raw_content, list):
            raw_content = "".join(part.get("text", "") for part in raw_content
                                  if isinstance(part, dict))
        if not isinstance(raw_content, str):
            raise ValueError("vision response content is not text")
        raw_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_content.strip(), flags=re.I)
        parsed = json.loads(raw_content)
        if not isinstance(parsed, dict):
            raise ValueError("vision response must be a JSON object")
        return parsed


def _to_model_jpeg(image_bytes: bytes) -> bytes:
    """Normalize mixed JPEG/PNG/WebP inputs and cap vision-request payload size."""
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=86, optimize=True)
        return output.getvalue()
