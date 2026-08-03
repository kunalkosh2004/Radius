import pytest

from app.main import app
from app.websocket.router import broadcast_nearby
from tests.websocket_client import ASGIWebSocketClient


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


async def open_socket(client, nickname, latitude, longitude):
    user = await create_user(client, nickname, latitude, longitude)
    ws = ASGIWebSocketClient(app, "/ws", f"user_id={user['id']}")
    await ws.__aenter__()
    return user, ws


async def test_location_update_refreshes_mover_and_notifies_peer(client):
    bob, bob_ws = await open_socket(client, "bob", 0.001, 0.0)
    try:
        assert (await bob_ws.receive_json())["type"] == "presence:initial"
        alice, alice_ws = await open_socket(client, "alice", 0.0, 0.0)
        try:
            assert (await alice_ws.receive_json())["type"] == "presence:initial"
            assert (await bob_ws.receive_json())["type"] == "presence:update"

            await alice_ws.send_json(
                {"type": "location:update", "latitude": 0.002, "longitude": 0.0}
            )

            nearby = await alice_ws.receive_json()
            assert nearby["type"] == "nearby:update"
            assert [u["nickname"] for u in nearby["users"]] == ["bob"]
            assert nearby["users"][0]["distance_m"] == pytest.approx(111.2, rel=0.05)

            peer = await bob_ws.receive_json()
            assert peer["type"] == "nearby:neighbor-updated"
            assert peer["user"]["id"] == str(alice["id"])
            assert peer["distance_m"] == pytest.approx(111.2, rel=0.05)
        finally:
            await alice_ws.__aexit__(None, None, None)
    finally:
        await bob_ws.__aexit__(None, None, None)


async def test_location_update_out_of_range_notifies_peer(client):
    bob, bob_ws = await open_socket(client, "bob", 0.001, 0.0)
    try:
        await bob_ws.receive_json()
        alice, alice_ws = await open_socket(client, "alice", 0.0, 0.0)
        try:
            await alice_ws.receive_json()
            await bob_ws.receive_json()

            await alice_ws.send_json(
                {"type": "location:update", "latitude": 10.0, "longitude": 10.0}
            )

            nearby = await alice_ws.receive_json()
            assert nearby["type"] == "nearby:update"
            assert nearby["users"] == []

            peer = await bob_ws.receive_json()
            assert peer["type"] == "nearby:neighbor-updated"
            assert peer["user"]["id"] == str(alice["id"])
            assert peer["distance_m"] is None
        finally:
            await alice_ws.__aexit__(None, None, None)
    finally:
        await bob_ws.__aexit__(None, None, None)


async def test_rest_patch_location_triggers_live_update(client):
    bob, bob_ws = await open_socket(client, "bob", 0.001, 0.0)
    try:
        await bob_ws.receive_json()
        alice, alice_ws = await open_socket(client, "alice", 0.0, 0.0)
        try:
            await alice_ws.receive_json()
            await bob_ws.receive_json()

            response = await client.patch(
                f"/api/v1/users/{alice['id']}/location",
                json={"latitude": 0.002, "longitude": 0.0},
            )
            assert response.status_code == 204

            assert (await alice_ws.receive_json())["type"] == "nearby:update"
            peer = await bob_ws.receive_json()
            assert peer["type"] == "nearby:neighbor-updated"
            assert peer["user"]["id"] == str(alice["id"])
        finally:
            await alice_ws.__aexit__(None, None, None)
    finally:
        await bob_ws.__aexit__(None, None, None)


async def test_invalid_location_update_returns_error(client):
    alice, alice_ws = await open_socket(client, "alice", 0.0, 0.0)
    try:
        await alice_ws.receive_json()

        await alice_ws.send_json(
            {"type": "location:update", "latitude": 95.0, "longitude": 0.0}
        )

        assert (await alice_ws.receive_json()) == {
            "type": "nearby:error",
            "error": "invalid location",
        }
    finally:
        await alice_ws.__aexit__(None, None, None)


async def test_broadcast_nearby_sends_full_list(client):
    bob, bob_ws = await open_socket(client, "bob", 0.001, 0.0)
    try:
        await bob_ws.receive_json()
        alice, alice_ws = await open_socket(client, "alice", 0.0, 0.0)
        try:
            await alice_ws.receive_json()
            await bob_ws.receive_json()

            await broadcast_nearby()

            nearby_bob = await bob_ws.receive_json()
            assert nearby_bob["type"] == "nearby:update"
            assert [u["nickname"] for u in nearby_bob["users"]] == ["alice"]

            nearby_alice = await alice_ws.receive_json()
            assert nearby_alice["type"] == "nearby:update"
            assert [u["nickname"] for u in nearby_alice["users"]] == ["bob"]
        finally:
            await alice_ws.__aexit__(None, None, None)
    finally:
        await bob_ws.__aexit__(None, None, None)
