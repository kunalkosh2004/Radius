from uuid import uuid4

from app.core.config import get_settings
from app.core.ws_token import create_ws_token, verify_ws_token

settings = get_settings()


async def test_ws_token_endpoint_returns_signed_token(client):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": "tok", "latitude": 0.0, "longitude": 0.0},
    )
    user_id = response.json()["id"]

    response = await client.post("/api/v1/auth/ws-token", json={"user_id": user_id})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["expires_in"] == settings.WS_TOKEN_TTL_S

    token = body["token"]
    assert "." in token
    assert verify_ws_token(token) is not None
    assert str(verify_ws_token(token)) == user_id


async def test_ws_token_endpoint_unknown_user_404(client):
    response = await client.post(
        "/api/v1/auth/ws-token", json={"user_id": str(uuid4())}
    )
    assert response.status_code == 404


async def test_ws_token_endpoint_rejects_missing_user_id(client):
    response = await client.post("/api/v1/auth/ws-token", json={})
    assert response.status_code == 422


def test_token_signature_is_verified():
    user_id = uuid4()
    token = create_ws_token(user_id)
    assert verify_ws_token(token) == user_id

    tampered = token + "x"
    assert verify_ws_token(tampered) is None

    # Flipping one character of the signature must fail verification.
    head, sig = token.rsplit(".", 1)
    flipped = "0" if sig[-1] != "0" else "1"
    assert verify_ws_token(f"{head}.{sig[:-1]}{flipped}") is None


def test_token_is_expiry_scoped(monkeypatch):
    user_id = uuid4()
    monkeypatch.setattr(settings, "WS_TOKEN_TTL_S", -1)
    assert verify_ws_token(create_ws_token(user_id)) is None
