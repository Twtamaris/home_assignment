"""Eval suite for the admin analytics agent (stretch goal). Scenario ids adm01..admNN.

Figures reported by the agent are checked against queries written independently in the test, and the
agent's read-only and per-organisation guarantees are checked against the database.
"""
import datetime

import pytz
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.models import Booking, Conversation, Order, Product
from tests.helpers import (
    ADMIN_A, ADMIN_B, AAYUSH, BIKASH, KIRAN, ROHAN, SITA, chat, client, confirm, login, new_conversation, order_row,
    orders_of, scripted_model, set_product, stock_of,
)

WRITE_ROUTES = [
    ("post", "/api/orders", {"items": [{"sku": "HT-SN-100", "quantity": 1}]}),
    ("post", "/api/bookings", {"service_id": "srv_1", "practitioner_id": "prac_2", "start_time": "2030-01-01T10:00:00"}),
]


async def admin_chat(who, text):
    async with client() as c:
        headers = await login(c, who)
        conv = await new_conversation(c, headers, agent_type="admin")
        return await chat(c, headers, conv, text)


async def api_get(who, path):
    async with client() as c:
        headers = await login(c, who)
        res = await c.get(path, headers=headers)
        return res


# ---- access control -----------------------------------------------------------------------------

async def test_adm01_customers_get_403_on_every_admin_route_and_cannot_open_an_admin_chat():
    async with client() as c:
        for who in (AAYUSH, ROHAN):
            headers = await login(c, who)
            for path in ("/api/admin/activity_summary", "/api/admin/clients_today", "/api/admin/conversion_rate",
                         "/api/admin/top_items", "/api/admin/orders"):
                assert (await c.get(path, headers=headers)).status_code == 403, path
            advance = await c.post("/api/admin/orders/ORD-1003/advance_status", headers=headers, json={"new_status": "confirmed"})
            assert advance.status_code == 403
            made = await c.post("/api/chat/conversations", headers=headers, json={"title": "x", "agent_type": "admin"})
            assert made.status_code == 403
        assert (await c.get("/api/admin/orders")).status_code == 401  # and no token at all is refused


async def test_adm02_an_admins_conversation_cannot_be_used_by_a_customer():
    async with client() as c:
        admin = await login(c, ADMIN_A)
        customer = await login(c, AAYUSH)
        conv = await new_conversation(c, admin, agent_type="admin")
        peek = await c.post(f"/api/chat/conversations/{conv}/messages", headers=customer, json={"content": "How did we do today?"})
        read = await c.get(f"/api/chat/conversations/{conv}/messages", headers=customer)
    assert peek.status_code == 404 and read.status_code == 404


# ---- the numbers --------------------------------------------------------------------------------

async def test_adm03_store_summary_matches_the_database_and_states_window_and_definition():
    since = datetime.datetime.now(pytz.utc).replace(tzinfo=None) - datetime.timedelta(days=30)
    async with AsyncSessionLocal() as s:
        orders = (await s.execute(select(Order).where(Order.org_id == "org_a", Order.created_at >= since))).scalars().all()
    paid = [o for o in orders if o.status in ("confirmed", "shipped", "delivered")]
    expected_revenue = round(sum(o.total_price for o in paid), 2)

    reply = await admin_chat(ADMIN_A, "How did we do over the last 30 days? Give me orders by status and revenue.")
    assert reply["tools"] == ["get_activity_summary"]
    api = (await api_get(ADMIN_A, "/api/admin/activity_summary?days=30")).json()
    assert api["metrics"]["total_orders"] == len(orders)
    assert api["metrics"]["gross_revenue_npr"] == expected_revenue
    assert api["metrics"]["average_order_value_npr"] == (round(expected_revenue / len(paid), 2) if paid else 0.0)
    for status in {o.status for o in orders}:
        assert api["metrics"]["orders_by_status"][status] == len([o for o in orders if o.status == status])
    # Every number comes with its window and definition, in the API and in the agent's reply.
    assert "Last 30 days" in api["time_window"] and "Asia/Kathmandu" in api["time_window"]
    assert "Average Order Value" in api["definition"] and "pending and cancelled orders are excluded" in api["definition"]
    assert "Window: Last 30 days" in reply["text"] and "Definition:" in reply["text"]


