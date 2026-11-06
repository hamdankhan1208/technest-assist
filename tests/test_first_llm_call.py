from types import SimpleNamespace

import pytest

import first_llm_call
from groq import GroqError


def test_uses_groq_when_api_key_is_set(monkeypatch):
    expected = "Groq answer"
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        first_llm_call,
        "Groq",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[
                            SimpleNamespace(message=SimpleNamespace(content=expected))
                        ]
                    )
                )
            )
        ),
    )
    monkeypatch.setattr(
        first_llm_call,
        "chat",
        lambda **kwargs: pytest.fail("Ollama should not be called"),
    )

    assert first_llm_call.generate_response([]) == expected


def test_falls_back_to_ollama_when_groq_fails(monkeypatch, capsys):
    expected = "Local answer"
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fail_groq(**kwargs):
        raise GroqError("request failed")

    monkeypatch.setattr(
        first_llm_call,
        "Groq",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fail_groq))
        ),
    )
    monkeypatch.setattr(
        first_llm_call,
        "chat",
        lambda **kwargs: SimpleNamespace(message=SimpleNamespace(content=expected)),
    )

    assert first_llm_call.generate_response([]) == expected
    assert "falling back to Ollama" in capsys.readouterr().err


def test_uses_ollama_when_api_key_is_unset(monkeypatch, capsys):
    expected = "Local answer"
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(
        first_llm_call,
        "chat",
        lambda **kwargs: SimpleNamespace(message=SimpleNamespace(content=expected)),
    )

    assert first_llm_call.generate_response([]) == expected
    assert "GROQ_API_KEY is unset" in capsys.readouterr().err
