"""Stretch goal: a third organisation added through configuration and seed data alone, no code changes."""
import importlib.util
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import KnowledgeChunk, Organisation
from tests.helpers import AAYUSH, ADMIN_A, ask, chat, client, confirm, login, new_conversation

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "add_third_org.py"
CLIMBER = ("climber@everest.test", "org_c")
ADMIN_C = ("admin@everest.test", "org_c")


async def _add_third_org():
    spec = importlib.util.spec_from_file_location("add_third_org", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    await module.add_third_organisation()


async def test_the_third_organisation_works_end_to_end_without_code_changes():
    await _add_third_org()
    await _add_third_org()  # running it again is harmless

    async with AsyncSessionLocal() as s:
        org = (await s.execute(select(Organisation).where(Organisation.id == "org_c"))).scalars().first()
        chunks = (await s.execute(select(KnowledgeChunk).where(KnowledgeChunk.org_id == "org_c"))).scalars().all()
    assert org.slug == "everest-gear" and org.agent_kind == "retail" and len(chunks) >= 5

    async with client() as c:
        listed = (await c.get("/api/orgs")).json()
        assert {o["slug"] for o in listed} >= {"himali-tea", "lotus-wellness", "everest-gear"}
        assert next(o for o in listed if o["slug"] == "everest-gear")["primary_color"] == "#0f172a"

        # It has its own branding entry point, sign-up, ordering, knowledge base and admin analytics.
        signup = await c.post("/api/auth/register", json={
            "email": "trekker@everest.test", "password": "Password123!", "name": "Tara Trekker", "org_id": "everest-gear"})
        assert signup.status_code == 200 and signup.json()["user"]["org_id"] == "org_c"

        headers = await login(c, CLIMBER)
        conv = await new_conversation(c, headers)
        stock = await chat(c, headers, conv, "What is the price of EG-ICE-01?")
        assert "Titanium Technical Ice Axe" in stock["text"] and "NPR 14500" in stock["text"]
        policy = await chat(c, headers, conv, "What is your return policy?")
        assert policy["citations"] and {cit["doc"] for cit in policy["citations"]} <= {"shipping_returns.md", "faq.md", "about.md"}
        assert "14 days" in policy["text"]
        order = await chat(c, headers, conv, "Order 1 x EG-ICE-01 deliver to Namche Bazaar")
        placed = await confirm(c, headers, order["card"]["proposal_id"])
        assert placed.status_code == 200 and placed.json()["result"]["total_price"] == 14500.0

        admin = await login(c, ADMIN_C)
        summary = (await c.get("/api/admin/activity_summary", headers=admin)).json()
        assert summary["org_id"] == "org_c" and summary["metrics"]["total_orders"] == 1
        assert summary["metrics"]["gross_revenue_npr"] == 0.0  # still pending, so not revenue yet
        top = (await c.get("/api/admin/top_items", headers=admin)).json()
        assert top["org_id"] == "org_c" and "best_selling_products" not in top

    # Isolation holds in both directions.
    store = await ask(AAYUSH, "price of EG-DWN-01")
    assert "No matching products" in store["text"]
    gear = await ask(CLIMBER, "price of HT-SN-100")
    assert "No matching products" in gear["text"]
    async with client() as c:
        a_admin = await login(c, ADMIN_A)
        assert all(o["customer_email"].endswith("@himali.test") for o in (await c.get("/api/admin/orders", headers=a_admin)).json())
