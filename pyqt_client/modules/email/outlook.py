"""win32com Outlook 访问封装"""
import os
import threading
import tempfile
from contextlib import contextmanager
import pythoncom
import win32com.client
import win32timezone  # noqa: F401 — PyInstaller must bundle this for win32com timezone handling

_INBOX = 6  # olFolderInbox

# 串行化所有 Outlook COM 访问：folder_list / mail_list / mail_get / search_* 各在
# 自己的 Worker 线程里跑，若并发同时自动化同一个 Outlook 实例，会触发
# RPC_E_CALL_REJECTED（“应用程序正忙”），表现为某个调用静默失败——例如启动时
# 文件夹树和邮件刷新同时拉 Outlook，文件夹就加载不出来。加全局锁逐个来。
_COM_LOCK = threading.Lock()


@contextmanager
def _session():
    """
    打开一次 MAPI 会话，离开时务必配对 CoUninitialize 并释放 namespace。

    历史 bug：旧 _ns() 每次调用只 CoInitialize 不 CoUninitialize，且每次新建
    Outlook.Application/namespace 从不释放。mail_get 又是每封邮件调一次，
    导致同时打开的 MAPI 对象越积越多，最终触发“Outlook 已用完所有共享资源”
    （MAPI_E_NO_RESOURCES）。务必通过本上下文管理器获取 namespace。
    """
    with _COM_LOCK:
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
    """返回所有文件夹路径列表"""
    import time
    result = []
    with _session() as ns:
        # 冷启动时若先于任何取信操作直接枚举 ns.Stores，MAPI 可能尚未 logon，
        # 返回空集合（表现为“加载完成 0 个”）。先碰一下默认收件箱强制 logon，
        # Outlook 刚被拉起时 logon 需要时间，重试等到 Stores 出现再枚举。
        for _ in range(20):   # 最多约 10s
            try:
                ns.GetDefaultFolder(_INBOX)
                if ns.Stores.Count > 0:
                    break
            except Exception:
                pass
            time.sleep(0.5)
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


# PST 不再由本程序挂载：用户用 Outlook 自带「打开 Outlook 数据文件」/「导入」即可，
# 挂载后会自然出现在 folder_list() / mail_list() 的 ns.Stores 遍历里，无需额外对接。


# ── 关键词搜索（主题 / 正文 / 发件人）────────────────────────
#
# 全部交给 Outlook 自带搜索，而不是在 Python 里做子串包含：
#   旧实现里主题、发件人是 `keyword in subject` 子串匹配，没有词边界，
#   会把无关邮件判为命中（关键词 "PO" 命中 "Report"、发件人 "li" 命中 "Alison"）。
# 这里改用内容索引的前缀匹配 ci_startswith —— 与 Outlook 搜索框输入关键词时
# 完全一致的引擎和语义（"inv" 带出 invoice，"PO" 带 Port/Position 但不命中 Report）。
# 不分中英文：中文由 Outlook 分词器自行处理，和搜索框表现一致。
# 仅当目标 store 没建内容索引（极少数 PST，连搜索框都会提示结果不完整）时，
# 才回退到 LIKE 子串，保证不漏匹配。

_SUBJECT_FIELD  = '"urn:schemas:httpmail:subject"'
_BODY_FIELD     = '"urn:schemas:httpmail:textdescription"'
_FROMNAME_FIELD = '"urn:schemas:httpmail:fromname"'
_FROMMAIL_FIELD = '"urn:schemas:httpmail:fromemail"'


def _resolve_folders(ns, scan_folders: list) -> list:
    folders = []
    if scan_folders:
        for path in scan_folders:
            try:
                folders.append(_get_folder(ns, path))
            except Exception:
                pass
    if not folders:
        folders = [ns.GetDefaultFolder(_INBOX)]
    return folders


