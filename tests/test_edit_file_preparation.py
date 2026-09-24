import pytest

from forgemind.runtime.versioning import calculate_content_version
from forgemind.schema.actions import AcceptedEditFileToolAction
from forgemind.tools.edit_file import (
    EditFileVersionMismatchError,
    EditTargetAmbiguousError,
    EditTargetNotFoundError,
    prepare_edit_from_snapshot,
)


def make_action(
    content: bytes,
    *,
    old_text: str = "discount = 1",
    new_text: str = "discount = 2",
    expected_version: str | None = None,
) -> AcceptedEditFileToolAction:
    return AcceptedEditFileToolAction(
        action_id="action-edit-001",
        task_id="task-001",
        action_type="tool_call",
        tool_name="edit_file",
        arguments={
            "path": "src/app.py",
            "old_text": old_text,
            "new_text": new_text,
            "expected_version": (
                expected_version or calculate_content_version(content)
            ),
        },
        reason="修正折扣逻辑",
    )


def test_prepare_edit_replaces_exactly_one_match() -> None:
    content = b"price = 10\ndiscount = 1\n"

    prepared = prepare_edit_from_snapshot(
        make_action(content),
        content=content,
    )

    assert prepared.before_bytes == content
    assert prepared.after_bytes == b"price = 10\ndiscount = 2\n"
    assert prepared.before_version == calculate_content_version(content)
    assert prepared.after_version == calculate_content_version(
        prepared.after_bytes
    )
    assert prepared.after_version != prepared.before_version
    assert "--- src/app.py.before" in prepared.diff
    assert "+++ src/app.py.after" in prepared.diff
    assert "-discount = 1" in prepared.diff
    assert "+discount = 2" in prepared.diff


def test_prepare_edit_allows_deleting_the_unique_match() -> None:
    content = b"price = 10\ndiscount = 1\n"

    prepared = prepare_edit_from_snapshot(
        make_action(content, old_text="discount = 1\n", new_text=""),
        content=content,
    )

    assert prepared.after_bytes == b"price = 10\n"
    assert "-discount = 1" in prepared.diff


def test_prepare_edit_rejects_missing_target() -> None:
    content = b"price = 10\n"

    with pytest.raises(EditTargetNotFoundError):
        prepare_edit_from_snapshot(make_action(content), content=content)


def test_prepare_edit_rejects_ambiguous_target_with_match_count() -> None:
    content = b"discount = 1\ndiscount = 1\n"

    with pytest.raises(EditTargetAmbiguousError) as captured:
        prepare_edit_from_snapshot(make_action(content), content=content)

    assert captured.value.match_count == 2


def test_prepare_edit_rejects_invalid_utf8() -> None:
    content = b"discount = 1\n\xff"

    with pytest.raises(UnicodeDecodeError):
        prepare_edit_from_snapshot(make_action(content), content=content)


def test_prepare_edit_checks_version_before_decoding() -> None:
    content = b"\xff"
    action = make_action(content, expected_version="sha256:approved-old-version")

    with pytest.raises(EditFileVersionMismatchError) as captured:
        prepare_edit_from_snapshot(action, content=content)

    assert captured.value.expected_version == "sha256:approved-old-version"
    assert captured.value.actual_version == calculate_content_version(content)
