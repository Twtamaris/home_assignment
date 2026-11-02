import datetime
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from app.models.models import (
    Order, OrderItem, Booking, User, Conversation, Product, Service,
    Practitioner, Message, InventoryEvent
)

class AdminAnalyticsTools:
    """
    Read-only Analytics Agent Tools for Store & Studio Admins.
    Strictly scoped to the admin's own org_id.
    Customer roles are blocked at the endpoint layer with HTTP 403.
    """

    @staticmethod
    async def get_activity_summary(db: AsyncSession, org_id: str, time_window_days: int = 30) -> Dict[str, Any]:
        """
        Activity summary:
        Org A: Orders by status, gross revenue, average order value.
        Org B: Bookings by status, cancellations, practitioner utilisation.
        """
        since_dt = datetime.datetime.utcnow() - datetime.timedelta(days=time_window_days)
        time_window_label = f"Last {time_window_days} days (from {since_dt.strftime('%Y-%m-%d')} UTC to present)"

        if org_id == "org_a":
            # Orders summary
            stmt = select(Order).where(Order.org_id == org_id, Order.created_at >= since_dt)
            res = await db.execute(stmt)
            orders = res.scalars().all()

            status_counts = {}
            total_revenue = 0.0
            confirmed_or_higher = ["confirmed", "shipped", "delivered"]
            revenue_order_count = 0

            for o in orders:
                status_counts[o.status] = status_counts.get(o.status, 0) + 1
                if o.status in confirmed_or_higher:
                    total_revenue += o.total_price
                    revenue_order_count += 1

            aov = round(total_revenue / revenue_order_count, 2) if revenue_order_count > 0 else 0.0

            return {
                "success": True,
                "org_id": org_id,
                "time_window": time_window_label,
                "definition": "Gross revenue and Average Order Value (AOV) calculated for all confirmed, shipped, and delivered orders within the specified date window.",
                "metrics": {
                    "total_orders": len(orders),
                    "orders_by_status": status_counts,
                    "gross_revenue_npr": round(total_revenue, 2),
                    "paid_order_count": revenue_order_count,
                    "average_order_value_npr": aov
                }
            }
        else:
            # Org B: Bookings summary
            stmt = select(Booking).where(Booking.org_id == org_id, Booking.created_at >= since_dt)
            res = await db.execute(stmt)
            bookings = res.scalars().all()

            status_counts = {}
            practitioner_bookings = {}
            total_cancellations = 0

            for b in bookings:
                status_counts[b.status] = status_counts.get(b.status, 0) + 1
                if b.status == "cancelled":
                    total_cancellations += 1
                else:
                    practitioner_bookings[b.practitioner_id] = practitioner_bookings.get(b.practitioner_id, 0) + 1

            # Fetch practitioners
            p_stmt = select(Practitioner).where(Practitioner.org_id == org_id)
            p_res = await db.execute(p_stmt)
            practitioners = p_res.scalars().all()

            utilisation_summary = []
            for p in practitioners:
                count = practitioner_bookings.get(p.id, 0)
                utilisation_summary.append({
                    "practitioner_id": p.id,
                    "practitioner_name": p.name,
                    "total_sessions": count,
                    "share_percentage": round((count / max(1, len(bookings) - total_cancellations)) * 100, 1)
                })

            return {
                "success": True,
                "org_id": org_id,
                "time_window": time_window_label,
                "definition": "Total bookings received, broken down by lifecycle status (confirmed, rescheduled, cancelled) and individual practitioner session volume.",
                "metrics": {
                    "total_bookings": len(bookings),
                    "bookings_by_status": status_counts,
                    "cancellations": total_cancellations,
                    "cancellation_rate_percentage": round((total_cancellations / max(1, len(bookings))) * 100, 1),
                    "practitioner_utilisation": utilisation_summary
                }
            }

    @staticmethod
    async def get_clients_today(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        """
        Unique customers who chatted today; new sign-ups today.
        """
        today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_label = f"Today UTC ({today_start.strftime('%Y-%m-%d')})"

        # 1. Unique customers who chatted today
        chat_stmt = select(distinct(Conversation.user_id)).join(
            Message, Message.conversation_id == Conversation.id
        ).where(
            Conversation.org_id == org_id,
            Message.created_at >= today_start,
            Message.sender == "user"
        )
        chat_res = await db.execute(chat_stmt)
        active_customer_ids = chat_res.scalars().all()

        # 2. New sign-ups today
        signup_stmt = select(User).where(
            User.org_id == org_id,
            User.created_at >= today_start,
            User.role == "customer"
        )
        signup_res = await db.execute(signup_stmt)
        new_users = signup_res.scalars().all()

        return {
            "success": True,
            "org_id": org_id,
            "date": today_label,
            "definition": "Unique customers who actively dispatched chat messages in conversations today, and count of newly registered customer accounts created since 00:00 UTC.",
            "metrics": {
                "unique_customers_chatted": len(active_customer_ids),
                "new_signups_today": len(new_users),
                "new_user_emails": [u.email for u in new_users]
            }
        }

    @staticmethod
    async def get_conversion_rate(db: AsyncSession, org_id: str, time_window_days: int = 30) -> Dict[str, Any]:
        """
        Conversion rate:
        Conversations that led to an order (Org A) or booking (Org B) ÷ all conversations in the period.
        Directly links orders/bookings to conversations via foreign key with heuristic fallback.
        """
        since_dt = datetime.datetime.utcnow() - datetime.timedelta(days=time_window_days)
        time_window_label = f"Last {time_window_days} days"

        # All customer conversations in period
        conv_stmt = select(Conversation).where(
            Conversation.org_id == org_id,
            Conversation.agent_type == "customer",
            Conversation.created_at >= since_dt
        )
        conv_res = await db.execute(conv_stmt)
        conversations = conv_res.scalars().all()
        total_conv = len(conversations)

        # Relational check: conversations with an order or booking foreign key
        if org_id == "org_a":
            ord_conv_stmt = select(distinct(Order.conversation_id)).where(
                Order.org_id == org_id,
                Order.conversation_id.isnot(None),
                Order.created_at >= since_dt
            )
            ord_conv_res = await db.execute(ord_conv_stmt)
            converted_conv_ids = set(r for r in ord_conv_res.scalars().all() if r)
        else:
            bkg_conv_stmt = select(distinct(Booking.conversation_id)).where(
                Booking.org_id == org_id,
                Booking.conversation_id.isnot(None),
                Booking.created_at >= since_dt
            )
            bkg_conv_res = await db.execute(bkg_conv_stmt)
            converted_conv_ids = set(r for r in bkg_conv_res.scalars().all() if r)

        # Count conversations that converted either via FK or via card/tool trace
        converted_conv_count = 0
        for conv in conversations:
            if conv.id in converted_conv_ids:
                converted_conv_count += 1
                continue

            m_stmt = select(Message).where(
                Message.conversation_id == conv.id,
                Message.sender == "agent"
            )
            m_res = await db.execute(m_stmt)
            msgs = m_res.scalars().all()
            has_converted = any(
                ("order_placed" in (m.card_json or "") or "create_order" in (m.tool_calls_json or ""))
                if org_id == "org_a"
                else ("booking_confirmed" in (m.card_json or "") or "create_booking" in (m.tool_calls_json or ""))
                for m in msgs
            )
            if has_converted:
                converted_conv_count += 1

        conv_rate = round((converted_conv_count / max(1, total_conv)) * 100, 1)

        return {
            "success": True,
            "org_id": org_id,
            "time_window": time_window_label,
            "definition": (
                "Formula: (Conversations resulting in a completed order or confirmed booking) / (Total customer conversations initiated) * 100."
            ),
            "metrics": {
                "total_conversations": total_conv,
                "converted_conversations": converted_conv_count,
                "conversion_rate_percentage": conv_rate
            }
        }

    @staticmethod
    async def get_top_items(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        """
        Top items:
        Org A: Best-selling products (from OrderItem); items most often out of stock (from InventoryEvent).
        Org B: Most-booked services; busiest time slots.
        """
        if org_id == "org_a":
            # Best selling products using OrderItem table
            item_stmt = (
                select(
                    OrderItem.sku,
                    OrderItem.name,
                    func.sum(OrderItem.quantity).label("units_sold")
                )
                .where(OrderItem.org_id == org_id)
                .group_by(OrderItem.sku, OrderItem.name)
                .order_by(func.sum(OrderItem.quantity).desc())
            )
            item_res = await db.execute(item_stmt)
            item_rows = item_res.all()

            sales_map = {r[0]: (r[1], int(r[2])) for r in item_rows}

            p_stmt = select(Product).where(Product.org_id == org_id)
            p_res = await db.execute(p_stmt)
            products = p_res.scalars().all()

            ranked_products = []
            for p in products:
                units_sold = sales_map.get(p.sku, (p.name, 0))[1]
                ranked_products.append({
                    "sku": p.sku,
                    "name": p.name,
                    "category": p.category,
                    "units_sold": units_sold,
                    "current_stock": p.stock
                })

            # Sort best-selling
            best_sellers = sorted(ranked_products, key=lambda x: x["units_sold"], reverse=True)[:5]

            # Out of stock and low stock items (<= 5)
            low_stock = [p for p in ranked_products if p["current_stock"] <= 5]

            # Historical stockouts from InventoryEvent
            inv_stmt = (
                select(InventoryEvent.sku, func.count().label("out_of_stock_events"))
                .where(InventoryEvent.org_id == org_id, InventoryEvent.stock_after == 0)
                .group_by(InventoryEvent.sku)
            )
            inv_res = await db.execute(inv_stmt)
            stockout_counts = {r[0]: int(r[1]) for r in inv_res.all()}

            for p in low_stock:
                p["historical_stockouts"] = stockout_counts.get(p["sku"], 0)

            return {
                "success": True,
                "org_id": org_id,
                "definition": "Top 5 best-selling teas/teaware by cumulative unit sales (from OrderItem lines), and inventory items currently with <= 5 units or historical stockouts.",
                "best_selling_products": best_sellers,
                "low_or_out_of_stock_items": low_stock
            }
        else:
            # Org B: Most-booked services & busiest hours
            b_stmt = select(Booking).where(Booking.org_id == org_id)
            b_res = await db.execute(b_stmt)
            bookings = b_res.scalars().all()

            service_counts = {}
            hour_counts = {}
            for b in bookings:
                service_counts[b.service_id] = service_counts.get(b.service_id, 0) + 1
                hour_key = f"{b.start_time.hour:02d}:00"
                hour_counts[hour_key] = hour_counts.get(hour_key, 0) + 1

            s_stmt = select(Service).where(Service.org_id == org_id)
            s_res = await db.execute(s_stmt)
            services = s_res.scalars().all()

            ranked_services = []
            for s in services:
                ranked_services.append({
                    "service_id": s.id,
                    "service_name": s.name,
                    "duration_minutes": s.duration_minutes,
                    "price": s.price,
                    "total_bookings": service_counts.get(s.id, 0)
                })

            ranked_services.sort(key=lambda x: x["total_bookings"], reverse=True)
            busiest_hours = sorted([{"hour": k, "bookings": v} for k, v in hour_counts.items()], key=lambda x: x["bookings"], reverse=True)

            return {
                "success": True,
                "org_id": org_id,
                "definition": "Most requested therapies ranked by booking count, alongside distribution of appointment start hours.",
                "most_booked_services": ranked_services,
                "busiest_time_slots": busiest_hours[:5]
            }

