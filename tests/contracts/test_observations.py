import pytest
from pydantic import ValidationError

from forgemind.schema.observations import (
    ObservationError,
    ObservationErrorCode,
    RejectedObservation,
)


def test_permission_rejection_has_no_success_result() -> None:
    observation = RejectedObservation(
        action_id="action-001",
        status="rejected",
        error=ObservationError(
            code=ObservationErrorCode.PERMISSION_DENIED,
            message="用户未授权读取该文件",
        ),
    )

    assert observation.action_id == "action-001"
    assert observation.status == "rejected"
    assert observation.error.code is ObservationErrorCode.PERMISSION_DENIED

    with pytest.raises(ValidationError) as captured:
        RejectedObservation.model_validate(
            {
                "action_id": "action-001",
                "status": "rejected",
                "error": {
                    "code": ObservationErrorCode.PERMISSION_DENIED,
                    "message": "用户未授权读取该文件",
                },
                "result": {"content": "不应存在"},
            }
        )

    assert captured.value.errors()[0]["type"] == "extra_forbidden"
    assert captured.value.errors()[0]["loc"] == ("result",)
