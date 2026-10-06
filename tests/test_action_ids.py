from uuid import UUID

from forgemind.runtime.ids import new_action_id, new_permission_request_id


def test_new_action_id_returns_prefixed_uuid() -> None:
    action_id = new_action_id()

    prefix = "action_"
    assert action_id.startswith(prefix)
    assert UUID(action_id.removeprefix(prefix)).version == 4


def test_new_permission_request_id_returns_prefixed_uuid() -> None:
    request_id = new_permission_request_id()

    prefix = "permission_request_"
    assert request_id.startswith(prefix)
    assert UUID(request_id.removeprefix(prefix)).version == 4
