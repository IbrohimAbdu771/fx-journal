"""Downscale + WebP-compress chart screenshots before they hit the database.

Two full-size screenshots per trade as raw BLOBs quickly bloat a small Postgres
(Neon free = 0.5 GB). Resizing to ~1280px on the long edge and re-encoding to
WebP typically shrinks a chart PNG/JPEG by 5–15×.
"""
from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def compress_image(data: bytes, max_side: int = 1280, quality: int = 80) -> tuple[bytes, str]:
    """Return (bytes, mime). Falls back to the original bytes on any failure."""
    if not data:
        return data, "image/jpeg"
    try:
        from PIL import Image
    except Exception:  # Pillow not installed — store as-is
        return data, "image/jpeg"
    try:
        im = Image.open(BytesIO(data))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        out = BytesIO()
        im.save(out, format="WEBP", quality=quality, method=4)
        return out.getvalue(), "image/webp"
    except Exception as exc:  # corrupt/unknown image — keep original
        logger.warning("Image compress failed, storing original: %s", exc)
        return data, "image/jpeg"
