import asyncio
import requests
from server.utils.settings import OCR_URL


def _ocr_sync(file_content: bytes, filename: str, timeout: int = 300) -> str:
    resp = requests.post(
        OCR_URL,
        files={"file": (filename, file_content)},
        timeout=timeout,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    # 兼容 {"result": "..."} 或直接返回字符串
    if isinstance(data, dict):
        return data.get("result") or data.get("text") or ""
    return str(data)


async def ocr(file_content: bytes, filename: str, timeout: int = 300) -> str:
    return await asyncio.to_thread(_ocr_sync, file_content, filename, timeout)
