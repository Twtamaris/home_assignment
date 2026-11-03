"""Order status changes made by staff. The admin API and the CLI script share this one implementation."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Order, OrderStatusHistory
from app.services.agent_a import AgentATools

TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["shipped", "cancelled"],
    "shipped": ["delivered"],
    "delivered": [],
    "cancelled": [],
}


class TransitionError(ValueError):
    pass


async def advance_order(db: AsyncSession, order: Order, new_status: str, changed_by: str, reason: str) -> str:
    """Move an order to its next status. Returns the previous status. Does not commit."""
    allowed = TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        raise TransitionError(
            f"Cannot transition order #{order.id} from '{order.status}' to '{new_status}'. Allowed next statuses: {allowed}"
        )
    if new_status == "cancelled":
        # Units reserved by this order go back on the shelf.
        await AgentATools.restock(db, order.org_id, order.items, "order_cancelled")
    old_status = order.status
    order.status = new_status
    db.add(OrderStatusHistory(
        order_id=order.id, old_status=old_status, new_status=new_status, changed_by=changed_by, reason=reason,
    ))
    return old_status
