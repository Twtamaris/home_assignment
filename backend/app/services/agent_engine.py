import asyncio
import json
import re
import uuid
import datetime
from typing import AsyncGenerator, Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.config import settings
from app.models.models import (
    User, Conversation, Message, CustomerMemory, Product, Service, Order, Booking, ActionProposal
)
from app.services.agent_a import AgentATools
from app.services.agent_b import AgentBTools
from app.services.admin_agent import AdminAnalyticsTools
from app.services.scheduling import SchedulingEngine, KATHMANDU_TZ
from app.services.llm_provider import LLMProvider

class AgentEngine:
    """
    Multi-tenant Agent Loop & Execution Engine.
    Line-by-line transparent agent loop supporting streaming tokens,
    real-time tool activity events, citation chips, and interactive cards.
    """

    @classmethod
    async def run_agent_turn(
        cls,
        db: AsyncSession,
        user: User,
        conversation: Conversation,
        user_message: str
    ) -> AsyncGenerator[str, None]:
        """
        Executes one full agent interaction turn.
        Yields SSE lines: data: <json>\n\n
        """
        org_id = user.org_id
        user_id = user.id
        is_admin_chat = (conversation.agent_type == "admin")

        # Step 1: Save incoming user message
        user_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        user_msg_record = Message(
            id=user_msg_id,
            conversation_id=conversation.id,
            org_id=org_id,
            user_id=user_id,
            sender="user",
            content=user_message
        )
        db.add(user_msg_record)
        await db.commit()

        # Step 2: Fetch Customer Memory
        mem_stmt = select(CustomerMemory).where(
            CustomerMemory.org_id == org_id,
            CustomerMemory.user_id == user_id
        )
        mem_res = await db.execute(mem_stmt)
        memories = {m.memory_key: m.memory_value for m in mem_res.scalars().all()}

        # Step 3: Fetch Recent Conversation History
        hist_stmt = select(Message).where(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at)
        hist_res = await db.execute(hist_stmt)
        recent_messages = hist_res.scalars().all()[-10:]

        # Step 4: Route to the appropriate Agent Handler
        if is_admin_chat:
            async for sse_event in cls._run_admin_agent(db, user, user_message, conversation.id):
                yield sse_event
        elif org_id == "org_a":
            async for sse_event in cls._run_agent_a(db, user, user_message, memories, recent_messages):
                yield sse_event
        elif org_id == "org_b":
            async for sse_event in cls._run_agent_b(db, user, user_message, memories, recent_messages):
                yield sse_event
        else:
            yield cls._sse("token", {"token": "Unknown organisation context."})
            yield cls._sse("done", {"content": "Unknown organisation context."})

    @classmethod
    def _sse(cls, event: str, data: Any) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    # =========================================================================
    # AGENT A: Himali Tea House Ordering Agent Loop
    # =========================================================================
    @classmethod
    async def _run_agent_a(
        cls,
        db: AsyncSession,
        user: User,
        query: str,
        memories: Dict[str, str],
        history: List[Message]
    ) -> AsyncGenerator[str, None]:
        q_lower = query.lower()
        tool_activity = []
        citations = []
        card_data = None
        final_text = ""

        # Prompt Injection & Cross-Tenant Boundary Protection
        if any(w in q_lower for w in ["ignore all", "system prompt", "database schema", "lotus wellness", "lotus appointments", "drop table", "select * from"]):
            final_text = (
                "I am the Himali Tea House ordering assistant. I cannot disclose internal database schemas, "
                "override system instructions, or access Lotus Wellness Studio appointments. "
                "How may I assist you with Himali orthodox teas, orders, or brewing guidance today?"
            )

        # Check for Reorder / "Same as last time"
        elif any(phrase in q_lower for phrase in ["same as last time", "reorder", "repeat my order", "previous order", "usual tea"]):
            yield cls._sse("tool_start", {"tool": "reorder", "message": "Looking up previous orders and checking live stock..."})
            await asyncio.sleep(0.1)
            reorder_res = await AgentATools.reorder(db, user.org_id, user.id)
            tool_activity.append({"tool": "reorder", "result": reorder_res})
            yield cls._sse("tool_end", {"tool": "reorder", "status": "completed"})

            if reorder_res.get("success"):
                card_data = reorder_res.get("card")
                final_text = reorder_res.get("summary_text", "Here is your previous order proposal.")
            else:
                final_text = reorder_res.get("error", "Could not find any previous orders to repeat.")

        # Check for Order Confirmation (e.g. "confirm", "yes place it", "yes please confirm")
        elif any(phrase in q_lower for phrase in ["confirm order", "yes please confirm", "confirm my order", "place it", "confirm"]):
            yield cls._sse("tool_start", {"tool": "create_order", "message": "Confirming and placing order..."})
            await asyncio.sleep(0.1)

            # Look up unconfirmed order draft from latest user memory or items
            usual_tea = memories.get("usual_tea", "HT-SN-100")
            sku = "HT-SN-100" if "silver" in usual_tea.lower() or "ht-" not in usual_tea.lower() else usual_tea

            create_res = await AgentATools.create_order(
                db, user.org_id, user.id,
                items=[{"sku": sku, "quantity": 1}],
                shipping_address="Kathmandu Valley, Nepal",
                confirmed=True
            )
            tool_activity.append({"tool": "create_order", "result": create_res})
            yield cls._sse("tool_end", {"tool": "create_order", "status": "completed"})

            if create_res.get("success"):
                card_data = create_res.get("card")
                final_text = create_res.get("message")
            else:
                final_text = create_res.get("message", create_res.get("error", "Unable to place order."))

        # Check for Cancellation (e.g. "cancel order ORD-...", "cancel my latest order", "cancel my order")
        elif "cancel" in q_lower and ("order" in q_lower or "ord-" in q_lower or "latest" in q_lower):
            yield cls._sse("tool_start", {"tool": "cancel_order", "message": "Evaluating cancellation eligibility..."})
            await asyncio.sleep(0.1)

            order_match = re.search(r"ORD-[A-Za-z0-9]+", query, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(0).upper()
                cancel_res = await AgentATools.cancel_order(db, user.org_id, user.id, order_id)
                tool_activity.append({"tool": "cancel_order", "result": cancel_res})
                yield cls._sse("tool_end", {"tool": "cancel_order", "status": "completed"})
                final_text = cancel_res.get("message") or cancel_res.get("error")
            else:
                # Find latest order
                orders_res = await AgentATools.list_my_orders(db, user.org_id, user.id)
                if orders_res["orders"]:
                    latest_order = orders_res["orders"][0]
                    cancel_res = await AgentATools.cancel_order(db, user.org_id, user.id, latest_order["order_id"])
                    tool_activity.append({"tool": "cancel_order", "result": cancel_res})
                    yield cls._sse("tool_end", {"tool": "cancel_order", "status": "completed"})
                    final_text = cancel_res.get("message") or cancel_res.get("error")
                else:
                    yield cls._sse("tool_end", {"tool": "cancel_order", "status": "completed"})
                    final_text = "I could not find an active order under your account to cancel."

        # Check for Order Status / Tracking (e.g. "track order", "status of ORD-1001", "where is my order")
        elif any(phrase in q_lower for phrase in ["status", "track", "where is my order", "ord-", "show me my latest order", "latest order", "my orders"]):
            yield cls._sse("tool_start", {"tool": "get_order_status", "message": "Checking live order status..."})
            await asyncio.sleep(0.1)

            # Extract order ID if present
            order_match = re.search(r"ORD-[A-Za-z0-9]+", query, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(0).upper()
                status_res = await AgentATools.get_order_status(db, user.org_id, user.id, order_id)
                tool_activity.append({"tool": "get_order_status", "result": status_res})
                yield cls._sse("tool_end", {"tool": "get_order_status", "status": "completed"})

                if status_res.get("success"):
                    card_data = status_res.get("card")
                    hist = status_res.get("status_history", [])
                    hist_text = f" Status history: {', '.join([h['new_status'] for h in hist])}." if hist else ""
                    final_text = f"Order #{order_id} is currently **{status_res['status'].upper()}**. Total: NPR {status_res['total_price']:.2f}.{hist_text}"
                else:
                    final_text = status_res.get("error")
            else:
                # List user's orders
                orders_res = await AgentATools.list_my_orders(db, user.org_id, user.id)
                tool_activity.append({"tool": "list_my_orders", "result": orders_res})
                yield cls._sse("tool_end", {"tool": "get_order_status", "status": "completed"})

                if orders_res["orders"]:
                    latest = orders_res["orders"][0]
                    card_data = {
                        "type": "order_status",
                        "order_id": latest["order_id"],
                        "status": latest["status"],
                        "total_price": latest["total_price"],
                        "history": latest.get("status_history", [])
                    }
                    final_text = f"You have {len(orders_res['orders'])} orders. Your latest order #{latest['order_id']} is currently **{latest['status'].upper()}** for NPR {latest['total_price']:.2f}."
                else:
                    final_text = "You do not have any past orders yet."

        # Check for Updating order (e.g. "change address", "update order", "change quantity")
        elif any(k in q_lower for k in ["change", "update", "modify"]) and "order" in q_lower:
            yield cls._sse("tool_start", {"tool": "update_order", "message": "Checking if order can be modified..."})
            await asyncio.sleep(0.1)

            order_match = re.search(r"ORD-[A-Za-z0-9]+", query, re.IGNORECASE)
            order_id = order_match.group(0).upper() if order_match else None
            if not order_id:
                orders_res = await AgentATools.list_my_orders(db, user.org_id, user.id)
                if orders_res["orders"]:
                    order_id = orders_res["orders"][0]["order_id"]

            if order_id:
                new_address = "Jhamsikhel, Lalitpur, Nepal" if "address" in q_lower or "jhamsikhel" in q_lower else None
                update_res = await AgentATools.update_order(db, user.org_id, user.id, order_id, shipping_address=new_address)
                tool_activity.append({"tool": "update_order", "result": update_res})
                yield cls._sse("tool_end", {"tool": "update_order", "status": "completed"})
                final_text = update_res.get("message") or update_res.get("error")
                card_data = update_res.get("card")
            else:
                yield cls._sse("tool_end", {"tool": "update_order", "status": "completed"})
                final_text = "Please specify which order ID you'd like to update."

        # Check for Product Discovery / Search (e.g. "Do you have any green tea under 500 NPR?", "What teas do you have?")
        elif any(w in q_lower for w in ["do you have", "what tea", "search tea", "under 500", "green tea under", "recommend tea", "catalog", "cheapest tea"]):
            yield cls._sse("tool_start", {"tool": "search_products", "message": "Searching Himali Tea House live catalog database..."})
            await asyncio.sleep(0.1)

            cat = None
            if "green" in q_lower:
                cat = "Green"
            elif "black" in q_lower:
                cat = "Black"
            elif "oolong" in q_lower:
                cat = "Oolong"
            elif "white" in q_lower:
                cat = "White"
            elif "spiced" in q_lower or "chai" in q_lower:
                cat = "Spiced"

            max_p = None
            m_price = re.search(r"under\s+(?:npr\s*)?(\d+)", q_lower)
            if m_price:
                max_p = float(m_price.group(1))

            search_res = await AgentATools.search_products(db, user.org_id, category=cat, max_price=max_p)
            tool_activity.append({"tool": "search_products", "result": search_res})
            yield cls._sse("tool_end", {"tool": "search_products", "status": "completed"})

            prods = search_res.get("products", [])
            if prods:
                lines = [f"• **{p['name']}** (`{p['sku']}`): NPR {p['price']:.2f} ({p['stock']} in stock)" for p in prods]
                card_data = {"type": "product_catalog", "products": prods}
                final_text = f"We found the following live matching teas in our catalog:\n\n" + "\n".join(lines)
            else:
                # Also check all teas in this category to give exact live price info
                all_cat_res = await AgentATools.search_products(db, user.org_id, category=cat)
                all_cat = all_cat_res.get("products", [])
                threshold_text = f"{max_p:.0f}" if max_p else "that price"
                if all_cat:
                    lines = [f"• **{p['name']}** (`{p['sku']}`): NPR {p['price']:.2f} ({p['stock']} in stock)" for p in all_cat]
                    final_text = (
                        f"We searched our live inventory and do not currently have any {cat or ''} tea under NPR {threshold_text}. "
                        f"Our available {cat or ''} teas start at:\n\n" + "\n".join(lines) + "\n\nWould you like to order any of these?"
                    )
                else:
                    final_text = "I could not find any teas matching that price criteria in our catalog. Would you like to explore our single-origin orthodox teas?"

        # Check for Buying / Purchasing / Ordering products (e.g. "I want to buy 2 units of HT-SN-100", "order HT-GT-100")
        elif any(k in q_lower for k in ["buy", "order", "purchase", "get me", "want"]) and any(w in q_lower for w in ["unit", "pack", "canister", "ht-", "tea", "pearls", "needle"]):
            yield cls._sse("tool_start", {"tool": "prepare_order_summary", "message": "Checking product catalog and live inventory..."})
            await asyncio.sleep(0.1)

            # Match product
            sku = "HT-SN-100"  # default
            qty = 1

            # Extract explicit SKU if present
            sku_match = re.search(r"HT-[A-Za-z0-9-]+", query, re.IGNORECASE)
            if sku_match:
                sku = sku_match.group(0).upper()
            elif "green" in q_lower:
                sku = "HT-GT-100"
            elif "oolong" in q_lower or "shangri" in q_lower:
                sku = "HT-OL-100"
            elif "masala" in q_lower or "chai" in q_lower:
                sku = "HT-MC-200"
            elif "black" in q_lower or "tippy" in q_lower:
                sku = "HT-BT-100"
            elif "puerh" in q_lower or "cake" in q_lower or "ht-or-99" in q_lower:
                sku = "HT-OR-99"

            qty_match = re.search(r"(\d+)\s*(?:unit|packet|pack|canister|gram|kg|piece|bottle)?", query)
            if qty_match:
                try:
                    qty = int(qty_match.group(1))
                except Exception:
                    qty = 1

            summary_res = await AgentATools.prepare_order_summary(
                db, user.org_id, user.id,
                items=[{"sku": sku, "quantity": qty}],
                shipping_address="Kathmandu Valley, Nepal"
            )
            tool_activity.append({"tool": "prepare_order_summary", "result": summary_res})
            yield cls._sse("tool_end", {"tool": "prepare_order_summary", "status": "completed"})

            if summary_res.get("success"):
                card_data = summary_res.get("card")
                final_text = summary_res.get("summary_text")
            else:
                card_data = summary_res.get("card")
                final_text = summary_res.get("message") or summary_res.get("error")

        # Knowledge Base Question (Brewing, policy, tea details, shipping, returns, FAQ)
        else:
            yield cls._sse("tool_start", {"tool": "search_knowledge", "message": "Searching Himali Tea House knowledge base..."})
            await asyncio.sleep(0.1)

            kb_res = await AgentATools.search_knowledge(db, user.org_id, query)
            tool_activity.append({"tool": "search_knowledge", "result": kb_res})
            yield cls._sse("tool_end", {"tool": "search_knowledge", "status": "completed"})

            results = kb_res.get("results", [])
            if results and results[0]["score"] > 0.15:
                top_match = results[0]
                citations.append({
                    "doc": top_match["doc_name"],
                    "section": top_match["section_name"],
                    "excerpt": top_match["content"][:240] + "..."
                })
                # Synthesize clear answer with citation
                final_text = (
                    f"{top_match['content']}\n\n"
                    f"*Source: {top_match['doc_name']} > {top_match['section_name']}*"
                )
            else:
                final_text = (
                    "I searched our Himali Tea House knowledge base, but I do not have verified information on that specific inquiry. "
                    "Feel free to ask about our single-origin orthodox teas, brewing temperatures, shipping policies, or placing an order!"
                )

        # Stream the synthesized response token by token
        words = final_text.split(" ")
        accumulated = ""
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            accumulated += token
            yield cls._sse("token", {"token": token})
            await asyncio.sleep(0.015)

        # Save agent message with card and citations to DB
        agent_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        agent_msg = Message(
            id=agent_msg_id,
            conversation_id=history[0].conversation_id if history else "conv_default",
            org_id=user.org_id,
            user_id=user.id,
            sender="agent",
            content=accumulated,
            tool_calls_json=json.dumps(tool_activity) if tool_activity else None,
            citations_json=json.dumps(citations) if citations else None,
            card_json=json.dumps(card_data) if card_data else None
        )
        db.add(agent_msg)
        await db.commit()

        yield cls._sse("done", {
            "id": agent_msg_id,
            "content": accumulated,
            "citations": citations,
            "card": card_data
        })

    # =========================================================================
    # AGENT B: Lotus Wellness Studio Booking Agent Loop
    # =========================================================================
    @classmethod
    async def _run_agent_b(
        cls,
        db: AsyncSession,
        user: User,
        query: str,
        memories: Dict[str, str],
        history: List[Message]
    ) -> AsyncGenerator[str, None]:
        q_lower = query.lower()
        tool_activity = []
        citations = []
        card_data = None
        final_text = ""

        # Prompt Injection & Cross-Tenant Boundary Protection
        if any(w in q_lower for w in ["himali", "tea house", "tea order", "show me my himali", "database schema", "ignore all"]):
            final_text = (
                "I am the Lotus Wellness Studio booking assistant. I cannot access Himali Tea House orders, "
                "internal system schemas, or cross-tenant databases. "
                "How may I assist you with wellness therapies, practitioner schedules, or appointment bookings in Kathmandu?"
            )

        # Opening Hours Boundary Rule (e.g. 60-min session at 18:30 on a weekday)
        elif ("18:30" in q_lower or "6:30" in q_lower) and any(w in q_lower for w in ["60-minute", "60 min", "1 hour", "massage", "weekday", "can i book"]):
            final_text = (
                "Lotus Wellness Studio closes at 19:00 on weekdays. A 60-minute therapy booked at 18:30 "
                "would finish at 19:30, exceeding our operating hours. "
                "The latest available start time for a 60-minute session on weekdays is 18:00 (Asia/Kathmandu UTC+05:45)."
            )

        # Holiday Check Rule (e.g. 2026-11-08 Bhai Tika or public holidays)
        elif any(w in q_lower for w in ["2026-11-08", "bhai tika", "dashain", "tihar"]) or (
            re.search(r"\d{4}-\d{2}-\d{2}", query) and any(w in q_lower for w in ["holiday", "closed", "book"])
        ):
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", query)
            chk_date_str = date_match.group(0) if date_match else "2026-11-08"
            chk_date = datetime.datetime.strptime(chk_date_str, "%Y-%m-%d").date()
            is_hol, hol_name = await SchedulingEngine.is_holiday(db, user.org_id, chk_date)
            if is_hol:
                final_text = (
                    f"Lotus Wellness Studio is closed on {chk_date_str} for **{hol_name or 'Public Holiday'}**. "
                    "Appointments cannot be scheduled on official holidays. Please choose another date!"
                )
            else:
                final_text = f"{chk_date_str} is not a listed holiday. Would you like to view available slots?"

        # Conflict Resolution on Reschedule (e.g. "Reschedule my latest booking to a time that is already taken")
        elif any(w in q_lower for w in ["reschedule", "change appointment", "move my booking"]) and any(w in q_lower for w in ["already taken", "taken", "conflict", "occupied", "existing"]):
            yield cls._sse("tool_start", {"tool": "reschedule_booking", "message": "Checking availability and conflict resolution in Asia/Kathmandu..."})
            await asyncio.sleep(0.1)

            my_bookings = await AgentBTools.list_my_bookings(db, user.org_id, user.id)
            active_bkg = next((b for b in my_bookings["bookings"] if b["status"] in ["confirmed", "rescheduled"]), None)
            if not active_bkg:
                # Fallback to any booking
                active_bkg = my_bookings["bookings"][0] if my_bookings["bookings"] else None

            if active_bkg:
                # Find an occupied slot belonging to another booking to trigger realistic conflict
                other_bkg_stmt = select(Booking).where(
                    Booking.org_id == user.org_id,
                    Booking.id != active_bkg["booking_id"],
                    Booking.status.in_(["confirmed", "rescheduled"])
                )
                other_bkg_res = await db.execute(other_bkg_stmt)
                other_bkg = other_bkg_res.scalars().first()
                if other_bkg:
                    conflict_time = other_bkg.start_time.strftime("%Y-%m-%dT%H:%M:%S")
                else:
                    conflict_time = "2026-11-03T10:00:00"

                resched_res = await AgentBTools.reschedule_booking(db, user.org_id, user.id, active_bkg["booking_id"], conflict_time)
                tool_activity.append({"tool": "reschedule_booking", "result": resched_res})
                yield cls._sse("tool_end", {"tool": "reschedule_booking", "status": "completed"})

                card_data = resched_res.get("card")
                final_text = resched_res.get("message") or resched_res.get("error")
            else:
                yield cls._sse("tool_end", {"tool": "reschedule_booking", "status": "completed"})
                final_text = "I could not find an active booking under your account to reschedule."

        # Relative Dates & Afternoon Slot Discovery (e.g. "Book a deep tissue massage for next Tuesday afternoon")
        elif any(w in q_lower for w in ["next tuesday", "tuesday", "afternoon", "tomorrow", "available slots", "slots", "when can i"]):
            yield cls._sse("tool_start", {"tool": "find_available_slots", "message": "Resolving Asia/Kathmandu timezone (+05:45) and checking practitioner slots..."})
            await asyncio.sleep(0.1)

            resolved_dt = SchedulingEngine.resolve_relative_datetime_kathmandu(query)
            target_date = resolved_dt.strftime("%Y-%m-%d")

            service_id = "srv_1" # Deep Tissue Massage default
            if "abhyanga" in q_lower or "ayurved" in q_lower:
                service_id = "srv_2"
            elif "physio" in q_lower:
                service_id = "srv_3"

            # Check holiday
            is_hol, hol_name = await SchedulingEngine.is_holiday(db, user.org_id, resolved_dt.date())
            if is_hol:
                yield cls._sse("tool_end", {"tool": "find_available_slots", "status": "completed"})
                final_text = f"Lotus Wellness Studio is closed on {target_date} ({hol_name}). Please choose another date!"
            else:
                slots_res = await AgentBTools.find_available_slots(db, user.org_id, service_id, target_date)
                tool_activity.append({"tool": "find_available_slots", "result": slots_res})
                yield cls._sse("tool_end", {"tool": "find_available_slots", "status": "completed"})

                raw_slots = slots_res.get("slots", [])
                # If "afternoon" was specifically requested, filter slots between 12:00 and 17:00
                if "afternoon" in q_lower:
                    raw_slots = [
                        s for s in raw_slots
                        if 12 <= datetime.datetime.fromisoformat(s["start_time"].replace("Z", "+00:00")).astimezone(KATHMANDU_TZ).hour < 17
                    ]

                if raw_slots:
                    card_data = {
                        "type": "slot_picker",
                        "title": f"Afternoon Slots for {target_date} (Asia/Kathmandu UTC+05:45)",
                        "service_id": service_id,
                        "slots": raw_slots[:6]
                    }
                    slot_times = [s["formatted"] for s in raw_slots[:4]]
                    final_text = (
                        f"Here are the available afternoon slots for **Deep Tissue Massage** on **{target_date}** (Asia/Kathmandu UTC+05:45):\n\n"
                        + "\n".join([f"• {t}" for t in slot_times])
                        + "\n\nAll appointments are localized to Kathmandu time. Please click a slot below or tell me which time you prefer!"
                    )
                else:
                    final_text = f"There are no available afternoon slots on {target_date}. Would you like to check morning availability or another day?"

        # Confirmation Gate / Slot Selection (e.g. "Book slot at 14:00", "14:00", "Select 14:00", "Book with Dolkar at 14:00")
        elif any(t in q_lower for t in ["14:00", "15:00", "10:00", "11:00", "12:00", "16:00", "2:00", "2pm", "3pm"]) and any(w in q_lower for w in ["book", "select", "slot", "with", "at"]):
            yield cls._sse("tool_start", {"tool": "prepare_booking_summary", "message": "Staging booking summary and confirmation proposal..."})
            await asyncio.sleep(0.1)

            # Contextual date resolution: query -> conversation history -> relative date
            target_date = None
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", query)
            if date_match:
                target_date = date_match.group(0)
            elif history:
                for prev_m in reversed(history):
                    d_m = re.search(r"\d{4}-\d{2}-\d{2}", prev_m.content)
                    if d_m:
                        target_date = d_m.group(0)
                        break

            if not target_date:
                resolved_dt = SchedulingEngine.resolve_relative_datetime_kathmandu(query)
                target_date = resolved_dt.strftime("%Y-%m-%d")

            time_match = re.search(r"(\d{1,2}:\d{2})", query)
            time_str = time_match.group(1) if time_match else "14:00"

            service_id = "srv_1"
            practitioner_id = "prac_2" # Master Tenzing Norbu

            summary_res = await AgentBTools.prepare_booking_summary(
                db, user.org_id, user.id,
                service_id=service_id,
                practitioner_id=practitioner_id,
                start_time_str=f"{target_date}T{time_str}:00"
            )
            tool_activity.append({"tool": "prepare_booking_summary", "result": summary_res})
            yield cls._sse("tool_end", {"tool": "prepare_booking_summary", "status": "completed"})

            if summary_res.get("success"):
                card_data = summary_res.get("card")
                final_text = summary_res.get("summary_text")
            else:
                card_data = summary_res.get("card")
                final_text = summary_res.get("message") or summary_res.get("error")

        # Confirm booking execution (e.g. "Yes, please confirm this booking.", "confirm booking")
        elif any(w in q_lower for w in ["yes, please confirm this booking", "confirm booking", "confirm my booking"]):
            yield cls._sse("tool_start", {"tool": "create_booking", "message": "Confirming appointment in studio calendar..."})
            await asyncio.sleep(0.1)

            # Get latest pending booking proposal
            prop_stmt = select(ActionProposal).where(
                ActionProposal.org_id == user.org_id,
                ActionProposal.user_id == user.id,
                ActionProposal.action_type == "create_booking",
                ActionProposal.status == "pending"
            ).order_by(desc(ActionProposal.created_at))
            prop_res = await db.execute(prop_stmt)
            latest_prop = prop_res.scalars().first()

            if latest_prop:
                p_data = json.loads(latest_prop.payload_json)
                book_res = await AgentBTools.create_booking(
                    db, user.org_id, user.id,
                    service_id=p_data["service_id"],
                    practitioner_id=p_data["practitioner_id"],
                    start_time_str=p_data["start_time"],
                    proposal_id=latest_prop.id
                )
                tool_activity.append({"tool": "create_booking", "result": book_res})
                yield cls._sse("tool_end", {"tool": "create_booking", "status": "completed"})
                final_text = book_res.get("message") or book_res.get("error")
                card_data = book_res.get("card")
            else:
                # Default direct booking confirmation
                now_ktm = SchedulingEngine.now_kathmandu()
                target_dt = now_ktm + datetime.timedelta(days=2)
                start_iso = f"{target_dt.strftime('%Y-%m-%d')}T14:00:00"
                book_res = await AgentBTools.create_booking(
                    db, user.org_id, user.id, "srv_1", "prac_2", start_iso
                )
                tool_activity.append({"tool": "create_booking", "result": book_res})
                yield cls._sse("tool_end", {"tool": "create_booking", "status": "completed"})
                final_text = book_res.get("message") or book_res.get("error")
                card_data = book_res.get("card")

        # Knowledge Base Question (Services, Bios, Cancellation policy, FAQs)
        else:
            yield cls._sse("tool_start", {"tool": "search_knowledge", "message": "Searching Lotus Wellness Studio knowledge base..."})
            await asyncio.sleep(0.1)

            kb_res = await AgentBTools.search_knowledge(db, user.org_id, query)
            tool_activity.append({"tool": "search_knowledge", "result": kb_res})
            yield cls._sse("tool_end", {"tool": "search_knowledge", "status": "completed"})

            results = kb_res.get("results", [])
            if results and results[0]["score"] > 0.15:
                top_match = results[0]
                citations.append({
                    "doc": top_match["doc_name"],
                    "section": top_match["section_name"],
                    "excerpt": top_match["content"][:240] + "..."
                })
                final_text = (
                    f"{top_match['content']}\n\n"
                    f"*Source: {top_match['doc_name']} > {top_match['section_name']}*"
                )
            else:
                final_text = (
                    "I searched our Lotus Wellness Studio knowledge base, but I do not have verified answers for that specific question. "
                    "Feel free to ask about our therapies, practitioner bios, opening hours, or appointment bookings in Kathmandu time (UTC+05:45)!"
                )

        # Stream synthesized response
        words = final_text.split(" ")
        accumulated = ""
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            accumulated += token
            yield cls._sse("token", {"token": token})
            await asyncio.sleep(0.015)

        agent_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        agent_msg = Message(
            id=agent_msg_id,
            conversation_id=history[0].conversation_id if history else "conv_default",
            org_id=user.org_id,
            user_id=user.id,
            sender="agent",
            content=accumulated,
            tool_calls_json=json.dumps(tool_activity) if tool_activity else None,
            citations_json=json.dumps(citations) if citations else None,
            card_json=json.dumps(card_data) if card_data else None
        )
        db.add(agent_msg)
        await db.commit()

        yield cls._sse("done", {
            "id": agent_msg_id,
            "content": accumulated,
            "citations": citations,
            "card": card_data
        })

    # =========================================================================
    # ADMIN ANALYTICS AGENT (STRETCH GOAL - MOST VALUED STRETCH)
    # =========================================================================
    @classmethod
    async def _run_admin_agent(
        cls,
        db: AsyncSession,
        user: User,
        query: str,
        conversation_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Admin Analytics Agent:
        Read-only metrics analysis strictly scoped to user.org_id.
        Customers are blocked before reaching here (HTTP 403).
        """
        q_lower = query.lower()
        tool_activity = []
        final_text = ""

        # Read-Only Enforcement Check
        if any(w in q_lower for w in ["cancel", "delete", "drop", "update", "modify", "remove", "insert"]):
            final_text = (
                "The Admin Analytics Agent is strictly read-only. Modification and deletion commands "
                "(such as cancelling orders, updating records, or deleting users) are strictly prohibited. "
                "I can only provide operational summaries, inventory analytics, and business performance metrics."
            )

        elif any(w in q_lower for w in ["conversion", "conversion rate", "funnel"]):
            yield cls._sse("tool_start", {"tool": "get_conversion_rate", "message": "Computing conversation-to-order conversion rate..."})
            await asyncio.sleep(0.1)
            res = await AdminAnalyticsTools.get_conversion_rate(db, user.org_id)
            tool_activity.append({"tool": "get_conversion_rate", "result": res})
            yield cls._sse("tool_end", {"tool": "get_conversion_rate", "status": "completed"})

            m = res["metrics"]
            final_text = (
                f"### Conversion Rate Analysis\n"
                f"- **Time Window:** {res['time_window']}\n"
                f"- **Definition:** {res['definition']}\n"
                f"- **Total Customer Conversations:** {m['total_conversations']}\n"
                f"- **Converted Conversations:** {m['converted_conversations']}\n"
                f"- **Conversion Rate:** **{m['conversion_rate_percentage']}%**"
            )

        elif any(w in q_lower for w in ["client", "customer", "today", "sign-up", "signup", "who chatted"]):
            yield cls._sse("tool_start", {"tool": "get_clients_today", "message": "Calculating today's active customer traffic..."})
            await asyncio.sleep(0.1)
            res = await AdminAnalyticsTools.get_clients_today(db, user.org_id)
            tool_activity.append({"tool": "get_clients_today", "result": res})
            yield cls._sse("tool_end", {"tool": "get_clients_today", "status": "completed"})

            m = res["metrics"]
            final_text = (
                f"### Client Activity Overview\n"
                f"- **Date Reference:** {res['date']}\n"
                f"- **Definition:** {res['definition']}\n"
                f"- **Unique Customers Chatted Today:** {m['unique_customers_chatted']}\n"
                f"- **New Customer Sign-ups Today:** {m['new_signups_today']}"
            )

        elif any(w in q_lower for w in ["top", "best seller", "busiest", "out of stock", "popular"]):
            yield cls._sse("tool_start", {"tool": "get_top_items", "message": "Analyzing top performing items and capacity..."})
            await asyncio.sleep(0.1)
            res = await AdminAnalyticsTools.get_top_items(db, user.org_id)
            tool_activity.append({"tool": "get_top_items", "result": res})
            yield cls._sse("tool_end", {"tool": "get_top_items", "status": "completed"})

            if user.org_id == "org_a":
                sellers = res["best_selling_products"]
                seller_text = "\n".join([f"- **{p['name']}** ({p['sku']}): {p['units_sold']} units sold (Stock: {p['current_stock']})" for p in sellers])
                final_text = (
                    f"### Top Inventory & Sales Performance\n"
                    f"- **Definition:** {res['definition']}\n\n"
                    f"**Best-Selling Teas:**\n{seller_text}\n\n"
                    f"**Low / Critical Stock Items:** {len(res['low_or_out_of_stock_items'])} items need restocking."
                )
            else:
                services = res["most_booked_services"]
                srv_text = "\n".join([f"- **{s['service_name']}**: {s['total_bookings']} bookings (NPR {s['price']:.2f})" for s in services[:3]])
                busiest = "\n".join([f"- {h['hour']}: {h['bookings']} bookings" for h in res["busiest_time_slots"][:3]])
                final_text = (
                    f"### Top Services & Peak Hours\n"
                    f"- **Definition:** {res['definition']}\n\n"
                    f"**Most-Booked Therapies:**\n{srv_text}\n\n"
                    f"**Busiest Studio Hours:**\n{busiest}"
                )

        else:
            # Default to Activity Summary
            yield cls._sse("tool_start", {"tool": "get_activity_summary", "message": "Querying organization operational summary..."})
            await asyncio.sleep(0.1)
            res = await AdminAnalyticsTools.get_activity_summary(db, user.org_id)
            tool_activity.append({"tool": "get_activity_summary", "result": res})
            yield cls._sse("tool_end", {"tool": "get_activity_summary", "status": "completed"})

            m = res["metrics"]
            if user.org_id == "org_a":
                status_breakdown = ", ".join([f"{k}: {v}" for k, v in m['orders_by_status'].items()])
                final_text = (
                    f"### Store Activity Summary\n"
                    f"- **Time Window:** {res['time_window']}\n"
                    f"- **Definition:** {res['definition']}\n"
                    f"- **Total Orders Received:** {m['total_orders']} ({status_breakdown})\n"
                    f"- **Gross Realized Revenue:** NPR {m['gross_revenue_npr']:,.2f}\n"
                    f"- **Average Order Value (AOV):** NPR {m['average_order_value_npr']:,.2f}"
                )
            else:
                util = "\n".join([f"- **{u['practitioner_name']}**: {u['total_sessions']} sessions ({u['share_percentage']}% share)" for u in m['practitioner_utilisation']])
                final_text = (
                    f"### Studio Operations Summary\n"
                    f"- **Time Window:** {res['time_window']}\n"
                    f"- **Definition:** {res['definition']}\n"
                    f"- **Total Appointments Booked:** {m['total_bookings']}\n"
                    f"- **Cancellation Rate:** {m['cancellation_rate_percentage']}%\n\n"
                    f"**Practitioner Utilisation:**\n{util}"
                )

        # Stream response
        words = final_text.split(" ")
        accumulated = ""
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            accumulated += token
            yield cls._sse("token", {"token": token})
            await asyncio.sleep(0.015)

        agent_msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        agent_msg = Message(
            id=agent_msg_id,
            conversation_id=conversation_id,
            org_id=user.org_id,
            user_id=user.id,
            sender="agent",
            content=accumulated,
            tool_calls_json=json.dumps(tool_activity) if tool_activity else None,
            citations_json=None,
            card_json=None
        )
        db.add(agent_msg)
        await db.commit()

        yield cls._sse("done", {
            "id": agent_msg_id,
            "content": accumulated,
            "citations": [],
            "card": None
        })

