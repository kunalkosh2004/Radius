import asyncio
import json

from anyio import create_memory_object_stream


class WebSocketDisconnect(Exception):
    """Raised when the server closes the connection."""

    def __init__(self, code: int | None = None, reason: str = "") -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"connection closed: {code} {reason}".strip())


class ASGIWebSocketClient:
    """Minimal in-process ASGI WebSocket client.

    Drives the ASGI app directly on the current event loop (the same trick
    httpx's ASGITransport uses for HTTP requests), without anyio task
    groups, so it composes predictably with pytest-asyncio. Kept deliberately
    tiny: it speaks just enough of the ASGI websocket protocol for tests.
    """

    def __init__(self, app, path: str, query_string: str = "") -> None:
        self._app = app
        self._scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": query_string.encode(),
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
        }
        to_app, from_client = create_memory_object_stream(max_buffer_size=16)
        to_client, self._from_app = create_memory_object_stream(max_buffer_size=16)
        self._to_app = to_app
        self._receive = from_client.receive
        self._send = to_client.send
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "ASGIWebSocketClient":
        self._task = asyncio.create_task(
            self._app(self._scope, self._receive, self._send)
        )
        # In ASGI the "server" must hand the app the connect message before
        # the app can accept (starlette's WebSocket.accept() waits for it).
        await self._to_app.send({"type": "websocket.connect"})
        first = await asyncio.wait_for(self._from_app.receive(), timeout=5)
        if first["type"] == "websocket.close":
            await self._wait_for_task()
            raise WebSocketDisconnect(
                first.get("code"), first.get("reason", "")
            )
        assert first["type"] == "websocket.accept", first
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._task is not None and not self._task.done():
            try:
                await self._to_app.send(
                    {"type": "websocket.disconnect", "code": 1000}
                )
            except Exception:
                pass
        await self._wait_for_task()

    async def send_json(self, data: dict) -> None:
        await self._to_app.send(
            {"type": "websocket.receive", "text": json.dumps(data)}
        )

    async def receive_json(self, timeout: float = 5.0):
        message = await asyncio.wait_for(
            self._from_app.receive(), timeout=timeout
        )
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(
                message.get("code"), message.get("reason", "")
            )
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def _wait_for_task(self) -> None:
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
