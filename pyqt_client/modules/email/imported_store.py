"""手动导入 .msg 的本机记录。

.msg 导入后直推后端、客户端本不留态，列表里也看不到。这里在本机记一份，
供「本地导入」页查看与本地删除（删除只移除本机记录，不动后端数据）。
"""
import json
from pathlib import Path

_FILE = Path.home() / '.email_assistant_imported_msgs.json'


def load() -> list:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text('utf-8'))
        except Exception:
            pass
    return []


def save(records: list):
    _FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), 'utf-8')


def add(record: dict):
    """记录一条导入；按 item_id 去重（重复导入则置顶刷新）。"""
    records = [r for r in load() if r.get('item_id') != record.get('item_id')]
    records.insert(0, record)
    save(records)


def delete(item_id):
    save([r for r in load() if r.get('item_id') != item_id])
