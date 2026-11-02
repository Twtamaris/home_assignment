import os
import sys
import json
import asyncio
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, delete

from app.core.config import settings
from app.core.database import Base
from app.core.security import get_password_hash
from app.models.models import (
    Organisation, User, Product, Service, Practitioner,
    Holiday, WeeklyOpeningHours, Order, OrderItem, OrderStatusHistory, Booking,
    KnowledgeChunk, CustomerMemory, Conversation, Message, InventoryEvent
)
from app.services.knowledge_base import get_embedding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def parse_markdown_chunks(file_path: Path, doc_name: str) -> list:
    """
    Splits markdown by headings (#, ##, ###) while preserving document hierarchy.
    Ensures complete, coherent semantic units (e.g. individual FAQs, policies, guides).
    """
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    chunks = []
    current_section = "Overview"
    current_lines = []

    for line in lines:
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            if current_lines:
                chunk_body = "\n".join(current_lines).strip()
                if chunk_body:
                    chunks.append({
                        "doc_name": doc_name,
                        "section_name": current_section,
                        "content": chunk_body
                    })
            current_section = line.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        chunk_body = "\n".join(current_lines).strip()
        if chunk_body:
            chunks.append({
                "doc_name": doc_name,
                "section_name": current_section,
                "content": chunk_body
            })

    return chunks

