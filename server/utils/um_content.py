import re

from server.utils.img import img_to_url, ocr_sync as ocr, one_box_download

# 匹配 :um_begin{...}/:um_end 包裹的图片/文件内容
_UM_RE = re.compile(r'/:um_begin\{([^}]+)\}/:um_end')


def parse_um_content(um_content: str):
    """解析 clouddrive 图片字段，返回 (ocr_result, img_url)。

    um_content 格式：download_url|Type|Size|FileName|0|W;H;extraction_code|...
    """
    parts = um_content.split("|")
    download_url    = parts[0]
    file_name       = parts[3]
    extraction_code = parts[5].split(";")[2] if len(parts) > 5 else ""

    file_info = one_box_download(download_url, extraction_code)
    if not file_info.download_result or not file_info.file_content:
        return "", ""

    ocr_result = ocr(file_info.file_content, file_name)
    img_url    = img_to_url(file_info.file_content, file_name)
    return ocr_result, img_url


def handle_match(match: re.Match) -> str:
    """regex sub 回调：把 :um_begin{...}/:um_end 替换成 Markdown 图片。"""
    ocr_result, img_url = parse_um_content(match.group(1))
    return f"![{ocr_result}]({img_url})"


def replace_um_images(text: str) -> str:
    """把文本中所有 :um_begin{...}/:um_end 替换为 Markdown 图片链接。"""
    return _UM_RE.sub(handle_match, text)
