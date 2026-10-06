"""WebSocket broadcast of { "type": ..., "payload": ... } events.

Each event can be limited to one student and/or a set of staff roles; the
server only sends an event to connections that are allowed to see it.
"""

import asyncio
import json
from dataclasses import dataclass

from fastapi import WebSocket

SEND_TIMEOUT_SECONDS = 3


@dataclass(eq=False)
class _Client:
    socket: WebSocket
    role: str | None  # student | canteen | print | admin | None (public board)
    student_id: int | None


class EventHub:
    def __init__(self) -> None:
        self._clients: set[_Client] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, socket: WebSocket, role: str | None, student_id: int | None) -> _Client:
        await socket.accept()
        client = _Client(socket, role, student_id)
        self._clients.add(client)
        return client

    def disconnect(self, client: _Client) -> None:
        self._clients.discard(client)

    @staticmethod
    def _allowed(client: _Client, student_id: int | None, roles: tuple[str, ...] | None) -> bool:
        if student_id is None and roles is None:
            return True
        if student_id is not None and client.role == "student" and client.student_id == student_id:
            return True
        return roles is not None and client.role in roles

    async def _send_one(self, client: _Client, message: str) -> None:
        try:
            await asyncio.wait_for(client.socket.send_text(message), timeout=SEND_TIMEOUT_SECONDS)
        except Exception:
            # Dead or stalled socket (e.g. a phone that went to sleep): drop it.
            # The client reconnects and refetches when it wakes up.
            self.disconnect(client)
            try:
                await client.socket.close()
            except Exception:
                pass

    async def _send(self, message: str, student_id: int | None, roles: tuple[str, ...] | None) -> None:
        # Send to everyone at once so one slow connection can't delay the others.
        targets = [c for c in list(self._clients) if self._allowed(c, student_id, roles)]
        await asyncio.gather(*(self._send_one(c, message) for c in targets))

    def publish(
        self,
        type_: str,
        payload: dict | None = None,
        *,
        student_id: int | None = None,
        roles: tuple[str, ...] | None = None,
    ) -> None:
        """Send an event from sync or async code. No-op if the server loop isn't running."""
        message = json.dumps({"type": type_, "payload": payload or {}}, default=str)
        if self._loop is None or self._loop.is_closed():
            return
        coro = self._send(message, student_id, roles)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, self._loop)


hub = EventHub()
