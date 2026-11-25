"""Prepare Telegram photos for Claude: decode any common format, shrink if needed, re-encode as JPEG."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # iPhone photos sent "as file" are often HEIC

MAX_EDGE = 2576          # plenty to read small cookbook print
MAX_BYTES = 4_500_000    # stay under the API's 5 MB per-image limit


def prepare_image(raw: bytes) -> tuple[str, str]:
    """Return (media_type, base64 data) ready for an image content block."""
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)  # respect the phone's rotation
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE))
    quality = 90
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= MAX_BYTES or quality <= 50:
            break
        quality -= 10
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()
