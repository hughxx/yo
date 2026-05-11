"""ews_cli 子进程封装"""
import json
import os
import subprocess
import sys

_NO_WIN = subprocess.CREATE_NO_WINDOW  # 不弹黑框


def _exe():
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'ews_cli.exe')
    candidates = [
        os.path.join(os.path.dirname(__file__), 'ews_cli.exe'),
        os.path.join(os.path.dirname(__file__), '..', 'ews_cli', 'dist', 'ews_cli.exe'),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return 'ews_cli.exe'


def _run(args: list) -> dict:
    r = subprocess.run(
        [_exe()] + args,
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        creationflags=_NO_WIN,
    )
    if r.returncode != 0:
        try:
            msg = json.loads(r.stderr).get('error', r.stderr)
        except Exception:
            msg = r.stderr or 'CLI 执行失败'
        raise RuntimeError(msg)
    return json.loads(r.stdout)


# ── config ────────────────────────────────────────────────
def config_get():
    return _run(['mail', 'config-show'])

def config_set(email: str, password: str, ews_url: str = ''):
    args = ['mail', 'config', '--email', email, '--password', password]
    if ews_url:
        args += ['--ews-url', ews_url]
    return _run(args)

# ── mail ──────────────────────────────────────────────────
def mail_list(count: int = 100, since: str = ''):
    args = ['mail', 'list', '--count', str(count)]
    if since:
        args += ['--since', since]
    return _run(args)

def mail_get(item_ids: list, img_api: str = ''):
    args = ['mail', 'get', '--item-ids', ','.join(item_ids)]
    if img_api:
        args += ['--img-api', img_api]
    return _run(args)

# ── folder ────────────────────────────────────────────────
def folder_list():
    return _run(['mail', 'folder', 'list'])

def folder_show():
    return _run(['mail', 'folder', 'show'])

def folder_add(path: str):
    return _run(['mail', 'folder', 'add', '--path', path])

def folder_remove(path: str):
    return _run(['mail', 'folder', 'remove', '--path', path])

# ── rule ──────────────────────────────────────────────────
def rule_list():
    return _run(['mail', 'rule', 'list'])

def rule_add(name, keywords, senders, logic):
    return _run(['mail', 'rule', 'add',
                 '--name', name,
                 '--keywords', ','.join(keywords),
                 '--senders',  ','.join(senders),
                 '--logic',    logic])

def rule_edit(rule_id, patch: dict):
    args = ['mail', 'rule', 'edit', '--id', rule_id]
    if 'name'     in patch: args += ['--name',     patch['name']]
    if 'keywords' in patch: args += ['--keywords', ','.join(patch['keywords'])]
    if 'senders'  in patch: args += ['--senders',  ','.join(patch['senders'])]
    if 'logic'    in patch: args += ['--logic',    patch['logic']]
    if 'enabled'  in patch: args += ['--enabled'   if patch['enabled'] else '--disabled']
    return _run(args)

def rule_delete(rule_id):
    return _run(['mail', 'rule', 'delete', '--id', rule_id])
