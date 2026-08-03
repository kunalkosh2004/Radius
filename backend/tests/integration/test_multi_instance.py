import asyncio
from contextlib import suppress
from uuid import uuid4

from app.core.pubsub import EVENTS_CHANNEL, publish, subscribe
from app.core.redis import get_redis
from app.main import app
from app.services.connection_tracker import ConnectionTracker
from app.websocket.manager import ConnectionManager
from tests.websocket_client import ASGIWebSocketClient

redis = get_redis()


class StubSocket:
    """A socket that records what it was told to send."""

    def __init__(self) -> None:
        self.received: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.received.append(data)


async def wait_for(predicate, timeout: float = 3.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def create_user(client, nickname):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": nickname, "latitude": 0.0, "longitude": 0.0},
    )
    assert response.status_code == 201
    return response.json()


async def test_pubsub_delivers_remote_events_and_skips_own():
    manager_b = ConnectionManager()
    instance_b = "instance-b"
    ready = asyncio.Event()
    task = asyncio.create_task(
        subscribe(redis, manager_b, origin=instance_b, ready=ready)
    )
    await asyncio.wait_for(ready.wait(), timeout=3)

    target = uuid4()
    socket_b = StubSocket()
    manager_b.add(target, socket_b)

    try:
        await publish(
            redis, ConnectionManager(), [target], {"type": "remote"}, origin="instance-a"
        )
        await wait_for(lambda: bool(socket_b.received))
        assert socket_b.received == [{"type": "remote"}]

        # Events from our own instance are skipped (already delivered locally).
        await publish(
            redis, ConnectionManager(), [target], {"type": "own"}, origin=instance_b
        )
        await asyncio.sleep(0.2)
        assert len(socket_b.received) == 1
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_connection_tracker_first_and_last_semantics():
    tracker = ConnectionTracker(redis)
    user_id = uuid4()
    try:
        assert await tracker.connect(user_id) is True
        assert await tracker.connect(user_id) is False
        assert await tracker.disconnect(user_id) is False
        assert await tracker.disconnect(user_id) is True
        # A redundant disconnect below zero is reset to zero: no sockets
        # remain anywhere, which is the "last connection" condition.
        assert await tracker.disconnect(user_id) is True
        assert await redis.get(f"radius:conns:{user_id}") == "0"
    finally:
        await redis.delete(f"radius:conns:{user_id}")


async def test_multi_instance_message_delivery(client):
    """A message sent on one "instance" reaches a socket on another."""
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    # "Instance B": a second manager + subscriber with a distinct origin.
    manager_b = ConnectionManager()
    ready = asyncio.Event()
    sub_task = asyncio.create_task(
        subscribe(redis, manager_b, origin="instance-b", ready=ready)
    )
    await asyncio.wait_for(ready.wait(), timeout=3)
    bob_socket_b = StubSocket()
    manager_b.add(bob["id"], bob_socket_b)

    try:
        async with ASGIWebSocketClient(
            app, "/ws", f"user_id={alice['id']}"
        ) as alice_ws:
            await alice_ws.receive_json()  # presence:initial
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": "cross-instance"}
            )
            await alice_ws.receive_json()  # message:ack

        await wait_for(lambda: bool(bob_socket_b.received))
        assert bob_socket_b.received[0]["type"] == "message:new"
        assert bob_socket_b.received[0]["message"]["body"] == "cross-instance"
    finally:
        sub_task.cancel()
        with suppress(asyncio.CancelledError):
            await sub_task
