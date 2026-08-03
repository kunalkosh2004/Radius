from uuid import uuid4

from app.websocket.manager import ConnectionManager


def make_socket():
    return object()


def test_first_and_last_connection_semantics():
    manager = ConnectionManager()
    user_id = uuid4()
    first, second = make_socket(), make_socket()

    assert manager.add(user_id, first) is True
    assert manager.add(user_id, second) is False
    assert manager.online_user_ids == {user_id}
    assert manager.connection_count == 2

    assert manager.remove(user_id, first) is False
    assert manager.online_user_ids == {user_id}

    assert manager.remove(user_id, second) is True
    assert manager.online_user_ids == set()
    assert manager.connection_count == 0


def test_removing_unknown_socket_returns_false():
    manager = ConnectionManager()
    assert manager.remove(uuid4(), make_socket()) is False