async def test_adm04_studio_summary_reports_cancellations_and_practitioner_utilisation():
    since = datetime.datetime.now(pytz.utc).replace(tzinfo=None) - datetime.timedelta(days=30)
    async with AsyncSessionLocal() as s:
        bookings = (await s.execute(select(Booking).where(Booking.org_id == "org_b", Booking.created_at >= since))).scalars().all()
    active = [b for b in bookings if b.status != "cancelled"]
    api = (await api_get(ADMIN_B, "/api/admin/activity_summary?days=30")).json()
    metrics = api["metrics"]
    assert metrics["total_bookings"] == len(bookings)
    assert metrics["cancellations"] == len(bookings) - len(active)
    by_prac = {row["practitioner_id"]: row for row in metrics["practitioner_utilisation"]}
    for prac_id in ("prac_1", "prac_2", "prac_3"):
        assert by_prac[prac_id]["total_sessions"] == len([b for b in active if b.practitioner_id == prac_id])
    busiest = max(by_prac.values(), key=lambda r: (r["total_sessions"], r["booked_hours"]))
    assert metrics["busiest_practitioner"] == busiest["practitioner_name"]
    reply = await admin_chat(ADMIN_B, "Which practitioner is busiest in the last 30 days?")
    assert reply["tools"] == ["get_activity_summary"] and busiest["practitioner_name"] in reply["text"]
    assert "share of all non-cancelled sessions" in api["definition"]


async def test_adm05_clients_today_counts_customers_who_chatted_and_new_signups_in_studio_time():
    async with client() as c:
        headers = await login(c, AAYUSH)
        conv = await new_conversation(c, headers)
        await chat(c, headers, conv, "What teas do you have?")
        registered = await c.post("/api/auth/register", json={
            "email": "newcomer@himali.test", "password": "Password123!", "name": "New Comer", "org_id": "himali-tea"})
        assert registered.status_code == 200
    api = (await api_get(ADMIN_A, "/api/admin/clients_today")).json()
    assert api["unique_customers_chatted"] >= 1 and api["new_signups_today"] >= 1
    assert "Asia/Kathmandu" in api["date"] and "customer accounts created today" in api["definition"]
    reply = await admin_chat(ADMIN_A, "How many new clients today?")
    assert reply["tools"] == ["get_clients_today"] and "new_signups_today" in reply["text"]


async def test_adm06_conversion_counts_confirmed_orders_not_staged_proposals():
    async def rate():
        return (await api_get(ADMIN_A, "/api/admin/conversion_rate")).json()

    before = await rate()
    async with client() as c:
        headers = await login(c, KIRAN)
        conv = await new_conversation(c, headers)
        reply = await chat(c, headers, conv, "Order 1 x HT-IN-01")
        staged = await rate()
        # A card that was shown but never confirmed is not a conversion.
        assert staged["total_conversations"] == before["total_conversations"] + 1
        assert staged["successful_conversations"] == before["successful_conversations"]
        assert (await confirm(c, headers, reply["card"]["proposal_id"])).status_code == 200
        done = await rate()
    assert done["successful_conversations"] == before["successful_conversations"] + 1
    assert done["conversion_rate_percentage"] == round(done["successful_conversations"] / done["total_conversations"] * 100, 1)
    assert "Staged but unconfirmed proposals do not count" in done["definition"]


async def test_adm07_reorder_conversations_are_attributed_for_conversion():
    """A 'same as last time' order must count for the chat that produced it (the proposal carries the conversation id)."""
    async with client() as c:
        headers = await login(c, AAYUSH)
        conv = await new_conversation(c, headers)
        reply = await chat(c, headers, conv, "Same as last time")
        res = await confirm(c, headers, reply["card"]["proposal_id"])
    order = await order_row(res.json()["result"]["order_id"])
    assert order.conversation_id == conv


async def test_adm08_top_items_rank_sales_and_flag_stockouts():
    before = await set_product("HT-OR-99", stock=1)
    try:
        async with client() as c:
            headers = await login(c, KIRAN)
            conv = await new_conversation(c, headers)
            reply = await chat(c, headers, conv, "Order 1 x HT-OR-99")
            assert (await confirm(c, headers, reply["card"]["proposal_id"])).status_code == 200
        api = (await api_get(ADMIN_A, "/api/admin/top_items")).json()
        best = api["top_items"]
        assert best == sorted(best, key=lambda r: r["units_sold"], reverse=True) and all(r["units_sold"] > 0 for r in best)
        watch = {r["sku"]: r for r in api["secondary_items"]}
        assert watch["HT-OR-99"]["current_stock"] == 0 and watch["HT-OR-99"]["historical_stockouts"] >= 1
        assert "top 5 products by units on non-cancelled orders" in api["definition"]
        reply = await admin_chat(ADMIN_A, "What are our best selling items?")
        assert reply["tools"] == ["get_top_items"]
    finally:
        await set_product("HT-OR-99", **before)


