"""chat_json can turn Nemotron reasoning off, and falls back if the endpoint refuses."""
import types

from src.ai.nebius_client import chat_json


class BadRequestError(Exception):
    pass


def _client(fail_on_extra_body=False):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if fail_on_extra_body and "extra_body" in kwargs:
            raise BadRequestError("unknown parameter")
        msg = types.SimpleNamespace(content='{"facts": []}')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")])

    c = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return c, calls


def test_thinking_off_sends_switch():
    c, calls = _client()
    assert chat_json(c, "m", "s", "u", thinking=False) == {"facts": []}
    assert calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_thinking_on_by_default():
    c, calls = _client()
    chat_json(c, "m", "s", "u")
    assert "extra_body" not in calls[0]


def test_falls_back_when_switch_refused():
    c, calls = _client(fail_on_extra_body=True)
    assert chat_json(c, "m", "s", "u", thinking=False) == {"facts": []}
    assert len(calls) == 2 and "extra_body" not in calls[1]
