"""WeLink 手动导出聊天记录解析

处理 WeLink「导出聊天记录」生成的 HistoryRecord 结构（一个 xxx.txt + 一个 xxx 图片
文件夹）。txt 里图片只是 [图片] 占位符，靠图片文件的修改时间戳与消息时间戳按时间序
对齐还原。时间戳精确到秒；多张图同一秒时顺序不可靠，会在 HTML 里插提示让人工核对。

纯逻辑、不依赖 Qt，便于单测。上传交给调用方：match_images 后由 panel 给每个图片 dict
写入 'url'，再交 build_html 渲染。
"""
import re
import zipfile
from datetime import datetime
from html import escape

_IMG_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')

# 消息头：姓名(工号)<空白>YYYY-MM-DD HH:MM:SS —— 不含换行，可匹配黏在同一行的相邻消息
_HEADER_RE = re.compile(r'([^\n(]+?)\((\w+)\)\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')

_IMG_TOKEN = '[图片]'

_MSG_DIV_OPEN = '<div style="margin:6px 0;padding:6px 10px;background:#f5f5f5;border-radius:4px;">'


# ── 读取 zip ──────────────────────────────────────────────

def read_zip(path: str):
    """读取导出 zip，返回 (txt_stem, txt_text, images)。

    images: list of {'name', 'mtime': datetime, 'data': bytes}
    不落盘；图片时间戳直接取 ZipInfo.date_time（即打包时的文件修改时间）。
    """
    with zipfile.ZipFile(path) as zf:
        infos = [zi for zi in zf.infolist() if not zi.is_dir()]

        txt_info = _pick_txt(infos)
        if txt_info is None:
            raise ValueError('压缩包内未找到聊天记录 txt（应在 HistoryRecord 文件夹下）')

        txt_text = _decode(zf.read(txt_info.filename))

        txt_name = txt_info.filename.replace('\\', '/')
        stem     = txt_name.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        txt_dir  = txt_name.rsplit('/', 1)[0] if '/' in txt_name else ''
        prefix   = (f'{txt_dir}/{stem}/' if txt_dir else f'{stem}/')

        img_infos = [
            zi for zi in infos
            if zi.filename.replace('\\', '/').startswith(prefix)
            and zi.filename.lower().endswith(_IMG_EXTS)
        ]
        if not img_infos:  # 兜底：取归档内所有图片文件
            img_infos = [zi for zi in infos if zi.filename.lower().endswith(_IMG_EXTS)]

        images = []
        for zi in img_infos:
            images.append({
                'name':  zi.filename.replace('\\', '/').rsplit('/', 1)[-1],
                'mtime': _zip_mtime(zi),
                'data':  zf.read(zi.filename),
            })
        return stem, txt_text, images


def _pick_txt(infos):
    """优先 HistoryRecord 下的 txt；否则任一 txt。"""
    txts = [zi for zi in infos if zi.filename.lower().endswith('.txt')]
    if not txts:
        return None
    for zi in txts:
        if 'historyrecord' in zi.filename.replace('\\', '/').lower():
            return zi
    return txts[0]


def _decode(raw: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='ignore')


def _zip_mtime(zi: zipfile.ZipInfo) -> datetime:
    try:
        return datetime(*zi.date_time)
    except (ValueError, TypeError):
        return datetime.min


# ── 解析 txt ──────────────────────────────────────────────

