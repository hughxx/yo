"""把选中的 WeLink 消息：富化图片 → 渲染 HTML+MD → 本地存档 → 上报后端。
录制/提取/定时三处共用。"""
from datetime import datetime

import requests

from modules.welink import render
from modules.email import local_archive


def _safe_ts(ms) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000).strftime('%Y%m%d_%H%M')
    except Exception:
        return datetime.now().strftime('%Y%m%d_%H%M')


def push_session(settings: dict, conv_name: str, group_id: str, msgs: list,
                 start_ms: int, end_ms: int, chat_id: str, is_daily: bool = False):
    """处理并上报一段会话。返回 (ok, message)。"""
    backend = (settings.get('backendUrl', '') or '').rstrip('/')
    user_id = settings.get('userId', '')
    if not backend:
        return False, '未配置后端地址'
    if not msgs:
        return False, '没有要处理的消息'

    render.enrich_images(msgs, backend)
    html = render.msgs_to_html(msgs)
    md   = render.msgs_to_md(msgs)

    # 本地存档：html + md（复用邮件那套 outputDir）
    title = f'welink_{conv_name}_{_safe_ts(start_ms)}'
    local_archive.save_email(settings.get('outputDir', ''), title, html, md)

    try:
        r = requests.post(
            f'{backend}/api/welink/receive',
            json={
                'ChatId':       chat_id,
                'GroupId':      str(group_id or ''),
                'GroupName':    conv_name,
                'StartTime':    start_ms,
                'EndTime':      end_ms,
                'HtmlBody':     html,
                'MarkdownBody': md,       # 新客户端直传 MD；旧服务端忽略、仍用 HtmlBody 自己转
                'UploadBy':     user_id,
                'IsDaily':      is_daily,
            },
            timeout=120, verify=False,
        )
        r.raise_for_status()
        res = r.json()
        if res.get('Duplicate'):
            return True, f'已存在，跳过（{len(msgs)} 条）'
        return True, f'上传成功（{len(msgs)} 条）'
    except Exception as e:
        return False, f'上传失败: {e}'
