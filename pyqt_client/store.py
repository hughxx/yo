"""设置 + 已处理邮件 ID 持久化"""
import json
import sys
from pathlib import Path

from paths import config_dir, default_output_dir, migrate

def _app_dir() -> Path:
    """exe 同目录（frozen）或脚本目录（开发模式）——仅用于迁移旧配置。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

_CFG       = config_dir()
_SETTINGS  = _CFG / 'settings.json'
_PROCESSED = _CFG / 'processed.json'
# 迁移旧位置（exe/脚本目录）的配置到新的 D 盘 config 目录
migrate(_app_dir() / '.email_assistant.json',           _SETTINGS)
migrate(_app_dir() / '.email_assistant_processed.json', _PROCESSED)

DEFAULT = {
    'backendUrl':          'https://coreinsight-beta.rnd.huawei.com/collection',
    'userId':              '',
    'namespace':           '',
    'scanIntervalMinutes': 60,
    'scanTimerMode':       'interval',
    'scanDailyTime':       '09:00',
    'customJsonConfig':    '{}',
    'scanFolders':         [],
    'outputDir':           str(default_output_dir()),   # html/md 本地保存目录
    # WeLink settings
    'welinkStartCmd':      '@云见 开始定位',
    'welinkEndCmd':        '@云见 结束定位',
    'welinkSummaryCmd':    '@云见 总结经验',
    'welinkUserId':        '',
    'welinkPollInterval':  3,
    'welinkDailyRecord':   False,
    'welinkDailyTime':     '01:00',
    'welinkScheduleRules': [],
    'welinkScheduleTime':  '02:00',
    'lastSyncTime':        '',
}

def load_settings() -> dict:
    if _SETTINGS.exists():
        try:
            return {**DEFAULT, **json.loads(_SETTINGS.read_text('utf-8'))}
        except Exception:
            pass
    return dict(DEFAULT)

def save_settings(s: dict):
    _SETTINGS.write_text(json.dumps(s, ensure_ascii=False, indent=2), 'utf-8')

def load_processed() -> set:
    if _PROCESSED.exists():
        try:
            return set(json.loads(_PROCESSED.read_text('utf-8')))
        except Exception:
            pass
    return set()

def add_processed(ids: list):
    existing = load_processed()
    existing.update(ids)
    _PROCESSED.write_text(json.dumps(list(existing), ensure_ascii=False), 'utf-8')

def clear_processed():
    _PROCESSED.write_text('[]', 'utf-8')

def processed_count() -> int:
    return len(load_processed())
