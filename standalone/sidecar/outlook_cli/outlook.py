"""win32com Outlook 访问封装（单机版 sidecar）。

与旧 pyqt_client 版的区别：
- 取邮件详情时**不再上传图片**，而是把内联 cid 附件导出到临时文件，
  返回 inline_images:[{cid, path}]，由 Rust 决定上传换链或剔除（见 DESIGN.md §6）。
- HTML 中的 cid: 引用保持原样，不再置空。
"""
import hashlib
import os
import tempfile
from contextlib import contextmanager

import pythoncom
import win32com.client
import win32timezone  # noqa: F401 — PyInstaller 需打包它以支持 win32com 时区

_INBOX = 6  # olFolderInbox


@contextmanager
def _session():
    """打开一次 MAPI 会话，离开时配对 CoUninitialize 并释放 namespace。

    历史 bug：不配对 CoInitialize/CoUninitialize、不释放 namespace 会导致
    MAPI 对象越积越多，最终触发 MAPI_E_NO_RESOURCES。务必通过本上下文获取。
    """
    pythoncom.CoInitialize()
    ns = None
    try:
        ns = win32com.client.Dispatch('Outlook.Application').GetNamespace('MAPI')
        yield ns
    finally:
        ns = None
        pythoncom.CoUninitialize()


# ── 文件夹 ────────────────────────────────────────────────

def folder_list() -> list:
    result = []
    with _session() as ns:
        for store in ns.Stores:
            try:
                _collect(store.GetRootFolder(), result, '')
            except Exception:
                pass
    return result


def _collect(folder, out: list, prefix: str):
    path = f'{prefix}\\{folder.Name}' if prefix else folder.Name
    out.append(path)
    try:
        for sub in folder.Folders:
            _collect(sub, out, path)
    except Exception:
        pass


def _get_folder(ns, path: str):
    parts = path.split('\\')
    for store in ns.Stores:
        try:
            root = store.GetRootFolder()
            if root.Name != parts[0] and store.DisplayName != parts[0]:
                continue
            folder = root
            for part in parts[1:]:
                folder = folder.Folders[part]
            return folder
        except Exception:
            continue
    raise FileNotFoundError(f'找不到文件夹: {path}')


# ── PST 挂载 ──────────────────────────────────────────────

def add_pst(path: str) -> str:
    """挂载 .pst，返回新 store 显示名；已挂载则返回空串。"""
    with _session() as ns:
        before = set()
        for st in ns.Stores:
            try:
                before.add(st.StoreID)
            except Exception:
                pass
        ns.AddStore(path)
        for st in ns.Stores:
            try:
                if st.StoreID not in before:
                    return st.DisplayName or ''
            except Exception:
                continue
        return ''


def remove_pst(display_name: str) -> bool:
    with _session() as ns:
        for st in ns.Stores:
            try:
                if st.DisplayName == display_name:
                    ns.RemoveStore(st.GetRootFolder())
                    return True
            except Exception:
                continue
    return False


# ── 正文搜索 ──────────────────────────────────────────────

_BODY_FIELD = '"urn:schemas:httpmail:textdescription"'


def search_body(scan_folders: list, keywords: list) -> list:
    """正文包含任一关键词（OR）的邮件 EntryID 列表。"""
    if not keywords:
        return []

    conditions = []
    for kw in keywords:
        escaped = kw.replace("'", "''")
        conditions.append(f"{_BODY_FIELD} LIKE '%{escaped}%'")
    dasl = (f'@SQL={conditions[0]}' if len(conditions) == 1
            else '@SQL=(' + ' OR '.join(conditions) + ')')

    matched = set()
    with _session() as ns:
        folders_to_scan = []
        if scan_folders:
            for path in scan_folders:
                try:
                    folders_to_scan.append(_get_folder(ns, path))
                except Exception:
                    pass
        if not folders_to_scan:
            folders_to_scan = [ns.GetDefaultFolder(_INBOX)]

        for folder in folders_to_scan:
            try:
                restricted = folder.Items.Restrict(dasl)
                item = restricted.GetFirst()
                while item is not None:
                    try:
                        matched.add(item.EntryID)
                    except Exception:
                        pass
                    item = restricted.GetNext()
            except Exception:
                pass

    return list(matched)


# ── 邮件列表 ──────────────────────────────────────────────

