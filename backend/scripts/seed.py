"""Rebuild the relational database and both knowledge bases from the seed files.

    python scripts/seed.py              drop everything and rebuild
    python scripts/seed.py --if-missing only seed when the database is empty (used by Docker start-up)

Organisations, products, services and knowledge documents are all driven by the files in
app/seed_data. Booking and order fixtures are dated relative to the day the seed runs, so
"past" bookings are always in the past and the upcoming one is always in the future.
"""
import sys
import json
import asyncio
import datetime
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import Base
from app.core.security import get_password_hash
from app.models.models import (
    Organisation, User, Product, Service, Practitioner,
    Holiday, WeeklyOpeningHours, Order, OrderItem, OrderStatusHistory, Booking,
    CustomerMemory, Conversation, InventoryEvent
)
from app.services import knowledge_base as kb
from app.services.seeding import ingest_knowledge, knowledge_dirs
from app.services.scheduling import KATHMANDU_TZ

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _first_org(data: dict, kind: str) -> str:
    for org in data["organisations"]:
        if (org.get("agent_kind") or "retail") == kind:
            return org["id"]
    raise SystemExit(f"initial_records.json has no organisation with agent_kind '{kind}'")


def _next_open_day(start: datetime.date, closed_dates: set) -> datetime.date:
    day = start
    while day.isoformat() in closed_dates:
        day += datetime.timedelta(days=1)
    return day


async def _already_seeded(engine) -> bool:
    try:
        async with engine.connect() as conn:
            return (await conn.execute(select(func.count()).select_from(Organisation))).scalar() > 0
    except Exception:
        return False


