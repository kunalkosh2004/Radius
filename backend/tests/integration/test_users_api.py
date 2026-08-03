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
    assert body["is_online"] is False
    assert body["id"]
    assert body["last_seen"] is None
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


async def test_update_location_returns_204_and_persists(client, db_session):
    created = await client.post(
        "/api/v1/users",
        json={"nickname": "Mover", "latitude": 0.0, "longitude": 0.0},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    response = await client.patch(
        f"/api/v1/users/{user_id}/location",
        json={"latitude": 51.5074, "longitude": -0.1278},
    )
    assert response.status_code == 204
    assert response.content == b""

    result = await db_session.execute(
        text(
            "SELECT ST_X(location::geometry), ST_Y(location::geometry) "
            "FROM users WHERE id = :id"
        ),
        {"id": user_id},
    )
    longitude, latitude = result.one()
    assert longitude == pytest.approx(-0.1278)
    assert latitude == pytest.approx(51.5074)


async def test_update_location_unknown_user_returns_404(client):
    response = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/location",
        json={"latitude": 0.0, "longitude": 0.0},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "user not found"


async def test_nearby_returns_users_within_radius(client, mark_user_online):
    origin = await client.post(
        "/api/v1/users",
        json={"nickname": "Origin", "latitude": 0.0, "longitude": 0.0},
    )
    origin_id = origin.json()["id"]

    near = await client.post(
        "/api/v1/users",
        json={"nickname": "Near", "latitude": 0.01, "longitude": 0.0},
    )
    await client.post(
        "/api/v1/users",
        json={"nickname": "Far", "latitude": 1.0, "longitude": 0.0},
    )

    await mark_user_online(origin_id)
    await mark_user_online(near.json()["id"])

    response = await client.get(f"/api/v1/users/{origin_id}/nearby?radius_m=5000")

    assert response.status_code == 200
    body = response.json()
    assert [user["nickname"] for user in body] == ["Near"]
    assert body[0]["distance_m"] == pytest.approx(1105.7, rel=0.01)


async def test_nearby_excludes_self(client, mark_user_online):
    origin = await client.post(
        "/api/v1/users",
        json={"nickname": "Origin", "latitude": 0.0, "longitude": 0.0},
    )
    await mark_user_online(origin.json()["id"])

    response = await client.get(
        f"/api/v1/users/{origin.json()['id']}/nearby?radius_m=5000"
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_nearby_default_radius_filters_beyond_500m(client, mark_user_online):
    origin = await client.post(
        "/api/v1/users",
        json={"nickname": "Origin", "latitude": 0.0, "longitude": 0.0},
    )
    close = await client.post(
        "/api/v1/users",
        json={"nickname": "Close", "latitude": 0.001, "longitude": 0.0},
    )
    await client.post(
        "/api/v1/users",
        json={"nickname": "Edge", "latitude": 0.01, "longitude": 0.0},
    )

    await mark_user_online(origin.json()["id"])
    await mark_user_online(close.json()["id"])

    response = await client.get(f"/api/v1/users/{origin.json()['id']}/nearby")

    assert [user["nickname"] for user in response.json()] == ["Close"]


async def test_nearby_unknown_user_returns_404(client):
    response = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/nearby"
    )
    assert response.status_code == 404


async def test_nearby_invalid_radius_returns_422(client):
    origin = await client.post(
        "/api/v1/users",
        json={"nickname": "Origin", "latitude": 0.0, "longitude": 0.0},
    )

    response = await client.get(
        f"/api/v1/users/{origin.json()['id']}/nearby?radius_m=0"
    )
    assert response.status_code == 422
