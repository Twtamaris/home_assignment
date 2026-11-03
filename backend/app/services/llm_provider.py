"""
Switchable chat providers.

Gemini uses the official google-genai SDK. Tool-call turns replay the SDK's
original model Content, including function-call ids and thought signatures.
Rebuilding a call from only the name and arguments is rejected by Gemini 3.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.config import settings

log = logging.getLogger("uvicorn.error")


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class ProviderTurn:
    """One model turn. gemini_content is the untouched SDK object when present."""
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    gemini_content: Any = None
    mistral_message: Optional[Dict[str, Any]] = None


@dataclass
class ChatMessage:
    """Neutral history item. Provider-specific payloads are kept for replay."""
    role: str  # user, model, tool
    content: str = ""
    gemini_content: Any = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    tool_name: str = ""
    mistral_message: Optional[Dict[str, Any]] = None


class LLMError(RuntimeError):
    pass


_working_model = ""
_exhausted_models: set[str] = set()
_FALLBACK_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class LLMProvider:
    @staticmethod
    async def complete(
        system_instruction: str,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> ProviderTurn:
        turn = ProviderTurn()
        async for event in LLMProvider.stream_events(system_instruction, messages, tools):
            if event["type"] == "token":
                turn.text += event["token"]
            elif event["type"] == "turn":
                turn = event["turn"]
                if not turn.text:
                    turn.text = event.get("text") or turn.text
        return turn

    @staticmethod
    async def stream_final(
        system_instruction: str,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """Stream the natural-language answer. Write tools must not be passed here."""
        async for event in LLMProvider.stream_events(system_instruction, messages, tools or []):
            if event["type"] == "token" and event.get("token"):
                yield event["token"]

    @staticmethod
    async def stream_events(
        system_instruction: str,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        provider = settings.LLM_PROVIDER
        if provider == "gemini":
            async for event in _gemini_stream(system_instruction, messages, tools):
                yield event
        elif provider in ("mistral", "groq", "ollama"):
            async for event in _openai_compat_stream(provider, system_instruction, messages, tools):
                yield event
        elif provider == "mock":
            async for event in _mock_stream(messages, tools):
                yield event
        else:
            raise LLMError(f"Unknown LLM_PROVIDER '{provider}'.")


def _require_gemini():
    if not settings.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not configured.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise LLMError("The google-genai package is not installed.") from exc
    return genai, types


def _gemini_schema(types, spec: Dict[str, Any]):
    schema_type = {
        "string": types.Type.STRING,
        "number": types.Type.NUMBER,
        "integer": types.Type.INTEGER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }.get(spec.get("type"), types.Type.STRING)
    kwargs: Dict[str, Any] = {"type": schema_type, "description": spec.get("description", "")}
    if schema_type == types.Type.ARRAY:
        kwargs["items"] = _gemini_schema(types, spec.get("items") or {"type": "string"})
    if schema_type == types.Type.OBJECT:
        kwargs["properties"] = {
            name: _gemini_schema(types, child)
            for name, child in (spec.get("properties") or {}).items()
        }
        if spec.get("required"):
            kwargs["required"] = spec["required"]
    return types.Schema(**kwargs)


def _gemini_declarations(types, tools: List[Dict[str, Any]]):
    declarations = []
    for tool in tools:
        params = tool.get("parameters") or {"type": "object", "properties": {}}
        properties = {
            name: _gemini_schema(types, spec)
            for name, spec in (params.get("properties") or {}).items()
        }
        declarations.append(types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties=properties,
                required=params.get("required") or [],
            ),
        ))
    return declarations


def _gemini_contents(types, messages: List[ChatMessage]):
    contents = []
    for message in messages:
        if message.gemini_content is not None:
            contents.append(message.gemini_content)
            continue
        if message.role == "tool":
            response_payload = {}
            try:
                response_payload = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                response_payload = {"result": message.content}
            part_kwargs = {
                "function_response": types.FunctionResponse(
                    name=message.tool_name or "tool",
                    response=_jsonable(response_payload) if isinstance(response_payload, dict) else {"result": message.content},
                )
            }
            if message.tool_call_id and hasattr(types.FunctionResponse, "model_fields") and "id" in types.FunctionResponse.model_fields:
                part_kwargs["function_response"] = types.FunctionResponse(
                    id=message.tool_call_id,
                    name=message.tool_name or "tool",
                    response=part_kwargs["function_response"].response,
                )
            contents.append(types.Content(role="user", parts=[types.Part(**part_kwargs)]))
            continue
        role = "model" if message.role == "model" else "user"
        contents.append(types.Content(
            role=role,
            parts=[types.Part(text=message.content or "")],
        ))
    return contents


def _retryable_gemini(exc: Exception) -> bool:
    message = str(exc)
    return isinstance(exc, TimeoutError) or any(
        token in message for token in ("503", "504", "UNAVAILABLE", "DEADLINE", "429", "RESOURCE_EXHAUSTED")
    )


def _gemini_failure(exc: Exception) -> LLMError:
    """TimeoutError from the client has an empty message. Never show a blank failure."""
    message = str(exc).strip()
    if "per day" in message or "PerDay" in message:
        return LLMError("The Gemini free-tier daily limit is used up for the models that were available. Please try again tomorrow.")
    if isinstance(exc, TimeoutError) or not message or "504" in message or "DEADLINE" in message:
        return LLMError("Gemini timed out before answering. Please try again.")
    if "503" in message or "UNAVAILABLE" in message:
        return LLMError("Gemini is temporarily unavailable. Please try again in a moment.")
    if "429" in message or "RESOURCE_EXHAUSTED" in message:
        return LLMError("The Gemini free tier is rate limiting requests. Wait a moment and try again.")
    return LLMError(f"Gemini request failed: {message}")


def _events_from_gemini_response(response):
    candidates = getattr(response, "candidates", None) or []
    content = candidates[0].content if candidates and getattr(candidates[0], "content", None) else None
    if content is None:
        feedback = getattr(response, "prompt_feedback", None)
        raise LLMError(f"Gemini returned no answer. {feedback or ''}".strip())
    tool_calls: List[ToolCall] = []
    text_parts: List[str] = []
    for part in content.parts or []:
        function_call = getattr(part, "function_call", None)
        if function_call and getattr(function_call, "name", None):
            call_id = getattr(function_call, "id", None) or f"call_{len(tool_calls) + 1}"
            tool_calls.append(ToolCall(id=str(call_id), name=function_call.name, args=dict(function_call.args or {})))
        elif getattr(part, "text", None):
            text_parts.append(part.text)
    text = "".join(text_parts)
    # Tool selection returns the whole response at once. The final answer uses
    # generate_content_stream instead, so those words are not sliced up here.
    yield {
        "type": "turn",
        "text": text,
        "turn": ProviderTurn(text=text, tool_calls=tool_calls, gemini_content=content),
    }


async def _gemini_stream(system_instruction, messages, tools):
    genai, types = _require_gemini()
    client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={"timeout": 25000})
    config_kwargs = {
        "system_instruction": system_instruction,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        "temperature": 0.2,
    }
    declarations = _gemini_declarations(types, tools)
    if declarations:
        config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
    config = types.GenerateContentConfig(**config_kwargs)
    contents = _gemini_contents(types, messages)

    models = _model_order()

    last_error: Exception | None = None
    for model in models:
        started = time.perf_counter()
        log.info("gemini request model=%s tools=%s", model, [tool.get("name") for tool in tools])
        sent = False
        try:
            async for event in _gemini_text_stream(client, types, model, contents, config):
                if event["type"] == "token":
                    sent = True
                if event["type"] == "turn":
                    names = [call.name for call in event["turn"].tool_calls]
                    log.info(
                        "gemini response model=%s seconds=%.1f tools=%s chars=%s",
                        model, time.perf_counter() - started, names, len(event.get("text") or ""),
                    )
                yield event
            _remember_model(model)
            return
        except LLMError:
            raise
        except Exception as exc:
            last_error = exc
            log.warning("gemini failed model=%s seconds=%.1f error=%s", model, time.perf_counter() - started, exc)
            if _daily_quota(exc):
                _exhausted_models.add(model)
            if (_retryable_gemini(exc) or _daily_quota(exc)) and not sent:
                continue
            raise _gemini_failure(exc) from exc
    raise _gemini_failure(last_error or TimeoutError())


def _daily_quota(exc: Exception) -> bool:
    message = str(exc)
    return "per day" in message or "PerDay" in message


def _model_order() -> List[str]:
    names = []
    if _working_model:
        names.append(_working_model)
    names.append(settings.GEMINI_MODEL)
    names.extend(_FALLBACK_MODELS)
    ordered = []
    for name in names:
        if name and name not in ordered and name not in _exhausted_models:
            ordered.append(name)
    return ordered or [settings.GEMINI_MODEL]


def _remember_model(model: str) -> None:
    global _working_model
    _working_model = model


async def _gemini_text_stream(client, types, model, contents, config):
    """Yield text as Gemini produces it. The original parts are kept for the thought signature."""
    collected_parts = []
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    stream = await asyncio.wait_for(
        client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ),
        timeout=25,
    )
    async with asyncio.timeout(30):
        async for chunk in stream:
            candidates = getattr(chunk, "candidates", None) or []
            if not candidates or not getattr(candidates[0], "content", None):
                continue
            for part in candidates[0].content.parts or []:
                collected_parts.append(part)
                function_call = getattr(part, "function_call", None)
                if function_call and getattr(function_call, "name", None):
                    call_id = getattr(function_call, "id", None) or f"call_{len(tool_calls) + 1}"
                    tool_calls.append(ToolCall(
                        id=str(call_id), name=function_call.name, args=dict(function_call.args or {}),
                    ))
                elif getattr(part, "text", None):
                    text_parts.append(part.text)
                    words = part.text.split(" ")
                    log.info("gemini text chunk chars=%s words=%s", len(part.text), len(words))
                    # Gemini often returns a short answer as one chunk. Yield each word
                    # and give the event loop a turn so the browser can paint it.
                    for index, word in enumerate(words):
                        piece = word if index == len(words) - 1 else word + " "
                        yield {"type": "token", "token": piece}
                        if len(words) > 1:
                            await asyncio.sleep(0.03)
    if not collected_parts:
        raise LLMError("Gemini returned no answer.")
    text = "".join(text_parts)
    yield {
        "type": "turn",
        "text": text,
        "turn": ProviderTurn(
            text=text,
            tool_calls=tool_calls,
            gemini_content=types.Content(role="model", parts=collected_parts),
        ),
    }


def _mistral_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    converted = []
    for tool in tools:
        converted.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return converted


@dataclass
class _Endpoint:
    """One OpenAI-compatible chat-completions service. Mistral, Groq and a local Ollama all speak this protocol."""
    label: str
    url: str
    api_key: str
    model: str
    needs_key: bool = True
    tool_message_name: bool = False  # Mistral wants a name on tool results; the others do not accept it
    timeout: float = 45.0


def _endpoint(provider: str) -> _Endpoint:
    if provider == "mistral":
        return _Endpoint("Mistral", "https://api.mistral.ai/v1/chat/completions", settings.MISTRAL_API_KEY,
                         settings.MISTRAL_MODEL, tool_message_name=True)
    if provider == "groq":
        return _Endpoint("Groq", "https://api.groq.com/openai/v1/chat/completions", settings.GROQ_API_KEY, settings.GROQ_MODEL)
    if provider == "ollama":
        base = settings.OLLAMA_BASE_URL.rstrip("/")
        return _Endpoint("Ollama", f"{base}/chat/completions", "", settings.OLLAMA_MODEL, needs_key=False, timeout=180.0)
    raise LLMError(f"Unknown LLM_PROVIDER '{provider}'.")


def _mistral_messages(system_instruction: str, messages: List[ChatMessage], tool_message_name: bool = True) -> List[Dict[str, Any]]:
    formatted = [{"role": "system", "content": system_instruction}]
    for message in messages:
        if message.mistral_message:
            formatted.append(message.mistral_message)
            continue
        if message.role == "tool":
            entry = {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            if tool_message_name:
                entry["name"] = message.tool_name
            formatted.append(entry)
        elif message.role == "model":
            entry: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.args)},
                    }
                    for call in message.tool_calls
                ]
            formatted.append(entry)
        else:
            formatted.append({"role": "user", "content": message.content or ""})
    return formatted


def _openai_failure(endpoint: _Endpoint, status: int, body: str) -> LLMError:
    if status == 429:
        return LLMError(f"{endpoint.label} is rate limiting requests on the free tier. Wait a moment and try again.")
    if status in (401, 403):
        return LLMError(f"{endpoint.label} rejected the API key. Check the key in .env.")
    return LLMError(f"{endpoint.label} API error ({status}): {body[:300]}")


async def _openai_compat_stream(provider: str, system_instruction, messages, tools):
    endpoint = _endpoint(provider)
    if endpoint.needs_key and not endpoint.api_key:
        raise LLMError(f"{provider.upper()}_API_KEY is not configured. Set it in .env, or choose another LLM_PROVIDER.")
    payload: Dict[str, Any] = {
        "model": endpoint.model,
        "messages": _mistral_messages(system_instruction, messages, endpoint.tool_message_name),
        "stream": True,
    }
    if tools:
        payload["tools"] = _mistral_tools(tools)
        payload["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    text_parts: List[str] = []
    tool_acc: Dict[int, Dict[str, str]] = {}
    try:
        async with httpx.AsyncClient(timeout=endpoint.timeout) as client:
            async with client.stream("POST", endpoint.url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise _openai_failure(endpoint, response.status_code, body)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        yield {"type": "token", "token": delta["content"]}
                    for call in delta.get("tool_calls") or []:
                        index = call.get("index", 0)
                        bucket = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if call.get("id"):
                            bucket["id"] = call["id"]
                        function = call.get("function") or {}
                        if function.get("name"):
                            bucket["name"] += function["name"]
                        if function.get("arguments"):
                            bucket["arguments"] += function["arguments"] if isinstance(function["arguments"], str) else json.dumps(function["arguments"])
    except httpx.ConnectError as exc:
        hint = " Is Ollama running (`ollama serve`)?" if provider == "ollama" else ""
        raise LLMError(f"Could not reach {endpoint.label}.{hint}") from exc
    except httpx.TimeoutException as exc:
        raise LLMError(f"{endpoint.label} timed out before answering. Please try again.") from exc

    tool_calls = []
    for index in sorted(tool_acc):
        bucket = tool_acc[index]
        try:
            args = json.loads(bucket["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(ToolCall(
            id=bucket["id"] or f"call_{index}",
            name=bucket["name"],
            args=args if isinstance(args, dict) else {},
        ))
    assistant_message = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        assistant_message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.args)},
            }
            for call in tool_calls
        ]
    yield {
        "type": "turn",
        "text": "".join(text_parts),
        "turn": ProviderTurn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            mistral_message=assistant_message,
        ),
    }


# ---------------------------------------------------------------------------
# Mock provider: a deterministic rule-based stand-in used for offline evals and demos.
# It is NOT a language model. It extracts explicit ids from the message (SKUs, order and
# booking ids, srv_/prac_ ids, ISO times) and calls the matching tool, then phrases the
# reply from the tool result. That lets the whole chat -> tool -> confirmation -> database
# path run in CI without network access or API keys.
# ---------------------------------------------------------------------------
_SKU = re.compile(r"\b([A-Za-z]{2,4}-[A-Za-z]{2,4}-\d{2,3})\b")
_ORDER_ID = re.compile(r"\b(ORD-[A-Za-z0-9]+)\b", re.I)
_BOOKING_ID = re.compile(r"\b(BKG-[A-Za-z0-9]+)\b", re.I)
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2})?)?)")
_RELATIVE = re.compile(
    r"\b(day after tomorrow|tomorrow|today|next week|(?:next |this )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"(?: (?:morning|afternoon|evening))?)\b", re.I)
_KNOWLEDGE = re.compile(
    r"\b(policy|policies|faq|brew|brewing|steep|shipping|delivery|deliver|return|returns|refund|how (?:do|to|long|should|many)|"
    r"why|organic|origin|about|bio|practitioner|who is|what is your|do you offer|parking|insurance|late|cancellation)\b", re.I)
_PRODUCT = re.compile(r"\b(price|cost|stock|have|sell|tea|teas|teaware|gaiwan|teapot|available|buy|show|list|catalog|under|below|oolong|green|black|white|herbal)\b", re.I)


def _quantity_for(text: str, sku: str, default: int = 1) -> int:
    pattern = re.compile(rf"(?:(-?\d+)\s*(?:x|×|of|units? of)?\s*{re.escape(sku)})|(?:{re.escape(sku)}\s*(?:x|×)\s*(-?\d+))", re.I)
    match = pattern.search(text)
    if not match:
        return default
    return int(match.group(1) or match.group(2))


def _mock_intent(text: str, tool_names: set) -> Optional[ToolCall]:
    lowered = text.lower()
    order_match = _ORDER_ID.search(text)
    order_id = order_match.group(1).upper() if order_match else None
    booking_match = _BOOKING_ID.search(text)
    booking_id = booking_match.group(1).upper() if booking_match else None
    skus: List[tuple] = []
    for match in _SKU.finditer(text):
        sku = match.group(1).upper()
        if sku not in [s for s, _ in skus]:
            skus.append((sku, _quantity_for(text, match.group(1))))
    iso = _ISO.findall(text)
    srv = re.search(r"\b(srv_\d+)\b", lowered)
    prac = re.search(r"\b(prac_\d+)\b", lowered)

    def call(name: str, args: Dict[str, Any]) -> ToolCall:
        return ToolCall(id="mock_1", name=name, args=args)

    if "get_activity_summary" in tool_names:  # admin analytics
        if re.search(r"\b(delete|remove|drop|wipe|cancel|create|update|change|place)\b", lowered):
            return None  # a write request: there is no tool for it, so the stub answers that it is read-only
        if re.search(r"\b(practitioner|practitioners|utilisation|utilization)\b", lowered):
            return call("get_activity_summary", {})
        if re.search(r"\b(conversion|convert)\b", lowered) and "get_conversion_rate" in tool_names:
            return call("get_conversion_rate", {})
        if re.search(r"\b(top|best|busiest|popular|most|out of stock)\b", lowered) and "get_top_items" in tool_names:
            return call("get_top_items", {})
        if re.search(r"\b(new clients|clients|sign.?ups?|chatted)\b", lowered) and "get_clients_today" in tool_names:
            return call("get_clients_today", {})
        days = re.search(r"\b(\d{1,3})\s*days?\b", lowered)
        return call("get_activity_summary", {"days": int(days.group(1))} if days else {})

    if "create_order" in tool_names:  # retail
        if order_id and re.search(r"\bcancel", lowered) and "cancel_order" in tool_names:
            return call("cancel_order", {"order_id": order_id})
        if order_id and re.search(r"\b(change|edit|update|modify|move|deliver)", lowered) and "update_order" in tool_names:
            args: Dict[str, Any] = {"order_id": order_id}
            if skus:
                args["items"] = [{"sku": s, "quantity": q} for s, q in skus]
            address = re.search(r"\b(?:to|address(?: to)?)\s+([A-Z][\w ,.\-]{3,60})$", text.strip())
            if address:
                args["shipping_address"] = address.group(1).strip()
            return call("update_order", args)
        if order_id and "get_order_status" in tool_names:
            return call("get_order_status", {"order_id": order_id})
        if re.search(r"\b(same as last time|reorder|re-order|order again|usual)\b", lowered):
            return call("reorder", {})
        if skus and re.search(r"\b(order|buy|purchase|get|want|add)\b", lowered):
            address = re.search(r"\b(?:deliver(?:ed)? to|ship(?:ped)? to|address[: ]+)\s*([A-Z][\w ,.\-]{3,60})$", text.strip())
            args = {"items": [{"sku": s, "quantity": q} for s, q in skus]}
            if address:
                args["shipping_address"] = address.group(1).strip()
            return call("create_order", args)
        if re.search(r"\b(my orders|past orders|order history|list orders|where is my order|track)\b", lowered):
            return call("list_my_orders", {})
        if _KNOWLEDGE.search(text) and not re.search(r"\b(price|cost|stock)\b", lowered):
            return call("search_knowledge", {"query": text})
        if _PRODUCT.search(text) or skus:
            args = {"query": text}
            under = re.search(r"\b(?:under|below|less than)\s*(?:npr|rs\.?)?\s*(\d+)", lowered)
            if under:
                args = {"query": re.sub(r"\b(?:under|below|less than)\s*(?:npr|rs\.?)?\s*\d+", "", text), "max_price": int(under.group(1))}
            return call("search_products", args)
        return call("search_knowledge", {"query": text}) if len(text.split()) > 3 else None

    if "find_available_slots" in tool_names:  # studio
        if booking_id and re.search(r"\bcancel", lowered):
            return call("cancel_booking", {"booking_id": booking_id})
        if booking_id and re.search(r"\b(reschedule|move|change|shift)\b", lowered) and iso:
            return call("reschedule_booking", {"booking_id": booking_id, "new_start_time": iso[-1]})
        if srv and prac and iso and re.search(r"\b(book|reserve|schedule|appointment)\b", lowered):
            return call("create_booking", {"service_id": srv.group(1), "practitioner_id": prac.group(1), "start_time": iso[-1]})
        if re.search(r"\b(my bookings|my appointments|upcoming|past bookings)\b", lowered):
            return call("list_my_bookings", {})
        if srv and (iso or _RELATIVE.search(text)) and re.search(r"\b(slot|slots|free|available|availability|times?|when)\b", lowered):
            args = {"service_id": srv.group(1), "date": iso[0].split("T")[0].split(" ")[0] if iso else _RELATIVE.search(text).group(1)}
            if prac:
                args["practitioner_id"] = prac.group(1)
            part = re.search(r"\b(morning|afternoon|evening)\b", lowered)
            if part:
                args["part_of_day"] = part.group(1)
            return call("find_available_slots", args)
        if re.search(r"\b(hours|open|opening|holiday|holidays|closed|close)\b", lowered):
            return call("get_opening_hours", {})
        if _KNOWLEDGE.search(text) and not re.search(r"\b(price|cost)\b", lowered):
            return call("search_knowledge", {"query": text})
        if re.search(r"\b(services?|price|prices|cost|duration|massage|physio|yoga|therapy|treatment)\b", lowered):
            return call("list_services", {})
        return call("search_knowledge", {"query": text}) if len(text.split()) > 3 else None
    return None


def _mock_sentence(payload: Dict[str, Any], tool_name: str) -> str:
    """Phrase the final reply from the tool result, using only what the tool returned."""
    if not isinstance(payload, dict):
        return "Here is what the tool returned."
    if payload.get("proposal_id") and payload.get("success", True):
        return payload.get("summary_text") or "Please confirm the proposal on the card. Nothing has been saved yet."
    if payload.get("success") is False:
        reason = payload.get("message") or payload.get("error") or "That could not be done."
        alternatives = payload.get("suggested_alternatives") or []
        if alternatives:
            names = "; ".join(
                a.get("formatted") or f"{a.get('name')} (NPR {a.get('price')}, {a.get('stock')} in stock)"
                for a in alternatives[:3]
            )
            return f"{reason} Nearest alternatives: {names}."
        return str(reason)
    if tool_name == "search_knowledge":
        if not payload.get("results"):
            return "I don't have that information in the knowledge base."
        top = payload["results"][0]
        body = " ".join(line for line in (top.get("content") or "").splitlines() if not line.startswith("#")).strip()
        return f"{body} (Source: {top.get('doc_name')} > {top.get('section_name')})"
    if tool_name == "search_products":
        rows = payload.get("products") or []
        if not rows:
            return "No matching products."
        return "Matching products: " + "; ".join(
            f"{r['name']} ({r['sku']}) NPR {r['price']:.0f}, {r['stock']} in stock" for r in rows[:6]
        ) + "."
    if tool_name == "get_order_status":
        history = ", ".join(h["new_status"] for h in payload.get("status_history", []))
        return f"Order {payload['order_id']} is {payload['status']}. Total NPR {payload['total_price']:.2f}. History: {history}."
    if tool_name == "list_my_orders":
        rows = payload.get("orders") or []
        return "You have no orders yet." if not rows else "Your orders, newest first: " + "; ".join(
            f"{r['order_id']} {r['status']} NPR {r['total_price']:.2f}" for r in rows
        ) + "."
    if tool_name == "list_services":
        return "Services: " + "; ".join(
            f"{s['name']} ({s['id']}), {s['duration_minutes']} min, NPR {s['price']:.0f}" for s in payload["services"]
        ) + "."
    if tool_name == "get_opening_hours":
        hours = "; ".join(f"{d}: {h}" for d, h in payload["weekly_hours"].items())
        holidays = "; ".join(f"{h['date']} {h['name']}" for h in payload["upcoming_holidays"]) or "none"
        return f"Opening hours ({payload['timezone']}): {hours}. Upcoming holidays: {holidays}."
    if tool_name == "find_available_slots":
        slots = payload.get("slots") or []
        if not slots:
            return payload.get("message") or "No free slots."
        return f"Free slots on {payload['date']} ({payload['timezone']}): " + "; ".join(s["formatted"] for s in slots[:6]) + "."
    if tool_name == "list_my_bookings":
        rows = payload.get("bookings") or []
        return "You have no bookings yet." if not rows else "Your bookings: " + "; ".join(
            f"{r['booking_id']} {r['service_name']} with {r['practitioner_name']}, {r['formatted_time']} ({r['status']})"
            for r in rows
        ) + "."
    if tool_name in {"get_activity_summary", "get_clients_today", "get_conversion_rate", "get_top_items"}:
        window = payload.get("time_window") or payload.get("date") or ""
        keys = ("best_selling_products", "low_or_out_of_stock_items", "most_booked_services", "busiest_time_slots")
        data = payload.get("metrics") or {k: v for k, v in payload.items() if k in keys}
        return f"Window: {window}. Definition: {payload.get('definition')} Figures: {json.dumps(data, default=str)}"
    return "Done."


async def _mock_words(sentence: str):
    """Stream a sentence word by word, pausing between words when MOCK_TOKEN_DELAY_MS is set."""
    words = sentence.split(" ")
    for index, word in enumerate(words):
        yield {"type": "token", "token": word + (" " if index < len(words) - 1 else "")}
        if settings.MOCK_TOKEN_DELAY_MS:
            await asyncio.sleep(settings.MOCK_TOKEN_DELAY_MS / 1000)


async def _mock_stream(messages: List[ChatMessage], tools: List[Dict[str, Any]]):
    """Deterministic stand-in. It is not a language model."""
    tool_names = {tool["name"] for tool in tools}
    last_user = ""
    for message in reversed(messages):
        if message.role == "user" and message.content and not message.content.startswith("Untrusted customer memory"):
            last_user = message.content
            break
    last_tool = next((message for message in reversed(messages) if message.role == "tool"), None)
    if last_tool is not None:
        try:
            payload = json.loads(last_tool.content or "{}")
        except json.JSONDecodeError:
            payload = {"result": last_tool.content}
        sentence = _mock_sentence(payload, last_tool.tool_name)
        words = sentence.split(" ")
        async for event in _mock_words(sentence):
            yield event
        yield {"type": "turn", "text": sentence, "turn": ProviderTurn(text=sentence)}
        return

    call = _mock_intent(last_user, tool_names) if tool_names else None
    if call:
        yield {"type": "turn", "text": "", "turn": ProviderTurn(text="", tool_calls=[call])}
        return
    if re.search(r"\b(delete|remove|drop|update|change|create|cancel)\b", last_user.lower()) and "get_activity_summary" in tool_names:
        sentence = "I am a read-only analytics assistant. I cannot create, change or delete records."
    else:
        sentence = "I can help with this organisation's catalog, policies, orders, or bookings. Ask me about one of those."
    async for event in _mock_words(sentence):
        yield event
    yield {"type": "turn", "text": sentence, "turn": ProviderTurn(text=sentence)}
