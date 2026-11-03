import datetime
from typing import Dict, Any, Tuple
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from app.models.models import (
    Order, OrderItem, Booking, User, Conversation, Product, Service,
    Practitioner, Message, InventoryEvent, Organisation
)
from app.services.scheduling import KATHMANDU_TZ

_PAID_STATUSES = ["confirmed", "shipped", "delivered"]


def _utc_now() -> datetime.datetime:
    """Naive UTC, the same convention the created_at columns use."""
    return datetime.datetime.now(pytz.utc).replace(tzinfo=None)


def _kathmandu(naive_utc: datetime.datetime) -> datetime.datetime:
    return pytz.utc.localize(naive_utc).astimezone(KATHMANDU_TZ)


def _window(days: int) -> Tuple[datetime.datetime, str]:
    """Rolling window ending now. Returns the naive-UTC start and a label in studio time."""
    now = _utc_now()
    start = now - datetime.timedelta(days=days)
    label = (
        f"Last {days} day{'s' if days != 1 else ''}: "
        f"{_kathmandu(start).strftime('%Y-%m-%d %H:%M')} to {_kathmandu(now).strftime('%Y-%m-%d %H:%M')} "
        "(Asia/Kathmandu, rolling window ending now)"
    )
    return start, label


async def _is_retail(db: AsyncSession, org_id: str) -> bool:
    """Which metrics apply comes from the organisation's configuration, never from its id."""
    kind = (await db.execute(
        select(Organisation.agent_kind).where(Organisation.id == org_id)
    )).scalar()
    return (kind or "retail") != "studio"


