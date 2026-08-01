import pytest
from sqlalchemy import text


async def test_create_user_success(client):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": "Radman", "latitude": 37.7749, "longitude": -122.4194},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["nickname"] == "Radman"
    assert body["latitude"] == 37.7749
    assert body["longitude"] == -122.4194
    assert body["is_online"] is True
    assert body["id"]
    assert body["last_seen"]
    assert body["created_at"]


async def test_create_user_duplicate_nickname_returns_409(client):
    payload = {"nickname": "Radman", "latitude": 37.7749, "longitude": -122.4194}

    first = await client.post("/api/v1/users", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/users", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "nickname already taken"


async def test_create_user_invalid_latitude_returns_422(client):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": "Radman", "latitude": 91.0, "longitude": 0.0},
    )

    assert response.status_code == 422


async def test_create_user_blank_nickname_returns_422(client):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": "", "latitude": 37.0, "longitude": -122.0},
    )

    assert response.status_code == 422


async def test_create_user_persists_geography(client, db_session):
    response = await client.post(
        "/api/v1/users",
        json={"nickname": "GeoTester", "latitude": 12.3456, "longitude": 98.7654},
    )
    assert response.status_code == 201

    result = await db_session.execute(
        text(
            "SELECT ST_X(location::geometry), ST_Y(location::geometry) FROM users "
            "WHERE nickname = 'GeoTester'"
        )
    )
    longitude, latitude = result.one()

    assert longitude == pytest.approx(98.7654)
    assert latitude == pytest.approx(12.3456)
