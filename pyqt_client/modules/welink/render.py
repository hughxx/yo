"""WeLink 消息 → HTML / Markdown，含图片/文件下载富化。HTML 渲染沿用旧逻辑，
Markdown 复用 email 的 html2md，保证与服务端一致。"""
from datetime import datetime
from html import escape

import requests

from modules.email.html2md import html2md as _html2md


def _fmt(ms) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S') if ms else ''


def parse_um_content(content: str):
    """/:um_begin{URL|Type|Size|FileName|0|W;H;extraction_code|...}/:um_end
    → (download_url, file_name, extraction_code) 或 (None, None, None)"""
    prefix, suffix = '/:um_begin{', '}/:um_end'
    if not (content.startswith(prefix) and content.endswith(suffix)):
        return None, None, None
    inner = content[len(prefix):-len(suffix)]
    parts = inner.split('|')
    if len(parts) < 6:
        return None, None, None
    field5 = parts[5].split(';')
    return parts[0], parts[3], (field5[2] if len(field5) > 2 else '')


def enrich_images(msgs: list, backend_base: str, log=None) -> None:
    """图片/文件经后端代理下载并拿到公开 URL，写入 _img_url / _img_name 供渲染。"""
    base = (backend_base or '').rstrip('/')
    for m in msgs:
        if m.get('contentType') not in ('PICTURE_MSG', 'FILE_MSG'):
            continue
        dl_url, fname, code = parse_um_content(m.get('content', ''))
        if not (dl_url and fname):
            continue
        m['_img_name'] = fname
        try:
            resp = requests.post(
                f'{base}/api/image/proxy',
                json={'download_url': dl_url, 'extraction_code': code, 'file_name': fname},
                timeout=60, verify=False,
            )
            data = resp.json()
            if data.get('success') and data.get('url'):
                m['_img_url'] = data['url']
            elif log:
                log(f'  图片下载失败: {fname} ({data.get("message")})')
        except Exception as e:
            if log:
                log(f'  图片请求失败: {fname} ({e})')


def msgs_to_html(msgs: list) -> str:
    rows = []
    for m in msgs:
        sender = escape(m.get('sender', ''))
        ct     = m.get('contentType', '')
        raw    = m.get('content', '')
        t      = _fmt(m.get('serverSendTime', 0))

        if ct in ('PICTURE_MSG', 'FILE_MSG'):
            img_url  = m.get('_img_url')
            img_name = escape(m.get('_img_name', ''))
            if ct == 'PICTURE_MSG' and img_url:
                body = (f'<img src="{img_url}" style="max-width:480px;display:block">'
                        f'<small style="color:#888">{img_name}</small>')
            elif ct == 'FILE_MSG' and img_url:
                body = f'<a href="{img_url}">[文件] {img_name}</a>'
            else:
                body = f'<em>[{"图片" if ct == "PICTURE_MSG" else "文件"}] {img_name}</em>'
        elif ct == 'CARD_MSG':
            body = '<em>[卡片消息]</em>'
        elif ct == 'NOTICE_MSG':
            body = f'<em>[系统通知] {escape(raw)}</em>'
        else:
            body = raw if raw.strip().startswith('<') else escape(raw).replace('\n', '<br>')

        rows.append(
            f'<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">'
            f'<span style="font-weight:bold;color:#1a73e8">{sender}</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{t}</span>'
            f'<div style="margin-top:4px">{body}</div></div>'
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:Arial,sans-serif;font-size:13px;color:#222;'
        'max-width:860px;margin:20px auto;padding:0 16px}</style></head><body>'
        + ''.join(rows) + '</body></html>'
    )


def msgs_to_md(msgs: list) -> str:
    return _html2md(msgs_to_html(msgs))