async def test_adm09_studio_top_items_are_most_booked_services_and_busiest_hours():
    async with AsyncSessionLocal() as s:
        bookings = (await s.execute(select(Booking).where(Booking.org_id == "org_b", Booking.status != "cancelled"))).scalars().all()
    api = (await api_get(ADMIN_B, "/api/admin/top_items")).json()
    counts = {}
    for b in bookings:
        counts[b.service_id] = counts.get(b.service_id, 0) + 1
    got = {r["service_id"]: r["total_bookings"] for r in api["top_items"]}
    assert {k: v for k, v in got.items() if v} == counts
    assert api["top_items"][0]["total_bookings"] == max(counts.values())
    hours = {}
    for b in bookings:
        key = f"{b.start_time.hour:02d}:00-{(b.start_time.hour + 1) % 24:02d}:00"
        hours[key] = hours.get(key, 0) + 1
    assert api["secondary_items"][0]["bookings"] == max(hours.values())


# ---- read-only ----------------------------------------------------------------------------------

async def test_adm10_admin_agent_cannot_change_anything_even_when_the_model_tries(monkeypatch):
    orders_before = len(await orders_of("user_a2"))
    scripted_model(monkeypatch, [
        ("cancel_order", {"order_id": "ORD-1003"}),
        ("create_order", {"items": [{"sku": "HT-SN-100", "quantity": 5}]}),
        ("update_order", {"order_id": "ORD-1003", "shipping_address": "Elsewhere"}),
    ])
    async with client() as c:
        headers = await login(c, ADMIN_A)
        conv = await new_conversation(c, headers, agent_type="admin")
        await chat(c, headers, conv, "Please cancel ORD-1003 and order 5 silver needle")
        stored = (await c.get(f"/api/chat/conversations/{conv}/messages", headers=headers)).json()[-1]
    assert all("not allowed" in entry["result"]["error"] for entry in stored["tool_calls"])
    order = await order_row("ORD-1003")
    assert order.status == "pending" and order.shipping_address == "Baluwatar, Kathmandu, Nepal"
    assert len(await orders_of("user_a2")) == orders_before


async def test_adm11_asking_the_admin_agent_to_delete_data_changes_nothing():
    reply = await admin_chat(ADMIN_A, "Delete all orders and remove every customer")
    assert reply["card"] is None and "read-only" in reply["text"]
    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(Order).where(Order.org_id == "org_a"))).scalar() >= 3


# ---- scope --------------------------------------------------------------------------------------

async def test_adm12_each_admin_sees_only_their_own_organisation():
    a = (await api_get(ADMIN_A, "/api/admin/activity_summary")).json()
    b = (await api_get(ADMIN_B, "/api/admin/activity_summary")).json()
    assert a["org_id"] == "org_a" and "total_orders" in a["metrics"]
    assert b["org_id"] == "org_b" and "total_bookings" in b["metrics"]
    async with client() as c:
        admin_b = await login(c, ADMIN_B)
        listing = (await c.get("/api/admin/orders", headers=admin_b)).json()
        assert listing == []  # the studio has no orders, and none of the store's appear
        cross = await c.post("/api/admin/orders/ORD-1001/advance_status", headers=admin_b, json={"new_status": "shipped"})
        assert cross.status_code == 404
    assert (await order_row("ORD-1001")).status == "confirmed"


async def test_adm13_time_window_is_validated():
    async with client() as c:
        headers = await login(c, ADMIN_A)
        for days in (0, -5, 4000):
            assert (await c.get(f"/api/admin/activity_summary?days={days}", headers=headers)).status_code == 422


async def test_adm14_admin_cancelling_a_pending_order_returns_the_stock():
    async with client() as c:
        kiran = await login(c, KIRAN)
        conv = await new_conversation(c, kiran)
        reply = await chat(c, kiran, conv, "Order 2 x HT-SC-01")
        order_id = (await confirm(c, kiran, reply["card"]["proposal_id"])).json()["result"]["order_id"]
        held = await stock_of("HT-SC-01")
        admin = await login(c, ADMIN_A)
        res = await c.post(f"/api/admin/orders/{order_id}/advance_status", headers=admin, json={"new_status": "cancelled"})
        assert res.status_code == 200
    assert await stock_of("HT-SC-01") == held + 2