def parse_chatlog(text: str) -> list:
    """切成消息列表。

    每条 Message: {'name','uid','ts': datetime, 'ts_str', 'segments'}
    segments: 有序的 ('text', str) / ('image', None)。
    """
    matches = list(_HEADER_RE.finditer(text))
    messages = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw = text[m.end():end]
        try:
            ts = datetime.strptime(m.group(3), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        messages.append({
            'name':     m.group(1).strip(),
            'uid':      m.group(2),
            'ts':       ts,
            'ts_str':   m.group(3),
            'segments': _split_segments(raw),
        })
    return messages


def _split_segments(raw: str) -> list:
    content = raw.strip()
    if not content:
        return []
    parts = content.split(_IMG_TOKEN)
    segments = []
    for j, part in enumerate(parts):
        p = part.strip()
        if p:
            segments.append(('text', p))
        if j < len(parts) - 1:
            segments.append(('image', None))
    return segments


# ── 图片对齐 ──────────────────────────────────────────────

def match_images(messages: list, images: list) -> dict:
    """把 [图片] 占位符按时间序对齐到图片文件。

    返回 dict:
      placeholders: [(msg_index, seg_index)] 文档顺序
      assign:       与 placeholders 等长，每项为 image dict 或 None
      hints:        {ordinal: str} 该图片前插入的歧义提示
      summary:      str 数量不等时的汇总提示（空串表示无）
      leftover:     list[image] 多余、未能定位的图片
    """
    placeholders = [
        (mi, si)
        for mi, msg in enumerate(messages)
        for si, (kind, _) in enumerate(msg['segments'])
        if kind == 'image'
    ]
    n = len(placeholders)

    # 按时间戳对齐：占位符按所属消息时间排序、图片按 mtime 排序，再逐位配对。
    # 这样即使消息时间戳完全对应图片修改时间（图片在消息发出时落盘），也能正确归位；
    # 不依赖占位符在文本中的物理先后。次序键带上文档序 k 以保证稳定。
    order       = sorted(range(n), key=lambda k: (messages[placeholders[k][0]]['ts'], k))
    imgs_sorted = sorted(images, key=lambda im: (im['mtime'], im['name']))

    assign = [None] * n
    for rank, k in enumerate(order):
        assign[k] = imgs_sorted[rank] if rank < len(imgs_sorted) else None
    leftover = imgs_sorted[n:]

    # 歧义：同一秒（mtime 相同）的多张图，组内顺序不可靠 —— 在最先渲染处插一次提示
    hints = {}
    groups = {}
    for rank in range(min(n, len(imgs_sorted))):
        groups.setdefault(imgs_sorted[rank]['mtime'], []).append(order[rank])
    for mtime, ks in groups.items():
        if len(ks) > 1:
            hints[min(ks)] = (
                f'⚠ 下面 {len(ks)} 张图片修改时间相同'
                f'（{mtime.strftime("%Y-%m-%d %H:%M:%S")}），'
                f'自动排序可能与实际不符，请自行核对'
            )

    summary = ''
    if n != len(images):
        summary = f'共 {n} 个 [图片] 占位符，{len(images)} 张图片，已按时间顺序对应。'
        if leftover:
            summary += f'多出的 {len(leftover)} 张未能在文本中定位，已附在末尾。'
        elif n > len(images):
            summary += f'有 {n - len(images)} 个占位符没有对应图片。'

    return {
        'placeholders': placeholders,
        'assign':       assign,
        'hints':        hints,
        'summary':      summary,
        'leftover':     leftover,
    }


# ── 渲染 HTML ─────────────────────────────────────────────

def build_html(messages: list, match: dict) -> str:
    """渲染为与在线录制一致的 HTML（每条消息一个 div）。

    调用前 panel 应已给每个 image dict 写入 'url'（上传得到的公开 URL，失败为 None）。
    """
    placeholders = match['placeholders']
    assign       = match['assign']
    hints        = match['hints']
    ph_index     = {key: k for k, key in enumerate(placeholders)}

    rows = []
    if match.get('summary'):
        rows.append(_warn_div(match['summary']))

    for mi, msg in enumerate(messages):
        body = []
        for si, (kind, val) in enumerate(msg['segments']):
            if kind == 'text':
                body.append(escape(val).replace('\n', '<br>'))
                continue
            k = ph_index.get((mi, si))
            if k is not None and k in hints:
                body.append(_warn_div(hints[k]))
            img = assign[k] if (k is not None and k < len(assign)) else None
            url = img.get('url') if img else None
            if url:
                body.append(f'<img src="{escape(url)}" style="max-width:480px;display:block">')
            else:
                body.append('<em style="color:#c00">[图片]（未找到对应图片）</em>')

        rows.append(
            f'{_MSG_DIV_OPEN}'
            f'<span style="font-weight:bold;color:#1a73e8">{escape(msg["name"])}({escape(msg["uid"])})</span>'
            f'<span style="font-size:11px;color:#aaa;margin-left:8px">{escape(msg["ts_str"])}</span>'
            f'<div style="margin-top:4px">{"".join(body)}</div></div>'
        )

    leftover = match.get('leftover') or []
    resolved_leftover = [im for im in leftover if im.get('url')]
    if resolved_leftover:
        rows.append(_warn_div('以下图片未能在文本中定位，按修改时间顺序附在末尾：'))
        for im in resolved_leftover:
            rows.append(
                f'{_MSG_DIV_OPEN}<div>'
                f'<img src="{escape(im["url"])}" style="max-width:480px;display:block">'
                f'<small style="color:#888">{escape(im["name"])}</small>'
                f'</div></div>'
            )

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<style>body{font-family:Arial,sans-serif;font-size:13px;color:#222;'
        'max-width:860px;margin:20px auto;padding:0 16px}</style></head><body>'
        + ''.join(rows)
        + '</body></html>'
    )


def _warn_div(text: str) -> str:
    return (
        '<div style="margin:4px 0;padding:4px 8px;font-size:12px;color:#b71c1c;'
        f'background:#fff8e1;border:1px solid #ffe082;border-radius:4px">{escape(text)}</div>'
    )
