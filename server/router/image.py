import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from server.db.db import get_db
from server.utils.img import img_to_url, one_box_download

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image")


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    filename: str = Form(None),
    db: Session = Depends(get_db),
):
    file_name = (filename or file.filename or "image.png").strip()
    logger.info("upload_image: %s", file_name)
    try:
        url = img_to_url(await file.read(), file_name, db=db)
        return {"success": True, "url": url}
    except Exception as e:
        logger.exception("upload_image failed: %s", file_name)
        return {"success": False, "message": str(e)}


@router.post("/proxy")
async def proxy_image(request: Request, db: Session = Depends(get_db)):
    """用机器人账号从 clouddrive 下载图片，上传到文件服务器，返回公开 URL。"""
    data = await request.json()
    download_url    = (data.get("download_url") or "").strip()
    extraction_code = (data.get("extraction_code") or "").strip()
    file_name       = (data.get("file_name") or "image.png").strip()

    if not download_url:
        return {"success": False, "message": "download_url is required"}

    result = one_box_download(download_url, extraction_code)
    if not result.download_result:
        return {"success": False, "message": result.download_error_msg}

    try:
        url = img_to_url(result.file_content, file_name, db=db)
        return {"success": True, "url": url}
    except Exception as e:
        return {"success": False, "message": str(e)}
