from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Settings
from .remote import HermesClient, WorkspaceClient
from .skills import get_skill


_UM_RE = re.compile(r"/:um_begin\{([^}]+)\}/:um_end")


class ExtractionCancelled(RuntimeError):
    pass


class LocalExperienceProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.workspaces = WorkspaceClient(settings.workspace_file_server_url)
        self.hermes = HermesClient(
            settings.hermes_url, settings.hermes_api_key, settings.hermes_timeout_seconds)

    def validate(self, upload_by: str, skill_id: str = "welink-experience-extractor") -> None:
        get_skill(skill_id)
        missing = []
        for name, value in (
            ("COREINSIGHT_HERMES_URL", self.settings.hermes_url),
            ("COREINSIGHT_HERMES_API_KEY", self.settings.hermes_api_key),
            ("COREINSIGHT_WORKSPACE_FILE_SERVER_URL", self.settings.workspace_file_server_url),
            ("COREINSIGHT_EXPERIENCE_ENGINE_URL", self.settings.experience_engine_url),
        ):
            if not value:
                missing.append(name)
        if not upload_by.strip():
            missing.append("COREINSIGHT_UPLOAD_BY")
        if missing:
            raise ValueError("缺少 Skill 提取配置：" + ", ".join(missing))

    def process(self, messages: list[dict], skill_id: str, upload_by: str,
                task_id: str, progress=None, cancel_event=None) -> dict:
        self._check_cancel(cancel_event)
        self.validate(upload_by, skill_id)
        skill = get_skill(skill_id)
        workspace_id = f"welink-{task_id}"
        run_id = ""
        self.workspaces.create(workspace_id)
        try:
            if progress:
                progress("workspace", "正在准备 Skill workspace 和聊天附件")
            markdown = self._to_markdown(messages, workspace_id, cancel_event)
            self.workspaces.write_text(workspace_id, "input/chat.md", markdown)
            self.workspaces.write_text(
                workspace_id, f"skills/{skill_id}/SKILL.md", skill["content"])
            self._check_cancel(cancel_event)
            if progress:
                progress("skill", f"正在运行 Skill：{skill['name']}")
            run_id = self.hermes.submit(workspace_id, task_id, skill_id)
            run_finished = threading.Event()
            if cancel_event is not None:
                threading.Thread(
                    target=self._watch_cancel,
                    args=(run_id, cancel_event, run_finished), daemon=True).start()
            try:
                final_answer = self.hermes.wait(run_id, cancel_event, progress)
            except RuntimeError as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise ExtractionCancelled("任务已取消") from exc
                raise
            finally:
                run_finished.set()
            self._check_cancel(cancel_event)
            result = self._read_result(workspace_id, final_answer)
            if progress:
                progress("pushing", "Skill 已完成，正在写入经验引擎")
            doc_id = uuid.uuid5(uuid.NAMESPACE_DNS, task_id).hex
            self._push_experience(result, upload_by, doc_id)
            return {"docId": doc_id, "title": result["title"],
                    "skillId": skill_id, "remoteRunId": run_id}
        finally:
            if cancel_event is not None and cancel_event.is_set() and run_id:
                self.hermes.stop(run_id)
            self.workspaces.delete(workspace_id)

    def _watch_cancel(self, run_id: str, cancel_event, run_finished) -> None:
        while not run_finished.wait(0.2):
            if cancel_event.is_set():
                self.hermes.stop(run_id)
                return

    @staticmethod
    def _check_cancel(cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ExtractionCancelled("任务已取消")

    def _to_markdown(self, messages: list[dict], workspace_id: str,
                     cancel_event=None) -> str:
        rows = []
        for item in sorted(messages, key=lambda value: (
                int(value.get("timestamp") or 0), str(value.get("id") or ""))):
            self._check_cancel(cancel_event)
            timestamp = int(item.get("timestamp") or 0)
            when = datetime.fromtimestamp(
                timestamp / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S") \
                if timestamp else ""
            content = str(item.get("rawContent") or item.get("content") or "")
            content = _UM_RE.sub(
                lambda match: self._workspace_attachment(
                    match, workspace_id, cancel_event), content)
            rows.append(
                f"### {item.get('sender') or ''}（{when}）\n\n"
                f"消息 ID：{item.get('id') or ''}\n\n{content}\n")
        return "\n".join(rows)

    def _workspace_attachment(self, match: re.Match, workspace_id: str,
                              cancel_event=None) -> str:
        self._check_cancel(cancel_event)
        parts = match.group(1).split("|")
        if len(parts) < 6:
            return "[无法解析的附件]"
        filename = Path(parts[3] or "attachment.bin").name
        if not self.settings.clouddrive_account or not self.settings.clouddrive_password:
            return f"[附件未下载：缺少 CloudDrive 配置] {filename}"
        try:
            codes = parts[5].split(";")
            content = self._download(parts[0], codes[2] if len(codes) > 2 else "")
            safe_name = f"{uuid.uuid4().hex[:10]}-{filename}"
            relative = self.workspaces.upload(
                workspace_id, "attachments", safe_name, content)
            ocr_text = ""
            if self.settings.ocr_url:
                response = requests.post(
                    self.settings.ocr_url, files={"file": (filename, content)},
                    timeout=300, verify=False)
                response.raise_for_status()
                data = response.json()
                ocr_text = str(data.get("result") or data.get("text") or "") \
                    if isinstance(data, dict) else str(data)
            annotation = f"\n\n> 图片 OCR：{ocr_text.strip()}" if ocr_text.strip() else ""
            return f"[附件：{filename}](/workspace/{workspace_id}/{relative}){annotation}"
        except Exception as exc:
            return f"[附件处理失败：{filename}，{type(exc).__name__}]"

    def _download(self, download_url: str, extraction_code: str) -> bytes:
        token_response = requests.post(
            "https://clouddrive.huawei.com/api/v2/token",
            json={"appId": "espace", "domain": "huawei",
                  "loginName": self.settings.clouddrive_account,
                  "password": self.settings.clouddrive_password},
            headers={"Content-Type": "application/json",
                     "x-device-sn": "coreinsight-local-agent", "x-device-type": "web",
                     "x-device-os": "win10", "x-device-name": "coreinsight",
                     "x-client-version": "10"}, timeout=60, verify=False)
        token_response.raise_for_status()
        token = token_response.json().get("token", "")
        authorization = (
            f"/:um_begin{{{download_url}|File|123|attachment|0|;;{extraction_code}"
            "|isOriginalImg:0}}/:um_end")
        response = requests.post(
            "https://clouddrive.huawei.com/imchat/api/v3/links/imdownload",
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"imAuthorization": authorization}, timeout=300, verify=False)
        response.raise_for_status()
        return response.content

    def _read_result(self, workspace_id: str, final_answer: str) -> dict:
        try:
            raw = self.workspaces.read_text(workspace_id, "output/experience.json")
        except Exception:
            raw = final_answer
        raw = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
        result = json.loads(fenced.group(1) if fenced else raw)
        required = ("title", "summary", "experience", "rag_search_text")
        if not isinstance(result, dict) or any(not isinstance(result.get(key), str) for key in required):
            raise RuntimeError("Skill 输出格式无效，必须包含四个字符串字段")
        return result

    def _push_experience(self, result: dict, upload_by: str, doc_id: str) -> None:
        response = requests.post(self.settings.experience_engine_url, json={
            "doc_id": doc_id, "scene_id": "251", "scene": "WeLink问题定位经验",
            "user_id": upload_by, "title": result["title"], "summary": result["summary"],
            "experience": result["experience"],
            "rag_search_text": result["rag_search_text"],
        }, timeout=60, verify=False)
        response.raise_for_status()
