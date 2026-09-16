from __future__ import annotations

import json
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from .config import Settings
from .drafts import DraftClient
from .instruction_files import InstructionFiles
from .model_resources import ModelResourceRunner


_UM_RE = re.compile(r"/:um_begin\{([^}]+)\}/:um_end")
_CHUNK_SIZE = 40_000
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
logger = logging.getLogger(__name__)


class ExtractionCancelled(RuntimeError):
    pass


class LocalExperienceProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.instructions = InstructionFiles(settings.data_dir)
        self.resources = ModelResourceRunner(settings)
        self.drafts = DraftClient(settings)

    def validate(self, upload_by: str, resource: str = "prompt",
                 extract_mode: str = "direct") -> None:
        self.resources.validate(resource)
        missing = []
        if not upload_by.strip():
            missing.append("COREINSIGHT_UPLOAD_BY")
        if extract_mode == "direct" and not self.settings.experience_engine_url:
            missing.append("COREINSIGHT_EXPERIENCE_ENGINE_URL")
        if missing:
            raise ValueError("缺少经验提取配置：" + ", ".join(missing))
        if extract_mode == "draft":
            self.drafts.validate()

    def process(self, messages: list[dict], upload_by: str, task_id: str,
                progress=None, cancel_event=None,
                group_id: str = "", scheduled: bool = False,
                extract_mode: str = "direct", source_type: str = "welink",
                scene: str = "", scene_id: str = "",
                resource: str = "prompt") -> dict:
        self._check_cancel(cancel_event)
        self.validate(upload_by, resource, extract_mode)
        workspace_id = self._workspace_id(
            task_id, group_id, upload_by, scheduled, extract_mode, source_type)
        workspace = self._workspace_path(
            group_id, workspace_id, source_type)
        input_dir = workspace / "input"
        output_path = workspace / "output" / "experiences.jsonl"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        existing_text = output_path.read_text(encoding="utf-8") \
            if scheduled and output_path.exists() else ""
        historical, _ = self._read_results(existing_text) if existing_text.strip() else ([], [])
        first_sequence = self._next_chunk_sequence(input_dir) if scheduled else 1
        logger.info(
            "local extraction start task_id=%s workspace=%s scheduled=%s messages=%d resource=%s",
            task_id, workspace, scheduled, len(messages), resource)
        if progress:
            progress("workspace", "正在生成本地 Markdown 文件")
        chunks = self._to_markdown_chunks(messages, cancel_event)
        input_paths: list[Path] = []
        for offset, chunk in enumerate(chunks):
            relative = self._chunk_path(first_sequence + offset, chunk)
            destination = workspace / relative
            self._write_text(destination, chunk["content"])
            input_paths.append(destination)
        logger.info("local workspace prepared task_id=%s chunks=%d", task_id, len(chunks))
        self._check_cancel(cancel_event)
        if resource == "prompt":
            instruction = self.instructions.read_prompt()
            skill_hash = ""
        else:
            _, skill_hash = self.instructions.read_skill()
            instruction = ""
        prompt = self._build_prompt(
            instruction, source_type, resource, workspace, input_paths,
            existing_text, self.instructions.skill_path, skill_hash)
        try:
            final_answer = self.resources.generate(
                resource, prompt, workspace, cancel_event, progress)
        except RuntimeError as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise ExtractionCancelled("任务已取消") from exc
            raise
        self._check_cancel(cancel_event)
        response_path = workspace / "output" / f"model-response-{first_sequence:06d}.txt"
        self._write_text(response_path, final_answer)
        records, _ = self._read_results(final_answer)
        if progress:
            progress("pushing", "模型已完成，正在写入提取结果")
        pushed = []
        current_records = list(historical)
        for record in records:
            self._check_cancel(cancel_event)
            operation = record["operation"]
            if source_type == "email" or scene or scene_id:
                if scene_id:
                    record["scene_id"] = scene_id
                elif operation == "create" and source_type == "email":
                    record.setdefault("scene_id", "251")
                if scene:
                    record["scene"] = scene
                elif operation == "create" and source_type == "email":
                    record.setdefault("scene", "问题定位数据飞轮")
            doc_id = self._push_experience(record, upload_by, extract_mode)
            record["doc_id"] = doc_id
            record["operation"] = "update"
            current_records.append(record)
            current_records = self._latest_experience_versions(current_records)
            self._write_records(output_path, current_records)
            pushed.append({"docId": doc_id, "title": str(record.get("title") or "")})
            logger.info(
                "experience pushed task_id=%s resource=%s doc_id=%s operation=%s",
                task_id, resource, doc_id, operation)
        if not output_path.exists():
            self._write_records(output_path, current_records)
        return {"docId": pushed[0]["docId"] if pushed else "",
                "docIds": [item["docId"] for item in pushed],
                "experiences": pushed,
                "title": pushed[0]["title"] if pushed else "",
                "experienceCount": len(pushed), "resource": resource,
                "workspaceId": workspace_id, "workspacePath": str(workspace),
                "modelResponsePath": str(response_path)}

    @staticmethod
    def _workspace_id(task_id: str, group_id: str, upload_by: str,
                      scheduled: bool,
                      extract_mode: str = "direct",
                      source_type: str = "welink") -> str:
        prefix = re.sub(r"[^0-9a-z-]+", "-", source_type.lower()).strip("-") or "source"
        if not scheduled:
            return f"{prefix}-manual-{task_id}"
        identity = "\0".join(
            (upload_by, group_id, extract_mode)).encode("utf-8")
        return f"{prefix}-schedule-" + hashlib.sha256(identity).hexdigest()[:24]

    def _workspace_path(self, group_id: str, workspace_id: str,
                        source_type: str) -> Path:
        safe_group_id = re.sub(
            r"[^0-9A-Za-z._-]+", "_", str(group_id or "")).strip("._")
        safe_group_id = safe_group_id[:120] or "manual"
        return self.settings.data_dir / "extraction" / source_type / safe_group_id / workspace_id

    @staticmethod
    def _next_chunk_sequence(input_dir: Path) -> int:
        values = []
        for path in input_dir.glob("*.md"):
            match = re.match(r"(\d{6})_", path.name)
            if match:
                values.append(int(match.group(1)))
        return max(values, default=0) + 1

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def _write_records(cls, path: Path, records: list[dict]) -> None:
        content = "\n".join(json.dumps(
            record, ensure_ascii=False, separators=(",", ":"))
            for record in records)
        cls._write_text(path, content + ("\n" if content else ""))

    @staticmethod
    def _build_prompt(base_prompt: str, source_type: str, resource: str,
                      workspace: Path, input_paths: list[Path],
                      existing_text: str, skill_path: Path | None = None,
                      skill_hash: str = "") -> str:
        source_label = "Outlook 邮件" if source_type == "email" else "WeLink 聊天记录"
        if resource == "skill":
            paths = "\n".join(
                f"- {path.relative_to(workspace).as_posix()}"
                for path in input_paths)
            history = "output/experiences.jsonl" if existing_text.strip() else "无"
            return (
                "你是受控的 CoreInsight 经验提取执行器。\n"
                f"唯一允许使用的主 Skill 文件：{skill_path}\n"
                f"该文件当前 SHA-256：{skill_hash}\n"
                "必须先核对文件 SHA-256，再用 Read 工具完整读取；哈希不一致立即失败。\n"
                "读取成功后严格按其中步骤执行。\n"
                "禁止使用斜杠命令重新分派 Skill，禁止改用其他同名 Skill。\n\n"
                f"本次来源：{source_label}\n"
                f"当前工作目录：{workspace}\n请读取这些新增输入文件：\n{paths}\n"
                f"已有经验文件：{history}\n只在最终回答中返回本轮新增或更新记录的严格 JSON。"
            )
        inputs = "\n\n".join(
            f"===== {path.name} =====\n{path.read_text(encoding='utf-8')}"
            for path in input_paths)
        history = existing_text.strip() or "无"
        return (
            f"{base_prompt}\n\n本次来源：{source_label}\n\n"
            f"已有经验：\n{history}\n\n新增输入：\n{inputs}\n\n"
            "只返回本轮新增或更新记录的严格 JSON。"
        )

    @staticmethod
    def _latest_experience_versions(records: list[dict]) -> list[dict]:
        latest: dict[str, tuple[int, dict]] = {}
        without_id: list[tuple[int, dict]] = []
        for index, record in enumerate(records):
            doc_id = str(record.get("doc_id") or "").strip()
            if doc_id:
                latest[doc_id] = (index, record)
            else:
                without_id.append((index, record))
        return [record for _, record in sorted(
            [*latest.values(), *without_id], key=lambda value: value[0])]

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
            if item.get("preformattedMarkdown"):
                rows.append({"timestamp": timestamp, "content": content.strip() + "\n"})
                continue
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
        is_image = Path(filename).suffix.lower() in _IMAGE_EXTENSIONS
        if not self.settings.clouddrive_account or not self.settings.clouddrive_password:
            return f"[附件未下载：缺少 CloudDrive 配置] {filename}"
        try:
            codes = parts[5].split(";")
            content = self._download(parts[0], codes[2] if len(codes) > 2 else "")
            file_id = uuid.uuid4().hex
            response = requests.post(
                self.settings.image_file_server_url,
                files={"file": (filename, content)}, timeout=60, verify=False)
            response.raise_for_status()
            try:
                body = response.json()
                public_url = str(body.get("url") or "") if isinstance(body, dict) else ""
            except ValueError:
                public_url = ""
            if not public_url:
                raise RuntimeError("image upload response did not contain url")
            ocr_text = ""
            if is_image and self.settings.ocr_url:
                try:
                    response = requests.post(
                        self.settings.ocr_url, files={"file": (filename, content)},
                        timeout=300, verify=False)
                    response.raise_for_status()
                    data = response.json()
                    ocr_text = str(data.get("result") or data.get("text") or "") \
                        if isinstance(data, dict) else str(data)
                except Exception:
                    # The image has already been uploaded. Do not replace its
                    # usable public URL just because OCR is temporarily down.
                    logger.warning("attachment OCR failed name=%s", filename,
                                   exc_info=True)
            alt_text = ocr_text.strip().replace("\r", " ").replace("\n", " ")
            alt_text = alt_text.replace("[", "\\[").replace("]", "\\]")
            if is_image:
                return f"![{alt_text or filename}]({public_url})"
            return f"[{filename}]({public_url})"
        except Exception as exc:
            logger.warning("attachment upload failed name=%s", filename,
                           exc_info=True)
            return f"![OCR结果](无法显示图片：{filename})"

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

    def _read_results(self, raw: str) -> tuple[list[dict], list[str]]:
        raw = raw.strip()
        if not raw:
            return [], []
        fenced = re.search(r"```(?:json|jsonl)?\s*([\s\S]*?)\s*```", raw)
        raw = fenced.group(1).strip() if fenced else raw
        try:
            values = self._decode_json_values(raw)
        except RuntimeError as original_error:
            values = self._decode_trailing_json_values(raw)
            if values is None:
                raise original_error
            logger.warning(
                "ignored explanatory text before trailing model JSON")
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
                raise RuntimeError(f"模型输出第 {record_number} 条经验必须是 JSON 对象")
            doc_id = str(result.get("doc_id") or "").strip()
            operation = str(result.get("operation") or "").strip().lower()
            if not operation and doc_id:
                operation = "update"
                result["operation"] = operation
            if operation not in ("create", "update"):
                raise RuntimeError(
                    f"模型输出第 {record_number} 条缺少合法 operation（create/update）")
            required = ("title", "summary", "experience", "rag_search_text")
            if operation == "create" and doc_id:
                raise RuntimeError(f"模型新建经验第 {record_number} 条不能携带 doc_id")
            if operation == "create" and any(not isinstance(result.get(key), str) or
                                  not result.get(key).strip() for key in required):
                raise RuntimeError(
                    f"模型新建经验第 {record_number} 条必须包含四个非空字符串字段")
            allowed = required + ("scene_id", "scene", "product", "metadata")
            if operation == "update" and not doc_id:
                raise RuntimeError(f"模型更新经验第 {record_number} 条必须携带 doc_id")
            if operation == "update" and not any(key in result for key in allowed):
                raise RuntimeError(f"模型更新经验第 {record_number} 条没有可更新字段")
            normalized_lines.append(json.dumps(
                result, ensure_ascii=False, separators=(",", ":")))
        return records, normalized_lines

    @staticmethod
    def _decode_trailing_json_values(raw: str) -> list | None:
        """Decode a JSON array/object placed after explanatory model text.

        Agent runtimes occasionally prepend reasoning even when instructed to
        return JSON only. Limit the fallback to a structured value that reaches
        the end of the response, so brackets in ordinary prose are not treated
        as extraction results.
        """
        stripped = raw.rstrip()
        if not stripped or stripped[-1] not in ("}", "]"):
            return None
        opening = "{" if stripped[-1] == "}" else "["
        for position in range(len(stripped) - 1, -1, -1):
            if stripped[position] != opening:
                continue
            try:
                return LocalExperienceProcessor._decode_json_values(
                    stripped[position:])
            except RuntimeError:
                continue
        return None

    @staticmethod
    def _decode_json_values(raw: str) -> list:
        original_error = None
        repairs = 0
        maximum_repairs = 100
        while True:
            try:
                values = LocalExperienceProcessor._decode_strict_json_values(raw)
                if repairs:
                    logger.warning(
                        "repaired malformed model JSON output repairs=%d", repairs)
                return values
            except json.JSONDecodeError as exc:
                original_error = original_error or exc
                if repairs >= maximum_repairs:
                    break
                repaired = LocalExperienceProcessor._repair_json_error(raw, exc)
                if repaired is None or repaired == raw:
                    break
                raw = repaired
                repairs += 1
        assert original_error is not None
        raise RuntimeError(
            f"模型输出在第 {original_error.lineno} 行第 "
            f"{original_error.colno} 列不是合法 JSON，自动修复失败") from original_error

    @staticmethod
    def _decode_strict_json_values(raw: str) -> list:
        decoder = json.JSONDecoder()
        values = []
        position = 0
        while position < len(raw):
            while position < len(raw) and raw[position].isspace():
                position += 1
            if position >= len(raw):
                break
            value, position = decoder.raw_decode(raw, position)
            values.append(value)
        return values

    @staticmethod
    def _repair_json_error(raw: str, error: json.JSONDecodeError) -> str | None:
        """Repair only deterministic, common model-generated JSON mistakes.

        The repaired text is always parsed again by the standard JSON decoder and
        then subjected to the normal experience schema validation. We deliberately
        avoid guessing missing values, keys, braces or business fields.
        """
        position = min(max(error.pos, 0), len(raw))
        message = error.msg

        if message.startswith("Invalid control character") and position < len(raw):
            escapes = {"\n": "\\n", "\r": "\\r", "\t": "\\t",
                       "\b": "\\b", "\f": "\\f"}
            if raw[position] in escapes:
                return raw[:position] + escapes[raw[position]] + raw[position + 1:]

        if message.startswith("Invalid \\escape") and position < len(raw):
            # Keep the literal backslash (common in Windows paths) by escaping it.
            if raw[position] == "\\":
                return raw[:position] + "\\\\" + raw[position + 1:]

        if message == "Expecting ',' delimiter":
            current = raw[position] if position < len(raw) else ""
            previous = LocalExperienceProcessor._previous_non_whitespace(raw, position)
            if current == '"' and previous is not None:
                # `"value" "nextKey"` -> `"value", "nextKey"`.
                return raw[:position] + "," + raw[position:]
            quote = LocalExperienceProcessor._previous_unescaped_quote(raw, position)
            if quote is not None and current not in ("", ",", "}", "]"):
                # `"text with "quoted" words"`: the decoder stopped at the
                # first inner quote. Preserve it as content and retry.
                return raw[:quote] + "\\" + raw[quote:]

        if message == "Expecting property name enclosed in double quotes":
            previous = LocalExperienceProcessor._previous_non_whitespace(raw, position)
            current = raw[position] if position < len(raw) else ""
            if current in ("}", "]") and previous is not None and raw[previous] == ",":
                # Remove a trailing comma before an object/array terminator.
                return raw[:previous] + raw[previous + 1:]
            # An inner quote followed by punctuation can look like a legitimate
            # string terminator until the decoder reaches the following word.
            if previous is not None:
                comma = raw.rfind(",", 0, position)
                if comma >= 0:
                    quote = LocalExperienceProcessor._previous_unescaped_quote(raw, comma)
                    if quote is not None and raw[quote + 1:comma].strip() == "":
                        return raw[:quote] + "\\" + raw[quote:]
        return None

    @staticmethod
    def _previous_non_whitespace(raw: str, position: int) -> int | None:
        index = min(position, len(raw)) - 1
        while index >= 0 and raw[index].isspace():
            index -= 1
        return index if index >= 0 else None

    @staticmethod
    def _previous_unescaped_quote(raw: str, position: int) -> int | None:
        index = min(position, len(raw)) - 1
        while index >= 0:
            if raw[index] == '"':
                backslashes = 0
                cursor = index - 1
                while cursor >= 0 and raw[cursor] == "\\":
                    backslashes += 1
                    cursor -= 1
                if backslashes % 2 == 0:
                    return index
            index -= 1
        return None

    def _push_experience(self, result: dict, upload_by: str,
                         extract_mode: str = "direct") -> str:
        if extract_mode == "draft":
            return self.drafts.save(result, upload_by)
        operation = str(result.get("operation") or "").strip().lower()
        doc_id = str(result.get("doc_id") or "").strip()
        if not operation and doc_id:
            operation = "update"
        create_url = self.settings.experience_engine_url.rstrip("/")
        if not create_url.endswith("/memory/experience/doc"):
            create_url += "/memory/experience/doc"
        payload = {"user_id": upload_by}
        for key in ("title", "summary", "experience", "rag_search_text",
                    "scene_id", "scene", "product", "metadata"):
            if key in result:
                payload[key] = result[key]
        if operation == "update":
            response = requests.put(
                f"{create_url}/{quote(doc_id, safe='')}", json=payload,
                timeout=60, verify=False)
        else:
            payload.setdefault("scene_id", "251")
            payload.setdefault("scene", "问题定位数据飞轮")
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
