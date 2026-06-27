"""Tests for strip_code_fence: tolerate a fenced model reply, nothing more."""

from app.agents.parsing import strip_code_fence


def test_strips_json_language_fence() -> None:
    text = '```json\n{"a": 1}\n```'
    assert strip_code_fence(text) == '{"a": 1}'


def test_strips_plain_fence() -> None:
    text = '```\n{"a": 1}\n```'
    assert strip_code_fence(text) == '{"a": 1}'


def test_leaves_bare_json_unchanged() -> None:
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_trims_surrounding_whitespace() -> None:
    assert strip_code_fence('  \n```json\n{"a": 1}\n```  \n') == '{"a": 1}'


def test_non_fenced_text_is_only_trimmed() -> None:
    assert strip_code_fence("  not json at all  ") == "not json at all"


def test_invalid_payload_after_stripping_is_returned_not_fixed() -> None:
    # Stripping is tolerant, not corrective: the caller's validation still fails.
    assert strip_code_fence("```json\nnot valid json\n```") == "not valid json"
