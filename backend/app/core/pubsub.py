import asyncio
import json
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.websocket.manager import ConnectionManager

# Events go through one channel; the envelope carries an `origin` instance id
# so a subscriber can ignore events its own process published (those are
# already delivered locally by `publish`).
EVENTS_CHANNEL = "radius:events"

# Every uvicorn process gets a fresh identity; used to dedupe self-published
# events in the subscription loop.
INSTANCE_ID = str(uuid4())


async def publish(
    redis: Redis,
    manager: ConnectionManager,
    target_ids: list[UUID],
    payload: dict,
    origin: str = INSTANCE_ID,
) -> None:
    """Fan an event out to every socket of `target_ids` across all instances.

    Delivers locally to this process's sockets and publishes an envelope so
    other instances deliver to theirs. Subscribers skip envelopes from
    `origin`, which prevents double delivery on the publishing instance.
    """
    envelope = json.dumps(
        {
            "origin": origin,
            "to": [str(target_id) for target_id in target_ids],
            "payload": payload,
        }
    )
    await redis.publish(EVENTS_CHANNEL, envelope)
    for target_id in target_ids:
        await manager.send_to_user(target_id, payload)


async def subscribe(
    redis: Redis,
    manager: ConnectionManager,
    origin: str = INSTANCE_ID,
    ready: asyncio.Event | None = None,
) -> None:
    """Forward remote events from the channel to this instance's sockets.

    Runs forever; cancel the task to stop. `origin` identifies this instance,
    so its own published events (already delivered locally) are skipped.
    When `ready` is given it is set once the subscription is live (for tests).
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    if ready is not None:
        ready.set()
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            event = json.loads(message["data"])
            if event.get("origin") == origin:
                continue
            payload = event.get("payload", {})
            for target_id in event.get("to", []):
                await manager.send_to_user(UUID(target_id), payload)
    finally:
        await pubsub.unsubscribe(EVENTS_CHANNEL)