class AdminAnalyticsTools:
    """
    Read-only Analytics Agent Tools for Store & Studio Admins.
    Every query filters on the admin's own org_id. Customer roles are blocked at the
    endpoint layer with HTTP 403 and the admin tool list contains no write tools.
    """

    @staticmethod
    async def get_activity_summary(db: AsyncSession, org_id: str, time_window_days: int = 30) -> Dict[str, Any]:
        """
        Retail: orders by status, gross revenue, average order value.
        Studio: bookings by status, cancellations, practitioner utilisation.
        """
        time_window_days = max(1, min(int(time_window_days), 365))
        since_dt, time_window_label = _window(time_window_days)

        if await _is_retail(db, org_id):
            orders = (await db.execute(
                select(Order).where(Order.org_id == org_id, Order.created_at >= since_dt)
            )).scalars().all()

            status_counts: Dict[str, int] = {}
            total_revenue = 0.0
            revenue_order_count = 0
            for o in orders:
                status_counts[o.status] = status_counts.get(o.status, 0) + 1
                if o.status in _PAID_STATUSES:
                    total_revenue += o.total_price
                    revenue_order_count += 1

            aov = round(total_revenue / revenue_order_count, 2) if revenue_order_count > 0 else 0.0

            return {
                "success": True,
                "org_id": org_id,
                "kind": "retail",
                "time_window": time_window_label,
                "definition": (
                    "Orders placed in the window, counted by current status. Gross revenue and Average Order Value (AOV) "
                    "use confirmed, shipped and delivered orders only (pending and cancelled orders are excluded). "
                    "AOV = gross revenue / number of those orders."
                ),
                "metrics": {
                    "total_orders": len(orders),
                    "orders_by_status": status_counts,
                    "gross_revenue_npr": round(total_revenue, 2),
                    "paid_order_count": revenue_order_count,
                    "average_order_value_npr": aov
                }
            }

        bookings = (await db.execute(
            select(Booking).where(Booking.org_id == org_id, Booking.created_at >= since_dt)
        )).scalars().all()
        durations = {
            s.id: s.duration_minutes
            for s in (await db.execute(select(Service).where(Service.org_id == org_id))).scalars().all()
        }

        status_counts = {}
        sessions: Dict[str, int] = {}
        minutes: Dict[str, int] = {}
        total_cancellations = 0
        for b in bookings:
            status_counts[b.status] = status_counts.get(b.status, 0) + 1
            if b.status == "cancelled":
                total_cancellations += 1
            else:
                sessions[b.practitioner_id] = sessions.get(b.practitioner_id, 0) + 1
                minutes[b.practitioner_id] = minutes.get(b.practitioner_id, 0) + durations.get(b.service_id, 0)
        active_total = sum(sessions.values())

        practitioners = (await db.execute(select(Practitioner).where(Practitioner.org_id == org_id))).scalars().all()
        utilisation_summary = [
            {
                "practitioner_id": p.id,
                "practitioner_name": p.name,
                "total_sessions": sessions.get(p.id, 0),
                "booked_hours": round(minutes.get(p.id, 0) / 60, 1),
                "share_percentage": round(sessions.get(p.id, 0) / max(1, active_total) * 100, 1),
            }
            for p in practitioners
        ]
        utilisation_summary.sort(key=lambda row: (row["total_sessions"], row["booked_hours"]), reverse=True)
        busiest = utilisation_summary[0] if utilisation_summary and utilisation_summary[0]["total_sessions"] else None

        return {
            "success": True,
            "org_id": org_id,
            "kind": "studio",
            "time_window": time_window_label,
            "definition": (
                "Bookings created in the window, counted by current status. Practitioner utilisation counts "
                "non-cancelled bookings per practitioner: sessions, booked hours (sum of service durations) and the "
                "practitioner's share of all non-cancelled sessions. Cancellation rate = cancelled / all bookings created."
            ),
            "metrics": {
                "total_bookings": len(bookings),
                "bookings_by_status": status_counts,
                "cancellations": total_cancellations,
                "cancellation_rate_percentage": round((total_cancellations / max(1, len(bookings))) * 100, 1),
                "busiest_practitioner": busiest["practitioner_name"] if busiest else None,
                "practitioner_utilisation": utilisation_summary
            }
        }

    @staticmethod
    async def get_clients_today(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        """
        Unique customers who chatted today; new sign-ups today. "Today" is the studio day in Asia/Kathmandu.
        """
        now_ktm = datetime.datetime.now(KATHMANDU_TZ)
        midnight_ktm = KATHMANDU_TZ.localize(datetime.datetime.combine(now_ktm.date(), datetime.time.min))
        today_start = midnight_ktm.astimezone(pytz.utc).replace(tzinfo=None)
        today_label = f"Today {now_ktm.date().isoformat()} (Asia/Kathmandu, 00:00 to {now_ktm.strftime('%H:%M')})"

        active_customer_ids = (await db.execute(
            select(distinct(Conversation.user_id)).join(
                Message, Message.conversation_id == Conversation.id
            ).where(
                Conversation.org_id == org_id,
                Conversation.agent_type == "customer",
                Message.created_at >= today_start,
                Message.sender == "user"
            )
        )).scalars().all()

        new_users = (await db.execute(
            select(User).where(
                User.org_id == org_id,
                User.created_at >= today_start,
                User.role == "customer"
            )
        )).scalars().all()

        return {
            "success": True,
            "org_id": org_id,
            "date": today_label,
            "time_window": today_label,
            "definition": (
                "Unique customers who sent at least one chat message to the customer agent today, and the count of "
                "customer accounts created today. Admin chats are not counted."
            ),
            "metrics": {
                "unique_customers_chatted": len(active_customer_ids),
                "new_signups_today": len(new_users),
                "new_user_emails": [u.email for u in new_users]
            }
        }

    @staticmethod
    async def get_conversion_rate(db: AsyncSession, org_id: str, time_window_days: int = 30) -> Dict[str, Any]:
        """
        Conversations that led to an order (retail) or booking (studio) / all customer conversations in the period.
        A conversation converts only when an order or booking row carries its conversation_id. A staged
        proposal that the customer never confirmed is not a conversion.
        """
        time_window_days = max(1, min(int(time_window_days), 365))
        since_dt, time_window_label = _window(time_window_days)
        retail = await _is_retail(db, org_id)

        conversation_ids = set((await db.execute(
            select(Conversation.id).where(
                Conversation.org_id == org_id,
                Conversation.agent_type == "customer",
                Conversation.created_at >= since_dt,
            )
        )).scalars().all())

        if retail:
            linked = (await db.execute(
                select(distinct(Order.conversation_id)).where(Order.org_id == org_id, Order.conversation_id.isnot(None))
            )).scalars().all()
        else:
            linked = (await db.execute(
                select(distinct(Booking.conversation_id)).where(Booking.org_id == org_id, Booking.conversation_id.isnot(None))
            )).scalars().all()
        converted = conversation_ids & set(linked)

        total = len(conversation_ids)
        noun = "order" if retail else "booking"
        return {
            "success": True,
            "org_id": org_id,
            "time_window": time_window_label,
            "definition": (
                f"Formula: (customer conversations started in the window that produced at least one confirmed {noun}) / "
                "(all customer conversations started in the window) x 100. Staged but unconfirmed proposals do not count."
            ),
            "metrics": {
                "total_conversations": total,
                "converted_conversations": len(converted),
                "conversion_rate_percentage": round(len(converted) / max(1, total) * 100, 1)
            }
        }

    @staticmethod
    async def get_top_items(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        """
        Retail: best-selling products (OrderItem) and items most often out of stock (InventoryEvent).
        Studio: most-booked services and busiest time slots (non-cancelled bookings).
        """
        if await _is_retail(db, org_id):
            sold_rows = (await db.execute(
                select(OrderItem.sku, func.sum(OrderItem.quantity))
                .join(Order, Order.id == OrderItem.order_id)
                .where(OrderItem.org_id == org_id, Order.status != "cancelled")
                .group_by(OrderItem.sku)
            )).all()
            sales_map = {sku: int(total) for sku, total in sold_rows}

            products = (await db.execute(select(Product).where(Product.org_id == org_id))).scalars().all()
            ranked_products = [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "category": p.category,
                    "units_sold": sales_map.get(p.sku, 0),
                    "current_stock": p.stock
                }
                for p in products
            ]
            best_sellers = sorted(
                (row for row in ranked_products if row["units_sold"] > 0),
                key=lambda row: row["units_sold"], reverse=True,
            )[:5]

            stockout_counts = {
                sku: int(count)
                for sku, count in (await db.execute(
                    select(InventoryEvent.sku, func.count())
                    .where(InventoryEvent.org_id == org_id, InventoryEvent.stock_after == 0)
                    .group_by(InventoryEvent.sku)
                )).all()
            }
            attention = []
            for row in ranked_products:
                stockouts = stockout_counts.get(row["sku"], 0)
                if row["current_stock"] <= 5 or stockouts:
                    attention.append({**row, "historical_stockouts": stockouts})
            attention.sort(key=lambda row: (row["historical_stockouts"], -row["current_stock"]), reverse=True)

            return {
                "success": True,
                "org_id": org_id,
                "kind": "retail",
                "time_window": "All time",
                "definition": (
                    "Best sellers: top 5 products by units on non-cancelled orders (all time). Out-of-stock watchlist: "
                    "products with 5 or fewer units now, ranked by how many inventory events left them at 0 (all time)."
                ),
                "best_selling_products": best_sellers,
                "low_or_out_of_stock_items": attention
            }

        bookings = (await db.execute(
            select(Booking).where(Booking.org_id == org_id, Booking.status != "cancelled")
        )).scalars().all()
        service_counts: Dict[str, int] = {}
        hour_counts: Dict[str, int] = {}
        for b in bookings:
            service_counts[b.service_id] = service_counts.get(b.service_id, 0) + 1
            hour_key = f"{b.start_time.hour:02d}:00-{(b.start_time.hour + 1) % 24:02d}:00"
            hour_counts[hour_key] = hour_counts.get(hour_key, 0) + 1

        services = (await db.execute(select(Service).where(Service.org_id == org_id))).scalars().all()
        ranked_services = sorted(
            (
                {
                    "service_id": s.id,
                    "service_name": s.name,
                    "duration_minutes": s.duration_minutes,
                    "price": s.price,
                    "total_bookings": service_counts.get(s.id, 0)
                }
                for s in services
            ),
            key=lambda row: row["total_bookings"], reverse=True,
        )
        busiest_hours = sorted(
            ({"hour": k, "bookings": v} for k, v in hour_counts.items()),
            key=lambda row: row["bookings"], reverse=True,
        )

        return {
            "success": True,
            "org_id": org_id,
            "kind": "studio",
            "time_window": "All time",
            "definition": (
                "Most-booked services: non-cancelled bookings per service (all time). Busiest time slots: "
                "non-cancelled bookings grouped by the hour the appointment starts, in Asia/Kathmandu."
            ),
            "most_booked_services": ranked_services,
            "busiest_time_slots": busiest_hours[:5]
        }
