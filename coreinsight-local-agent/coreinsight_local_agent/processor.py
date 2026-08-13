from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

import requests

from .config import Settings


SYSTEM_PROMPT = """你是专业的技术知识整理专家。请将 WeLink 聊天记录整理为一条结构化经验文档。
严格输出 JSON，字段为 title、summary、experience、rag_search_text，不要输出额外说明。
experience 使用 Markdown，可包含：问题背景、问题现象、分析过程、根因、解决方案、讨论摘要。
保留代码、接口、错误日志等技术细节，剔除无关闲聊。讨论摘要使用真实发送人和时间。"""
MERGE_PROMPT = """你是专业的技术知识整理专家。下面是同一批聊天记录分段提取出的 JSON 经验草稿。
请去重并合并为一条完整经验，严格输出 JSON，字段为 title、summary、experience、rag_search_text。
不得遗漏关键代码、错误日志、根因、解决方案和图片 Markdown 链接。"""
_UM_RE = re.compile(r"/:um_begin\{([^}]+)\}/:um_end")


class ExtractionCancelled(RuntimeError):
    pass


class LocalExperienceProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, upload_by: str) -> None:
        missing = []
        for name, value in (
            ("COREINSIGHT_LLM_BASE_URL", self.settings.llm_base_url),
            ("COREINSIGHT_LLM_API_KEY", self.settings.llm_api_key),
            ("COREINSIGHT_LLM_MODEL_ID", self.settings.llm_model_id),
            ("COREINSIGHT_EXPERIENCE_ENGINE_URL", self.settings.experience_engine_url),
        ):
            if not value: missing.append(name)
        if not upload_by.strip(): missing.append("COREINSIGHT_UPLOAD_BY")
        if missing:
            raise ValueError("缺少本地提取配置：" + ", ".join(missing))

    def process(self, messages: list[dict], prompt_content: str, upload_by: str,
                task_id: str, progress=None, cancel_event=None) -> dict:
        self._check_cancel(cancel_event)
        self.validate(upload_by)
        if progress: progress("markdown", "正在生成 Markdown 并处理附件")
        markdown = self._to_markdown(messages, cancel_event)
        chunks = self._split_markdown(markdown)
        results = []
        for index, chunk in enumerate(chunks, 1):
            self._check_cancel(cancel_event)
            if progress:
                progress("llm", f"正在调用大模型提取经验（{index}/{len(chunks)}）")
            results.append(self._call_llm(chunk, prompt_content))
        self._check_cancel(cancel_event)
        result = results[0] if len(results) == 1 else self._merge_results(
            results, prompt_content, cancel_event, progress)
        self._check_cancel(cancel_event)
        if progress: progress("pushing", "正在推送经验引擎")
        doc_id = uuid.uuid5(uuid.NAMESPACE_DNS, task_id).hex
        self._push_experience(result, upload_by, doc_id)
        return {"docId": doc_id, "title": result.get("title", "")}

    @staticmethod
    def _check_cancel(cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ExtractionCancelled("任务已取消")

    def _to_markdown(self, messages: list[dict], cancel_event=None) -> str:
        rows = []
        for item in sorted(messages, key=lambda x: (int(x.get("timestamp") or 0), str(x.get("id") or ""))):
            self._check_cancel(cancel_event)
            timestamp = int(item.get("timestamp") or 0)
            when = datetime.fromtimestamp(timestamp / 1000, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
            content = str(item.get("rawContent") or item.get("content") or "")
            content = _UM_RE.sub(self._replace_attachment, content)
            rows.append(f"### {item.get('sender') or ''}（{when}）\n\n{content}\n")
        return "\n".join(rows)

    def _split_markdown(self, markdown: str) -> list[str]:
        limit = self.settings.llm_chunk_chars
        if len(markdown) <= limit:
            return [markdown]
        chunks, current, size = [], [], 0
        for block in re.split(r"(?=^### )", markdown, flags=re.MULTILINE):
            if not block:
                continue
            if current and size + len(block) > limit:
                chunks.append("".join(current)); current, size = [], 0
            if len(block) > limit:
                if current:
                    chunks.append("".join(current)); current, size = [], 0
                chunks.extend(block[pos:pos + limit] for pos in range(0, len(block), limit))
            else:
                current.append(block); size += len(block)
        if current:
            chunks.append("".join(current))
        return chunks

    def _merge_results(self, results: list[dict], prompt_content: str,
                       cancel_event=None, progress=None) -> dict:
        system = MERGE_PROMPT + (f"\n\n用户补充要求：\n{prompt_content.strip()}" if prompt_content.strip() else "")
        level = list(results)
        round_number = 0
        while len(level) > 1:
            round_number += 1
            merged = []
            total = (len(level) + 1) // 2
            for index in range(0, len(level), 2):
                self._check_cancel(cancel_event)
                pair = level[index:index + 2]
                if len(pair) == 1:
                    merged.append(pair[0]); continue
                if progress:
                    progress("llm", f"正在合并分段结果（第 {round_number} 轮 {index // 2 + 1}/{total}）")
                merged.append(self._request_llm(system, json.dumps(pair, ensure_ascii=False)))
            level = merged
        return level[0]

    def _replace_attachment(self, match: re.Match) -> str:
        parts = match.group(1).split("|")
        if len(parts) < 6:
            return "[无法解析的附件]"
        if not all((self.settings.clouddrive_account, self.settings.clouddrive_password,
                    self.settings.file_server_url, self.settings.rag_pic_public_base)):
            return f"[附件] {parts[3]}"
        try:
            content = self._download(parts[0], parts[5].split(";")[2] if len(parts[5].split(";")) > 2 else "")
            filename = parts[3] or "attachment.bin"
            file_id = uuid.uuid4().hex
            response = requests.post(f"{self.settings.file_server_url}/rag_pic/{file_id}",
                                     files={"file": (filename, content)}, timeout=60, verify=False)
            response.raise_for_status()
            url = f"{self.settings.rag_pic_public_base}/rag_pic/{file_id}/{filename}"
            ocr_text = ""
            if self.settings.ocr_url:
                ocr_response = requests.post(self.settings.ocr_url, files={"file": (filename, content)},
                                             timeout=300, verify=False)
                ocr_response.raise_for_status(); data = ocr_response.json()
                ocr_text = str(data.get("result") or data.get("text") or "") if isinstance(data, dict) else str(data)
            suffix = f"\n> **[图片文字]** {ocr_text}" if ocr_text.strip() else ""
            return f"![]({url}){suffix}"
        except Exception:
            return f"[附件处理失败] {parts[3]}"

    def _download(self, download_url: str, extraction_code: str) -> bytes:
        token_response = requests.post("https://clouddrive.huawei.com/api/v2/token", json={
            "appId": "espace", "domain": "huawei", "loginName": self.settings.clouddrive_account,
            "password": self.settings.clouddrive_password,
        }, headers={"Content-Type": "application/json", "x-device-sn": "coreinsight-local-agent",
                    "x-device-type": "web", "x-device-os": "win10", "x-device-name": "coreinsight",
                    "x-client-version": "10"}, timeout=60, verify=False)
        token_response.raise_for_status(); token = token_response.json().get("token", "")
        authorization = f"/:um_begin{{{download_url}|File|123|attachment|0|;;{extraction_code}|isOriginalImg:0}}/:um_end"
        response = requests.post("https://clouddrive.huawei.com/imchat/api/v3/links/imdownload",
                                 headers={"Authorization": token, "Content-Type": "application/json"},
                                 json={"imAuthorization": authorization}, timeout=300, verify=False)
        response.raise_for_status(); return response.content

    def _call_llm(self, markdown: str, prompt_content: str) -> dict:
        system = SYSTEM_PROMPT + (f"\n\n用户补充要求：\n{prompt_content.strip()}" if prompt_content.strip() else "")
        return self._request_llm(system, markdown)

    def _request_llm(self, system: str, content: str) -> dict:
        response = requests.post(f"{self.settings.llm_base_url}/chat/completions",
                                 headers={"Authorization": f"Bearer {self.settings.llm_api_key}", "Content-Type": "application/json"},
                                 json={"model": self.settings.llm_model_id, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}], "temperature": 0.3, "stream": False},
                                 timeout=999, verify=False)
        response.raise_for_status(); raw = response.json()["choices"][0]["message"]["content"].strip()
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw)
        return json.loads(fenced.group(1) if fenced else raw)

    def _push_experience(self, result: dict, upload_by: str, doc_id: str) -> None:
        response = requests.post(self.settings.experience_engine_url, json={
            "doc_id": doc_id, "scene_id": "251", "scene": "WeLink问题定位经验",
            "user_id": upload_by, "title": result.get("title", ""), "summary": result.get("summary", ""),
            "experience": result.get("experience", ""), "rag_search_text": result.get("rag_search_text", ""),
        }, timeout=60, verify=False)
        response.raise_for_status()
