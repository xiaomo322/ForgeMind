import pytest
from pydantic import ValidationError

from forgemind.schema.search_code import SearchCodeArguments


def test_search_arguments_apply_controlled_defaults() -> None:
    arguments = SearchCodeArguments(query="discount")

    assert arguments.model_dump() == {
        "query": "discount",
        "scope": ".",
        "max_results": 20,
    }


def test_search_arguments_preserve_explicit_values() -> None:
    arguments = SearchCodeArguments(
        query="calculate_price",
        scope="src",
        max_results=50,
    )

    assert arguments.query == "calculate_price"
    assert arguments.scope == "src"
    assert arguments.max_results == 50


@pytest.mark.parametrize(
    ("max_results", "error_type"),
    [
        (0, "greater_than_equal"),
        (101, "less_than_equal"),
    ],
)
def test_search_arguments_reject_result_limit_outside_bounds(
    max_results: int,
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeArguments(query="discount", max_results=max_results)

    assert captured.value.errors()[0]["type"] == error_type


@pytest.mark.parametrize(
    "invalid_arguments",
    [
        {"query": ""},
        {"query": "discount", "scope": ""},
    ],
)
def test_search_arguments_reject_empty_text(
    invalid_arguments: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeArguments(**invalid_arguments)

    assert captured.value.errors()[0]["type"] == "string_too_short"


@pytest.mark.parametrize(
    ("invalid_arguments", "error_type"),
    [
        ({"query": 123}, "string_type"),
        ({"query": "discount", "max_results": "20"}, "int_type"),
        ({"query": "discount", "unknown": True}, "extra_forbidden"),
    ],
)
def test_search_arguments_reject_wrong_types_and_unknown_fields(
    invalid_arguments: dict[str, object],
    error_type: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeArguments(**invalid_arguments)

    assert captured.value.errors()[0]["type"] == error_type
