from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from .prompts import DEFAULT_PROMPT, DEFAULT_SKILL


class InstructionFiles:
    """Creates editable defaults once and reads a fresh snapshot per task."""

    def __init__(self, data_dir: Path):
        self.root = data_dir / "instructions"
        self.prompt_path = self.root / "prompt.md"
        self.skill_path = self.root / "experience-extraction" / "SKILL.md"
        self._lock = threading.RLock()
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        with self._lock:
            self._create_if_missing(self.prompt_path, DEFAULT_PROMPT)
            self._create_if_missing(self.skill_path, DEFAULT_SKILL)

    @staticmethod
    def _create_if_missing(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content.rstrip() + "\n")
        except FileExistsError:
            pass

    def read_prompt(self) -> str:
        return self._read_nonempty(self.prompt_path, "Prompt")[0]

    def read_skill(self) -> tuple[str, str]:
        content, raw = self._read_nonempty(self.skill_path, "Skill")
        digest = hashlib.sha256(raw).hexdigest()
        return content, digest

    @staticmethod
    def _read_nonempty(path: Path, label: str) -> tuple[str, bytes]:
        error: OSError | None = None
        for attempt in range(3):
            try:
                raw = path.read_bytes()
                time.sleep(0.05)
                if raw != path.read_bytes():
                    if attempt < 2:
                        continue
                    raise ValueError(f"{label} 文件正在被修改，请保存完成后重试：{path}")
                content = raw.decode("utf-8-sig").strip()
                if not content:
                    raise ValueError(f"{label} 文件不能为空：{path}")
                return content, raw
            except UnicodeDecodeError as exc:
                raise ValueError(f"{label} 文件必须使用 UTF-8 编码：{path}") from exc
            except OSError as exc:
                error = exc
                if attempt < 2:
                    time.sleep(0.1)
        raise ValueError(f"无法读取 {label} 文件：{path}") from error
