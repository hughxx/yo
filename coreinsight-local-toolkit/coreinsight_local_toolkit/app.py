from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, load_settings
from .extraction import ExtractionRuntime
from .email_runtime import EmailRuntime, EmailScheduleRuntime
from .email_store import EmailConfigStore
from .outlook import OutlookClient
from .processor import LocalExperienceProcessor
from .models import (
    EmailConfig, EmailDetailRequest, EmailExtractRequest, EmailListRequest,
    EmailScanRequest,
    EmailScheduleSetRequest,
    GroupConfig, GroupCreate, GroupDelete, MessagePage, MessagePageQuery,
    ExtractCancelRequest, ExtractRequest, MessageQuery, PreviewMessage,
    ScheduleCancelRequest,
    ScheduleSetRequest, WelinkCliStatus,
)
from .notifications import MessageNotifier
from .scheduler import ScheduleRuntime
from .skills import available_skills
from .store import GroupStore
from .updates import UpdateManager
from .welink import WelinkHistory
from .time_format import epoch_milliseconds


logger = logging.getLogger(__name__)


def _to_timestamp(value: str | None, field_name: str) -> int:
    if not value:
        return 0
    try:
        return epoch_milliseconds(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} 不是有效的 ISO 8601 时间") from exc


def _uses_api_envelope(path: str) -> bool:
    return path in {'/health', '/capabilities', '/version'} or path.startswith(
        ('/welink/', '/email/', '/update/'))


def _envelope(status_code: int, payload) -> tuple[int, dict]:
    if status_code >= 400:
        message = payload.get('detail') if isinstance(payload, dict) else None
        if isinstance(message, list):
            message = '; '.join(
                str(item.get('msg', item)) if isinstance(item, dict) else str(item)
                for item in message)
        return status_code, {
            'code': status_code,
            'msg': str(message or '请求失败'),
            'data': None,
        }
    return 200, {'code': 200, 'msg': 'ok', 'data': payload}


