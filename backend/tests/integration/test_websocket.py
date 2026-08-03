from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.core.background import sweep_once
from app.main import app
from app.models import User
from tests.websocket_client import ASGIWebSocketClient, WebSocketDisconnect


async def create_user(client, nickname, latitude, longitude):
    response = await client.post(
        "/api/v1/users",
        json={
            "nickname": nickname,
            "latitude": latitude,
            "longitude": longitude,
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_connect_sends_initial_presence(client):
    alice = await create_user(client, "alice", 0.0, 0.0)
    bob = await create_user(client, "bob", 0.001, 0.0)

    async with ASGIWebSocketClient(app, "/ws", f"user_id={bob['id']}") as bob_ws:
        initial_bob = await bob_ws.receive_json()
        assert initial_bob["type"] == "presence:initial"
        assert initial_bob["users"] == []

        async with ASGIWebSocketClient(
            app, "/ws", f"user_id={alice['id']}"
        ) as alice_ws:
            initial_alice = await alice_ws.receive_json()
            assert initial_alice["type"] == "presence:initial"
            assert [u["nickname"] for u in initial_alice["users"]] == ["bob"]

            update_msg = await bob_ws.receive_json()
            assert update_msg["type"] == "presence:update"
            assert update_msg["status"] == "online"
            assert update_msg["user"]["nickname"] == "alice"
            assert update_msg["distance_m"] == pytest.approx(111.2, rel=0.05)


async def test_heartbeat_ping_pong(client):
    user = await create_user(client, "hrt", 0.0, 0.0)

    async with ASGIWebSocketClient(app, "/ws", f"user_id={user['id']}") as ws:
        assert (await ws.receive_json())["type"] == "presence:initial"

        await ws.send_json({"type": "ping"})
        assert await ws.receive_json() == {"type": "pong"}


async def test_disconnect_notifies_nearby_user(client):
    alice = await create_user(client, "alice", 0.0, 0.0)
    bob = await create_user(client, "bob", 0.001, 0.0)

    async with ASGIWebSocketClient(app, "/ws", f"user_id={bob['id']}") as bob_ws:
        await bob_ws.receive_json()

        async with ASGIWebSocketClient(
            app, "/ws", f"user_id={alice['id']}"
        ) as alice_ws:
            await alice_ws.receive_json()
            assert (await bob_ws.receive_json())["status"] == "online"

        offline_msg = await bob_ws.receive_json()
        assert offline_msg["type"] == "presence:update"
        assert offline_msg["status"] == "offline"
        assert offline_msg["user"]["nickname"] == "alice"


async def test_connect_unknown_user_is_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        async with ASGIWebSocketClient(
            app, "/ws", "user_id=00000000-0000-0000-0000-000000000000"
        ) as ws:
            await ws.receive_json()


async def test_sweep_marks_stale_users_offline(client, db_session, mark_user_online):
    fresh = await create_user(client, "fresh", 0.0, 0.0)
    stale = await create_user(client, "stale", 0.0, 0.0)
    await mark_user_online(fresh["id"])
    await mark_user_online(stale["id"])

    await db_session.execute(
        update(User)
        .where(User.id == stale["id"])
        .values(last_seen=datetime.now(UTC) - timedelta(minutes=10))
    )
    await db_session.commit()

    assert await sweep_once() == 1

    result = await db_session.execute(select(User).order_by(User.nickname))
    online_by_nickname = {u.nickname: u.is_online for u in result.scalars()}
    assert online_by_nickname == {"fresh": True, "stale": False}