def mail_list(scan_folders: list = None, count: int = 9999) -> list:
    result = []
    with _session() as ns:
        if scan_folders:
            folders = []
            for path in scan_folders:
                try:
                    folders.append(_get_folder(ns, path))
                except Exception:
                    pass
            if not folders:
                folders = [ns.GetDefaultFolder(_INBOX)]
        else:
            folders = [ns.GetDefaultFolder(_INBOX)]

        for folder in folders:
            try:
                items = folder.Items
                try:
                    items.Sort('[ReceivedTime]', True)
                except Exception:
                    pass
                ok = 0
                m = items.GetFirst()
                while m is not None and ok < count:
                    try:
                        rt = getattr(m, 'ReceivedTime', None)
                        result.append({
                            'item_id':            m.EntryID,
                            'subject':            getattr(m, 'Subject', '') or '',
                            'sender_name':        getattr(m, 'SenderName', '') or '',
                            'sender_email':       getattr(m, 'SenderEmailAddress', '') or '',
                            'received_time':      rt.strftime('%Y-%m-%dT%H:%M:%S') if rt else '1970-01-01T00:00:00',
                            'conversation_topic': getattr(m, 'ConversationTopic', '') or '',
                        })
                        ok += 1
                    except Exception:
                        pass
                    m = items.GetNext()
            except Exception:
                pass

    result.sort(key=lambda x: x['received_time'], reverse=True)
    return result[:count]


# ── 邮件详情 ──────────────────────────────────────────────

def mail_get(entry_id: str) -> dict:
    with _session() as ns:
        m = ns.GetItemFromID(entry_id)
        html = m.HTMLBody or ''
        html = html.replace('<head>', '<head><meta charset="utf-8">', 1)
        inline = _extract_inline_images(m)
        return {
            'item_id':            entry_id,
            'subject':            m.Subject or '',
            'sender_name':        m.SenderName or '',
            'sender_email':       m.SenderEmailAddress or '',
            'received_time':      m.ReceivedTime.strftime('%Y-%m-%dT%H:%M:%S'),
            'conversation_topic': m.ConversationTopic or '',
            'html_body':          html,
            'inline_images':      inline,
        }


def msg_get(path: str) -> dict:
    """读取磁盘 .msg 为邮件详情，字段与 mail_get 一致。"""
    with _session() as ns:
        m = ns.OpenSharedItem(path)
        try:
            html = m.HTMLBody or ''
        except Exception:
            html = ''
        html = html.replace('<head>', '<head><meta charset="utf-8">', 1)
        inline = _extract_inline_images(m)

        subject = getattr(m, 'Subject', '') or ''
        stem = os.path.splitext(os.path.basename(path))[0]
        topic = (getattr(m, 'ConversationTopic', '') or '') or subject or stem

        rt = None
        for attr in ('ReceivedTime', 'SentOn'):
            try:
                v = getattr(m, attr, None)
                if v:
                    rt = v
                    break
            except Exception:
                pass
        try:
            rt_str = rt.strftime('%Y-%m-%dT%H:%M:%S') if rt else ''
        except Exception:
            rt_str = ''

        try:
            entry = getattr(m, 'EntryID', '') or ''
        except Exception:
            entry = ''
        if not entry:
            entry = 'msg_' + hashlib.md5(path.encode('utf-8', 'ignore')).hexdigest()[:16]

        return {
            'item_id':            entry,
            'subject':            subject,
            'sender_name':        getattr(m, 'SenderName', '') or '',
            'sender_email':       getattr(m, 'SenderEmailAddress', '') or '',
            'received_time':      rt_str or '1970-01-01T00:00:00',
            'conversation_topic': topic,
            'html_body':          html,
            'inline_images':      inline,
        }


def _extract_inline_images(mail_item) -> list:
    """把内联 cid 附件导出到临时文件，返回 [{cid, path}]。

    不上传、不改写 HTML —— Rust 侧据 inline_images 决定上传换链或剔除。
    """
    PR_ATTACH_CONTENT_ID = 'http://schemas.microsoft.com/mapi/proptag/0x3712001E'
    out = []
    try:
        attachments = mail_item.Attachments
    except Exception:
        return out

    tmp_dir = tempfile.mkdtemp(prefix='outlook_cli_img_')
    idx = 0
    for att in attachments:
        try:
            if att.Type != 1:  # olByValue
                continue
        except Exception:
            continue
        try:
            cid = att.PropertyAccessor.GetProperty(PR_ATTACH_CONTENT_ID).strip('<>')
        except Exception:
            cid = ''
        if not cid:
            # 无 cid 的附件不是内联图，跳过（避免把普通附件也导出）
            continue

        try:
            suffix = os.path.splitext(att.FileName)[1] or '.bin'
        except Exception:
            suffix = '.bin'
        idx += 1
        dest = os.path.join(tmp_dir, f'img_{idx:03d}{suffix}')
        try:
            att.SaveAsFile(dest)
            out.append({'cid': cid, 'path': dest})
        except Exception:
            pass
    return out