async def seed():
    print("[*] Rebuilding database and knowledge bases...")
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Load initial JSON data
    seed_json_path = backend_dir / "app" / "seed_data" / "initial_records.json"
    data = json.loads(seed_json_path.read_text(encoding="utf-8"))

    async with async_session() as session:
        # 1. Organisations
        print(" -> Seeding Organisations...")
        for org in data["organisations"]:
            session.add(Organisation(
                id=org["id"],
                slug=org["slug"],
                name=org["name"],
                tagline=org.get("tagline"),
                primary_color=org.get("primary_color", "#1b4332"),
                secondary_color=org.get("secondary_color", "#2d6a4f"),
                accent_color=org.get("accent_color", "#d4a373"),
                agent_name=org.get("agent_name", "Assistant"),
                agent_role=org.get("agent_role", "Guide"),
                greeting=org.get("greeting")
            ))
        await session.commit()

        # 2. Users
        print(" -> Seeding Users (Customers & Admins)...")
        for u in data["users"]:
            session.add(User(
                id=u["id"],
                org_id=u["org_id"],
                email=u["email"],
                hashed_password=get_password_hash(u["password"]),
                name=u["name"],
                role=u["role"]
            ))
        await session.commit()

        # 3. Products (Org A)
        print(f" -> Seeding Products for Org A ({len(data['products'])} items)...")
        for p in data["products"]:
            session.add(Product(
                org_id="org_a",
                sku=p["sku"],
                name=p["name"],
                category=p["category"],
                price=p["price"],
                stock=p["stock"],
                description=p["description"]
            ))
        await session.commit()

        # 4. Services & Practitioners (Org B)
        print(f" -> Seeding Services ({len(data['services'])}) and Practitioners ({len(data['practitioners'])}) for Org B...")
        for s in data["services"]:
            session.add(Service(
                id=s["id"],
                org_id="org_b",
                name=s["name"],
                duration_minutes=s["duration_minutes"],
                price=s["price"],
                description=s["description"]
            ))

        for pr in data["practitioners"]:
            prac = Practitioner(
                id=pr["id"],
                org_id="org_b",
                name=pr["name"],
                title=pr["title"],
                bio=pr["bio"]
            )
            prac.specialties = pr["specialties"]
            session.add(prac)

        # Weekly Hours (Org B)
        opening = data["opening_hours"]["schedule"]
        for day, times in opening.items():
            session.add(WeeklyOpeningHours(
                org_id="org_b",
                day_of_week=day,
                open_time=times["open"],
                close_time=times["close"],
                is_closed=False
            ))

        # Holidays (Org B)
        for h in data["holidays"]:
            session.add(Holiday(
                org_id="org_b",
                holiday_date=h["date"],
                name=h["name"]
            ))
        await session.commit()

        # 5. Conversations & Past Orders for Org A Customers (Rule: 3 customers, 2 with past orders)
        print(" -> Seeding Conversations and Past Orders for Org A customers...")
        conv_a1 = Conversation(
            id="conv_seed_a1",
            org_id="org_a",
            user_id="user_a1",
            title="Spring Teas Order Inquiry",
            agent_type="customer"
        )
        conv_a2 = Conversation(
            id="conv_seed_a2",
            org_id="org_a",
            user_id="user_a2",
            title="Green Pearl Tea Purchase",
            agent_type="customer"
        )
        conv_a3 = Conversation(
            id="conv_seed_a3",
            org_id="org_a",
            user_id="user_a3",
            title="General Catalog Question",
            agent_type="customer"
        )
        session.add_all([conv_a1, conv_a2, conv_a3])
        await session.commit()

        # Order 1 for Aayush (confirmed order)
        o1 = Order(
            id="ORD-1001",
            org_id="org_a",
            user_id="user_a1",
            conversation_id=conv_a1.id,
            status="confirmed",
            total_price=2800.0,
            shipping_address="Thamel, Kathmandu, Nepal"
        )
        o1.items = [
            {"sku": "HT-SN-100", "name": "Himalayan Spring Silver Needle (100g)", "unit_price": 1850.0, "quantity": 1, "subtotal": 1850.0},
            {"sku": "HT-BT-100", "name": "Golden Tippy Orthodox Black Tea (100g)", "unit_price": 950.0, "quantity": 1, "subtotal": 950.0}
        ]
        session.add(o1)

        # Order 2 for Aayush (delivered order)
        o2 = Order(
            id="ORD-1002",
            org_id="org_a",
            user_id="user_a1",
            conversation_id=conv_a1.id,
            status="delivered",
            total_price=1600.0,
            shipping_address="Thamel, Kathmandu, Nepal"
        )
        o2.items = [
            {"sku": "HT-OL-100", "name": "Shangri-La High Mountain Oolong (100g)", "unit_price": 1600.0, "quantity": 1, "subtotal": 1600.0}
        ]
        session.add(o2)

        # Order 3 for Priya (pending order to test edit & cancel)
        o3 = Order(
            id="ORD-1003",
            org_id="org_a",
            user_id="user_a2",
            conversation_id=conv_a2.id,
            status="pending",
            total_price=1200.0,
            shipping_address="Baluwatar, Kathmandu, Nepal"
        )
        o3.items = [
            {"sku": "HT-GT-100", "name": "Dhankuta Imperial Green Pearls (100g)", "unit_price": 1200.0, "quantity": 1, "subtotal": 1200.0}
        ]
        session.add(o3)
        await session.commit()

        # Seed relational OrderItems for analytics & sales accuracy
        prod_map = {p.sku: p.id for p in (await session.execute(select(Product).where(Product.org_id == "org_a"))).scalars().all()}
        order_items_to_seed = [
            OrderItem(org_id="org_a", order_id="ORD-1001", product_id=prod_map.get("HT-SN-100", 1), sku="HT-SN-100", name="Himalayan Spring Silver Needle (100g)", quantity=1, unit_price=1850.0, subtotal=1850.0),
            OrderItem(org_id="org_a", order_id="ORD-1001", product_id=prod_map.get("HT-BT-100", 2), sku="HT-BT-100", name="Golden Tippy Orthodox Black Tea (100g)", quantity=1, unit_price=950.0, subtotal=950.0),
            OrderItem(org_id="org_a", order_id="ORD-1002", product_id=prod_map.get("HT-OL-100", 3), sku="HT-OL-100", name="Shangri-La High Mountain Oolong (100g)", quantity=1, unit_price=1600.0, subtotal=1600.0),
            OrderItem(org_id="org_a", order_id="ORD-1003", product_id=prod_map.get("HT-GT-100", 4), sku="HT-GT-100", name="Dhankuta Imperial Green Pearls (100g)", quantity=1, unit_price=1200.0, subtotal=1200.0),
        ]
        session.add_all(order_items_to_seed)

        # Seed initial inventory events
        inv_events = [
            InventoryEvent(org_id="org_a", product_id=prod_map.get("HT-SN-100", 1), sku="HT-SN-100", delta=-1, reason="order_created", stock_after=40),
            InventoryEvent(org_id="org_a", product_id=prod_map.get("HT-BT-100", 2), sku="HT-BT-100", delta=-1, reason="order_created", stock_after=65),
            InventoryEvent(org_id="org_a", product_id=prod_map.get("HT-OL-100", 3), sku="HT-OL-100", delta=-1, reason="order_created", stock_after=50),
            InventoryEvent(org_id="org_a", product_id=prod_map.get("HT-GT-100", 4), sku="HT-GT-100", delta=-1, reason="order_created", stock_after=80),
        ]
        session.add_all(inv_events)

        # Order histories
        session.add(OrderStatusHistory(order_id="ORD-1001", old_status="pending", new_status="confirmed", changed_by="Store Manager", reason="Payment confirmed"))
        session.add(OrderStatusHistory(order_id="ORD-1002", old_status="confirmed", new_status="delivered", changed_by="Courier Delivery Agent", reason="Signed upon delivery"))
        session.add(OrderStatusHistory(order_id="ORD-1003", old_status="none", new_status="pending", changed_by="Customer", reason="Cart order placement"))
        await session.commit()

        # 6. Conversations & Past Bookings for Org B Customers (Rule: 3 customers, 2 with past bookings)
        print(" -> Seeding Conversations and Past Bookings for Org B customers...")
        conv_b1 = Conversation(
            id="conv_seed_b1",
            org_id="org_b",
            user_id="user_b1",
            title="Therapeutic Massage Consultation",
            agent_type="customer"
        )
        conv_b2 = Conversation(
            id="conv_seed_b2",
            org_id="org_b",
            user_id="user_b2",
            title="Sports Rehab Followup",
            agent_type="customer"
        )
        conv_b3 = Conversation(
            id="conv_seed_b3",
            org_id="org_b",
            user_id="user_b3",
            title="Yoga Schedule Inquiry",
            agent_type="customer"
        )
        session.add_all([conv_b1, conv_b2, conv_b3])
        await session.commit()

        import datetime
        b1 = Booking(
            id="BKG-2001",
            org_id="org_b",
            user_id="user_b1",
            conversation_id=conv_b1.id,
            service_id="srv_1",
            practitioner_id="prac_2",
            start_time=datetime.datetime(2026, 11, 2, 10, 0, 0),
            end_time=datetime.datetime(2026, 11, 2, 11, 0, 0),
            status="confirmed",
            notes="Focus on upper trapezius stiffness."
        )
        b2 = Booking(
            id="BKG-2002",
            org_id="org_b",
            user_id="user_b2",
            conversation_id=conv_b2.id,
            service_id="srv_3",
            practitioner_id="prac_1",
            start_time=datetime.datetime(2026, 11, 3, 14, 0, 0),
            end_time=datetime.datetime(2026, 11, 3, 14, 45, 0),
            status="confirmed",
            notes="Post-knee arthroscopy follow-up."
        )
        session.add(b1)
        session.add(b2)
        await session.commit()

        # 7. Customer Memories
        session.add(CustomerMemory(org_id="org_a", user_id="user_a1", memory_key="usual_tea", memory_value="Himalayan Spring Silver Needle (100g)"))
        session.add(CustomerMemory(org_id="org_b", user_id="user_b1", memory_key="preferred_practitioner", memory_value="Master Tenzing Norbu"))
        await session.commit()

        # 8. Load Knowledge Base Documents & Vectors
        print(" -> Ingesting and embedding Knowledge Base for Org A...")
        org_a_kb_dir = backend_dir / "app" / "seed_data" / "org_a_knowledge"
        for md_file in org_a_kb_dir.glob("*.md"):
            chunks = parse_markdown_chunks(md_file, md_file.name)
            for ch in chunks:
                emb = await get_embedding(ch["content"])
                session.add(KnowledgeChunk(
                    org_id="org_a",
                    doc_name=ch["doc_name"],
                    section_name=ch["section_name"],
                    content=ch["content"],
                    embedding_json=json.dumps(emb)
                ))

        print(" -> Ingesting and embedding Knowledge Base for Org B...")
        org_b_kb_dir = backend_dir / "app" / "seed_data" / "org_b_knowledge"
        for md_file in org_b_kb_dir.glob("*.md"):
            chunks = parse_markdown_chunks(md_file, md_file.name)
            for ch in chunks:
                emb = await get_embedding(ch["content"])
                session.add(KnowledgeChunk(
                    org_id="org_b",
                    doc_name=ch["doc_name"],
                    section_name=ch["section_name"],
                    content=ch["content"],
                    embedding_json=json.dumps(emb)
                ))

        await session.commit()

    print("[SUCCESS] Database and Knowledge Bases successfully seeded!")

if __name__ == "__main__":
    asyncio.run(seed())