async def seed(if_missing: bool = False):
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    if if_missing and await _already_seeded(engine):
        print("[*] Database already seeded, leaving it as it is.")
        await engine.dispose()
        return

    print("[*] Rebuilding database and knowledge bases...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    kb.reset_collection()
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    data = json.loads((backend_dir / "app" / "seed_data" / "initial_records.json").read_text(encoding="utf-8"))
    retail_org = _first_org(data, "retail")
    studio_org = _first_org(data, "studio")

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_ktm = datetime.datetime.now(KATHMANDU_TZ).replace(tzinfo=None)

    async with async_session() as session:
        print(" -> Seeding organisations...")
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
                greeting=org.get("greeting"),
                agent_kind=org.get("agent_kind") or "retail",
            ))
        await session.commit()

        print(" -> Seeding users (customers and admins)...")
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

        print(f" -> Seeding {len(data['products'])} products...")
        for p in data["products"]:
            session.add(Product(
                org_id=p.get("org_id", retail_org),
                sku=p["sku"],
                name=p["name"],
                category=p["category"],
                price=p["price"],
                stock=p["stock"],
                description=p["description"]
            ))
        await session.commit()

        print(f" -> Seeding {len(data['services'])} services, {len(data['practitioners'])} practitioners, hours and holidays...")
        for s in data["services"]:
            session.add(Service(
                id=s["id"],
                org_id=s.get("org_id", studio_org),
                name=s["name"],
                duration_minutes=s["duration_minutes"],
                price=s["price"],
                description=s["description"]
            ))
        for pr in data["practitioners"]:
            prac = Practitioner(
                id=pr["id"],
                org_id=pr.get("org_id", studio_org),
                name=pr["name"],
                title=pr["title"],
                bio=pr["bio"]
            )
            prac.specialties = pr["specialties"]
            session.add(prac)
        for day, times in data["opening_hours"]["schedule"].items():
            session.add(WeeklyOpeningHours(
                org_id=data["opening_hours"].get("org_id", studio_org),
                day_of_week=day,
                open_time=times["open"],
                close_time=times["close"],
                is_closed=bool(times.get("closed", False)),
            ))
        for h in data["holidays"]:
            session.add(Holiday(org_id=h.get("org_id", studio_org), holiday_date=h["date"], name=h["name"]))
        await session.commit()

        # ---- Retail demo orders: 3 customers, 2 with past orders, 1 with a pending order ----
        print(" -> Seeding conversations and orders for the retail organisation...")
        stamp = {"o1": now_utc - datetime.timedelta(days=12), "o2": now_utc - datetime.timedelta(days=24),
                 "o3": now_utc - datetime.timedelta(hours=1)}
        session.add_all([
            Conversation(id="conv_seed_a1", org_id=retail_org, user_id="user_a1", title="Spring Teas Order Inquiry",
                         agent_type="customer", created_at=stamp["o2"], updated_at=stamp["o1"]),
            Conversation(id="conv_seed_a2", org_id=retail_org, user_id="user_a2", title="Green Pearl Tea Purchase",
                         agent_type="customer", created_at=stamp["o3"], updated_at=stamp["o3"]),
            Conversation(id="conv_seed_a3", org_id=retail_org, user_id="user_a3", title="General Catalog Question",
                         agent_type="customer"),
        ])
        await session.commit()

        demo_orders = [
            ("ORD-1001", "user_a1", "conv_seed_a1", "confirmed", "Thamel, Kathmandu, Nepal", stamp["o1"], [
                ("HT-SN-100", 1), ("HT-BT-100", 1)]),
            ("ORD-1002", "user_a1", "conv_seed_a1", "delivered", "Thamel, Kathmandu, Nepal", stamp["o2"], [
                ("HT-OL-100", 1)]),
            ("ORD-1003", "user_a2", "conv_seed_a2", "pending", "Baluwatar, Kathmandu, Nepal", stamp["o3"], [
                ("HT-GT-100", 1)]),
        ]
        products = {p.sku: p for p in (await session.execute(
            select(Product).where(Product.org_id == retail_org))).scalars().all()}
        for order_id, user_id, conv_id, status, address, created, lines in demo_orders:
            resolved = [
                {"sku": sku, "name": products[sku].name, "unit_price": products[sku].price,
                 "quantity": qty, "subtotal": products[sku].price * qty}
                for sku, qty in lines
            ]
            order = Order(
                id=order_id, org_id=retail_org, user_id=user_id, conversation_id=conv_id, status=status,
                total_price=sum(line["subtotal"] for line in resolved), shipping_address=address,
                created_at=created, updated_at=created,
            )
            order.items = resolved
            session.add(order)
            await session.flush()
            for line in resolved:
                session.add(OrderItem(
                    org_id=retail_org, order_id=order_id, product_id=products[line["sku"]].id, sku=line["sku"],
                    name=line["name"], quantity=line["quantity"], unit_price=line["unit_price"], subtotal=line["subtotal"],
                ))
                session.add(InventoryEvent(
                    org_id=retail_org, product_id=products[line["sku"]].id, sku=line["sku"], delta=-line["quantity"],
                    reason="order_created", stock_after=products[line["sku"]].stock, created_at=created,
                ))
            session.add(OrderStatusHistory(order_id=order_id, old_status="none", new_status="pending",
                                           changed_by="Customer", reason="Order placed in chat", created_at=created))
            if status in ("confirmed", "delivered"):
                session.add(OrderStatusHistory(order_id=order_id, old_status="pending", new_status="confirmed",
                                               changed_by="Store Manager", reason="Payment confirmed (cash on delivery)",
                                               created_at=created + datetime.timedelta(hours=2)))
            if status == "delivered":
                session.add(OrderStatusHistory(order_id=order_id, old_status="confirmed", new_status="delivered",
                                               changed_by="Courier", reason="Signed upon delivery",
                                               created_at=created + datetime.timedelta(days=3)))
        await session.commit()

        # ---- Studio demo bookings: 3 customers, 2 with past bookings, plus one upcoming ----
        print(" -> Seeding conversations and bookings for the studio organisation...")
        session.add_all([
            Conversation(id="conv_seed_b1", org_id=studio_org, user_id="user_b1", title="Therapeutic Massage Consultation",
                         agent_type="customer", created_at=now_utc - datetime.timedelta(days=6)),
            Conversation(id="conv_seed_b2", org_id=studio_org, user_id="user_b2", title="Sports Rehab Followup",
                         agent_type="customer", created_at=now_utc - datetime.timedelta(days=3)),
            Conversation(id="conv_seed_b3", org_id=studio_org, user_id="user_b3", title="Yoga Schedule Inquiry",
                         agent_type="customer"),
        ])
        await session.commit()

        closed = {h["date"] for h in data["holidays"]}
        past_1 = (now_ktm - datetime.timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
        past_2 = (now_ktm - datetime.timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        next_day = _next_open_day((now_ktm + datetime.timedelta(days=2)).date(), closed)
        upcoming = datetime.datetime.combine(next_day, datetime.time(11, 0))
        services = {s.id: s for s in (await session.execute(select(Service).where(Service.org_id == studio_org))).scalars().all()}

        demo_bookings = [
            ("BKG-2001", "user_b1", "conv_seed_b1", "srv_1", "prac_2", past_1, "Focus on upper trapezius stiffness."),
            ("BKG-2002", "user_b2", "conv_seed_b2", "srv_3", "prac_1", past_2, "Post-knee arthroscopy follow-up."),
            # Upcoming appointment held by Rohan. It occupies Master Tenzing at this time, so a
            # booking or reschedule by another customer into that slot is refused.
            ("BKG-2003", "user_b1", "conv_seed_b1", "srv_1", "prac_2", upcoming, "Follow-up deep tissue session."),
        ]
        for booking_id, user_id, conv_id, service_id, prac_id, start, notes in demo_bookings:
            session.add(Booking(
                id=booking_id, org_id=studio_org, user_id=user_id, conversation_id=conv_id, service_id=service_id,
                practitioner_id=prac_id, start_time=start,
                end_time=start + datetime.timedelta(minutes=services[service_id].duration_minutes),
                status="confirmed", notes=notes, created_at=min(start, now_ktm) - datetime.timedelta(days=2),
            ))
        await session.commit()

        # ---- Long-term customer memory ----
        session.add(CustomerMemory(org_id=retail_org, user_id="user_a1", memory_key="usual_tea",
                                   memory_value=products["HT-SN-100"].name))
        session.add(CustomerMemory(org_id=studio_org, user_id="user_b1", memory_key="preferred_practitioner",
                                   memory_value="Master Tenzing Norbu"))
        await session.commit()

        # ---- Knowledge bases: one folder per organisation ----
        known = {o["id"] for o in data["organisations"]}
        indexed_all = True
        for org_id, directory in knowledge_dirs().items():
            if org_id not in known:
                continue  # e.g. org_c_knowledge is loaded by add_third_org.py
            print(f" -> Ingesting knowledge base for {org_id} ({directory.name})...")
            count, indexed = await ingest_knowledge(session, org_id, directory)
            indexed_all = indexed_all and indexed
            print(f"    {count} chunks, {'vectors stored in Chroma' if indexed else 'relational rows only'}")
        await session.commit()

    await engine.dispose()
    if indexed_all:
        mode = f"Chroma vectors ({settings.GEMINI_EMBEDDING_MODEL})"
    elif kb.embeddings_enabled():
        mode = "BM25 lexical fallback (embedding calls failed, see above)"
    else:
        mode = "BM25 lexical retrieval (EMBEDDING_PROVIDER is not gemini or GEMINI_API_KEY is empty)"
    print(f"[SUCCESS] Database and knowledge bases seeded. Retrieval: {mode}.")


if __name__ == "__main__":
    asyncio.run(seed(if_missing="--if-missing" in sys.argv))
