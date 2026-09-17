"""Small-image fallback for image proxy request-size limits."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image


logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
# Keep enough headroom for multipart headers when the proxy limit is 1 MiB.
MAX_FALLBACK_BYTES = 800_000
MAX_DIMENSION = 3000


def _compress(filename: str, content: bytes) -> tuple[str, bytes]:
    image = Image.open(BytesIO(content))
    image.load()
    scale = min(1.0, MAX_DIMENSION / max(image.width, image.height))
    if scale < 1:
        image = image.resize((max(1, int(image.width * scale)),
                              max(1, int(image.height * scale))), Image.Resampling.LANCZOS)

    # JPEG is substantially smaller for screenshots/photos. Composite alpha
    # onto white so transparent PNGs do not become black.
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    quality = 82
    data = b""
    while quality >= 45:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= MAX_FALLBACK_BYTES:
            break
        quality -= 10
    while len(data) > MAX_FALLBACK_BYTES and max(image.size) > 800:
        image = image.resize((max(1, int(image.width * .8)),
                              max(1, int(image.height * .8))), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=65, optimize=True, progressive=True)
        data = buffer.getvalue()
    return f"{Path(filename).stem or 'attachment'}.jpg", data


def upload(url: str, filename: str, content: bytes,
           timeout: int = 60) -> tuple[str, str, bytes]:
    logger.info("image upload start name=%s size=%d bytes", filename, len(content))
    response = requests.post(url, files={"file": (filename, content)},
                             timeout=timeout, verify=False)
    if response.status_code == 413 and Path(filename).suffix.lower() in IMAGE_EXTENSIONS:
        original_name = filename
        original_size = len(content)
        filename, content = _compress(filename, content)
        logger.warning(
            "image upload got 413, compressed name=%s original=%d bytes compressed=%d bytes ratio=%.1f%%",
            original_name, original_size, len(content), len(content) * 100 / max(original_size, 1))
        response = requests.post(url, files={"file": (filename, content)},
                                 timeout=timeout, verify=False)
    response.raise_for_status()
    try:
        body = response.json()
        public_url = body.get("url") if isinstance(body, dict) else ""
    except ValueError as exc:
        raise RuntimeError("image upload response is not JSON") from exc
    if not public_url:
        raise RuntimeError("image upload response did not contain url")
    return str(public_url), filename, content
