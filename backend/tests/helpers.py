"""Shared helpers for the eval scenarios. Everything goes through the real HTTP API and the real database."""
import datetime
import json
from typing import Any, Dict, Optional

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.models import Booking, Order, Product, Service

PASSWORD = "Password123!"

# Seed identities. Ids are from initial_records.json.
AAYUSH = ("aayush@himali.test", "org_a")   # customer with past orders ORD-1001 (confirmed), ORD-1002 (delivered)
PRIYA = ("priya@himali.test", "org_a")     # customer with a pending order ORD-1003
KIRAN = ("kiran@himali.test", "org_a")     # customer with no orders
ADMIN_A = ("admin@himali.test", "org_a")
ROHAN = ("rohan@lotus.test", "org_b")      # past booking BKG-2001 and upcoming BKG-2003 with prac_2
SITA = ("sita@lotus.test", "org_b")        # past booking BKG-2002
BIKASH = ("bikash@lotus.test", "org_b")    # no bookings
ADMIN_B = ("admin@lotus.test", "org_b")


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def login(c: AsyncClient, who: tuple) -> Dict[str, str]:
    email, org = who
    res = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD, "org_id": org})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def new_conversation(c: AsyncClient, headers: Dict[str, str], agent_type: str = "customer") -> str:
    res = await c.post("/api/chat/conversations", headers=headers, json={"title": "New Chat", "agent_type": agent_type})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def parse_sse(body: str) -> Dict[str, Any]:
    """Turn a server-sent-events body into text, tool activity, citations, the card and the raw events."""
    events = []
    for block in body.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if name:
            events.append((name, json.loads(data) if data else None))
    text = "".join(d["token"] for n, d in events if n == "token")
    done = next((d for n, d in reversed(events) if n == "done"), {}) or {}
    return {
        "text": text or done.get("content", ""),
        "tools": [d["tool"] for n, d in events if n == "tool_start" and d["tool"] != "thinking"],
        "citations": done.get("citations") or [],
        "card": done.get("card"),
        "events": events,
        "done": done,
    }


async def chat(c: AsyncClient, headers: Dict[str, str], conv_id: str, text: str) -> Dict[str, Any]:
    res = await c.post(f"/api/chat/conversations/{conv_id}/messages", headers=headers, json={"content": text})
    assert res.status_code == 200, res.text
    return parse_sse(res.text)


async def ask(who: tuple, text: str, conv_id: Optional[str] = None) -> Dict[str, Any]:
    """Sign in as `who`, send one chat message in a fresh conversation, and return the parsed reply."""
    async with client() as c:
        headers = await login(c, who)
        conv = conv_id or await new_conversation(c, headers)
        reply = await chat(c, headers, conv, text)
        reply["conv_id"] = conv
        return reply


async def confirm(c: AsyncClient, headers: Dict[str, str], proposal_id: str):
    return await c.post(f"/api/actions/proposals/{proposal_id}/confirm", headers=headers)


# ---- database readers ----------------------------------------------------------------------

async def stock_of(sku: str, org_id: str = "org_a") -> int:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Product.stock).where(Product.org_id == org_id, Product.sku == sku))).scalar()


async def set_product(sku: str, org_id: str = "org_a", **fields) -> Dict[str, Any]:
    """Change a product row and return the previous values so the test can put them back."""
    async with AsyncSessionLocal() as s:
        product = (await s.execute(select(Product).where(Product.org_id == org_id, Product.sku == sku))).scalars().first()
        before = {key: getattr(product, key) for key in fields}
        for key, value in fields.items():
            setattr(product, key, value)
        await s.commit()
        return before


async def order_row(order_id: str) -> Optional[Order]:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Order).where(Order.id == order_id))).scalars().first()


async def orders_of(user_id: str) -> list:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Order).where(Order.user_id == user_id).order_by(Order.created_at))).scalars().all()


async def booking_row(booking_id: str) -> Optional[Booking]:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Booking).where(Booking.id == booking_id))).scalars().first()


async def bookings_of(user_id: str) -> list:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Booking).where(Booking.user_id == user_id).order_by(Booking.start_time))).scalars().all()


async def service_row(service_id: str) -> Service:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Service).where(Service.id == service_id))).scalars().first()


def iso_at(day: datetime.date, hour: int, minute: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:{minute:02d}:00"


def scripted_model(monkeypatch, calls, final: str = "Done."):
    """Replace the model with one that asks for the given tool calls, then answers `final`.

    Used to prove the server holds the line when a model misbehaves, which a well-behaved mock cannot show.
    """
    from app.services.llm_provider import LLMProvider, ProviderTurn, ToolCall

    state = {"round": 0}

    async def fake(system, messages, tools):
        if state["round"] == 0:
            state["round"] += 1
            yield {"type": "turn", "text": "", "turn": ProviderTurn(
                tool_calls=[ToolCall(id=f"call_{i}", name=name, args=args) for i, (name, args) in enumerate(calls)])}
        else:
            yield {"type": "token", "token": final}
            yield {"type": "turn", "text": final, "turn": ProviderTurn(text=final)}

    monkeypatch.setattr(LLMProvider, "stream_events", staticmethod(fake))
