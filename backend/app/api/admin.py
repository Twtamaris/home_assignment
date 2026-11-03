from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.security import require_admin
from app.models.models import User, Order, OrderStatusHistory, Booking, Service, Practitioner
from app.services.order_lifecycle import TransitionError, advance_order
from app.models.schemas import (
    OrderStatusAdvance, OrderOut, AdminActivitySummary, AdminClientsToday, AdminConversionRate, AdminTopItems
)
from app.services.admin_agent import AdminAnalyticsTools

router = APIRouter(prefix="/admin", tags=["Admin Operations (Scoped with 403 Enforcement)"])

@router.get("/orders")
async def list_org_orders(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Every order in the admin's own organisation, newest first."""
    rows = (await db.execute(
        select(Order, User.name, User.email)
        .join(User, User.id == Order.user_id)
        .where(Order.org_id == admin_user.org_id)
        .order_by(desc(Order.created_at))
    )).all()
    return [
        {
            "id": o.id,
            "status": o.status,
            "items": o.items,
            "total_price": o.total_price,
            "shipping_address": o.shipping_address,
            "customer_name": name,
            "customer_email": email,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
        }
        for o, name, email in rows
    ]

@router.get("/bookings")
async def list_org_bookings(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Every booking in the admin's own organisation, soonest first. Times are studio wall-clock time."""
    rows = (await db.execute(
        select(Booking, User.name, User.email, Service.name, Practitioner.name)
        .join(User, User.id == Booking.user_id)
        .join(Service, Service.id == Booking.service_id)
        .join(Practitioner, Practitioner.id == Booking.practitioner_id)
        .where(Booking.org_id == admin_user.org_id)
        .order_by(desc(Booking.start_time))
    )).all()
    return [
        {
            "id": b.id,
            "status": b.status,
            "start_time": b.start_time,
            "end_time": b.end_time,
            "service_name": service_name,
            "practitioner_name": practitioner_name,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "cancellation_fee": b.cancellation_fee or 0.0,
        }
        for b, customer_name, customer_email, service_name, practitioner_name in rows
    ]

@router.post("/orders/{order_id}/advance_status", response_model=OrderOut)
async def advance_order_status(
    order_id: str,
    payload: OrderStatusAdvance,
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """
    Admin endpoint to advance order status (pending -> confirmed -> shipped -> delivered).
    Enforces that the order belongs to admin_user.org_id.
    """
    stmt = select(Order).where(Order.id == order_id, Order.org_id == admin_user.org_id)
    res = await db.execute(stmt)
    order = res.scalars().first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order #{order_id} not found in this organisation."
        )

    try:
        await advance_order(
            db, order, payload.new_status,
            changed_by=f"Admin ({admin_user.email})",
            reason=payload.reason or "Admin status advancement",
        )
    except TransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await db.commit()
    await db.refresh(order)

    return OrderOut(
        id=order.id,
        org_id=order.org_id,
        user_id=order.user_id,
        status=order.status,
        items=order.items,
        total_price=order.total_price,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at
    )

@router.get("/activity_summary", response_model=AdminActivitySummary)
async def get_activity_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    res = await AdminAnalyticsTools.get_activity_summary(db, admin_user.org_id, time_window_days=days)
    return AdminActivitySummary(
        org_id=res["org_id"],
        time_window=res["time_window"],
        definition=res["definition"],
        metrics=res["metrics"]
    )

@router.get("/clients_today", response_model=AdminClientsToday)
async def get_clients_today(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    res = await AdminAnalyticsTools.get_clients_today(db, admin_user.org_id)
    return AdminClientsToday(
        org_id=res["org_id"],
        date=res["date"],
        unique_customers_chatted=res["metrics"]["unique_customers_chatted"],
        new_signups_today=res["metrics"]["new_signups_today"],
        definition=res["definition"]
    )

@router.get("/conversion_rate", response_model=AdminConversionRate)
async def get_conversion_rate(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    res = await AdminAnalyticsTools.get_conversion_rate(db, admin_user.org_id, time_window_days=days)
    return AdminConversionRate(
        org_id=res["org_id"],
        time_window=res["time_window"],
        total_conversations=res["metrics"]["total_conversations"],
        successful_conversations=res["metrics"]["converted_conversations"],
        conversion_rate_percentage=res["metrics"]["conversion_rate_percentage"],
        definition=res["definition"]
    )

@router.get("/top_items", response_model=AdminTopItems)
async def get_top_items(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    res = await AdminAnalyticsTools.get_top_items(db, admin_user.org_id)
    if res["kind"] == "retail":
        top = res["best_selling_products"]
        sec = res["low_or_out_of_stock_items"]
    else:
        top = res["most_booked_services"]
        sec = res["busiest_time_slots"]

    return AdminTopItems(
        org_id=res["org_id"],
        time_window=res["time_window"],
        top_items=top,
        secondary_items=sec,
        definition=res["definition"]
    )

