import uuid
import json
import datetime
from typing import List, Dict, Any, Optional
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.models.models import (
    Service, Practitioner, Booking, Holiday, WeeklyOpeningHours,
    CustomerMemory, ActionProposal
)
from app.services.knowledge_base import KnowledgeBaseService
from app.services.scheduling import SchedulingEngine, KATHMANDU_TZ

class AgentBTools:
    """
    Booking Agent Tools for Lotus Wellness Studio (Org B).
    Enforces all 6 core business rules:
    1. Opening hours and holiday validation + duration fit.
    2. Overlap prevention: no practitioner double booking, no client holding 2 simultaneous bookings.
    3. Concurrency-safe slot grabbing.
    4. Conflict refusal on reschedule + nearest free alternatives.
    5. Pre-confirmation of service, practitioner, date, time, price.
    6. Relative dates resolve in Asia/Kathmandu (UTC+05:45).
    """

    @staticmethod
    async def search_knowledge(db: AsyncSession, org_id: str, query: str) -> Dict[str, Any]:
        results = await KnowledgeBaseService.search_knowledge(db, org_id, query, top_k=3)
        return {
            "success": True,
            "query": query,
            "results": results,
            "answerable": bool(results),
            "note": (
                "Answer only from these passages and cite them. Prices, hours and availability must come from list_services, get_opening_hours and find_available_slots."
                if results else
                "No relevant passage found. Say you do not have that information; do not guess."
            ),
            "citations": [
                {
                    "doc": result.get("doc_name") or "Knowledge",
                    "section": result.get("section_name") or "",
                    "excerpt": result.get("content") or "",
                }
                for result in results
            ]
        }

    @staticmethod
    async def list_services(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        services = (await db.execute(select(Service).where(Service.org_id == org_id))).scalars().all()
        practitioners = (await db.execute(select(Practitioner).where(Practitioner.org_id == org_id))).scalars().all()
        return {
            "success": True,
            "services": [
                {
                    "id": s.id,
                    "name": s.name,
                    "duration_minutes": s.duration_minutes,
                    "price": s.price,
                    "description": s.description,
                    "practitioner_ids": [p.id for p in practitioners if SchedulingEngine.practitioner_offers(p, s)],
                }
                for s in services
            ],
            # Ids the other tools need. A practitioner may only be booked for the services listed here.
            "practitioners": [
                {
                    "id": p.id,
                    "name": p.name,
                    "title": p.title,
                    "offers_service_ids": [s.id for s in services if SchedulingEngine.practitioner_offers(p, s)],
                }
                for p in practitioners
            ],
        }

    @staticmethod
    async def resolve_service(db: AsyncSession, org_id: str, ref: Optional[str]) -> Optional[Service]:
        """A service by id, or by name (case-insensitive, partial). None if it matches nothing or is ambiguous."""
        if not ref:
            return None
        services = (await db.execute(select(Service).where(Service.org_id == org_id))).scalars().all()
        needle = ref.strip().lower()
        exact = [s for s in services if s.id.lower() == needle or s.name.lower() == needle]
        if exact:
            return exact[0]
        partial = [s for s in services if needle in s.name.lower() or s.name.lower() in needle]
        return partial[0] if len(partial) == 1 else None

    @staticmethod
    async def resolve_practitioner(db: AsyncSession, org_id: str, ref: Optional[str]) -> Optional[Practitioner]:
        """A practitioner by id or by name ("Master Tenzing", "Dr. Sunita"). None if unknown or ambiguous."""
        if not ref:
            return None
        people = (await db.execute(select(Practitioner).where(Practitioner.org_id == org_id))).scalars().all()
        needle = ref.strip().lower()
        exact = [p for p in people if p.id.lower() == needle or p.name.lower() == needle]
        if exact:
            return exact[0]
        words = [w for w in needle.replace(".", " ").split() if w not in {"dr", "master", "mr", "ms", "mrs"} and len(w) > 2]
        partial = [p for p in people if needle in p.name.lower() or (words and all(w in p.name.lower() for w in words))]
        return partial[0] if len(partial) == 1 else None

    @staticmethod
    async def _unknown(db: AsyncSession, org_id: str, kind: str, ref: str) -> Dict[str, Any]:
        """A clear error listing the valid choices, so the model can correct itself instead of reporting no slots."""
        if kind == "practitioner":
            rows = (await db.execute(select(Practitioner).where(Practitioner.org_id == org_id))).scalars().all()
            options = [f"{r.id} ({r.name})" for r in rows]
        else:
            rows = (await db.execute(select(Service).where(Service.org_id == org_id))).scalars().all()
            options = [f"{r.id} ({r.name})" for r in rows]
        return {
            "success": False,
            "error": f"Unknown {kind} '{ref}'. Valid {kind}s: {', '.join(options)}.",
            "message": f"I could not match '{ref}' to a {kind}. Use one of: {', '.join(options)}.",
        }

    @staticmethod
    async def get_opening_hours(db: AsyncSession, org_id: str) -> Dict[str, Any]:
        # Hours
        h_stmt = select(WeeklyOpeningHours).where(WeeklyOpeningHours.org_id == org_id)
        h_res = await db.execute(h_stmt)
        hours_records = h_res.scalars().all()

        weekly = {}
        for r in hours_records:
            weekly[r.day_of_week] = "Closed" if r.is_closed else f"{r.open_time} - {r.close_time}"

        # Upcoming holidays only, soonest first
        today = SchedulingEngine.now_kathmandu().strftime("%Y-%m-%d")
        hol_stmt = select(Holiday).where(Holiday.org_id == org_id, Holiday.holiday_date >= today).order_by(Holiday.holiday_date)
        hol_res = await db.execute(hol_stmt)
        holidays = [{"date": h.holiday_date, "name": h.name} for h in hol_res.scalars().all()]

        return {
            "success": True,
            "timezone": "Asia/Kathmandu (UTC+05:45)",
            "weekly_hours": weekly or {
                "Monday-Friday": "08:00 - 19:00",
                "Saturday": "09:00 - 18:00",
                "Sunday": "10:00 - 16:00"
            },
            "upcoming_holidays": holidays
        }

    @staticmethod
    async def find_available_slots(
        db: AsyncSession,
        org_id: str,
        service_id: str,
        date_str: str,
        practitioner_id: Optional[str] = None,
        user_id: Optional[str] = None,
        part_of_day: Optional[str] = None,
    ) -> Dict[str, Any]:
        service = await AgentBTools.resolve_service(db, org_id, service_id)
        if service is None:
            return await AgentBTools._unknown(db, org_id, "service", service_id)
        service_id = service.id
        if practitioner_id:
            practitioner = await AgentBTools.resolve_practitioner(db, org_id, practitioner_id)
            if practitioner is None:
                return await AgentBTools._unknown(db, org_id, "practitioner", practitioner_id)
            practitioner_id = practitioner.id
            if not SchedulingEngine.practitioner_offers(practitioner, service):
                return {
                    "success": False,
                    "error": f"{practitioner.name} does not offer {service.name}.",
                    "message": f"{practitioner.name} does not offer {service.name}. Omit practitioner_id to see everyone who does.",
                }
        slots = await SchedulingEngine.find_available_slots(
            db, org_id, service_id, date_str, practitioner_id,
            customer_id=user_id, part_of_day=part_of_day,
        )
        label = f" ({part_of_day})" if part_of_day else ""
        result: Dict[str, Any] = {
            "success": True,
            "service_id": service_id,
            "service_name": service.name,
            "date": date_str,
            "timezone": "Asia/Kathmandu (UTC+05:45)",
            "count": len(slots),
            "slots": [
                {k: s[k] for k in ("practitioner_id", "practitioner_name", "start_time", "formatted")}
                for s in slots[:40]
            ],
            "card": {
                "type": "slot_picker",
                "title": f"{service.name}: free slots on {date_str}{label}",
                "service_id": service_id,
                "service_name": service.name,
                "slots": slots[:12],
                "total": len(slots),
            } if slots else None,
        }
        if not slots:
            result["message"] = (
                "No free slots on that date. The studio may be closed (holiday or day off), the day may be fully "
                "booked, or the time has passed. Offer to check another date."
            )
        return result

    @staticmethod
    async def prepare_booking_summary(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        service_id: str,
        practitioner_id: str,
        start_time_str: str,
        stage_proposal: bool = True,
        conversation_id: Optional[str] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """
        Business Rule 5: Confirms service, practitioner, date, time and price before booking.
        """
        service = await AgentBTools.resolve_service(db, org_id, service_id)
        if not service:
            return await AgentBTools._unknown(db, org_id, "service", service_id)
        practitioner = await AgentBTools.resolve_practitioner(db, org_id, practitioner_id)
        if not practitioner:
            return await AgentBTools._unknown(db, org_id, "practitioner", practitioner_id)
        service_id, practitioner_id = service.id, practitioner.id

        if not SchedulingEngine.practitioner_offers(practitioner, service):
            qualified = (await db.execute(select(Practitioner).where(Practitioner.org_id == org_id))).scalars().all()
            names = [p.name for p in qualified if SchedulingEngine.practitioner_offers(p, service)]
            return {
                "success": False,
                "error": f"{practitioner.name} does not offer {service.name}.",
                "message": f"{practitioner.name} does not offer {service.name}. Practitioners who do: {', '.join(names) or 'none'}.",
                "qualified_practitioners": names,
            }

        # Parse start_time in Asia/Kathmandu
        try:
            start_dt = SchedulingEngine.parse_datetime_kathmandu(start_time_str)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        # Validate slot rules (Opening hours, holiday, no double booking, customer no overlap)
        is_valid, reason = await SchedulingEngine.validate_slot(
            db, org_id, start_dt, service.duration_minutes, practitioner_id, user_id
        )
        if not is_valid:
            # Find alternatives
            alternatives = await SchedulingEngine.find_nearest_alternatives(
                db, org_id, service_id, start_dt, practitioner_id, count=3, customer_id=user_id
            )
            return {
                "success": False,
                "error": reason,
                "suggested_alternatives": alternatives,
                "card": {"type": "slot_picker", "title": "Nearest free alternatives", "service_id": service_id,
                         "service_name": service.name, "slots": alternatives, "total": len(alternatives)} if alternatives else None,
                "message": f"Cannot book this slot: {reason} Here are nearest available slots."
            }

        end_dt = start_dt + datetime.timedelta(minutes=service.duration_minutes)

        proposal_id = None
        if stage_proposal:
            proposal_id = f"prop_bkg_{uuid.uuid4().hex[:8]}"
            proposal_payload = {
                "service_id": service.id,
                "service_name": service.name,
                "practitioner_id": practitioner.id,
                "practitioner_name": practitioner.name,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "price": service.price,
            }
            proposal = ActionProposal(
                id=proposal_id,
                org_id=org_id,
                user_id=user_id,
                conversation_id=conversation_id,
                action_type="create_booking",
                payload_json=json.dumps(proposal_payload),
                summary_text=f"Booking Summary: {service.name} with {practitioner.name} on {start_dt.strftime('%A, %b %d at %I:%M %p')}",
                status="pending",
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=30),
            )
            db.add(proposal)
            if commit:
                await db.commit()

        return {
            "success": True,
            "is_summary": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "service_id": service.id,
            "service_name": service.name,
            "practitioner_id": practitioner.id,
            "practitioner_name": practitioner.name,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "formatted_time": start_dt.strftime("%A, %B %d, %Y at %I:%M %p"),
            "duration_minutes": service.duration_minutes,
            "price": service.price,
            "card": {
                "type": "booking_summary",
                "proposal_id": proposal_id,
                "title": "Please Confirm Your Appointment",
                "service_name": service.name,
                "practitioner_name": practitioner.name,
                "start_time": start_dt.isoformat(),
                "formatted_time": start_dt.strftime("%A, %B %d, %Y at %I:%M %p"),
                "duration_minutes": service.duration_minutes,
                "price": service.price,
                "action": "book",
                "confirm_label": "Confirm Booking",
            },
            "summary_text": (
                f"Booking Summary: {service.name} ({service.duration_minutes} min) with {practitioner.name} "
                f"on {start_dt.strftime('%A, %b %d, %Y at %I:%M %p')} for NPR {service.price:.2f}. "
                + (f"Proposal #{proposal_id} staged. Would you like me to confirm this booking?" if proposal_id else "Confirm this booking on the card to save it.")
            )
        }

    @staticmethod
    async def create_booking(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        service_id: str,
        practitioner_id: str,
        start_time_str: str,
        notes: Optional[str] = None,
        proposal_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        stage_proposal: bool = True,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates confirmed booking in DB.
        Safe against race conditions with atomic transactional validation and slot mutex lock.
        """
        summary = await AgentBTools.prepare_booking_summary(
            db, org_id, user_id, service_id, practitioner_id, start_time_str,
            stage_proposal=stage_proposal,
            conversation_id=conversation_id,
            commit=manage_transaction,
        )
        if not summary.get("success"):
            return summary

        start_dt = datetime.datetime.fromisoformat(summary["start_time"])
        end_dt = datetime.datetime.fromisoformat(summary["end_time"])
        booking_id = f"BKG-{uuid.uuid4().hex[:8].upper()}"

        naive_start = start_dt.replace(tzinfo=None)
        naive_end = end_dt.replace(tzinfo=None)

        # Critical concurrency section: serialized via booking_lock + DB conflict check
        async with SchedulingEngine.booking_lock:
            conflict_stmt = select(Booking).where(
                Booking.org_id == org_id,
                Booking.practitioner_id == practitioner_id,
                Booking.status.in_(["confirmed", "rescheduled"]),
                Booking.start_time < naive_end,
                Booking.end_time > naive_start
            )
            c_res = await db.execute(conflict_stmt)
            if c_res.scalars().first():
                return {
                    "success": False,
                    "error": "This slot was just booked by another customer. Please choose another slot.",
                    "suggested_alternatives": await SchedulingEngine.find_nearest_alternatives(
                        db, org_id, service_id, start_dt, practitioner_id, count=3, customer_id=user_id
                    )
                }

            booking = Booking(
                id=booking_id,
                org_id=org_id,
                user_id=user_id,
                conversation_id=conversation_id,
                service_id=service_id,
                practitioner_id=practitioner_id,
                start_time=naive_start,
                end_time=naive_end,
                status="confirmed",
                notes=notes
            )
            db.add(booking)

            # Update ActionProposal status if proposal_id provided
            pid = proposal_id or summary.get("proposal_id")
            if pid:
                prop_stmt = select(ActionProposal).where(ActionProposal.id == pid, ActionProposal.org_id == org_id)
                prop_res = await db.execute(prop_stmt)
                prop = prop_res.scalars().first()
                if prop:
                    prop.status = "confirmed"

            # Update customer memory (preferred practitioner)
            mem_stmt = select(CustomerMemory).where(
                CustomerMemory.org_id == org_id,
                CustomerMemory.user_id == user_id,
                CustomerMemory.memory_key == "preferred_practitioner"
            )
            mem_res = await db.execute(mem_stmt)
            mem = mem_res.scalars().first()
            if not mem:
                mem = CustomerMemory(
                    org_id=org_id,
                    user_id=user_id,
                    memory_key="preferred_practitioner",
                    memory_value=summary["practitioner_name"]
                )
                db.add(mem)
            else:
                mem.memory_value = summary["practitioner_name"]

            await db.flush()
            if manage_transaction:
                await db.commit()
                await db.refresh(booking)

        return {
            "success": True,
            "booking_id": booking_id,
            "status": "confirmed",
            "service_name": summary["service_name"],
            "practitioner_name": summary["practitioner_name"],
            "formatted_time": summary["formatted_time"],
            "price": summary["price"],
            "card": {
                "type": "booking_confirmed",
                "booking_id": booking_id,
                "service_name": summary["service_name"],
                "practitioner_name": summary["practitioner_name"],
                "formatted_time": summary["formatted_time"],
                "price": summary["price"]
            },
            "message": (
                f"Your appointment #{booking_id} for {summary['service_name']} with {summary['practitioner_name']} "
                f"on {summary['formatted_time']} has been confirmed! Price: NPR {summary['price']:.2f}."
            )
        }

    @staticmethod
    async def reschedule_booking(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        booking_id: str,
        new_start_time_str: str,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Business Rule 4:
        If reschedule would conflict, it is REFUSED and the agent offers the nearest free alternatives!
        """
        stmt = select(Booking).where(
            Booking.id == booking_id, Booking.org_id == org_id, Booking.user_id == user_id
        )
        res = await db.execute(stmt)
        booking = res.scalars().first()
        if not booking:
            return {"success": False, "error": f"Booking #{booking_id} not found."}

        refusal = AgentBTools._not_changeable(booking, "rescheduled")
        if refusal:
            return {"success": False, "error": refusal}

        # Fetch service details
        s_stmt = select(Service).where(Service.id == booking.service_id)
        s_res = await db.execute(s_stmt)
        service = s_res.scalars().first()

        p_stmt = select(Practitioner).where(Practitioner.id == booking.practitioner_id)
        p_res = await db.execute(p_stmt)
        practitioner = p_res.scalars().first()

        # Parse new datetime in Asia/Kathmandu
        try:
            new_start_dt = SchedulingEngine.parse_datetime_kathmandu(new_start_time_str)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        # Validate new slot (excluding current booking) inside booking_lock
        async with SchedulingEngine.booking_lock:
            is_valid, reason = await SchedulingEngine.validate_slot(
                db, org_id, new_start_dt, service.duration_minutes, booking.practitioner_id, user_id, exclude_booking_id=booking.id
            )

            if not is_valid:
                # Rule 4: Refuse and offer nearest free alternatives!
                alternatives = await SchedulingEngine.find_nearest_alternatives(
                    db, org_id, booking.service_id, new_start_dt, booking.practitioner_id, count=3,
                    customer_id=user_id, exclude_booking_id=booking.id,
                )
                return {
                    "success": False,
                    "conflict": True,
                    "error": f"Reschedule refused: {reason}",
                    "suggested_alternatives": alternatives,
                    "card": {
                        "type": "reschedule_conflict",
                        "booking_id": booking.id,
                        "reason": reason,
                        "suggested_slots": alternatives
                    },
                    "message": (
                        f"I cannot move booking #{booking_id} to that time because {reason}. "
                        f"Here are the nearest alternative free slots you can choose from:"
                    )
                }

            new_end_dt = new_start_dt + datetime.timedelta(minutes=service.duration_minutes)
            booking.start_time = new_start_dt.replace(tzinfo=None)
            booking.end_time = new_end_dt.replace(tzinfo=None)
            booking.status = "rescheduled"
            booking.reschedule_count = (booking.reschedule_count or 0) + 1
            booking.updated_at = datetime.datetime.utcnow()
            await db.flush()
            if manage_transaction:
                await db.commit()
                await db.refresh(booking)

        formatted_time = new_start_dt.strftime("%A, %B %d, %Y at %I:%M %p")
        return {
            "success": True,
            "booking_id": booking.id,
            "status": "rescheduled",
            "new_time": formatted_time,
            "practitioner_name": practitioner.name if practitioner else "Your Practitioner",
            "card": {
                "type": "booking_rescheduled",
                "booking_id": booking.id,
                "service_name": service.name if service else "Service",
                "practitioner_name": practitioner.name if practitioner else "Practitioner",
                "new_time": formatted_time
            },
            "message": f"Appointment #{booking.id} has been successfully rescheduled to {formatted_time}."
        }

    @staticmethod
    async def cancel_booking(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        booking_id: str,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Cancels booking applying cancellation policy:
        Free if cancelled >= 4 hours before. Less than 4 hours incurs 50% fee.
        """
        stmt = select(Booking).where(
            Booking.id == booking_id, Booking.org_id == org_id, Booking.user_id == user_id
        )
        res = await db.execute(stmt)
        booking = res.scalars().first()
        if not booking:
            return {"success": False, "error": f"Booking #{booking_id} not found."}

        refusal = AgentBTools._not_changeable(booking, "cancelled")
        if refusal:
            return {"success": False, "error": refusal}

        # Calculate notice hours
        # Localize start_time to Kathmandu
        now_ktm = SchedulingEngine.now_kathmandu()
        booking_start_ktm = KATHMANDU_TZ.localize(booking.start_time)
        hours_notice = (booking_start_ktm - now_ktm).total_seconds() / 3600.0

        s_stmt = select(Service).where(Service.id == booking.service_id)
        s_res = await db.execute(s_stmt)
        service = s_res.scalars().first()
        price = service.price if service else 0.0

        if hours_notice >= 4.0:
            cancellation_fee = 0.0
            fee_msg = "Cancelled free of charge (more than 4 hours notice)."
        else:
            cancellation_fee = round(price * 0.5, 2)
            fee_msg = f"Late cancellation notice (<4 hours). A 50% cancellation fee of NPR {cancellation_fee:.2f} applies per studio policy."

        booking.status = "cancelled"
        booking.cancellation_fee = cancellation_fee
        booking.updated_at = datetime.datetime.utcnow()
        if manage_transaction:
            await db.commit()
        else:
            await db.flush()

        return {
            "success": True,
            "booking_id": booking.id,
            "status": "cancelled",
            "hours_notice": round(hours_notice, 1),
            "cancellation_fee": cancellation_fee,
            "card": {
                "type": "booking_cancelled",
                "booking_id": booking.id,
                "service_name": service.name if service else booking.service_id,
                "formatted_time": booking_start_ktm.strftime("%A, %B %d, %Y at %I:%M %p"),
                "cancellation_fee": cancellation_fee,
                "fee_note": fee_msg,
            },
            "message": f"Appointment #{booking.id} has been cancelled. {fee_msg}"
        }

    @staticmethod
    def _not_changeable(booking: Booking, verb: str) -> Optional[str]:
        """Reason a booking can no longer be rescheduled or cancelled, or None."""
        if booking.status == "cancelled":
            return f"Booking #{booking.id} is already cancelled and cannot be {verb}."
        starts = SchedulingEngine._localize(booking.start_time)
        if starts <= SchedulingEngine.now_kathmandu():
            return (
                f"Booking #{booking.id} was scheduled for {starts.strftime('%A, %b %d at %I:%M %p')}, "
                f"which has already passed, so it cannot be {verb}."
            )
        return None

    @staticmethod
    async def list_my_bookings(
        db: AsyncSession,
        org_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        stmt = select(Booking).where(
            Booking.org_id == org_id,
            Booking.user_id == user_id
        ).order_by(desc(Booking.start_time))
        res = await db.execute(stmt)
        bookings = res.scalars().all()

        results = []
        for b in bookings:
            # fetch service and practitioner names
            s_stmt = select(Service).where(Service.id == b.service_id)
            s_res = await db.execute(s_stmt)
            srv = s_res.scalars().first()

            p_stmt = select(Practitioner).where(Practitioner.id == b.practitioner_id)
            p_res = await db.execute(p_stmt)
            prac = p_res.scalars().first()

            ktm_dt = KATHMANDU_TZ.localize(b.start_time) if b.start_time.tzinfo is None else b.start_time

            results.append({
                "booking_id": b.id,
                "status": b.status,
                "service_name": srv.name if srv else b.service_id,
                "practitioner_name": prac.name if prac else b.practitioner_id,
                "start_time": b.start_time.isoformat(),
                "formatted_time": ktm_dt.strftime("%A, %b %d, %Y at %I:%M %p"),
                "is_past": ktm_dt <= SchedulingEngine.now_kathmandu(),
                "cancellation_fee": b.cancellation_fee
            })

        return {
            "success": True,
            "count": len(results),
            "timezone": "Asia/Kathmandu (UTC+05:45)",
            "bookings": results,
            "card": {"type": "booking_list", "title": "Your bookings", "bookings": results[:8]} if results else None,
        }

    @staticmethod
    def cancellation_fee_for(price: float, start_time: datetime.datetime) -> Dict[str, Any]:
        now_ktm = SchedulingEngine.now_kathmandu()
        booking_start = start_time if start_time.tzinfo else KATHMANDU_TZ.localize(start_time)
        hours_notice = (booking_start - now_ktm).total_seconds() / 3600.0
        if hours_notice >= 4.0:
            fee = 0.0
            message = "Cancellation is free because notice is at least 4 hours."
        else:
            fee = round(price * 0.5, 2)
            message = f"Less than 4 hours notice. A 50% fee of NPR {fee:.2f} applies."
        return {"hours_notice": round(hours_notice, 1), "cancellation_fee": fee, "fee_message": message}

    @staticmethod
    async def propose_reschedule(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        booking_id: str,
        new_start_time_str: str,
        conversation_id: Optional[str] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        booking = (await db.execute(
            select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id, Booking.user_id == user_id)
        )).scalars().first()
        if not booking:
            return {"success": False, "error": f"Booking #{booking_id} not found."}
        refusal = AgentBTools._not_changeable(booking, "rescheduled")
        if refusal:
            return {"success": False, "error": refusal}
        service = (await db.execute(select(Service).where(Service.id == booking.service_id, Service.org_id == org_id))).scalars().first()
        practitioner = (await db.execute(select(Practitioner).where(Practitioner.id == booking.practitioner_id, Practitioner.org_id == org_id))).scalars().first()
        try:
            new_start = SchedulingEngine.parse_datetime_kathmandu(new_start_time_str)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        is_valid, reason = await SchedulingEngine.validate_slot(
            db, org_id, new_start, service.duration_minutes, booking.practitioner_id, user_id, exclude_booking_id=booking.id
        )
        if not is_valid:
            alternatives = await SchedulingEngine.find_nearest_alternatives(
                db, org_id, booking.service_id, new_start, booking.practitioner_id, count=3,
                customer_id=user_id, exclude_booking_id=booking.id,
            )
            return {
                "success": False,
                "conflict": True,
                "error": f"Reschedule refused: {reason}",
                "suggested_alternatives": alternatives,
                "card": {"type": "reschedule_conflict", "booking_id": booking.id, "reason": reason, "suggested_slots": alternatives},
                "message": f"I cannot move booking #{booking_id} to that time because {reason}",
            }
        new_end = new_start + datetime.timedelta(minutes=service.duration_minutes)
        proposal_id = f"prop_rs_{uuid.uuid4().hex[:8]}"
        payload = {
            "booking_id": booking.id,
            "service_id": service.id,
            "service_name": service.name,
            "practitioner_id": practitioner.id if practitioner else booking.practitioner_id,
            "practitioner_name": practitioner.name if practitioner else "",
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
            "price": service.price,
        }
        summary = (
            f"Move booking #{booking.id} to {new_start.strftime('%A, %b %d, %Y at %I:%M %p')} "
            f"with {payload['practitioner_name']} for NPR {service.price:.2f}."
        )
        db.add(ActionProposal(
            id=proposal_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            action_type="reschedule_booking",
            payload_json=json.dumps(payload),
            summary_text=summary,
            status="pending",
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=30),
        ))
        if commit:
            await db.commit()
        previous = SchedulingEngine._localize(booking.start_time)
        return {
            "success": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "summary_text": summary + " Nothing is moved until you confirm.",
            "card": {
                "type": "booking_summary",
                "proposal_id": proposal_id,
                "title": f"Confirm reschedule of #{booking.id}",
                "service_name": service.name,
                "practitioner_name": payload["practitioner_name"],
                "formatted_time": new_start.strftime("%A, %B %d, %Y at %I:%M %p"),
                "previous_time": previous.strftime("%A, %B %d, %Y at %I:%M %p"),
                "price": service.price,
                "action": "reschedule",
                "confirm_label": "Confirm Reschedule",
            },
        }

    @staticmethod
    async def propose_cancel_booking(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        booking_id: str,
        conversation_id: Optional[str] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        booking = (await db.execute(
            select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id, Booking.user_id == user_id)
        )).scalars().first()
        if not booking:
            return {"success": False, "error": f"Booking #{booking_id} not found."}
        refusal = AgentBTools._not_changeable(booking, "cancelled")
        if refusal:
            return {"success": False, "error": refusal}
        service = (await db.execute(select(Service).where(Service.id == booking.service_id, Service.org_id == org_id))).scalars().first()
        practitioner = (await db.execute(select(Practitioner).where(Practitioner.id == booking.practitioner_id, Practitioner.org_id == org_id))).scalars().first()
        price = service.price if service else 0.0
        fee = AgentBTools.cancellation_fee_for(price, booking.start_time)
        proposal_id = f"prop_bc_{uuid.uuid4().hex[:8]}"
        payload = {
            "booking_id": booking.id,
            "service_name": service.name if service else booking.service_id,
            "price": price,
            "cancellation_fee": fee["cancellation_fee"],
            "hours_notice": fee["hours_notice"],
            "start_time": booking.start_time.isoformat(),
        }
        summary = f"Cancel booking #{booking.id}. {fee['fee_message']}"
        db.add(ActionProposal(
            id=proposal_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            action_type="cancel_booking",
            payload_json=json.dumps(payload),
            summary_text=summary,
            status="pending",
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=30),
        ))
        if commit:
            await db.commit()
        return {
            "success": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "summary_text": summary,
            "card": {
                "type": "booking_summary",
                "proposal_id": proposal_id,
                "title": f"Confirm cancellation of #{booking.id}",
                "service_name": payload["service_name"],
                "practitioner_name": practitioner.name if practitioner else "",
                "formatted_time": SchedulingEngine._localize(booking.start_time).strftime("%A, %B %d, %Y at %I:%M %p"),
                "price": price,
                "cancellation_fee": fee["cancellation_fee"],
                "fee_note": fee["fee_message"],
                "action": "cancel",
                "confirm_label": "Confirm Cancellation",
            },
        }

