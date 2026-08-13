from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, load_settings
from .extraction import ExtractionRuntime
from .processor import LocalExperienceProcessor
from .models import (
    GroupConfig, GroupCreate, GroupDelete, MessagePage, MessagePageQuery,
    ExtractRequest, MessageQuery, PreviewMessage, ScheduleCancelRequest,
    ScheduleSetRequest,
)
from .scheduler import ScheduleRuntime
from .store import GroupStore
from .welink import WelinkHistory


def _to_timestamp(value: str | None, field_name: str) -> int:
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} 不是有效的 ISO 8601 时间") from exc
    return int(parsed.timestamp() * 1000)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = GroupStore(settings.data_dir)
    history = WelinkHistory(settings.welink_cli)
    extraction = ExtractionRuntime(history, store, LocalExperienceProcessor(settings), settings.upload_by)
    scheduler = ScheduleRuntime(store, extraction)
    browser_origins = {
        *settings.allowed_origins,
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    }
    app = FastAPI(title="CoreInsight Local Agent", version=__version__)
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
        response = await call_next(request)
        if request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/demo"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "coreinsight-local-agent", "version": __version__}

    @app.get("/capabilities")
    def capabilities():
        return {
            "welinkGroupManagement": True,
            "welinkMessagePreview": True,
            "welinkExtraction": True,
            "welinkScheduling": True,
        }

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
            for field in ("name", "extractMode", "extractMethod", "startTime", "endTime",
                          "quickRange", "promptContent", "scheduleFreq", "scheduleTime",
                          "scheduleCron"):
                setattr(current, field, getattr(payload, field))
            return store.update(current)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="群组不存在") from exc

    @app.delete("/welink/group/delete", status_code=204)
    def delete_group(payload: GroupDelete):
        task = extraction.status()
        if task.get("running") and task.get("groupId") == payload.groupId:
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

    @app.get("/welink/extract/status")
    def extract_status():
        return extraction.status()

    @app.post("/welink/extract/cancel")
    def cancel_extract():
        return extraction.cancel()

    @app.post("/welink/schedule/set")
    def set_schedule(payload: ScheduleSetRequest):
        task = extraction.status()
        if task.get("running") and task.get("groupId") == payload.groupId:
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

    @app.get("/", include_in_schema=False)
    def demo_redirect():
        return RedirectResponse("/demo/")

    web_dir = Path(__file__).with_name("web")
    app.mount("/demo", StaticFiles(directory=web_dir, html=True), name="demo")

    return app


app = create_app()
