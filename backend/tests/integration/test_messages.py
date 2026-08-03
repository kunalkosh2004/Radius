from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.main import app
from tests.websocket_client import ASGIWebSocketClient

settings = get_settings()


async def create_user(client, nickname, latitude=0.0, longitude=0.0):
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


def connect(client, user_id):
    return ASGIWebSocketClient(app, "/ws", f"user_id={user_id}")


async def test_send_message_delivers_ack_and_new(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, bob["id"]) as bob_ws:
        await bob_ws.receive_json()  # presence:initial

        async with connect(client, alice["id"]) as alice_ws:
            await alice_ws.receive_json()  # presence:initial
            await bob_ws.receive_json()  # presence:update online

            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": "hello bob"}
            )
            ack = await alice_ws.receive_json()
            assert ack["type"] == "message:ack"
            assert ack["message"]["body"] == "hello bob"
            assert ack["message"]["from"] == alice["id"]
            assert ack["message"]["to"] == bob["id"]

            delivered = await bob_ws.receive_json()
            assert delivered["type"] == "message:new"
            assert delivered["message"]["id"] == ack["message"]["id"]
            assert delivered["message"]["body"] == "hello bob"


async def test_send_message_delivers_to_all_devices(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, bob["id"]) as bob_phone, connect(
        client, bob["id"]
    ) as bob_laptop:
        await bob_phone.receive_json()  # presence:initial
        await bob_laptop.receive_json()  # presence:initial

        async with connect(client, alice["id"]) as alice_ws:
            await alice_ws.receive_json()  # presence:initial
            await bob_phone.receive_json()  # presence:update online
            await bob_laptop.receive_json()  # presence:update online
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": "multi-device"}
            )
            await alice_ws.receive_json()  # message:ack

            assert (await bob_phone.receive_json())["message"]["body"] == "multi-device"
            assert (
                await bob_laptop.receive_json()
            )["message"]["body"] == "multi-device"


async def test_send_message_to_offline_peer_is_acknowledged(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()  # presence:initial
        await alice_ws.send_json(
            {"type": "message:send", "to": bob["id"], "body": "while you were away"}
        )
        ack = await alice_ws.receive_json()
        assert ack["type"] == "message:ack"

    response = await client.get(
        f"/api/v1/users/{bob['id']}/messages/{alice['id']}"
    )
    assert response.status_code == 200
    assert [m["body"] for m in response.json()] == ["while you were away"]


@pytest.mark.parametrize(
    "send",
    [
        {"type": "message:send", "to": "", "body": "hi"},
        {"type": "message:send", "to": "not-a-uuid", "body": "hi"},
        {"type": "message:send", "to": 42, "body": "hi"},
    ],
)
async def test_send_message_invalid_recipient(client, send):
    alice = await create_user(client, "alice")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        await alice_ws.send_json(send)
        error = await alice_ws.receive_json()
        assert error["type"] == "message:error"
        assert error["error"] == "invalid recipient"


async def test_send_message_unknown_recipient(client):
    alice = await create_user(client, "alice")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        await alice_ws.send_json(
            {"type": "message:send", "to": str(uuid4()), "body": "hi"}
        )
        error = await alice_ws.receive_json()
        assert error["type"] == "message:error"
        assert error["error"] == "user not found"


async def test_send_message_self_not_allowed(client):
    alice = await create_user(client, "alice")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        await alice_ws.send_json(
            {"type": "message:send", "to": alice["id"], "body": "to myself"}
        )
        error = await alice_ws.receive_json()
        assert error["type"] == "message:error"
        assert error["error"] == "cannot message yourself"


async def test_send_message_empty_body_rejected(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        for body in ["", "   ", None, 123]:
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": body}
            )
            error = await alice_ws.receive_json()
            assert error["type"] == "message:error"
            assert error["error"] == "message body is required"


async def test_send_message_oversized_body_rejected(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        await alice_ws.send_json(
            {
                "type": "message:send",
                "to": bob["id"],
                "body": "x" * (settings.MESSAGE_MAX_LENGTH + 1),
            }
        )
        error = await alice_ws.receive_json()
        assert error["type"] == "message:error"
        assert "exceeds" in error["error"]


async def test_conversation_history_is_bidirectional_and_newest_first(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        for i, body in enumerate(["a1", "a2"]):
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": body}
            )
            await alice_ws.receive_json()  # ack

    async with connect(client, bob["id"]) as bob_ws:
        await bob_ws.receive_json()
        await bob_ws.send_json(
            {"type": "message:send", "to": alice["id"], "body": "b1"}
        )
        await bob_ws.receive_json()  # ack

    response = await client.get(
        f"/api/v1/users/{alice['id']}/messages/{bob['id']}"
    )
    assert response.status_code == 200
    messages = response.json()
    assert [m["body"] for m in messages] == ["b1", "a2", "a1"]
    assert [m["sender_id"] for m in messages] == [
        bob["id"],
        alice["id"],
        alice["id"],
    ]


async def test_conversation_history_pagination(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        for i in range(5):
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": f"m{i}"}
            )
            await alice_ws.receive_json()  # ack

    url = f"/api/v1/users/{alice['id']}/messages/{bob['id']}"

    page1 = (await client.get(url, params={"limit": 2})).json()
    assert [m["body"] for m in page1] == ["m4", "m3"]

    page2 = (await client.get(url, params={"limit": 2, "before": page1[1]["id"]})).json()
    assert [m["body"] for m in page2] == ["m2", "m1"]

    page3 = (await client.get(url, params={"limit": 2, "before": page2[1]["id"]})).json()
    assert [m["body"] for m in page3] == ["m0"]


async def test_conversation_history_unknown_user(client):
    alice = await create_user(client, "alice")
    response = await client.get(
        f"/api/v1/users/{alice['id']}/messages/{uuid4()}"
    )
    assert response.status_code == 404
