"""统一数据目录：配置与存档优先放 D 盘（D 不可用时退回用户主目录）。"""
import shutil
import sys
from pathlib import Path

_APP_NAME = 'CoreMiner'
_LEGACY_APP_NAME = '问题定位助手'


def app_data_dir() -> Path:
    """数据根目录：优先 D:\\CoreMiner；不可用时退回用户目录或程序目录。"""
    for base in (Path('D:/') / _APP_NAME, Path.home() / _APP_NAME):
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base
        except Exception:
            continue
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent


def config_dir() -> Path:
    p = app_data_dir() / 'config'
    try:
        p.mkdir(parents=True, exist_ok=True)
        # First CoreMiner launch keeps existing settings/rules from the old
        # product name without copying potentially large mail archives.
        for legacy_root in (Path('D:/') / _LEGACY_APP_NAME, Path.home() / _LEGACY_APP_NAME):
            legacy_config = legacy_root / 'config'
            if not legacy_config.exists():
                continue
            for source in legacy_config.iterdir():
                target = p / source.name
                if source.is_file() and not target.exists():
                    shutil.copy2(source, target)
    except Exception:
        pass
    return p


def default_output_dir() -> Path:
    """html / md 默认保存目录。"""
    return app_data_dir() / '邮件存档'


def migrate(old: Path, new: Path) -> None:
    """旧位置存在、新位置不存在时，把旧配置搬过来一次（不丢用户已有配置）。"""
    try:
        if old.exists() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_bytes(old.read_bytes())
    except Exception:
        pass
