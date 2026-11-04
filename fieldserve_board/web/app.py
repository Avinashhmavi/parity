"""FastAPI backend: reads the board, accepts edits, runs syncs, streams events.

Binds to localhost by default and has **no authentication**: it is a local
operations console. Put it behind your own auth before exposing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from ..backends import make_backend
from ..client import ApiError
from ..config import REPO_ROOT, ConfigError, Settings
from ..engine import SyncEngine, build_engine
from ..locking import LockTimeout
from ..state import StateStore
from .service import BoardService, NotFound, ValidationError

log = logging.getLogger("fieldserve_board.web")


class EditBody(BaseModel):
    """Editable fields only; anything else is a 422, matching the API's own 400."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[str] = None
    engineer: Optional[str] = None
    manager: Optional[str] = None
    purchase_order: Optional[str] = None
    delivery_note: Optional[str] = None
    work_report: Optional[str] = None
    invoice: Optional[str] = None


class Hub:
    """Fan-out of server events to connected browsers."""

    def __init__(self) -> None:
        self.clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def drop(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.drop(ws)


def create_app(settings: Optional[Settings] = None, service: Optional[BoardService] = None) -> FastAPI:
    hub = Hub()
    sync_lock = asyncio.Lock()

    if service is None:
        settings = settings or Settings.from_env(require_key=False)
        store = StateStore(settings.state_path)
        engine: Optional[SyncEngine] = None
        if settings.api_key:
            engine = build_engine(settings)
            backend = engine.backend
        else:
            backend = make_backend(settings)
        service = BoardService(settings, backend, store, engine)
    settings = service.settings

    async def run_sync(mode: str, reason: str) -> Dict[str, Any]:
        await hub.broadcast({"type": "sync.started", "reason": reason})
        try:
            result = await asyncio.to_thread(service.run_sync, mode)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            await hub.broadcast({"type": "sync.failed", "error": message})
            raise
        payload = result.as_dict()
        await hub.broadcast({"type": "sync.finished", "result": payload})
        return payload

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = None
        if settings.sync_interval_seconds > 0 and service.engine is not None:

            async def loop() -> None:
                while True:
                    await asyncio.sleep(settings.sync_interval_seconds)
                    if sync_lock.locked():
                        continue
                    async with sync_lock:
                        try:
                            await run_sync("incremental", "schedule")
                        except Exception:
                            log.exception("scheduled sync failed")

            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()

    app = FastAPI(title="FieldServe Ticket Board", version="1.0.0", lifespan=lifespan)
    origins = [o for o in (os.environ.get("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])

    @app.exception_handler(NotFound)
    async def _not_found(_req, exc: NotFound):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValidationError)
    async def _invalid(_req, exc: ValidationError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        info = service.sync_info()
        return {
            "status": "ok",
            "backend": service.backend.describe(),
            "canSync": service.engine is not None,
            "syncing": sync_lock.locked(),
            "conflictPolicy": settings.conflict_policy,
            "autoSyncSeconds": settings.sync_interval_seconds,
            **info,
        }

    @app.get("/api/board")
    def board_view(
        q: str = "",
        stage: str = "",
        owner: str = "",
        status: str = "",
        job_type: str = Query("", alias="jobType"),
        flagged: bool = False,
        sort: str = "id",
        order: str = Query("asc", pattern="^(asc|desc)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(100, ge=1, le=200, alias="pageSize"),
    ) -> Dict[str, Any]:
        return service.board(
            q=q, stage=stage, owner=owner, status=status, job_type=job_type, flagged=flagged, sort=sort, order=order, page=page, page_size=page_size
        )

    @app.get("/api/facets")
    def facets() -> Dict[str, Any]:
        return service.facets()

    @app.get("/api/summary")
    def summary() -> Dict[str, Any]:
        return service.summary()

    @app.get("/api/tickets/{ticket_id}")
    def ticket(ticket_id: int) -> Dict[str, Any]:
        return service.ticket(ticket_id)

    @app.patch("/api/tickets/{ticket_id}")
    async def edit_ticket(ticket_id: int, body: EditBody, sync: bool = False) -> Dict[str, Any]:
        changes = body.model_dump(exclude_none=True)
        result = await asyncio.to_thread(service.edit, ticket_id, changes)
        await hub.broadcast({"type": "board.changed", "ticketId": ticket_id})
        if sync and service.engine is not None and not sync_lock.locked():
            async with sync_lock:
                with contextlib.suppress(Exception):
                    await run_sync("incremental", "edit")
            return await asyncio.to_thread(service.ticket, ticket_id)
        return result

    @app.get("/api/noise")
    def noise() -> List[Dict[str, str]]:
        return service.noise()

    @app.get("/api/conflicts")
    def conflicts() -> List[Dict[str, Any]]:
        return service.conflicts()

    @app.get("/api/activity")
    def activity() -> List[Dict[str, Any]]:
        return service.activity()

    @app.get("/api/sync")
    def sync_status() -> Dict[str, Any]:
        return {"syncing": sync_lock.locked(), **service.sync_info()}

    @app.post("/api/sync", status_code=202)
    async def start_sync(full: bool = True) -> Dict[str, Any]:
        if service.engine is None:
            raise HTTPException(409, "no FIELDOPS_API_KEY configured; this board is read-only")
        if sync_lock.locked():
            raise HTTPException(409, "a sync is already running")

        async def job() -> None:
            async with sync_lock:
                try:
                    await run_sync("full" if full else "incremental", "manual")
                except (ApiError, LockTimeout, ConfigError) as exc:
                    log.error("sync failed: %s", exc)
                except Exception:
                    log.exception("sync failed")

        # Reserve the lock before returning so a second click gets 409.
        asyncio.get_running_loop().create_task(job())
        await asyncio.sleep(0)
        return {"accepted": True}

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await hub.connect(socket)
        try:
            await socket.send_json({"type": "hello", "syncing": sync_lock.locked()})
            while True:
                await socket.receive_text()  # keep-alive; clients send nothing meaningful
        except WebSocketDisconnect:
            pass
        finally:
            hub.drop(socket)

    dist = Path(os.environ.get("CLIENT_DIST") or REPO_ROOT / "client" / "dist")
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (dist / path).resolve()
            if path and dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


def _default_app() -> FastAPI:
    return create_app()


# `uvicorn fieldserve_board.web.app:app` builds the app lazily so importing the
# module (tests, tooling) never requires a configured environment.
def __getattr__(name: str):
    if name == "app":
        return _default_app()
    raise AttributeError(name)
