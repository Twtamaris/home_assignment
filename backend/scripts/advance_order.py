"""Admin script that advances an order's status, so tracking and the edit rules can be demonstrated.

    python scripts/advance_order.py ORD-1003 confirmed
    python scripts/advance_order.py ORD-1003 shipped "left the warehouse"

Allowed moves: pending -> confirmed -> shipped -> delivered; pending or confirmed -> cancelled.
Uses the same lifecycle code as the admin API (POST /api/admin/orders/{id}/advance_status).
"""
import sys
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.models.models import Order
from app.services.order_lifecycle import TransitionError, advance_order

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def run(order_id: str, target_status: str, reason: str) -> int:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with async_session() as session:
            order = (await session.execute(select(Order).where(Order.id == order_id))).scalars().first()
            if not order:
                print(f"[ERROR] Order #{order_id} not found.")
                return 1
            try:
                old_status = await advance_order(session, order, target_status, "CLI script (advance_order.py)", reason)
            except TransitionError as exc:
                print(f"[ERROR] {exc}")
                return 1
            await session.commit()
            print(f"[OK] Order #{order_id}: '{old_status}' -> '{target_status}'.")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(asyncio.run(run(sys.argv[1], sys.argv[2].lower(), sys.argv[3] if len(sys.argv) > 3 else "CLI status advancement")))
