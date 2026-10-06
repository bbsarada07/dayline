"""FastAPI app: routers under /api, realtime on /ws, optional built frontend."""

import asyncio
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.auth import COOKIE_NAME, principal_from_token
from app.config import APP_NAME, settings
from app.db import create_tables, engine
from app.errors import ApiError, install_error_handlers
from app.demo import ensure_demo_clock
from app.events import hub
from app.models import Student
from app.routers import admin, agent, agent_tools, attendance, auth, canteen, collect, memory, system, timetable, today
from app.routers import print as print_router
from app.services import maintenance, memory_service


def lan_addresses() -> list[str]:
    """Best-effort list of this machine's LAN IPv4 addresses."""
    found: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # no packet is sent
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_tables()
    # A fresh deployment (or a host that wiped the disk) starts with an empty database.
    with Session(engine) as session:
        empty = session.exec(select(Student.id)).first() is None
    if empty:
        from app.seed import seed

        seed()
    ensure_demo_clock()
    # Connect to Qdrant (and create the collection) now, in the background, so the
    # first memory action of the day isn't the slow one.
    asyncio.get_running_loop().run_in_executor(None, memory_service.status)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    hub.bind_loop(asyncio.get_running_loop())
    print(f"[{APP_NAME}] API ready on port {settings.port}")
    for address in lan_addresses():
        print(f"[{APP_NAME}] On the same Wi-Fi/hotspot, open http://{address}:{settings.port}")
    housekeeping = asyncio.create_task(maintenance.loop())
    yield
    housekeeping.cancel()


app = FastAPI(title=APP_NAME, lifespan=lifespan)
install_error_handlers(app)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

for module in (auth, timetable, attendance, today, admin, print_router, canteen, collect, system, memory, agent,
               agent_tools):
    app.include_router(module.router, prefix="/api")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(path: str) -> None:
    """Unknown API paths return the JSON error shape instead of the frontend."""
    raise ApiError(404, "not_found", "That API endpoint doesn't exist.")


@app.websocket("/ws")
async def websocket(socket_: WebSocket) -> None:
    """Realtime events. The session cookie decides which events this client receives."""
    with Session(engine) as session:
        principal = principal_from_token(socket_.cookies.get(COOKIE_NAME), session)
    role = principal.role if principal else None
    student_id = principal.id if principal and principal.kind == "student" else None
    client = await hub.connect(socket_, role, student_id)
    try:
        while True:
            # The client pings every few seconds and treats a missing pong as a dead connection.
            if await socket_.receive_text() == "ping":
                await socket_.send_text('{"type":"pong","payload":{}}')
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(client)


if settings.serve_frontend and settings.frontend_dist.is_dir():
    dist = settings.frontend_dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        """Serve the built frontend; unknown paths get index.html (client routing)."""
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")
