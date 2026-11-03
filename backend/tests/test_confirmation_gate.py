"""Confirmation gate, tenant login, migration, and retrieval fallback."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text

from app.core.config import Settings, settings
from app.core.database import AsyncSessionLocal, upgrade_sqlite_schema
from app.core.security import create_access_token
from app.main import app
from app.models.models import Order, Product, User
from app.services.actions_service import ActionService
from app.services.agent_a import AgentATools
from app.services.knowledge_base import KnowledgeBaseService
from app.services.llm_provider import ChatMessage, _gemini_contents
from app.services.tool_registry import ADMIN_TOOLS, MUTATION_TOOLS, tools_for


def _token():
    return create_access_token({
        "sub": "user_a1",
        "org_id": "org_a",
        "role": "customer",
        "email": "aayush@himali.test",
        "name": "Aayush Sharma",
    })


@pytest.mark.asyncio
async def test_customer_write_routes_require_a_proposal():
    headers = {"Authorization": f"Bearer {_token()}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        order = await client.post(
            "/api/orders",
            headers=headers,
            json={"items": [{"sku": "HT-SN-100", "quantity": 1}]},
        )
        edit = await client.patch(
            "/api/orders/ORD-1001",
            headers=headers,
            json={"shipping_address": "Thamel"},
        )
        cancel = await client.post("/api/orders/ORD-1001/cancel", headers=headers)
        booking = await client.post(
            "/api/bookings",
            headers=headers,
            json={"service_id": "srv_1", "practitioner_id": "prac_1", "start_time": "2026-11-12T10:00:00"},
        )
        move = await client.post(
            "/api/bookings/BKG-1/reschedule",
            headers=headers,
            json={"new_start_time": "2026-11-12T11:00:00"},
        )
        drop = await client.post("/api/bookings/BKG-1/cancel", headers=headers)
    for response in (order, edit, cancel, booking, move, drop):
        assert response.status_code == 400
        assert "proposals" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_requires_the_organisation_entry_point():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/auth/login", json={"email": "aayush@himali.test", "password": "Password123!"})
        unknown = await client.post(
            "/api/auth/login",
            json={"email": "aayush@himali.test", "password": "Password123!", "org_id": "does-not-exist"},
        )
    assert missing.status_code == 401
    assert unknown.status_code == 401


@pytest.mark.asyncio
async def test_confirm_places_once_and_a_repeat_does_not():
    async with AsyncSessionLocal() as session:
        before = (await session.execute(select(Order).where(Order.user_id == "user_a1"))).scalars().all()
        staged = await AgentATools.prepare_order_summary(
            session, "org_a", "user_a1", [{"sku": "HT-SN-100", "quantity": 1}], "Lazimpat"
        )
    assert staged["success"] is True
    proposal_id = staged["proposal_id"]

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == "user_a1"))).scalars().first()
        first = await ActionService.confirm(session, user, proposal_id)
    assert first["status"] == "confirmed"

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == "user_a1"))).scalars().first()
        with pytest.raises(Exception) as caught:
            await ActionService.confirm(session, user, proposal_id)
    assert getattr(caught.value, "status_code", None) == 400

    async with AsyncSessionLocal() as session:
        after = (await session.execute(select(Order).where(Order.user_id == "user_a1"))).scalars().all()
    assert len(after) == len(before) + 1


@pytest.mark.asyncio
async def test_stale_price_commits_a_replacement_and_does_not_charge_the_old_total():
    async with AsyncSessionLocal() as session:
        product = (await session.execute(
            select(Product).where(Product.org_id == "org_a", Product.sku == "HT-SN-100")
        )).scalars().first()
        original = product.price
        staged = await AgentATools.prepare_order_summary(
            session, "org_a", "user_a1", [{"sku": "HT-SN-100", "quantity": 1}], "Lazimpat"
        )
        product.price = original + 25
        await session.commit()
    proposal_id = staged["proposal_id"]
    try:
        async with AsyncSessionLocal() as session:
            before = (await session.execute(select(Order).where(Order.user_id == "user_a1"))).scalars().all()
            user = (await session.execute(select(User).where(User.id == "user_a1"))).scalars().first()
            result = await ActionService.confirm(session, user, proposal_id)
            after = (await session.execute(select(Order).where(Order.user_id == "user_a1"))).scalars().all()
        assert result["status"] == "stale"
        replacement = result["result"]
        assert replacement["success"] is True
        assert replacement["proposal_id"] != proposal_id
        assert replacement["total_price"] != staged["total_price"]
        assert len(after) == len(before)
    finally:
        async with AsyncSessionLocal() as session:
            product = (await session.execute(
                select(Product).where(Product.org_id == "org_a", Product.sku == "HT-SN-100")
            )).scalars().first()
            product.price = original
            await session.commit()


@pytest.mark.asyncio
async def test_two_sessions_cannot_take_the_last_unit_twice():
    async with AsyncSessionLocal() as session:
        product = (await session.execute(
            select(Product).where(Product.org_id == "org_a", Product.sku == "HT-GT-100")
        )).scalars().first()
        if product is None:
            pytest.skip("HT-GT-100 is not in this database")
        original = product.stock
        product.stock = 2
        await session.commit()
        first = await AgentATools.prepare_order_summary(
            session, "org_a", "user_a1", [{"sku": "HT-GT-100", "quantity": 1}], "Lazimpat"
        )
        second = await AgentATools.prepare_order_summary(
            session, "org_a", "user_a2", [{"sku": "HT-GT-100", "quantity": 1}], "Patan"
        )
        product.stock = 1
        await session.commit()

    async def confirm(proposal_id, user_id):
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.id == user_id))).scalars().first()
            try:
                return await ActionService.confirm(session, user, proposal_id)
            except Exception as exc:
                return exc

    try:
        left, right = await asyncio.gather(
            confirm(first["proposal_id"], "user_a1"),
            confirm(second["proposal_id"], "user_a2"),
        )
        outcomes = []
        for item in (left, right):
            if isinstance(item, dict):
                outcomes.append(item["status"])
            else:
                outcomes.append(f"error:{getattr(item, 'status_code', type(item).__name__)}")
        assert outcomes.count("confirmed") == 1
        assert any(status != "confirmed" for status in outcomes)
        async with AsyncSessionLocal() as session:
            product = (await session.execute(
                select(Product).where(Product.org_id == "org_a", Product.sku == "HT-GT-100")
            )).scalars().first()
            assert product.stock == 0
    finally:
        async with AsyncSessionLocal() as session:
            product = (await session.execute(
                select(Product).where(Product.org_id == "org_a", Product.sku == "HT-GT-100")
            )).scalars().first()
            if product is not None:
                product.stock = original
                await session.commit()


def test_sqlite_migration_is_idempotent_and_keeps_lotus_as_studio(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE organisations (id VARCHAR(50) PRIMARY KEY, slug VARCHAR(80))"
        ))
        conn.execute(text("INSERT INTO organisations (id, slug) VALUES ('org_a', 'himali-tea-house')"))
        conn.execute(text("INSERT INTO organisations (id, slug) VALUES ('org_b', 'lotus-wellness')"))
        upgrade_sqlite_schema(conn)
        upgrade_sqlite_schema(conn)
        rows = conn.execute(text("SELECT slug, agent_kind FROM organisations ORDER BY slug")).fetchall()
    assert list(rows) == [("himali-tea-house", "retail"), ("lotus-wellness", "studio")]


def test_secret_key_cannot_be_blank():
    with pytest.raises(ValidationError):
        Settings(SECRET_KEY="   ")


def test_gemini_history_keeps_the_original_model_content():
    original = {"role": "model", "parts": [{"thoughtSignature": "sig", "functionCall": {"name": "create_order"}}]}
    contents = _gemini_contents(None, [ChatMessage(role="model", content="ignored", gemini_content=original)])
    assert contents == [original]


def test_admin_tools_cannot_mutate():
    names = {tool["name"] for tool in tools_for("retail", is_admin=True)}
    assert names.isdisjoint(MUTATION_TOOLS)
    assert {tool["name"] for tool in ADMIN_TOOLS} == names


@pytest.mark.asyncio
async def test_knowledge_fallback_is_labelled_bm25():
    previous = settings.EMBEDDING_PROVIDER
    settings.EMBEDDING_PROVIDER = "bm25"
    session = AsyncSessionLocal()
    try:
        hits = await KnowledgeBaseService.search_knowledge(session, "org_a", "how to brew silver needle white tea")
    finally:
        settings.EMBEDDING_PROVIDER = previous
        await session.close()
    assert hits
    assert hits[0]["retrieval"] == "bm25"
    assert "brewing" in hits[0]["doc_name"] or "Silver" in hits[0]["section_name"] or "White" in hits[0]["section_name"]


# ---- regression tests for the edit path and for failed confirmations ---------------------------------

async def _place(who_headers, client_, text):
    conv = (await client_.post("/api/chat/conversations", headers=who_headers, json={"title": "t"})).json()["id"]
    reply = (await client_.post(f"/api/chat/conversations/{conv}/messages", headers=who_headers, json={"content": text}))
    from tests.helpers import parse_sse
    return conv, parse_sse(reply.text)


@pytest.mark.asyncio
async def test_a_price_change_while_editing_stages_a_replacement_edit_not_a_second_order():
    from tests.helpers import KIRAN, client, confirm, login, orders_of, set_product

    async with client() as c:
        headers = await login(c, KIRAN)
        _, placed = await _place(headers, c, "Order 1 x HT-WP-100 deliver to Old Road 1")
        order_id = (await confirm(c, headers, placed["card"]["proposal_id"])).json()["result"]["order_id"]
        _, edit = await _place(headers, c, f"Change order {order_id} address to New Road 2")
        before = await orders_of("user_a3")
        original = await set_product("HT-WP-100", price=1400.0)  # the catalogue price moves after the card was shown
        try:
            res = await confirm(c, headers, edit["card"]["proposal_id"])
            assert res.status_code == 200 and res.json()["status"] == "stale"
            replacement = res.json()["result"]
            assert replacement["success"] and replacement["card"]["action"] == "update"
            assert replacement["total_price"] == 1400.0
            assert len(await orders_of("user_a3")) == len(before), "a stale edit must never place a new order"
            async with AsyncSessionLocal() as s:
                from app.models.models import ActionProposal
                staged = (await s.execute(select(ActionProposal).where(ActionProposal.id == replacement["proposal_id"]))).scalars().first()
                assert staged.action_type == "update_order" and staged.status == "pending"
            final = await confirm(c, headers, replacement["proposal_id"])
            assert final.status_code == 200
        finally:
            await set_product("HT-WP-100", **original)
    async with AsyncSessionLocal() as s:
        row = (await s.execute(select(Order).where(Order.id == order_id))).scalars().first()
    assert row.shipping_address == "New Road 2" and row.total_price == 1400.0 and row.status == "pending"
    assert len(await orders_of("user_a3")) == len(before)


@pytest.mark.asyncio
async def test_a_confirm_that_can_no_longer_succeed_is_a_409_and_writes_nothing():
    from tests.helpers import KIRAN, client, confirm, login, orders_of, set_product, stock_of

    async with client() as c:
        headers = await login(c, KIRAN)
        conv, card = await _place(headers, c, "Order 2 x HT-CP-01")
        before_orders, before_stock = len(await orders_of("user_a3")), await stock_of("HT-CP-01")
        original = await set_product("HT-CP-01", stock=1)  # someone else bought the units after the card was shown
        try:
            res = await confirm(c, headers, card["card"]["proposal_id"])
        finally:
            await set_product("HT-CP-01", **original)
        thread = (await c.get(f"/api/chat/conversations/{conv}/messages", headers=headers)).json()
    assert res.status_code == 409 and "Not enough stock" in res.json()["detail"]
    assert len(await orders_of("user_a3")) == before_orders and await stock_of("HT-CP-01") == before_stock
    assert "Not enough stock" in thread[-1]["content"]  # the thread explains what happened
    async with AsyncSessionLocal() as s:
        from app.models.models import ActionProposal
        proposal = (await s.execute(select(ActionProposal).where(ActionProposal.id == card["card"]["proposal_id"]))).scalars().first()
    assert proposal.status == "failed"


@pytest.mark.asyncio
async def test_an_expired_order_proposal_cannot_be_confirmed():
    import datetime
    from tests.helpers import KIRAN, client, confirm, login, orders_of

    async with client() as c:
        headers = await login(c, KIRAN)
        _, card = await _place(headers, c, "Order 1 x HT-IN-01")
        pid = card["card"]["proposal_id"]
        async with AsyncSessionLocal() as s:
            from app.models.models import ActionProposal
            proposal = (await s.execute(select(ActionProposal).where(ActionProposal.id == pid))).scalars().first()
            proposal.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
            await s.commit()
        before = len(await orders_of("user_a3"))
        res = await confirm(c, headers, pid)
    assert res.status_code == 400 and "expired" in res.json()["detail"]
    assert len(await orders_of("user_a3")) == before