def create_app(settings: Settings | None = None,
               update_manager: UpdateManager | None = None) -> FastAPI:
    settings = settings or load_settings()
    update_manager = update_manager or UpdateManager(settings)
    store = GroupStore(settings.data_dir)
    history = WelinkHistory(settings.welink_cli)
    processor = LocalExperienceProcessor(settings)
    notifier = MessageNotifier(settings)
    extraction = ExtractionRuntime(
        history, store, processor, settings.upload_by, notifier)
    scheduler = ScheduleRuntime(store, extraction)
    email_store = EmailConfigStore(settings.data_dir)
    outlook = OutlookClient(settings)
    email = EmailRuntime(
        outlook, email_store, processor, notifier, settings.upload_by)
    email_scheduler = EmailScheduleRuntime(email_store, email)
    browser_origins = {
        *settings.allowed_origins,
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    }
    app = FastAPI(title="CoreInsight Local Toolkit", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(browser_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CoreInsight-Protocol"],
        max_age=600,
    )

    @app.middleware("http")
    async def local_browser_guard(request: Request, call_next):
        origin = request.headers.get("origin", "").rstrip("/")
        if origin and origin not in browser_origins:
            return JSONResponse(status_code=403, content={"detail": "Origin 不在本地服务白名单中"})
        if (request.method != "OPTIONS" and update_manager.forced
                and (request.url.path == "/capabilities"
                     or request.url.path.startswith(("/welink/", "/email/")))):
            return JSONResponse(status_code=426, content={
                "detail": "当前版本已停止服务，必须升级后继续使用",
                "update": update_manager.snapshot(),
            })
        response = await call_next(request)
        if request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/demo"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware('http')
    async def api_response_envelope(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            if not _uses_api_envelope(request.url.path):
                raise
            logger.exception('unhandled api error path=%s', request.url.path)
            return JSONResponse(
                content={'code': 500, 'msg': '本地服务内部错误', 'data': None},
                status_code=500)
        if not _uses_api_envelope(request.url.path):
            return response
        raw = b''.join([chunk async for chunk in response.body_iterator])
        if raw:
            try:
                payload = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = raw.decode('utf-8', errors='replace')
        else:
            payload = None
        http_status, content = _envelope(response.status_code, payload)
        headers = {
            key: value for key, value in response.headers.items()
            if key.lower() not in {'content-length', 'content-type'}
        }
        return JSONResponse(content=content, status_code=http_status, headers=headers)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "coreinsight-local-toolkit", "version": __version__}

    @app.get("/capabilities")
    def capabilities():
        return {
            "welinkGroupManagement": True,
            "welinkMessagePreview": True,
            "welinkExtraction": True,
            "welinkScheduling": True,
            "welinkSkillExtraction": True,
            "welinkCliProbe": True,
            "outlookProbe": True,
            "emailFolderManagement": True,
            "emailPreview": True,
            "emailRuleFiltering": True,
            "emailSkillExtraction": True,
            "emailScheduling": True,
        }

    @app.get("/welink/cli/status", response_model=WelinkCliStatus)
    def welink_cli_status():
        return history.probe()

    @app.get("/version")
    def version():
        return {"version": __version__,
                "updateConfigured": bool(settings.update_enabled and settings.update_config_url
                                         and settings.update_config_key),
                "updateConfigKey": settings.update_config_key}

    @app.post("/update/check")
    def update_check():
        try:
            return update_manager.check().to_dict()
        except (ValueError, requests.RequestException) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/update/status")
    def update_status():
        return update_manager.snapshot()

    @app.post("/update/install", status_code=202)
    def update_install():
        try:
            return update_manager.request_install()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"版本检查失败：{exc}") from exc

    @app.get("/welink/skill/list")
    def list_skills():
        return [skill for skill in available_skills()
                if skill["id"].startswith("welink-")]

    @app.get("/email/skill/list")
    def list_email_skills():
        return [skill for skill in available_skills()
                if skill["id"].startswith("email-")]

    @app.get("/email/status")
    def email_status():
        return outlook.probe()

    @app.get("/email/folder/list")
    def email_folders():
        try:
            return outlook.list_folders()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"读取 Outlook 文件夹失败：{exc}") from exc

    @app.get("/email/config", response_model=EmailConfig)
    def get_email_config():
        return email_store.get()

    @app.put("/email/config", response_model=EmailConfig)
    def update_email_config(payload: EmailConfig):
        current = email_store.get()
        current.folders = payload.folders
        current.rules = payload.rules
        current.blacklist = payload.blacklist
        current.skillId = payload.skillId
        current.extractMode = payload.extractMode
        current.uploadBy = payload.uploadBy.strip()
        if current.scheduleEnabled and not any(
                rule.enabled and (rule.subjectKeywords or rule.bodyKeywords
                                  or rule.senders)
                for rule in current.rules):
            current.scheduleEnabled = False
            current.scheduleNextRun = ""
        return email_store.save(current)

    @app.post("/email/message/list")
    def list_email_messages(payload: EmailListRequest):
        # An empty selection is an explicit "scan nothing" state.  The UI
        # selects the account-specific default Inbox by its returned path.
        if not payload.folders:
            return {"items": [], "total": 0, "totalExact": True,
                    "offset": payload.offset, "limit": payload.limit,
                    "hasMore": False, "scanned": 0, "source": "empty-selection"}
        start_ms = _to_timestamp(payload.startTime, "startTime")
        end_ms = _to_timestamp(payload.endTime, "endTime")
        if start_ms and end_ms and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="startTime 不能晚于 endTime")
        try:
            return email.list_message_page(
                payload.folders, start_ms, end_ms,
                payload.query, payload.matchedOnly,
                payload.offset, payload.limit)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"读取 Outlook 邮件失败：{exc}") from exc

    @app.post("/email/message/scan")
    def start_email_scan(payload: EmailScanRequest):
        try:
            return email.start_scan(payload.folders, payload.forceFull)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/email/message/scan/status")
    def email_scan_status():
        return email.scan_status(include_items=True)

    @app.post("/email/message/get")
    def get_email_message(payload: EmailDetailRequest):
        try:
            return outlook.get_message(payload.itemId, process_attachments=False)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"读取邮件正文失败：{exc}") from exc

    @app.post("/email/extract", status_code=202)
    def start_email_extract(payload: EmailExtractRequest):
        start_ms = _to_timestamp(payload.startTime, "startTime")
        end_ms = _to_timestamp(payload.endTime, "endTime")
        if start_ms and end_ms and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="startTime 不能晚于 endTime")
        try:
            return email.start(payload, start_ms, end_ms)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/email/extract/status")
    def email_extract_status():
        return email.status()

    @app.get("/email/extract/item-status")
    def email_extract_item_status():
        task = email.status()
        return {
            "taskId": task.get("taskId", ""),
            "running": bool(task.get("running")),
            "scheduled": bool(task.get("scheduled")),
            "items": list((task.get("itemStatuses") or {}).values()),
        }

    @app.get("/email/extract/tasks")
    def email_extract_tasks():
        return email.tasks()

    @app.post("/email/extract/cancel")
    def cancel_email_extract():
        task = email.status()
        if not task.get("running"):
            raise HTTPException(status_code=404, detail="没有正在运行的邮件提取任务")
        return email.cancel()

    @app.post("/email/schedule/set")
    def set_email_schedule(payload: EmailScheduleSetRequest):
        if email.status().get("running"):
            raise HTTPException(status_code=409, detail="邮件提取正在执行，请完成或取消后再设置定时")
        try:
            return email_scheduler.set(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/email/schedule/cancel")
    def cancel_email_schedule():
        return email_scheduler.cancel()

    @app.get("/welink/group/list", response_model=list[GroupConfig])
    def list_groups():
        return store.list()

    @app.post("/welink/group/add", response_model=GroupConfig, status_code=201)
    def add_group(payload: GroupCreate):
        try:
            return store.add(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/welink/group/update", response_model=GroupConfig)
    def update_group(payload: GroupConfig):
        try:
            current = store.get(payload.groupId)
            if not current:
                raise KeyError(payload.groupId)
            for field in ("name", "extractMode", "skillId", "startTime", "endTime",
                          "quickRange", "scheduleFreq", "scheduleTime",
                          "scheduleCron"):
                setattr(current, field, getattr(payload, field))
            return store.update(current)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="群组不存在") from exc

    @app.delete("/welink/group/delete", status_code=204)
    def delete_group(payload: GroupDelete):
        task = extraction.status(group_id=payload.groupId)
        if task and task.get('running'):
            raise HTTPException(status_code=409, detail="该群组正在提取，请先取消当前任务")
        try:
            group = store.get(payload.groupId)
            if group and group.scheduleEnabled:
                scheduler.cancel(payload.groupId)
            store.delete(payload.groupId)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="群组不存在") from exc

    @app.post("/welink/message/list", response_model=list[PreviewMessage])
    def list_messages(payload: MessageQuery):
        group_id = payload.groupId.strip()
        if not store.get(group_id):
            raise HTTPException(status_code=404, detail="请先绑定该群组")
        start_ms = _to_timestamp(payload.startTime, "startTime")
        end_ms = _to_timestamp(payload.endTime, "endTime")
        if start_ms and end_ms and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="startTime 不能晚于 endTime")
        try:
            return history.fetch(group_id, start_ms, end_ms)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/welink/message/page", response_model=MessagePage)
    def page_messages(payload: MessagePageQuery):
        group_id = payload.groupId.strip()
        if not store.get(group_id):
            raise HTTPException(status_code=404, detail="请先绑定该群组")
        start_ms = _to_timestamp(payload.startTime, "startTime")
        end_ms = _to_timestamp(payload.endTime, "endTime")
        if start_ms and end_ms and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="startTime 不能晚于 endTime")
        try:
            return history.fetch_page(
                group_id, start_ms, end_ms, payload.cursor, payload.limit
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/welink/extract", status_code=202)
    def start_extract(payload: ExtractRequest):
        start_ms = _to_timestamp(payload.startTime, "startTime")
        end_ms = _to_timestamp(payload.endTime, "endTime")
        if start_ms and end_ms and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="startTime 不能晚于 endTime")
        try:
            group = store.get(payload.groupId)
            if group and group.scheduleEnabled:
                raise RuntimeError("该群组已设定定时提取，请先取消定时任务")
            return extraction.start(payload, start_ms, end_ms)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get('/welink/extract/status')
    def extract_status(taskId: str = '', groupId: str = ''):
        task = extraction.status(task_id=taskId.strip(), group_id=groupId.strip())
        if task is None:
            raise HTTPException(status_code=404, detail='提取任务不存在')
        return task

    @app.get('/welink/extract/tasks')
    def extract_tasks():
        return extraction.tasks()

    @app.post('/welink/extract/cancel')
    def cancel_extract(payload: Optional[ExtractCancelRequest] = None):
        payload = payload or ExtractCancelRequest()
        task = extraction.cancel(task_id=payload.taskId.strip(),
                                 group_id=payload.groupId.strip())
        if task is None:
            raise HTTPException(status_code=404, detail='没有找到可取消的提取任务')
        return task

    @app.post("/welink/schedule/set")
    def set_schedule(payload: ScheduleSetRequest):
        task = extraction.status(group_id=payload.groupId)
        if task and task.get('running'):
            raise HTTPException(status_code=409, detail="该群组正在提取，请先取消当前任务")
        try:
            return scheduler.set(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/welink/schedule/cancel")
    def cancel_schedule(payload: ScheduleCancelRequest):
        try:
            return scheduler.cancel(payload.groupId)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.on_event("shutdown")
    def shutdown_scheduler():
        scheduler.close()
        extraction.close()
        email_scheduler.close()
        email.close()

    @app.get("/", include_in_schema=False)
    def demo_redirect():
        return RedirectResponse("/demo/")

    web_dir = Path(__file__).with_name("web")
    @app.get("/welcome/icon.svg", include_in_schema=False)
    def welcome_icon():
        return FileResponse(
            Path(__file__).with_name("assets") / "icon.svg",
            media_type="image/svg+xml")

    app.mount(
        "/welcome", StaticFiles(directory=web_dir / "welcome", html=True),
        name="welcome")
    app.mount("/demo", StaticFiles(directory=web_dir, html=True), name="demo")

    return app
