"""The switchable chat providers. Mistral, Groq and Ollama share one OpenAI-compatible client; these tests
drive it through a fake HTTP transport, so they need no API key, no network and no quota."""
import json

import httpx
import pytest

from app.core.config import settings
from app.services import llm_provider as lp
from app.services.llm_provider import ChatMessage, LLMError, LLMProvider, ToolCall

TOOLS = [{"name": "search_products", "description": "x", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]


def sse(*chunks) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


REAL_CLIENT = httpx.AsyncClient  # captured once, so installing a fake twice never wraps a fake


def install(monkeypatch, handler):
    monkeypatch.setattr(lp.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


async def collect(provider: str, messages=None):
    events = []
    async for event in lp._openai_compat_stream(provider, "system prompt", messages or [ChatMessage(role="user", content="tea?")], TOOLS):
        events.append(event)
    return events


async def test_groq_request_shape_and_a_tool_call_streamed_in_pieces(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers.get("authorization"), json.loads(request.content)
        return httpx.Response(200, content=sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "function": {"name": "search_products", "arguments": '{"que'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ry": "green"}'}}]}}]},
        ))

    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    install(monkeypatch, handler)
    history = [
        ChatMessage(role="user", content="green tea?"),
        ChatMessage(role="model", content="", tool_calls=[ToolCall(id="c1", name="search_products", args={"query": "green"})]),
        ChatMessage(role="tool", content='{"count": 1}', tool_name="search_products", tool_call_id="c1"),
    ]
    events = await collect("groq", history)

    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions" and seen["auth"] == "Bearer gsk_test"
    assert seen["body"]["model"] == settings.GROQ_MODEL and seen["body"]["stream"] is True
    assert seen["body"]["tools"][0]["function"]["name"] == "search_products"
    tool_result = seen["body"]["messages"][-1]
    assert tool_result["role"] == "tool" and tool_result["tool_call_id"] == "c1" and "name" not in tool_result
    assistant = seen["body"]["messages"][-2]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "green"}

    turn = events[-1]["turn"]
    assert [(c.id, c.name, c.args) for c in turn.tool_calls] == [("call_9", "search_products", {"query": "green"})]


async def test_streamed_text_arrives_token_by_token(monkeypatch):
    install(monkeypatch, lambda r: httpx.Response(200, content=sse(
        {"choices": [{"delta": {"content": "Hello "}}]}, {"choices": [{"delta": {"content": "tea lover"}}]})))
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    events = await collect("groq")
    assert [e["token"] for e in events if e["type"] == "token"] == ["Hello ", "tea lover"]
    assert events[-1]["turn"].text == "Hello tea lover" and events[-1]["turn"].tool_calls == []


async def test_mistral_still_sends_a_name_on_tool_results(monkeypatch):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "ok"}}]}))

    monkeypatch.setattr(settings, "MISTRAL_API_KEY", "m_test")
    install(monkeypatch, handler)
    await collect("mistral", [ChatMessage(role="tool", content="{}", tool_name="list_my_orders", tool_call_id="c2")])
    assert seen["body"]["messages"][-1]["name"] == "list_my_orders"


async def test_ollama_needs_no_key_and_points_at_the_local_server(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "hi"}}]}))

    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    install(monkeypatch, handler)
    await collect("ollama")
    assert seen["url"] == "http://localhost:11434/v1/chat/completions" and seen["auth"] is None


async def test_failures_become_plain_messages_not_stack_traces(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    for status, fragment in ((429, "rate limiting"), (401, "rejected the API key"), (500, r"API error \(500\)")):
        install(monkeypatch, lambda r, s=status: httpx.Response(s, content=b'{"error": "x"}'))
        with pytest.raises(LLMError, match=fragment):
            await collect("groq")

    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    with pytest.raises(LLMError, match="GROQ_API_KEY is not configured"):
        await collect("groq")

    def refuse(request):
        raise httpx.ConnectError("refused")

    install(monkeypatch, refuse)
    with pytest.raises(LLMError, match="Is Ollama running"):
        await collect("ollama")


async def test_the_provider_is_chosen_by_one_setting(monkeypatch):
    chosen = []

    async def fake(provider, system, messages, tools):
        chosen.append(provider)
        yield {"type": "turn", "text": "", "turn": lp.ProviderTurn()}

    monkeypatch.setattr(lp, "_openai_compat_stream", fake)
    for name in ("mistral", "groq", "ollama"):
        monkeypatch.setattr(settings, "LLM_PROVIDER", name)
        async for _ in LLMProvider.stream_events("s", [], []):
            pass
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    assert chosen == ["mistral", "groq", "ollama"]
