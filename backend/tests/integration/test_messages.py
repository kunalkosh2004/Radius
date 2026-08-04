from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.core.ws_token import create_ws_token
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
    return ASGIWebSocketClient(app, "/ws", f"token={create_ws_token(user_id)}")


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


async def test_read_receipt_marks_messages_and_persists(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        ids = []
        for body in ["m1", "m2"]:
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": body}
            )
            ids.append((await alice_ws.receive_json())["message"]["id"])

    async with connect(client, bob["id"]) as bob_ws:
        await bob_ws.receive_json()  # presence:initial
        await bob_ws.send_json({"type": "message:read", "ids": ids})
        read_ack = await bob_ws.receive_json()
        assert read_ack["type"] == "message:read"
        assert set(read_ack["ids"]) == set(ids)
        assert read_ack["read_at"] is not None

    response = await client.get(
        f"/api/v1/users/{alice['id']}/messages/{bob['id']}"
    )
    assert all(m["read_at"] is not None for m in response.json())


async def test_read_receipt_notifies_sender(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()  # alice initial
        async with connect(client, bob["id"]) as bob_ws:
            await bob_ws.receive_json()  # bob initial
            await alice_ws.receive_json()  # alice sees bob online

            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": "read me"}
            )
            ack = await alice_ws.receive_json()
            await bob_ws.receive_json()  # delivery

            await bob_ws.send_json(
                {"type": "message:read", "ids": [ack["message"]["id"]]}
            )
            await bob_ws.receive_json()  # bob's read ack
            receipt = await alice_ws.receive_json()
            assert receipt["type"] == "message:read"
            assert receipt["ids"] == [ack["message"]["id"]]
            assert receipt["read_at"] is not None


async def test_cannot_mark_own_sent_messages_read(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        async with connect(client, bob["id"]) as bob_ws:
            await bob_ws.receive_json()
            await alice_ws.receive_json()  # alice sees bob online

            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": "m"}
            )
            ack = await alice_ws.receive_json()
            await bob_ws.receive_json()  # delivery

            await alice_ws.send_json(
                {"type": "message:read", "ids": [ack["message"]["id"]]}
            )
            read_ack = await alice_ws.receive_json()
            assert read_ack["type"] == "message:read"
            assert read_ack["ids"] == []


async def test_message_read_invalid_payloads(client):
    alice = await create_user(client, "alice")
    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        for payload in [
            {"type": "message:read"},
            {"type": "message:read", "ids": []},
            {"type": "message:read", "ids": "x"},
            {"type": "message:read", "ids": ["not-a-uuid"]},
        ]:
            await alice_ws.send_json(payload)
            error = await alice_ws.receive_json()
            assert error["type"] == "message:error"


async def test_conversations_lists_peers_ordered_by_activity(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")
    carol = await create_user(client, "carol")

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        for body in ["to bob 1", "to bob 2"]:
            await alice_ws.send_json(
                {"type": "message:send", "to": bob["id"], "body": body}
            )
            await alice_ws.receive_json()

    async with connect(client, carol["id"]) as carol_ws:
        await carol_ws.receive_json()
        await carol_ws.send_json(
            {"type": "message:send", "to": alice["id"], "body": "hi alice"}
        )
        await carol_ws.receive_json()

    response = await client.get(f"/api/v1/users/{alice['id']}/conversations")
    assert response.status_code == 200
    convos = response.json()

    assert [c["peer"]["nickname"] for c in convos] == ["carol", "bob"]
    assert convos[0]["last_message"]["body"] == "hi alice"
    assert convos[0]["unread_count"] == 1
    assert convos[1]["last_message"]["body"] == "to bob 2"
    assert convos[1]["unread_count"] == 0


async def test_conversations_reflect_read_receipts(client):
    alice = await create_user(client, "alice")
    bob = await create_user(client, "bob")

    async with connect(client, bob["id"]) as bob_ws:
        await bob_ws.receive_json()
        await bob_ws.send_json(
            {"type": "message:send", "to": alice["id"], "body": "unread"}
        )
        ack = await bob_ws.receive_json()

    url = f"/api/v1/users/{alice['id']}/conversations"
    assert (await client.get(url)).json()[0]["unread_count"] == 1

    async with connect(client, alice["id"]) as alice_ws:
        await alice_ws.receive_json()
        await alice_ws.send_json(
            {"type": "message:read", "ids": [ack["message"]["id"]]}
        )
        await alice_ws.receive_json()

    assert (await client.get(url)).json()[0]["unread_count"] == 0


async def test_conversations_empty(client):
    alice = await create_user(client, "alice")
    response = await client.get(f"/api/v1/users/{alice['id']}/conversations")
    assert response.status_code == 200
    assert response.json() == []


async def test_conversations_unknown_user(client):
    response = await client.get(f"/api/v1/users/{uuid4()}/conversations")
    assert response.status_code == 404
