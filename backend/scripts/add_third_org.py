"""Add a third organisation from configuration and seed files alone. No application code changes.

    python scripts/add_third_org.py

Reads app/seed_data/org_c_example.json (organisation, users, products) and the markdown files in
app/seed_data/org_c_knowledge/. The organisation then appears at /a/<slug>, can sign up and chat,
gets knowledge search scoped to its own org_id, and its admin gets the same analytics, because
every behaviour is selected by the organisation's agent_kind and org_id and never by its name.
"""
import sys
import json
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.models import Organisation, User, Product
from app.services.seeding import ingest_knowledge, knowledge_dirs

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def add_third_organisation():
    data = json.loads((backend_dir / "app" / "seed_data" / "org_c_example.json").read_text(encoding="utf-8"))
    org_data = data["organisation"]

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        if (await session.execute(select(Organisation).where(Organisation.id == org_data["id"]))).scalars().first():
            print(f"[*] {org_data['name']} already exists, nothing to do.")
            await engine.dispose()
            return

        session.add(Organisation(
            id=org_data["id"],
            slug=org_data["slug"],
            name=org_data["name"],
            tagline=org_data.get("tagline"),
            primary_color=org_data["primary_color"],
            secondary_color=org_data["secondary_color"],
            accent_color=org_data["accent_color"],
            agent_name=org_data["agent_name"],
            agent_role=org_data["agent_role"],
            greeting=org_data.get("greeting"),
            agent_kind=org_data.get("agent_kind", "retail"),
        ))
        await session.flush()
        for u in data.get("users", []):
            session.add(User(
                id=u["id"], org_id=u["org_id"], email=u["email"],
                hashed_password=get_password_hash(u["password"]), name=u["name"], role=u["role"],
            ))
        for p in data.get("products", []):
            session.add(Product(
                org_id=org_data["id"], sku=p["sku"], name=p["name"], category=p["category"],
                price=p["price"], stock=p["stock"], description=p["description"],
            ))
        await session.flush()

        directory = knowledge_dirs().get(org_data["id"])
        chunks, _ = await ingest_knowledge(session, org_data["id"], directory) if directory else (0, False)
        await session.commit()

    await engine.dispose()
    print(f"[OK] Added '{org_data['name']}' ({org_data['id']}) with {len(data.get('products', []))} products "
          f"and {chunks} knowledge chunks, using configuration and seed data only.")
    print(f"     Entry point: /a/{org_data['slug']}   Logins: " + ", ".join(u["email"] for u in data.get("users", [])))


if __name__ == "__main__":
    asyncio.run(add_third_organisation())
