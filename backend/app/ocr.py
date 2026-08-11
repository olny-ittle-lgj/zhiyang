from __future__ import annotations

import io
import importlib
import threading
from typing import Any

from .config import settings


class OcrError(RuntimeError):
    """Raised when an image cannot be validated or recognized."""


_engine: Any = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()


def inspect_image(data: bytes) -> dict[str, int | str]:
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OcrError("The uploaded file is not a readable image") from exc

    if width <= 0 or height <= 0:
        raise OcrError("The image dimensions are invalid")
    if width * height > settings.ocr_max_image_pixels:
        raise OcrError("The image resolution exceeds the OCR limit")
    return {"width": width, "height": height, "format": image_format or "IMAGE"}


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    importlib.invalidate_caches()
                    from rapidocr_onnxruntime import RapidOCR
                except ImportError as exc:
                    detail = str(exc).strip() or exc.__class__.__name__
                    raise OcrError(f"RapidOCR is unavailable: {detail}") from exc
                _engine = RapidOCR()
    return _engine


def extract_image_text(data: bytes) -> dict[str, object]:
    metadata = inspect_image(data)
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image_array = np.asarray(image)
        with _inference_lock:
            result, _ = _get_engine()(image_array)
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"Local OCR failed: {str(exc).strip() or exc.__class__.__name__}") from exc

    lines: list[dict[str, object]] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        text = str(item[1]).strip()
        if not text:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item[2])))
        except (TypeError, ValueError):
            confidence = 0.0
        lines.append({"text": text, "confidence": confidence})

    content = "\n".join(str(line["text"]) for line in lines).strip()
    average_confidence = (
        sum(float(line["confidence"]) for line in lines) / len(lines) if lines else 0.0
    )
    return {
        **metadata,
        "content": content,
        "lines": len(lines),
        "confidence": round(average_confidence, 4),
    }
