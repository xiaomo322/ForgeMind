import pytest
from pydantic import ValidationError

from forgemind.schema.search_code import (
    SearchCodeMatch,
    SearchCodeResult,
    SearchIncompleteReason,
)


def test_complete_zero_match_result_is_valid() -> None:
    result = SearchCodeResult(
        query="discount",
        searched_scope=".",
        matches=(),
        returned_count=0,
        is_complete=True,
        incomplete_reasons=(),
    )

    assert result.matches == ()
    assert result.returned_count == 0
    assert result.is_complete is True


def test_result_preserves_actual_match_facts() -> None:
    match = SearchCodeMatch(
        path="src/pricing.py",
        line_number=12,
        line_text="discount = calculate_discount(price)",
    )
    result = SearchCodeResult(
        query="discount",
        searched_scope="src",
        matches=(match,),
        returned_count=1,
        is_complete=False,
        incomplete_reasons=(SearchIncompleteReason.RESULT_LIMIT_REACHED,),
    )

    assert result.matches == (match,)
    assert result.matches[0].line_number == 12


def test_match_rejects_non_positive_line_number() -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeMatch(
            path="src/pricing.py",
            line_number=0,
            line_text="discount = 1",
        )

    assert captured.value.errors()[0]["type"] == "greater_than_equal"


def test_result_rejects_returned_count_different_from_matches() -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeResult(
            query="discount",
            searched_scope=".",
            matches=(),
            returned_count=1,
            is_complete=True,
            incomplete_reasons=(),
        )

    assert "returned_count" in str(captured.value)


def test_complete_result_rejects_incomplete_reasons() -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeResult(
            query="discount",
            searched_scope=".",
            matches=(),
            returned_count=0,
            is_complete=True,
            incomplete_reasons=(SearchIncompleteReason.FILE_SKIPPED,),
        )

    assert "完整结果" in str(captured.value)


def test_incomplete_result_requires_reason() -> None:
    with pytest.raises(ValidationError) as captured:
        SearchCodeResult(
            query="discount",
            searched_scope=".",
            matches=(),
            returned_count=0,
            is_complete=False,
            incomplete_reasons=(),
        )

    assert "不完整结果" in str(captured.value)


@pytest.mark.parametrize("field", ["query", "searched_scope"])
def test_result_rejects_empty_required_text(field: str) -> None:
    payload = {
        "query": "discount",
        "searched_scope": ".",
        "matches": (),
        "returned_count": 0,
        "is_complete": True,
        "incomplete_reasons": (),
    }
    payload[field] = ""

    with pytest.raises(ValidationError) as captured:
        SearchCodeResult.model_validate(payload)

    assert captured.value.errors()[0]["type"] == "string_too_short"
