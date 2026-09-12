from __future__ import annotations

import json
import logging
import os
import signal
import shutil
import subprocess
import threading
import time
from pathlib import Path

import requests

from .config import Settings


logger = logging.getLogger(__name__)


class ModelResourceRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, resource: str) -> None:
        if resource == "prompt":
            missing = []
            if not self.settings.llm_base_url:
                missing.append("COREINSIGHT_LLM_BASE_URL")
            if not self.settings.llm_api_key:
                missing.append("COREINSIGHT_LLM_API_KEY")
            if not self.settings.llm_model_id:
                missing.append("COREINSIGHT_LLM_MODEL_ID")
            if missing:
                raise ValueError("缺少大模型配置：" + ", ".join(missing))
        elif resource != "skill":
            raise ValueError("resource 只支持 prompt 或 skill")

    def generate(self, resource: str, prompt: str, workspace: Path,
                 cancel_event=None, progress=None) -> str:
        self.validate(resource)
        if resource == "prompt":
            return self._llm(prompt, cancel_event, progress)
        return self._codeagent(prompt, workspace, cancel_event, progress)

    def _llm(self, prompt: str, cancel_event=None, progress=None) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        if progress:
            progress("model", "正在使用 Prompt 调用大模型")
        response = requests.post(
            self.settings.llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.settings.llm_model_id,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.2, "stream": False},
            timeout=self.settings.model_timeout_seconds, verify=False)
        response.raise_for_status()
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        try:
            return str(response.json()["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("大模型返回格式无效") from exc

    def _codeagent(self, prompt: str, workspace: Path,
                   cancel_event=None, progress=None) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        if progress:
            progress("agent", "正在使用 CodeAgent 和 Skill 提取")
        workspace.mkdir(parents=True, exist_ok=True)
        arguments = ["--skip-safe-check", "--print", "--verbose",
                     "--output-format", "stream-json", "--permission-mode",
                     "bypassPermissions"]
        if self.settings.codeagent_model:
            arguments.extend(["--model", self.settings.codeagent_model])
        command = self._resolve_codeagent_command(arguments)
        popen_options = self._process_group_options()
        try:
            process = subprocess.Popen(
                command, cwd=str(workspace), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                **popen_options)
        except OSError as exc:
            raise ValueError(
                f"CodeAgent 不可用，请检查命令：{self.settings.codeagent_command}") from exc

        outputs: list[str] = []
        diagnostics: list[str] = []
        terminal = threading.Event()
        reader_finished = threading.Event()
        session_ids: list[str] = []
        log_path = self.settings.data_dir / "logs" / "model-resource.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        reader = threading.Thread(
            target=self._read_codeagent_events,
            args=(process, log_path, outputs, diagnostics, session_ids, terminal,
                  reader_finished), daemon=True)
        reader.start()
        try:
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            self._kill_process_tree(process)
            raise RuntimeError("CodeAgent 未能从 stdin 接收任务") from exc

        deadline = time.monotonic() + self.settings.model_timeout_seconds
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("任务已取消")
                if terminal.is_set():
                    reader_finished.wait(1.0)
                    break
                if process.poll() is not None:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"CodeAgent 执行超过 {self.settings.model_timeout_seconds} 秒")
                terminal.wait(0.2)
        except Exception:
            self._kill_process_tree(process)
            raise
        finally:
            if terminal.is_set() and process.poll() is None:
                self._kill_process_tree(process)
            reader.join(timeout=2)

        code = process.poll()
        if not terminal.is_set():
            detail = f"：{diagnostics[-1]}" if diagnostics else ""
            raise RuntimeError(
                f"CodeAgent 未返回 result 终止事件，退出码 {code}{detail}")
        if session_ids:
            logger.info("codeagent completed session_id=%s", session_ids[-1])
        if not outputs:
            raise RuntimeError("CodeAgent result 事件中没有可用结果")
        return outputs[-1].strip()

    def _resolve_codeagent_command(self, arguments: list[str],
                                   windows: bool | None = None) -> list[str] | str:
        configured = self.settings.codeagent_command.strip().strip('"')
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            executable = str(configured_path.resolve())
        else:
            executable = shutil.which(configured) or ""
        if not executable:
            raise ValueError(
                "CodeAgent 不可用：未在 PATH 中找到命令 "
                f"{self.settings.codeagent_command}")

        command = [executable, *arguments]
        is_windows = os.name == "nt" if windows is None else windows
        if not is_windows or Path(executable).suffix.lower() not in (".cmd", ".bat"):
            return command

        command_processor = (
            os.environ.get("COMSPEC", "").strip()
            or shutil.which("cmd.exe")
            or "cmd.exe"
        )
        # Keep the task prompt on stdin.  Only the fixed CLI arguments pass
        # through cmd.exe, which is required for npm's .cmd/.bat wrappers.
        command_line = subprocess.list2cmdline(command)
        prefix = subprocess.list2cmdline(
            [command_processor, "/d", "/s", "/c"])
        # Popen must receive one Windows command-line string here. Passing the
        # quoted /c payload as a list item makes Python escape its quotes with
        # backslashes; cmd.exe then treats the literal \"path\" as the command.
        return f'{prefix} "{command_line}"'

    @staticmethod
    def _read_codeagent_events(process: subprocess.Popen, log_path: Path,
                               outputs: list[str], diagnostics: list[str],
                               session_ids: list[str],
                               terminal: threading.Event,
                               finished: threading.Event) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as log:
                for line in process.stdout or []:
                    log.write(line)
                    log.flush()
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        value = line.strip()
                        if value:
                            diagnostics.append(value[-1000:])
                            del diagnostics[:-20]
                        continue
                    session_id = ModelResourceRunner._find_string(
                        item, "session_id")
                    if session_id:
                        session_ids.append(session_id)
                    event_type = str(item.get("type") or "").lower()
                    if event_type == "assistant":
                        outputs.extend(
                            ModelResourceRunner._assistant_texts(item))
                    if event_type == "result":
                        result = item.get("result")
                        if isinstance(result, str) and result.strip():
                            outputs.append(result)
                        terminal.set()
        finally:
            finished.set()

    @staticmethod
    def _assistant_texts(item: object) -> list[str]:
        texts: list[str] = []
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "text" and isinstance(value, str) and value.strip():
                    texts.append(value)
                elif key in ("message", "content"):
                    texts.extend(ModelResourceRunner._assistant_texts(value))
        elif isinstance(item, list):
            for value in item:
                texts.extend(ModelResourceRunner._assistant_texts(value))
        return texts

    @staticmethod
    def _find_string(item: object, key: str) -> str:
        if isinstance(item, dict):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
            for child in item.values():
                found = ModelResourceRunner._find_string(child, key)
                if found:
                    return found
        elif isinstance(item, list):
            for child in item:
                found = ModelResourceRunner._find_string(child, key)
                if found:
                    return found
        return ""

    @staticmethod
    def _process_group_options() -> dict:
        if os.name == "nt":
            return {"creationflags": (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0))}
        return {"start_new_session": True}

    @staticmethod
    def _kill_process_tree(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=False, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            logger.warning("failed to terminate CodeAgent process tree pid=%s",
                           process.pid, exc_info=True)
        finally:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