def _dasl(fields: list, keywords: list, force_like: bool = False) -> str:
    """构造 @SQL 查询：每个关键词在所有 fields 上取 OR，关键词之间也取 OR。

    默认用 ci_startswith（前缀匹配，与 Outlook 搜索框一致，不分中英文）；
    force_like=True 时退化为 LIKE 子串（用于 store 无内容索引的兜底）。
    """
    conds = []
    for kw in keywords:
        esc = kw.replace("'", "''")
        for field in fields:
            if force_like:
                conds.append(f"{field} LIKE '%{esc}%'")
            else:
                conds.append(f"{field} ci_startswith '{esc}'")
    body = conds[0] if len(conds) == 1 else '(' + ' OR '.join(conds) + ')'
    return '@SQL=' + body


def _collect(folder, dasl: str, out: set):
    restricted = folder.Items.Restrict(dasl)
    item = restricted.GetFirst()
    while item is not None:
        try:
            out.add(item.EntryID)
        except Exception:
            pass
        item = restricted.GetNext()  # 逐个推进，旧 item 引用即时释放


def _search(scan_folders: list, fields: list, keywords: list) -> set:
    """在 fields 上搜 keywords（OR），返回命中邮件的 EntryID 集合。

    每个文件夹先用 ci_startswith（前缀，和搜索框一致）；若该 store 未建索引
    导致 Restrict 抛错，则回退该文件夹到 LIKE 子串，避免漏匹配。
    """
    if not keywords:
        return set()
    matched = set()
    with _session() as ns:
        for folder in _resolve_folders(ns, scan_folders):
            try:
                _collect(folder, _dasl(fields, keywords), matched)
            except Exception:
                try:  # 该 store 未建内容索引时 ci_phrasematch 会抛错，退化为 LIKE
                    _collect(folder, _dasl(fields, keywords, force_like=True), matched)
                except Exception:
                    pass
    return matched


def search_subject(scan_folders: list, keywords: list) -> set:
    """整词搜索主题命中的邮件 EntryID。"""
    return _search(scan_folders, [_SUBJECT_FIELD], keywords)


def search_body(scan_folders: list, keywords: list) -> set:
    """整词搜索正文命中的邮件 EntryID。"""
    return _search(scan_folders, [_BODY_FIELD], keywords)


def search_senders(scan_folders: list, keywords: list) -> set:
    """整词搜索发件人（姓名或邮箱）命中的邮件 EntryID。"""
    return _search(scan_folders, [_FROMNAME_FIELD, _FROMMAIL_FIELD], keywords)


# ── 邮件列表 ──────────────────────────────────────────────

def mail_list(scan_folders: list = None, count: int = 9999) -> list:
    """
    返回邮件摘要列表（不含正文），按接收时间倒序。
    scan_folders 为空时扫描默认收件箱。
    """
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
                folder_count = items.Count
                try:
                    items.Sort('[ReceivedTime]', True)
                except Exception:
                    pass
                ok = 0
                first_err = None
                # GetFirst/GetNext 逐个枚举：每推进一次旧 item 引用即释放，
                # 避免按索引一次性打开上千个 MAPI 对象导致资源耗尽。
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
                    except Exception as e:
                        if first_err is None:
                            first_err = repr(e)
                    m = items.GetNext()
                diag = f'{folder.Name} ({folder_count}封，读取{ok}封)'
                if first_err:
                    diag += f'  错误: {first_err}'
                result.append({'_diag': diag})
            except Exception as e:
                result.append({'_folder_error': str(e)})

    diag_entries = [x for x in result if '_diag' in x or '_folder_error' in x]
    email_entries = [x for x in result if '_diag' not in x and '_folder_error' not in x]
    email_entries.sort(key=lambda x: x['received_time'], reverse=True)
    return diag_entries + email_entries[:count]


# ── 邮件详情 ──────────────────────────────────────────────

def mail_get(entry_id: str, img_api: str = '') -> dict:
    """获取单封邮件详情，含 HTML 正文，可选处理内联图片"""
    import re
    with _session() as ns:
        m = ns.GetItemFromID(entry_id)
        html = m.HTMLBody or ''
        html = html.replace('<head>', '<head><meta charset="utf-8">', 1)

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
                    f'{img_api.rstrip("/")}/api/image/upload',
                    files={'file': (att.FileName, f)},
                    timeout=30, verify=False,
                )
                resp.raise_for_status()
                data = resp.json()
                url = data.get('url')
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
