"""A reply must never send the customer to a Confirm button that does not exist."""
import pytest

from app.services.agent_loop import _NO_CARD_FALLBACK
from app.services.llm_provider import LLMProvider, ProviderTurn, ToolCall
from tests.helpers import KIRAN, ask

CLAIM = "I have prepared your order. Please press the Confirm Order button on the card to complete it."


def _script(monkeypatch, rounds):
    """Replace the model with a fixed list of replies, one per call: (text, tool_calls)."""
    calls = iter(rounds)

    async def fake(system, messages, tools):
        text, tool_calls = next(calls)
        if text:
            yield {"type": "token", "token": text}
        yield {"type": "turn", "turn": ProviderTurn(text=text, tool_calls=tool_calls)}

    monkeypatch.setattr(LLMProvider, "stream_events", staticmethod(fake))


@pytest.mark.asyncio
async def test_a_confirm_claim_with_no_proposal_is_retried_then_replaced_by_an_honest_message(monkeypatch):
    _script(monkeypatch, [(CLAIM, []), (CLAIM, [])])
    reply = await ask(KIRAN, "I'd like 1 Golden Tippy, deliver to Lazimpat")
    assert reply["card"] is None
    assert reply["text"].endswith(_NO_CARD_FALLBACK)
    assert [name for name, _ in reply["events"]].count("reset") == 2


@pytest.mark.asyncio
async def test_a_confirm_claim_is_retried_and_the_second_try_stages_a_real_card(monkeypatch):
    order = ToolCall(id="c1", name="create_order", args={"items": [{"sku": "HT-WP-100", "quantity": 1}], "shipping_address": "Test Road 1"})
    _script(monkeypatch, [(CLAIM, []), ("", [order]), ("Please review the card and press Confirm Order.", [])])
    reply = await ask(KIRAN, "I'd like 1 White Peony, deliver to Test Road 1")
    assert reply["card"] and reply["card"]["proposal_id"]
    assert [name for name, _ in reply["events"]].count("reset") == 1
