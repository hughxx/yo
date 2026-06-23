"""outlook_cli —— 单机版 Outlook 操作命令行工具。

约定（DESIGN.md §9）：
- 成功：stdout 输出 JSON，退出码 0。
- 失败：stderr 输出 {"error": "..."}，退出码非 0。

子命令：
  folder-list
  list        --folders a,b   --count N
  search-body --folders a,b   --keywords k1,k2
  get         --entry-id ID
  msg-get     --path file.msg
  add-pst     --path file.pst
  remove-pst  --display-name N
"""
import argparse
import json
import sys

import outlook


def _emit(obj):
    # 显式 UTF-8 字节输出：Windows 下 piped stdout 默认 GBK，会让中文变乱码。
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


def _split(csv: str) -> list:
    return [x for x in (csv or '').split(',') if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(prog='outlook_cli')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('folder-list')

    p_list = sub.add_parser('list')
    p_list.add_argument('--folders', default='')
    p_list.add_argument('--count', type=int, default=9999)

    p_sb = sub.add_parser('search-body')
    p_sb.add_argument('--folders', default='')
    p_sb.add_argument('--keywords', default='')

    p_get = sub.add_parser('get')
    p_get.add_argument('--entry-id', required=True)

    p_msg = sub.add_parser('msg-get')
    p_msg.add_argument('--path', required=True)

    p_add = sub.add_parser('add-pst')
    p_add.add_argument('--path', required=True)

    p_rm = sub.add_parser('remove-pst')
    p_rm.add_argument('--display-name', required=True)

    args = parser.parse_args()

    if args.cmd == 'folder-list':
        _emit(outlook.folder_list())
    elif args.cmd == 'list':
        _emit(outlook.mail_list(_split(args.folders), args.count))
    elif args.cmd == 'search-body':
        _emit(outlook.search_body(_split(args.folders), _split(args.keywords)))
    elif args.cmd == 'get':
        _emit(outlook.mail_get(args.entry_id))
    elif args.cmd == 'msg-get':
        _emit(outlook.msg_get(args.path))
    elif args.cmd == 'add-pst':
        _emit({'display_name': outlook.add_pst(args.path)})
    elif args.cmd == 'remove-pst':
        _emit({'ok': outlook.remove_pst(args.display_name)})
    else:
        raise SystemExit(2)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 — 顶层兜底，统一错误输出
        sys.stderr.buffer.write(json.dumps({'error': str(e)}, ensure_ascii=False).encode('utf-8'))
        sys.stderr.buffer.flush()
        sys.exit(1)
