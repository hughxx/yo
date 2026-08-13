from __future__ import annotations

import json
from urllib.parse import quote

import requests


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

    def upload(self, workspace_id: str, path: str, filename: str, content: bytes) -> str:
        data = self._request("post", f"/api/workspaces/{workspace_id}/upload",
                             data={"path": path}, files={"file": (filename, content)})
        return str(data.get("path") or f"{path}/{filename}")

    def read_text(self, workspace_id: str, path: str) -> str:
        data = self._request("get", f"/api/workspaces/{workspace_id}/file",
                             params={"path": path})
        return str(data.get("content") or "")

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

    def submit(self, workspace_id: str, session_id: str, skill_id: str) -> str:
        workspace_path = f"/workspace/{workspace_id}"
        prompt = (
            f"使用 `{skill_id}` Skill 执行本次 WeLink 经验提取。"
            "读取 input/chat.md 和 attachments/，严格按 Skill 要求写出 output/experience.json。"
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
        response.raise_for_status()
        return response.json() if response.content else {}

    def _headers(self, accept: str) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json; charset=utf-8", "Accept": accept}
