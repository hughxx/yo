"""把邮件的 HTML 与 MD 两份都存到本地目录（用户可在初始配置里改目录）。"""
import re
from pathlib import Path


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', name or '').strip().strip('.')
    return (name or 'untitled')[:120]


def save_email(output_dir: str, title: str, html: str, md: str) -> None:
    """在 output_dir 下写 <安全标题>.html 和 .md。尽力而为，失败不影响同步。"""
    if not output_dir:
        return
    try:
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)
        stem = _safe_name(title)
        if html:
            (base / f'{stem}.html').write_text(html, encoding='utf-8')
        if md:
            (base / f'{stem}.md').write_text(md, encoding='utf-8')
    except Exception:
        pass
