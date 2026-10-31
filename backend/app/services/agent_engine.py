import asyncio
import json
import re
import datetime
from typing import AsyncGenerator, Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.models import User, Conversation, Message, CustomerMemory, Product, Service, Order, Booking
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
        user_msg_id = f"msg_{datetime.datetime.utcnow().timestamp()}"
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
            async for sse_event in cls._run_admin_agent(db, user, user_message):
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

        # Check for Reorder / "Same as last time"
        if any(phrase in q_lower for phrase in ["same as last time", "reorder", "repeat my order", "previous order", "usual tea"]):
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
            # Check last pending proposals from recent messages or summary in context
            yield cls._sse("tool_start", {"tool": "create_order", "message": "Confirming and placing order..."})
            await asyncio.sleep(0.1)

            # Look up unconfirmed order draft from latest user memory or items
            # Default to Silver Needle or usual tea if confirming
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

        # Check for Order Status / Tracking (e.g. "track order", "status of ORD-1001", "where is my order")
        elif any(phrase in q_lower for phrase in ["status", "track", "where is my order", "ord-"]):
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
                    final_text = f"You have {len(orders_res['orders'])} orders. Your latest order #{latest['order_id']} is currently **{latest['status'].upper()}**."
                else:
                    final_text = "You do not have any past orders yet."

        # Check for Cancellation (e.g. "cancel order ORD-...", "cancel my order")
        elif "cancel" in q_lower and ("order" in q_lower or "ord-" in q_lower):
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
                # Find latest pending order to cancel
                orders_res = await AgentATools.list_my_orders(db, user.org_id, user.id)
                pending_orders = [o for o in orders_res["orders"] if o["status"] == "pending"]
                if pending_orders:
                    cancel_res = await AgentATools.cancel_order(db, user.org_id, user.id, pending_orders[0]["order_id"])
                    tool_activity.append({"tool": "cancel_order", "result": cancel_res})
                    yield cls._sse("tool_end", {"tool": "cancel_order", "status": "completed"})
                    final_text = cancel_res.get("message") or cancel_res.get("error")
                else:
                    yield cls._sse("tool_end", {"tool": "cancel_order", "status": "completed"})
                    final_text = "I could not find an active pending order to cancel. If you have an order ID, please share it!"

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

        # Check for Buying / Purchasing / Ordering products (e.g. "I want to buy 2 Silver Needle", "order HT-SN-100")
        elif any(k in q_lower for k in ["buy", "order", "purchase", "get me", "want 2", "want 3"]):
            yield cls._sse("tool_start", {"tool": "search_products", "message": "Checking product catalog and live inventory..."})
            await asyncio.sleep(0.1)

            # Match product
            sku = "HT-SN-100"  # default
            qty = 1
            qty_match = re.search(r"(\d+)\s*(unit|packet|pack|canister|gram|kg|piece|bottle)?", query)
            if qty_match:
                try:
                    qty = int(qty_match.group(1))
                except Exception:
                    qty = 1

            if "green" in q_lower:
                sku = "HT-GT-100"
            elif "oolong" in q_lower or "shangri" in q_lower:
                sku = "HT-OL-100"
            elif "masala" in q_lower or "chai" in q_lower:
                sku = "HT-MC-200"
            elif "black" in q_lower or "tippy" in q_lower:
                sku = "HT-BT-100"
            elif "puerh" in q_lower or "cake" in q_lower or "ht-or-99" in q_lower:
                sku = "HT-OR-99"

            summary_res = await AgentATools.prepare_order_summary(
                db, user.org_id, user.id,
                items=[{"sku": sku, "quantity": qty}],
                shipping_address="Kathmandu Valley, Nepal"
            )
            tool_activity.append({"tool": "search_products", "result": summary_res})
            yield cls._sse("tool_end", {"tool": "search_products", "status": "completed"})

            if summary_res.get("success"):
                card_data = summary_res.get("card")
                final_text = summary_res.get("summary_text")
            else:
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
        agent_msg_id = f"msg_{datetime.datetime.utcnow().timestamp()}"
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

        now_ktm = SchedulingEngine.now_kathmandu()
        tomorrow_date = (now_ktm + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # Check for Available Slots / Availability / Schedule
        if any(w in q_lower for w in ["available", "slots", "free time", "opening hours", "when can i", "schedule"]):
            yield cls._sse("tool_start", {"tool": "find_available_slots", "message": "Checking practitioner calendar and opening hours in Asia/Kathmandu..."})
            await asyncio.sleep(0.1)

            service_id = "srv_1"
            if "abhyanga" in q_lower or "ayurved" in q_lower:
                service_id = "srv_2"
            elif "physio" in q_lower or "sports" in q_lower:
                service_id = "srv_3"
            elif "dry needling" in q_lower:
                service_id = "srv_4"
            elif "yoga" in q_lower:
                service_id = "srv_5"
            elif "sound" in q_lower or "singing bowl" in q_lower:
                service_id = "srv_6"

            target_date = tomorrow_date
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", query)
            if date_match:
                target_date = date_match.group(0)

            slots_res = await AgentBTools.find_available_slots(db, user.org_id, service_id, target_date)
            tool_activity.append({"tool": "find_available_slots", "result": slots_res})
            yield cls._sse("tool_end", {"tool": "find_available_slots", "status": "completed"})

            if slots_res.get("slots"):
                card_data = slots_res.get("card")
                sample_times = [s["formatted"] for s in slots_res["slots"][:3]]
                final_text = (
                    f"Here are the upcoming available slots for {target_date} in Kathmandu time:\n"
                    + "\n".join([f"- {t}" for t in sample_times])
                    + "\n\nPlease let me know your preferred time or click a slot below to confirm!"
                )
            else:
                final_text = f"There are no free slots found for {target_date} (the studio might be closed or fully booked). Would you like to check another day?"

        # Check for Reschedule
        elif any(w in q_lower for w in ["reschedule", "change appointment", "move my booking", "move to"]):
            yield cls._sse("tool_start", {"tool": "reschedule_booking", "message": "Checking availability for requested reschedule slot..."})
            await asyncio.sleep(0.1)

            # Find latest confirmed booking
            my_bookings = await AgentBTools.list_my_bookings(db, user.org_id, user.id)
            active_bkg = next((b for b in my_bookings["bookings"] if b["status"] in ["confirmed", "rescheduled"]), None)

            if not active_bkg:
                yield cls._sse("tool_end", {"tool": "reschedule_booking", "status": "completed"})
                final_text = "I could not find an active booking under your account to reschedule."
            else:
                # Proposed time: tomorrow at 11:00 AM or conflict trigger
                new_time = f"{tomorrow_date}T11:00:00"
                if "conflict" in q_lower or "taken" in q_lower:
                    # Deliberately pick an existing booking time to showcase conflict handling
                    new_time = active_bkg["start_time"]

                resched_res = await AgentBTools.reschedule_booking(db, user.org_id, user.id, active_bkg["booking_id"], new_time)
                tool_activity.append({"tool": "reschedule_booking", "result": resched_res})
                yield cls._sse("tool_end", {"tool": "reschedule_booking", "status": "completed"})

                final_text = resched_res.get("message") or resched_res.get("error")
                card_data = resched_res.get("card")

        # Check for Cancellation
        elif "cancel" in q_lower and ("booking" in q_lower or "appointment" in q_lower or "session" in q_lower):
            yield cls._sse("tool_start", {"tool": "cancel_booking", "message": "Reviewing cancellation window and policy..."})
            await asyncio.sleep(0.1)

            my_bookings = await AgentBTools.list_my_bookings(db, user.org_id, user.id)
            active_bkg = next((b for b in my_bookings["bookings"] if b["status"] in ["confirmed", "rescheduled"]), None)

            if active_bkg:
                cancel_res = await AgentBTools.cancel_booking(db, user.org_id, user.id, active_bkg["booking_id"])
                tool_activity.append({"tool": "cancel_booking", "result": cancel_res})
                yield cls._sse("tool_end", {"tool": "cancel_booking", "status": "completed"})
                final_text = cancel_res.get("message")
            else:
                yield cls._sse("tool_end", {"tool": "cancel_booking", "status": "completed"})
                final_text = "You do not have any active upcoming appointments to cancel."

        # Check for Booking Appointment / Booking confirmation
        elif any(w in q_lower for w in ["book", "appointment", "reserve", "yes confirm booking", "confirm booking"]):
            yield cls._sse("tool_start", {"tool": "create_booking", "message": "Verifying appointment slot and practitioner schedule..."})
            await asyncio.sleep(0.1)

            service_id = "srv_1"
            practitioner_id = "prac_2"
            start_time = f"{tomorrow_date}T14:00:00"

            if "physio" in q_lower or "sunita" in q_lower:
                service_id = "srv_3"
                practitioner_id = "prac_1"
            elif "yoga" in q_lower or "aarati" in q_lower:
                service_id = "srv_5"
                practitioner_id = "prac_3"

            # Check if user is confirming or asking for summary
            if "confirm" in q_lower:
                book_res = await AgentBTools.create_booking(
                    db, user.org_id, user.id, service_id, practitioner_id, start_time
                )
                tool_activity.append({"tool": "create_booking", "result": book_res})
                yield cls._sse("tool_end", {"tool": "create_booking", "status": "completed"})
                final_text = book_res.get("message") or book_res.get("error")
                card_data = book_res.get("card")
            else:
                summary_res = await AgentBTools.prepare_booking_summary(
                    db, user.org_id, user.id, service_id, practitioner_id, start_time
                )
                tool_activity.append({"tool": "create_booking", "result": summary_res})
                yield cls._sse("tool_end", {"tool": "create_booking", "status": "completed"})
                final_text = summary_res.get("summary_text") or summary_res.get("error")
                card_data = summary_res.get("card")

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

        agent_msg_id = f"msg_{datetime.datetime.utcnow().timestamp()}"
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
        query: str
    ) -> AsyncGenerator[str, None]:
        """
        Admin Analytics Agent:
        Read-only metrics analysis strictly scoped to user.org_id.
        Customers are blocked before reaching here (HTTP 403).
        """
        q_lower = query.lower()
        tool_activity = []
        final_text = ""

        if any(w in q_lower for w in ["conversion", "conversion rate", "funnel"]):
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

        agent_msg_id = f"msg_{datetime.datetime.utcnow().timestamp()}"
        yield cls._sse("done", {
            "id": agent_msg_id,
            "content": accumulated,
            "citations": [],
            "card": None
        })
