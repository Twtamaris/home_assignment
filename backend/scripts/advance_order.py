import sys
import asyncio
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.models.models import Order, OrderStatusHistory

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

async def advance_order(order_id: str, target_status: str, reason: str = "Script manual status transition"):
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        stmt = select(Order).where(Order.id == order_id)
        res = await session.execute(stmt)
        order = res.scalars().first()

        if not order:
            print(f"[ERROR] Order #{order_id} not found in database.")
            return

        valid_transitions = {
            "pending": ["confirmed", "cancelled"],
            "confirmed": ["shipped", "cancelled"],
            "shipped": ["delivered"],
            "delivered": [],
            "cancelled": []
        }

        allowed = valid_transitions.get(order.status, [])
        if target_status not in allowed:
            print(f"[ERROR] Cannot advance order #{order_id} from '{order.status}' to '{target_status}'. Allowed transitions: {allowed}")
            return

        old_status = order.status
        order.status = target_status

        hist = OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=target_status,
            changed_by="CLI Script (advance_order.py)",
            reason=reason
        )
        session.add(hist)
        await session.commit()
        print(f"[OK] Order #{order_id} status updated from '{old_status}' -> '{target_status}'.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/advance_order.py <ORDER_ID> <confirmed|shipped|delivered|cancelled> [REASON]")
        sys.exit(1)

    oid = sys.argv[1]
    status_arg = sys.argv[2].lower()
    reason_arg = sys.argv[3] if len(sys.argv) > 3 else "CLI status advancement"
    asyncio.run(advance_order(oid, status_arg, reason_arg))
