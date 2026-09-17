import pytest
from pydantic import ValidationError

from forgemind.schema.base import StrictContractModel


def test_contract_model_rejects_unknown_fields() -> None:
    class ExampleContract(StrictContractModel):
        count: int

    with pytest.raises(ValidationError) as captured:
        ExampleContract(count=1, unexpected=True)

    assert captured.value.errors()[0]["type"] == "extra_forbidden"


def test_contract_model_rejects_type_coercion() -> None:
    class ExampleContract(StrictContractModel):
        count: int

    with pytest.raises(ValidationError) as captured:
        ExampleContract(count="1")

    assert captured.value.errors()[0]["type"] == "int_type"


def test_contract_model_rejects_changes_after_validation() -> None:
    class ExampleContract(StrictContractModel):
        count: int

    contract = ExampleContract(count=1)

    with pytest.raises(ValidationError) as captured:
        contract.count = 2

    assert captured.value.errors()[0]["type"] == "frozen_instance"
