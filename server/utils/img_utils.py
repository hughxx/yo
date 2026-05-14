from server.utils.ocr import _ocr_sync
from server.service.email_service import img_to_url  # noqa: F401 — re-export


def ocr(file_content: bytes, filename: str) -> str:
    return _ocr_sync(file_content, filename)
