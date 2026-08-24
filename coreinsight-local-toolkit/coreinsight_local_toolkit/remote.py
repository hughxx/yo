from __future__ import annotations

import json
import hashlib
import logging
from urllib.parse import quote

import requests


logger = logging.getLogger(__name__)


class WorkspaceClient:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def create(self, workspace_id: str) -> None:
        self._request("post", f"/api/workspaces/{workspace_id}")

    def write_text(self, workspace_id: str, path: str, content: str) -> None:
        self._request("put", f"/api/workspaces/{workspace_id}/file",
                      json={"path": path, "content": content})

    def read_text(self, workspace_id: str, path: str) -> str:
        data = self._request("get", f"/api/workspaces/{workspace_id}/file",
                             params={"path": path})
        return str(data.get("content") or "")

    def delete_path(self, workspace_id: str, path: str) -> None:
        self._request("delete", f"/api/workspaces/{workspace_id}/path",
                      params={"path": path}, timeout=30)

    def delete(self, workspace_id: str) -> None:
        try:
            self._request("delete", f"/api/workspaces/{workspace_id}", timeout=30)
        except Exception:
            pass

    def _request(self, method: str, path: str, timeout: int = 60, **kwargs):
        response = self.session.request(method, self.server_url + path, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}


class HermesClient:
    TERMINAL_FAILURES = {"run.failed", "run.stopped", "run.cancelled", "run.canceled"}

    def __init__(self, server_url: str, api_key: str, timeout_seconds: int = 1800):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False
        logger.info(
            "Hermes client ready url=%s api_key_present=%s api_key_len=%d api_key_sha256=%s",
            self.server_url, bool(self.api_key), len(self.api_key or ""),
            hashlib.sha256((self.api_key or "").encode()).hexdigest()[:12],
        )

    def submit(self, workspace_id: str, session_id: str, skill_id: str,
               input_paths: list[str] | None = None, scheduled: bool = False) -> str:
        workspace_path = f"/workspace/{workspace_id}"
        paths = input_paths or []
        path_text = "、".join(paths)
        run_kind = "定时增量" if scheduled else "手动"
        prompt = (
            f"使用 `{skill_id}` Skill 执行本次 WeLink {run_kind}经验提取。"
            f"本轮新增输入文件为：{path_text}。"
            "按文件名顺序读取；需要合并时参考 workspace 内已有输出。"
            "严格原样保留 `![OCR结果](公开URL)`，并按 Skill 要求将本轮新增或更新的经验"
            "逐行追加到 output/experiences.jsonl。不要改写已有行。"
            "必须通过标准 JSON 序列化写入，并在结束前逐行执行 json.loads 校验。"
        )
        instructions = (
            f"当前工作目录是 {workspace_path}。所有文件操作只能在该目录内进行。"
            f"本次必须先读取 {workspace_path}/skills/{skill_id}/SKILL.md 并严格作为 Skill 执行。"
        )
        data = self._json("post", "/v1/runs", json={
            "input": prompt, "session_id": session_id, "instructions": instructions,
        })
        run_id = str(data.get("run_id") or "")
        if not run_id:
            raise RuntimeError(f"Hermes 未返回 run_id：{data}")
        return run_id

    def wait(self, run_id: str, cancel_event=None, progress=None) -> str:
        response = self.session.get(
            f"{self.server_url}/v1/runs/{quote(run_id)}/events",
            headers=self._headers("text/event-stream"), stream=True,
            timeout=(10, self.timeout_seconds),
        )
        response.raise_for_status()
        event_type = ""
        try:
            for raw in response.iter_lines(decode_unicode=False):
                if cancel_event is not None and cancel_event.is_set():
                    self.stop(run_id)
                    raise RuntimeError("任务已取消")
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("event:"):
                    event_type = line[6:].strip(); continue
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if not value or value == "[DONE]":
                    continue
                try:
                    event = json.loads(value)
                except json.JSONDecodeError:
                    continue
                kind = str(event.get("event") or event_type)
                event_type = ""
                if kind == "tool.started" and progress:
                    progress("skill", f"Skill 正在调用工具：{event.get('tool') or 'tool'}")
                if kind == "run.completed":
                    return self.final_answer(run_id)
                if kind in self.TERMINAL_FAILURES:
                    raise RuntimeError(str(event.get("error") or event.get("message") or kind))
        finally:
            response.close()
        return self.final_answer(run_id)

    def final_answer(self, run_id: str) -> str:
        data = self._json("get", f"/v1/runs/{quote(run_id)}")
        output = data.get("output") or data.get("result") or ""
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)

    def stop(self, run_id: str) -> None:
        try:
            self._json("post", f"/v1/runs/{quote(run_id)}/stop", json={}, timeout=10)
        except Exception:
            pass

    def _json(self, method: str, path: str, timeout: int = 30, **kwargs):
        response = self.session.request(
            method, self.server_url + path, headers=self._headers("application/json"),
            timeout=timeout, **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            body = response.text[:500].replace("\n", " ")
            logger.error(
                "Hermes request rejected method=%s path=%s status=%s body=%s",
                method.upper(), path, response.status_code, body,
            )
            raise
        return response.json() if response.content else {}

    def _headers(self, accept: str) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8", "Accept": accept}
