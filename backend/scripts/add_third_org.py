import sys
import json
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.models import Organisation, User, Product

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def add_third_organisation():
    cfg_file = backend_dir / "app" / "seed_data" / "org_c_example.json"
    data = json.loads(cfg_file.read_text(encoding="utf-8"))

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        org_data = data["organisation"]
        org = Organisation(
            id=org_data["id"],
            slug=org_data["slug"],
            name=org_data["name"],
            tagline=org_data.get("tagline"),
            primary_color=org_data["primary_color"],
            secondary_color=org_data["secondary_color"],
            accent_color=org_data["accent_color"],
            agent_name=org_data["agent_name"],
            agent_role=org_data["agent_role"],
            greeting=org_data.get("greeting")
        )
        session.add(org)

        for u in data.get("users", []):
            user = User(
                id=u["id"],
                org_id=u["org_id"],
                email=u["email"],
                hashed_password=get_password_hash(u["password"]),
                name=u["name"],
                role=u["role"]
            )
            session.add(user)

        for p in data.get("products", []):
            prod = Product(
                org_id=org_data["id"],
                sku=p["sku"],
                name=p["name"],
                category=p["category"],
                price=p["price"],
                stock=p["stock"],
                description=p["description"]
            )
            session.add(prod)

        await session.commit()
        print(f"[OK] Added third organization '{org_data['name']}' ({org_data['id']}) purely via configuration!")

if __name__ == "__main__":
    asyncio.run(add_third_organisation())
