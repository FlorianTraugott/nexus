"""Tests for the generation provider abstraction and prompt assembly."""

from types import SimpleNamespace

import pytest
from anthropic.types import TextBlock
from tests.fakes import FakeGenerationProvider

from app.services.generation import (
    ClaudeGenerationProvider,
    OpenAIGenerationProvider,
    build_prompt,
    get_generation_provider,
)


def test_build_prompt_includes_context_and_question() -> None:
    system, user = build_prompt("What is X?", ["first fact", "second fact"])

    assert "ONLY" in system  # answer only from the provided context
    assert "[1] first fact" in user
    assert "[2] second fact" in user
    assert "Question: What is X?" in user


def test_build_prompt_handles_empty_context() -> None:
    _, user = build_prompt("anything?", [])

    assert "no context passages" in user
    assert "Question: anything?" in user


def test_build_prompt_without_history_is_unchanged() -> None:
    # Omitting history must reproduce the pre-9B.3 output byte-for-byte, so the
    # faithfulness baseline (which never passes history) stays comparable.
    system_none, user_none = build_prompt("What is X?", ["a fact"])
    system_empty, user_empty = build_prompt("What is X?", ["a fact"], history=[])

    assert system_none == system_empty
    assert user_none == user_empty
    assert "Previous conversation:" not in user_none
    assert "conversation" not in system_none  # no framing clause on a single turn
    assert user_none == "Context passages:\n[1] a fact\n\nQuestion: What is X?"


def test_build_prompt_with_history_renders_block_and_framing_clause() -> None:
    history = [("user", "tell me about bravo"), ("assistant", "bravo is a fruit")]
    system, user = build_prompt("what about it?", ["a fact"], history=history)

    # The delimited history block precedes the passages and the question.
    assert "Previous conversation:" in user
    assert "user: tell me about bravo" in user
    assert "assistant: bravo is a fruit" in user
    assert user.index("Previous conversation:") < user.index("Context passages:")
    assert "[1] a fact" in user
    assert "Question: what about it?" in user

    # The framing rule is stated: history clarifies intent, never grounds a claim.
    assert "ONLY to understand what the user is asking" in system
    assert "never from the conversation" in system


async def test_fake_provider_is_deterministic_and_records_calls() -> None:
    provider = FakeGenerationProvider(answer="grounded")

    answer = await provider.generate("sys", "prompt")

    assert answer == "grounded"
    assert provider.calls == [("sys", "prompt")]


async def test_claude_provider_sends_prompts_and_joins_text(monkeypatch) -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[
                TextBlock(type="text", text="part one. "),
                SimpleNamespace(type="tool_use"),  # ignored: not a text block
                TextBlock(type="text", text="part two."),
            ]
        )

    provider = ClaudeGenerationProvider(api_key="x", model="m", max_tokens=128)
    monkeypatch.setattr(provider._client.messages, "create", fake_create)

    answer = await provider.generate("the system", "the question")

    assert answer == "part one. part two."
    assert captured["model"] == "m"
    assert captured["max_tokens"] == 128
    assert captured["system"] == "the system"
    assert captured["messages"] == [{"role": "user", "content": "the question"}]


async def test_openai_provider_sends_prompts_and_returns_text(monkeypatch) -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="grounded answer")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    provider = OpenAIGenerationProvider(
        api_key="x", model="gpt-4.1-mini", max_tokens=64
    )
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    answer = await provider.generate("the system", "the question")

    assert answer == "grounded answer"
    assert captured["model"] == "gpt-4.1-mini"
    assert captured["max_tokens"] == 64
    assert captured["messages"] == [
        {"role": "system", "content": "the system"},
        {"role": "user", "content": "the question"},
    ]


async def test_openai_provider_json_mode_toggles_response_format(monkeypatch) -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.clear()
        captured.update(kwargs)
        message = SimpleNamespace(content="{}")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    provider = OpenAIGenerationProvider(api_key="x", model="m", max_tokens=64)
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    await provider.generate("sys", "prompt", json_mode=True)
    assert captured["response_format"] == {"type": "json_object"}

    # Default (e.g. the /query path): response_format is not sent at all.
    await provider.generate("sys", "prompt")
    assert "response_format" not in captured


async def test_openai_provider_generate_stream_yields_content_deltas(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)

        async def chunks():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]
            )
            # delta.content None (role/finish frame) and empty choices are skipped.
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]
            )
            yield SimpleNamespace(choices=[])

        return chunks()

    provider = OpenAIGenerationProvider(api_key="x", model="m", max_tokens=64)
    monkeypatch.setattr(provider._client.chat.completions, "create", fake_create)

    out = [delta async for delta in provider.generate_stream("sys", "prompt")]

    assert out == ["Hel", "lo"]
    assert captured["stream"] is True
    assert captured["model"] == "m"
    assert captured["max_tokens"] == 64
    assert "response_format" not in captured  # streaming never sets json mode
    assert captured["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "prompt"},
    ]


def test_claude_provider_generate_stream_raises_not_implemented() -> None:
    provider = ClaudeGenerationProvider(api_key="x", model="m", max_tokens=64)
    with pytest.raises(NotImplementedError, match="does not implement streaming"):
        provider.generate_stream("sys", "prompt")


def test_get_generation_provider_rejects_unknown(monkeypatch) -> None:
    from app.core import config

    get_generation_provider.cache_clear()
    monkeypatch.setattr(config.get_settings(), "LLM_PROVIDER", "bogus", raising=False)

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_generation_provider()

    get_generation_provider.cache_clear()
