"""win32com Outlook 访问封装"""
import os
import tempfile
import pythoncom
import win32com.client

_INBOX = 6  # olFolderInbox


def _ns():
    pythoncom.CoInitialize()
    return win32com.client.Dispatch('Outlook.Application').GetNamespace('MAPI')


# ── 文件夹 ────────────────────────────────────────────────

def folder_list() -> list:
    """返回所有文件夹路径列表"""
    ns = _ns()
    result = []
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
    """按路径获取文件夹，格式 StoreName\\Inbox\\Sub"""
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


# ── 正文搜索 ──────────────────────────────────────────────

_BODY_FIELD = '"urn:schemas:httpmail:textdescription"'


def search_body(scan_folders: list, keywords: list) -> set:
    """
    用 Outlook Restrict() 搜索正文包含关键词的邮件，返回 EntryID 集合。
    关键词之间取 OR（任一命中即返回）。
    """
    if not keywords:
        return set()

    ns = _ns()
    folders_to_scan = []
    if scan_folders:
        for path in scan_folders:
            try:
                folders_to_scan.append(_get_folder(ns, path))
            except Exception:
                pass
    if not folders_to_scan:
        folders_to_scan = [ns.GetDefaultFolder(_INBOX)]

    conditions = []
    for kw in keywords:
        escaped = kw.replace("'", "''")
        conditions.append(f"{_BODY_FIELD} LIKE '%{escaped}%'")

    if len(conditions) == 1:
        dasl = f'@SQL={conditions[0]}'
    else:
        dasl = '@SQL=(' + ' OR '.join(conditions) + ')'

    matched = set()
    for folder in folders_to_scan:
        try:
            for item in folder.Items.Restrict(dasl):
                try:
                    matched.add(item.EntryID)
                except Exception:
                    pass
        except Exception:
            pass

    return matched


# ── 邮件列表 ──────────────────────────────────────────────

def mail_list(scan_folders: list = None, count: int = 9999) -> list:
    """
    返回邮件摘要列表（不含正文），按接收时间倒序。
    scan_folders 为空时扫描默认收件箱。
    """
    ns = _ns()

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

    result = []
    for folder in folders:
        try:
            items = folder.Items
            folder_count = items.Count
            result.append({'_diag': f'{folder.Name} ({folder_count}封)'})
            try:
                items.Sort('[ReceivedTime]', True)
            except Exception:
                pass
            n = min(count, folder_count)
            for i in range(n):
                try:
                    m = items[i + 1]
                    result.append({
                        'item_id':            m.EntryID,
                        'subject':            m.Subject or '',
                        'sender_name':        m.SenderName or '',
                        'sender_email':       m.SenderEmailAddress or '',
                        'received_time':      m.ReceivedTime.strftime('%Y-%m-%dT%H:%M:%S'),
                        'conversation_topic': m.ConversationTopic or '',
                    })
                except Exception:
                    pass
        except Exception as e:
            result.append({'_folder_error': str(e)})

    result.sort(key=lambda x: x['received_time'], reverse=True)
    return result[:count]


# ── 邮件详情 ──────────────────────────────────────────────

def mail_get(entry_id: str, img_api: str = '') -> dict:
    """获取单封邮件详情，含 HTML 正文，可选处理内联图片"""
    import re
    ns = _ns()
    m = ns.GetItemFromID(entry_id)
    html = m.HTMLBody or ''

    if img_api:
        try:
            html = _process_images(m, html, img_api)
        except Exception:
            pass
    # 清理未能上传的 cid: 引用，避免浏览器显示裂图
    html = re.sub(r'src=["\']cid:[^"\']*["\']', 'src=""', html)

    return {
        'item_id':            entry_id,
        'subject':            m.Subject or '',
        'sender_name':        m.SenderName or '',
        'sender_email':       m.SenderEmailAddress or '',
        'received_time':      m.ReceivedTime.strftime('%Y-%m-%dT%H:%M:%S'),
        'conversation_topic': m.ConversationTopic or '',
        'html_body':          html,
    }


def _process_images(mail_item, html: str, img_api: str) -> str:
    """上传内联附件图片，替换 cid: 引用为远端 URL"""
    import requests

    PR_ATTACH_CONTENT_ID = 'http://schemas.microsoft.com/mapi/proptag/0x3712001E'
    cid_map = {}

    for att in mail_item.Attachments:
        if att.Type != 1:   # olByValue
            continue
        try:
            cid = att.PropertyAccessor.GetProperty(PR_ATTACH_CONTENT_ID).strip('<>')
        except Exception:
            cid = att.FileName

        suffix = os.path.splitext(att.FileName)[1] or '.bin'
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            att.SaveAsFile(tmp.name)
            tmp.close()
            with open(tmp.name, 'rb') as f:
                resp = requests.post(
                    f'{img_api.rstrip("/")}/api/email/upload_image',
                    files={'file': (att.FileName, f)},
                    timeout=30, verify=False,
                )
                resp.raise_for_status()
                data = resp.json()
                url = data.get('Url') or data.get('url') or data.get('URL')
                if url:
                    cid_map[cid] = url
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    for cid, url in cid_map.items():
        html = html.replace(f'cid:{cid}', url)
    return html
