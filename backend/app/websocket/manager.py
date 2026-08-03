from uuid import UUID

from fastapi import WebSocket


class ConnectionManager:
    """In-process registry of live WebSocket connections.

    Keyed by user_id, holding a set of sockets so one account can be
    connected from several devices at once. This registry is process-local:
    when we scale to multiple instances (Sprint 8) it moves to Redis and
    the fan-out becomes pub/sub.
    """

    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = {}

    @property
    def online_user_ids(self) -> set[UUID]:
        return set(self._connections)

    @property
    def connection_count(self) -> int:
        return sum(len(sockets) for sockets in self._connections.values())

    def add(self, user_id: UUID, websocket: WebSocket) -> bool:
        """Register a socket. Returns True if it is the user's first."""
        sockets = self._connections.setdefault(user_id, set())
        is_first = not sockets
        sockets.add(websocket)
        return is_first

    def remove(self, user_id: UUID, websocket: WebSocket) -> bool:
        """Unregister a socket. Returns True if it was the user's last."""
        sockets = self._connections.get(user_id)
        if sockets is None:
            return False
        sockets.discard(websocket)
        if not sockets:
            del self._connections[user_id]
            return True
        return False

    async def send_to_user(self, user_id: UUID, message: dict) -> None:
        for websocket in list(self._connections.get(user_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:
                self.remove(user_id, websocket)
