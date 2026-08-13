from __future__ import annotations

import json
import hashlib
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from .config import Settings
from .remote import HermesClient, WorkspaceClient
from .skills import get_skill


_UM_RE = re.compile(r"/:um_begin\{([^}]+)\}/:um_end")
_CHUNK_SIZE = 40_000


class ExtractionCancelled(RuntimeError):
    pass


class LocalExperienceProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.workspaces = WorkspaceClient(settings.workspace_file_server_url)
        self.hermes = HermesClient(
            settings.hermes_url, settings.hermes_api_key, settings.hermes_timeout_seconds)
        self._state_path = settings.data_dir / "welink_workspace_state.json"
        self._state_lock = threading.RLock()

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
                task_id: str, progress=None, cancel_event=None,
                group_id: str = "", scheduled: bool = False) -> dict:
        self._check_cancel(cancel_event)
        self.validate(upload_by, skill_id)
        skill = get_skill(skill_id)
        workspace_id = self._workspace_id(
            task_id, group_id, skill_id, upload_by, scheduled)
        session_id = workspace_id
        state = self._load_workspace_state(workspace_id) if scheduled else {
            "nextChunkSeq": 1, "outputLineOffset": 0}
        first_sequence = int(state.get("nextChunkSeq") or 1)
        run_id = ""
        self.workspaces.create(workspace_id)
        try:
            if progress:
                progress("workspace", "正在生成带图片链接和 OCR 的 Markdown")
            chunks = self._to_markdown_chunks(messages, cancel_event)
            input_paths = []
            for offset, chunk in enumerate(chunks):
                sequence = first_sequence + offset
                path = self._chunk_path(sequence, chunk)
                self.workspaces.write_text(workspace_id, path, chunk["content"])
                input_paths.append(path)
            self.workspaces.write_text(
                workspace_id, f"skills/{skill_id}/SKILL.md", skill["content"])
            self._check_cancel(cancel_event)
            if progress:
                progress("skill", f"正在运行 Skill：{skill['name']}")
            run_id = self.hermes.submit(
                workspace_id, session_id, skill_id, input_paths, scheduled)
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
            records, raw_lines = self._read_results(workspace_id, final_answer)
            output_offset = int(state.get("outputLineOffset") or 0)
            if output_offset > len(records):
                raise RuntimeError("Skill 改写了 experiences.jsonl 历史行，已拒绝继续入库")
            if progress:
                progress("pushing", "Skill 已完成，正在写入经验引擎")
            pushed = []
            for index in range(output_offset, len(records)):
                self._check_cancel(cancel_event)
                record = records[index]
                doc_id = self._push_experience(record, upload_by)
                record["doc_id"] = doc_id
                raw_lines[index] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                self.workspaces.write_text(
                    workspace_id, "output/experiences.jsonl", "\n".join(raw_lines) + "\n")
                pushed.append({"docId": doc_id, "title": str(record.get("title") or "")})
                if scheduled:
                    state["outputLineOffset"] = index + 1
                    self._save_workspace_state(workspace_id, state)
            if scheduled:
                state["nextChunkSeq"] = first_sequence + len(chunks)
                state["outputLineOffset"] = len(records)
                self._save_workspace_state(workspace_id, state)
            return {"docId": pushed[0]["docId"] if pushed else "",
                    "docIds": [item["docId"] for item in pushed],
                    "title": pushed[0]["title"] if pushed else "",
                    "experienceCount": len(pushed), "skillId": skill_id,
                    "remoteRunId": run_id, "workspaceId": workspace_id}
        finally:
            if cancel_event is not None and cancel_event.is_set() and run_id:
                self.hermes.stop(run_id)
            if not scheduled:
                self.workspaces.delete(workspace_id)

    @staticmethod
    def _workspace_id(task_id: str, group_id: str, skill_id: str,
                      upload_by: str, scheduled: bool) -> str:
        if not scheduled:
            return f"welink-manual-{task_id}"
        identity = "\0".join((upload_by, group_id, skill_id)).encode("utf-8")
        return "welink-schedule-" + hashlib.sha256(identity).hexdigest()[:24]

    def _load_workspace_state(self, workspace_id: str) -> dict:
        with self._state_lock:
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            value = data.get(workspace_id, {}) if isinstance(data, dict) else {}
            return {"nextChunkSeq": int(value.get("nextChunkSeq") or 1),
                    "outputLineOffset": int(value.get("outputLineOffset") or 0)}

    def _save_workspace_state(self, workspace_id: str, state: dict) -> None:
        with self._state_lock:
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            data[workspace_id] = {
                "nextChunkSeq": int(state["nextChunkSeq"]),
                "outputLineOffset": int(state["outputLineOffset"]),
            }
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._state_path)

    def _watch_cancel(self, run_id: str, cancel_event, run_finished) -> None:
        while not run_finished.wait(0.2):
            if cancel_event.is_set():
                self.hermes.stop(run_id)
                return

    @staticmethod
    def _check_cancel(cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ExtractionCancelled("任务已取消")

    def _message_rows(self, messages: list[dict], cancel_event=None) -> list[dict]:
        rows: list[dict] = []
        for item in sorted(messages, key=lambda value: (
                int(value.get("timestamp") or 0), str(value.get("id") or ""))):
            self._check_cancel(cancel_event)
            timestamp = int(item.get("timestamp") or 0)
            when = datetime.fromtimestamp(
                timestamp / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S") \
                if timestamp else ""
            content = str(item.get("rawContent") or item.get("content") or "")
            content = _UM_RE.sub(
                lambda match: self._replace_attachment(match, cancel_event), content)
            rows.append({
                "timestamp": timestamp,
                "content": (
                    f"### {item.get('sender') or ''}（{when}）\n\n"
                    f"消息 ID：{item.get('id') or ''}\n\n{content}\n"),
            })
        return rows

    def _to_markdown(self, messages: list[dict], cancel_event=None) -> str:
        return "\n".join(row["content"] for row in self._message_rows(messages, cancel_event))

    def _to_markdown_chunks(self, messages: list[dict], cancel_event=None) -> list[dict]:
        chunks: list[dict] = []
        current: list[dict] = []
        size = 0
        for row in self._message_rows(messages, cancel_event):
            row_size = len(row["content"])
            if current and size + 1 + row_size > _CHUNK_SIZE:
                chunks.append(self._finish_chunk(current))
                current, size = [], 0
            current.append(row)
            size += row_size + (1 if size else 0)
        if current:
            chunks.append(self._finish_chunk(current))
        return chunks

    @staticmethod
    def _finish_chunk(rows: list[dict]) -> dict:
        timestamps = [row["timestamp"] for row in rows if row["timestamp"]]
        return {"content": "\n".join(row["content"] for row in rows),
                "start": min(timestamps) if timestamps else 0,
                "end": max(timestamps) if timestamps else 0}

    @staticmethod
    def _chunk_path(sequence: int, chunk: dict) -> str:
        def stamp(timestamp: int) -> str:
            if not timestamp:
                return "unknown"
            return datetime.fromtimestamp(
                timestamp / 1000, timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S")
        return f"input/{sequence:06d}_{stamp(chunk['start'])}-{stamp(chunk['end'])}.md"

    def _replace_attachment(self, match: re.Match, cancel_event=None) -> str:
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
            file_id = uuid.uuid4().hex
            response = requests.post(
                f"{self.settings.image_file_server_url}/rag_pic/{file_id}",
                files={"file": (filename, content)}, timeout=60, verify=False)
            response.raise_for_status()
            public_url = (
                f"{self.settings.rag_pic_public_base}/rag_pic/"
                f"{file_id}/{quote(filename)}")
            ocr_text = ""
            if self.settings.ocr_url:
                response = requests.post(
                    self.settings.ocr_url, files={"file": (filename, content)},
                    timeout=300, verify=False)
                response.raise_for_status()
                data = response.json()
                ocr_text = str(data.get("result") or data.get("text") or "") \
                    if isinstance(data, dict) else str(data)
            alt_text = ocr_text.strip().replace("\r", " ").replace("\n", " ")
            alt_text = alt_text.replace("[", "\\[").replace("]", "\\]")
            return f"![{alt_text}]({public_url})"
        except Exception as exc:
            return f"[附件处理失败：{filename}，{type(exc).__name__}]"

    def _download(self, download_url: str, extraction_code: str) -> bytes:
        token_response = requests.post(
            "https://clouddrive.huawei.com/api/v2/token",
            json={"appId": "espace", "domain": "huawei",
                  "loginName": self.settings.clouddrive_account,
                  "password": self.settings.clouddrive_password},
            headers={"Content-Type": "application/json",
                     "x-device-sn": "coreinsight-local-toolkit", "x-device-type": "web",
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

    def _read_results(self, workspace_id: str, final_answer: str) -> tuple[list[dict], list[str]]:
        try:
            raw = self.workspaces.read_text(workspace_id, "output/experiences.jsonl")
        except Exception:
            raw = final_answer
        raw = raw.strip()
        if not raw:
            return [], []
        fenced = re.search(r"```(?:json|jsonl)?\s*([\s\S]*?)\s*```", raw)
        raw = fenced.group(1).strip() if fenced else raw
        values = self._decode_json_values(raw)
        records: list[dict] = []
        for value in values:
            if isinstance(value, list):
                records.extend(value)
            elif isinstance(value, dict) and isinstance(value.get("experiences"), list):
                records.extend(value["experiences"])
            else:
                records.append(value)
        normalized_lines = []
        for record_number, result in enumerate(records, 1):
            if not isinstance(result, dict):
                raise RuntimeError(f"Skill 输出第 {record_number} 条经验必须是 JSON 对象")
            doc_id = str(result.get("doc_id") or "").strip()
            required = ("title", "summary", "experience", "rag_search_text")
            if not doc_id and any(not isinstance(result.get(key), str) or
                                  not result.get(key).strip() for key in required):
                raise RuntimeError(
                    f"Skill 新建经验第 {record_number} 条必须包含四个非空字符串字段")
            allowed = required + ("scene_id", "scene", "product", "metadata")
            if doc_id and not any(key in result for key in allowed):
                raise RuntimeError(f"Skill 更新经验第 {record_number} 条没有可更新字段")
            normalized_lines.append(json.dumps(
                result, ensure_ascii=False, separators=(",", ":")))
        return records, normalized_lines

    @staticmethod
    def _decode_json_values(raw: str) -> list:
        decoder = json.JSONDecoder()
        values = []
        position = 0
        while position < len(raw):
            while position < len(raw) and raw[position].isspace():
                position += 1
            if position >= len(raw):
                break
            try:
                value, position = decoder.raw_decode(raw, position)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Skill 输出在第 {exc.lineno} 行第 {exc.colno} 列不是合法 JSON") from exc
            values.append(value)
        return values

    def _push_experience(self, result: dict, upload_by: str) -> str:
        doc_id = str(result.get("doc_id") or "").strip()
        create_url = self.settings.experience_engine_url.rstrip("/")
        if not create_url.endswith("/memory/experience/doc"):
            create_url += "/memory/experience/doc"
        payload = {"user_id": upload_by}
        for key in ("title", "summary", "experience", "rag_search_text",
                    "scene_id", "scene", "product", "metadata"):
            if key in result:
                payload[key] = result[key]
        if doc_id:
            response = requests.put(
                f"{create_url}/{quote(doc_id, safe='')}", json=payload,
                timeout=60, verify=False)
        else:
            payload.setdefault("scene_id", "251")
            payload.setdefault("scene", "WeLink问题定位经验")
            response = requests.post(
                create_url, json=payload, timeout=60, verify=False)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError("经验引擎返回的不是 JSON") from exc
        if body.get("code") not in (None, 200):
            raise RuntimeError(f"经验引擎写入失败：{body}")
        returned = body.get("data") or {}
        returned_id = returned.get("doc_id") or returned.get("id") or doc_id
        if not returned_id:
            raise RuntimeError("经验新建成功但接口未返回 doc_id")
        return str(returned_id)
