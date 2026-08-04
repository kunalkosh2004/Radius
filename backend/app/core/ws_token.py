import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from app.core.config import get_settings


def _secret() -> bytes:
    return get_settings().WS_TOKEN_SECRET.encode()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_ws_token(user_id: UUID) -> str:
    """Mint a short-lived, HMAC-signed token for the given user.

    The token embeds the user id and an absolute expiry timestamp so it
    cannot be forged without the shared secret or replayed past expiry.
    """
    settings = get_settings()
    payload = _b64url_encode(
        json.dumps(
            {"sub": str(user_id), "exp": int(time.time()) + settings.WS_TOKEN_TTL_S},
            separators=(",", ":"),
        ).encode()
    )
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_ws_token(token: str) -> UUID | None:
    """Return the embedded user id if the token is valid and unexpired."""
    if not isinstance(token, str):
        return None
    try:
        payload_b64, signature = token.rsplit(".", 1)
    except ValueError:
        return None

    expected = hmac.new(_secret(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
        user_id = UUID(str(payload["sub"]))
        exp = int(payload["exp"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

    if exp < time.time():
        return None
    return user_id
