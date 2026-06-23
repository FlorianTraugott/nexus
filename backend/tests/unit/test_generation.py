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


def test_get_generation_provider_rejects_unknown(monkeypatch) -> None:
    from app.core import config

    get_generation_provider.cache_clear()
    monkeypatch.setattr(config.get_settings(), "LLM_PROVIDER", "bogus", raising=False)

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_generation_provider()

    get_generation_provider.cache_clear()
