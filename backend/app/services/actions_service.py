"""Single writer for customer orders and bookings."""
import datetime
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import begin_immediate
from app.models.models import ActionProposal, Booking, Message, Order, Product, Service, User
from app.services.agent_a import AgentATools
from app.services.agent_b import AgentBTools
from app.services.scheduling import SchedulingEngine


def _record(db: AsyncSession, user: User, proposal: ActionProposal, content: str, card: Optional[Dict[str, Any]]) -> None:
    """Write the outcome into the chat thread so it is still there after a reload."""
    if not proposal.conversation_id:
        return
    db.add(Message(
        id=f"msg_{uuid.uuid4().hex[:12]}",
        conversation_id=proposal.conversation_id,
        org_id=user.org_id,
        user_id=user.id,
        sender="agent",
        content=content,
        card_json=json.dumps(card) if card else None,
    ))


def _card_of(result: Any) -> Optional[Dict[str, Any]]:
    return result.get("card") if isinstance(result, dict) else None


class ActionService:
    @staticmethod
    async def confirm(db: AsyncSession, user: User, proposal_id: str) -> Dict[str, Any]:
        try:
            await begin_immediate(db)
            claim = await db.execute(
                update(ActionProposal)
                .where(
                    ActionProposal.id == proposal_id,
                    ActionProposal.org_id == user.org_id,
                    ActionProposal.user_id == user.id,
                    ActionProposal.status == "pending",
                    or_(ActionProposal.expires_at.is_(None), ActionProposal.expires_at > datetime.datetime.utcnow()),
                )
                .values(status="executing")
            )
            if claim.rowcount == 0:
                org_id = user.org_id
                user_id = user.id
                await db.rollback()
                return await _missing_proposal(db, user_id, org_id, proposal_id)

            proposal = (await db.execute(
                select(ActionProposal).where(ActionProposal.id == proposal_id)
            )).scalars().first()
            payload = json.loads(proposal.payload_json)
            stale = await _stale_replacement(db, user, proposal, payload)
            if stale is not None:
                _record(db, user, proposal, stale["message"], _card_of(stale.get("result")))
                await db.commit()
                if stale["status"] == "failed":
                    # The world changed after the card was shown (slot taken, stock gone). Nothing was written.
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=stale["message"])
                return stale  # "stale": a replacement card with the new price is in the result

            await db.execute(text("SAVEPOINT mutation"))
            result = await _execute(db, user, proposal, payload)
            if not result.get("success"):
                await db.execute(text("ROLLBACK TO SAVEPOINT mutation"))
                proposal.status = "failed"
                proposal.summary_text = result.get("message") or result.get("error") or "Could not complete this action."
                _record(db, user, proposal, proposal.summary_text, _card_of(result))
                await db.commit()
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=proposal.summary_text)

            proposal.status = "confirmed"
            message = result.get("message") or "Confirmed."
            _record(db, user, proposal, message, _card_of(result))
            await db.commit()
            return {
                "proposal_id": proposal.id,
                "status": "confirmed",
                "action_type": proposal.action_type,
                "result": result,
                "message": message,
            }
        except OperationalError as exc:
            await db.rollback()
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Another change is being saved. Please try again.",
                ) from exc
            raise
        except HTTPException:
            raise
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def reject(db: AsyncSession, user: User, proposal_id: str) -> Dict[str, Any]:
        """Discard a pending proposal. Nothing was written, so this only closes the card."""
        claim = await db.execute(
            update(ActionProposal)
            .where(
                ActionProposal.id == proposal_id,
                ActionProposal.org_id == user.org_id,
                ActionProposal.user_id == user.id,
                ActionProposal.status == "pending",
            )
            .values(status="rejected")
        )
        if claim.rowcount == 0:
            org_id, user_id = user.org_id, user.id
            await db.rollback()
            return await _missing_proposal(db, user_id, org_id, proposal_id)
        proposal = (await db.execute(select(ActionProposal).where(ActionProposal.id == proposal_id))).scalars().first()
        _record(db, user, proposal, "No problem. I discarded that proposal and nothing was changed.", None)
        await db.commit()
        return {"success": True, "proposal_id": proposal_id, "status": "rejected"}


async def _missing_proposal(db: AsyncSession, user_id: str, org_id: str, proposal_id: str) -> Dict[str, Any]:
    # A proposal that belongs to another organisation or another customer reads as missing.
    existing = (await db.execute(
        select(ActionProposal).where(
            ActionProposal.id == proposal_id, ActionProposal.org_id == org_id, ActionProposal.user_id == user_id
        )
    )).scalars().first()
    if existing is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if existing.status == "pending" and existing.expires_at and datetime.datetime.utcnow() > existing.expires_at:
        existing.status = "expired"
        await db.commit()
        raise HTTPException(status_code=400, detail="Proposal has expired. Please request a new summary.")
    raise HTTPException(status_code=400, detail=f"Proposal is already {existing.status}.")


async def _catalog_row(db, org_id: str, sku: str):
    return (await db.execute(
        select(Product).where(Product.org_id == org_id, Product.sku == sku)
    )).scalars().first()


async def _prices_match(db, org_id: str, resolved_items) -> bool:
    for item in resolved_items or []:
        product = await _catalog_row(db, org_id, item.get("sku"))
        if product is None or abs(product.price - float(item.get("unit_price", -1))) > 0.01:
            return False
    return True


async def _stock_covers(db, org_id: str, resolved_items, reserved: Optional[Dict[str, int]] = None) -> bool:
    reserved = reserved or {}
    for item in resolved_items or []:
        product = await _catalog_row(db, org_id, item.get("sku"))
        if product is None or int(item.get("quantity", 0)) > product.stock + reserved.get(product.sku, 0):
            return False
    return True


def _failed(proposal, action: str, result: Dict[str, Any], message: str) -> Dict[str, Any]:
    proposal.status = "failed"
    return {
        "proposal_id": proposal.id,
        "status": "failed",
        "action_type": action,
        "result": result,
        "message": message,
    }


async def _stale_replacement(db, user, proposal, payload) -> Dict[str, Any] | None:
    org_id = user.org_id
    action = proposal.action_type
    if action in {"create_order", "update_order"}:
        resolved = payload.get("resolved_items") or []
        items = payload.get("items") or [
            {"sku": item["sku"], "quantity": item["quantity"]} for item in resolved
        ]
        reserved: Dict[str, int] = {}
        if action == "update_order":
            order = (await db.execute(
                select(Order).where(Order.id == payload.get("order_id"), Order.org_id == org_id, Order.user_id == user.id)
            )).scalars().first()
            if order is None or order.status != "pending":
                shown = order.status if order else "missing"
                return _failed(
                    proposal, action,
                    {"success": False, "error": f"Order is no longer editable ({shown})."},
                    f"Order #{payload.get('order_id')} can no longer be changed (status: {shown}).",
                )
            reserved = {line["sku"]: int(line["quantity"]) for line in order.items}
        if not await _prices_match(db, org_id, resolved):
            proposal.status = "stale"
            if action == "update_order":
                replacement = await AgentATools.propose_update_order(
                    db, org_id, user.id, payload["order_id"], items=items,
                    shipping_address=payload.get("shipping_address"),
                    conversation_id=proposal.conversation_id, commit=False,
                )
            else:
                replacement = await AgentATools.prepare_order_summary(
                    db, org_id, user.id, items, payload.get("shipping_address"),
                    stage_proposal=True, conversation_id=proposal.conversation_id, commit=False,
                )
            if not replacement.get("success"):
                return _failed(
                    proposal, action, replacement,
                    replacement.get("message") or "This order can no longer be placed.",
                )
            return {
                "proposal_id": proposal.id,
                "status": "stale",
                "action_type": action,
                "result": replacement,
                "message": "The price changed. Please confirm the updated summary.",
            }
        if not await _stock_covers(db, org_id, resolved, reserved):
            return _failed(
                proposal, action,
                {"success": False, "error": "Not enough stock remains for this proposal."},
                "Not enough stock remains for this proposal.",
            )
        return None
    if action == "create_booking":
        return await _booking_still_available(db, user, proposal, payload, exclude_booking_id=None)
    if action == "reschedule_booking":
        return await _booking_still_available(db, user, proposal, payload, exclude_booking_id=payload.get("booking_id"))
    if action == "cancel_booking":
        booking = (await db.execute(
            select(Booking).where(Booking.id == payload.get("booking_id"), Booking.org_id == org_id, Booking.user_id == user.id)
        )).scalars().first()
        refusal = AgentBTools._not_changeable(booking, "cancelled") if booking else "This booking no longer exists."
        if refusal:
            return _failed(proposal, action, {"success": False, "error": refusal}, refusal)
        service = (await db.execute(
            select(Service).where(Service.id == booking.service_id, Service.org_id == org_id)
        )).scalars().first()
        price = service.price if service else float(payload.get("price") or 0)
        fee = AgentBTools.cancellation_fee_for(price, booking.start_time)
        # The fee depends on the clock. If it moved since the card was shown, stage a new card.
        if abs(fee["cancellation_fee"] - float(payload.get("cancellation_fee") or 0)) > 0.01:
            proposal.status = "stale"
            replacement = await AgentBTools.propose_cancel_booking(
                db, org_id, user.id, booking.id, proposal.conversation_id, commit=False
            )
            return {
                "proposal_id": proposal.id,
                "status": "stale",
                "action_type": action,
                "result": replacement,
                "message": "The cancellation fee changed. Please confirm the updated fee.",
            }
    if action == "cancel_order":
        order = (await db.execute(
            select(Order).where(Order.id == payload.get("order_id"), Order.org_id == org_id, Order.user_id == user.id)
        )).scalars().first()
        if order is None or order.status != "pending":
            shown = order.status if order else "missing"
            return _failed(
                proposal, action,
                {"success": False, "error": f"Order is no longer cancellable ({shown})."},
                f"Order #{payload.get('order_id')} can no longer be cancelled (status: {shown}).",
            )
    return None


async def _booking_still_available(db, user, proposal, payload, exclude_booking_id):
    service = (await db.execute(
        select(Service).where(Service.id == payload.get("service_id"), Service.org_id == user.org_id)
    )).scalars().first()
    if service is None:
        return _failed(proposal, proposal.action_type, {"success": False}, "That service is no longer available.")
    if abs(service.price - float(payload.get("price") or service.price)) > 0.01:
        proposal.status = "stale"
        if proposal.action_type == "reschedule_booking":
            replacement = await AgentBTools.propose_reschedule(
                db, user.org_id, user.id, payload["booking_id"], payload["start_time"],
                conversation_id=proposal.conversation_id, commit=False,
            )
        else:
            replacement = await AgentBTools.prepare_booking_summary(
                db, user.org_id, user.id, payload["service_id"], payload["practitioner_id"],
                payload["start_time"], stage_proposal=True, conversation_id=proposal.conversation_id,
                commit=False,
            )
        if not replacement.get("success"):
            return _failed(
                proposal, proposal.action_type, replacement,
                replacement.get("message") or "That appointment can no longer be confirmed.",
            )
        return {
            "proposal_id": proposal.id,
            "status": "stale",
            "action_type": proposal.action_type,
            "result": replacement,
            "message": "The price changed. Please confirm the updated summary.",
        }
    if exclude_booking_id:
        booking = (await db.execute(
            select(Booking).where(Booking.id == exclude_booking_id, Booking.org_id == user.org_id, Booking.user_id == user.id)
        )).scalars().first()
        refusal = AgentBTools._not_changeable(booking, "rescheduled") if booking else "This booking no longer exists."
        if refusal:
            return _failed(proposal, proposal.action_type, {"success": False, "error": refusal}, refusal)
    start = SchedulingEngine.parse_datetime_kathmandu(payload["start_time"])
    valid, reason = await SchedulingEngine.validate_slot(
        db, user.org_id, start, service.duration_minutes,
        payload.get("practitioner_id"), user.id, exclude_booking_id=exclude_booking_id,
    )
    if not valid:
        alternatives = await SchedulingEngine.find_nearest_alternatives(
            db, user.org_id, service.id, start, payload.get("practitioner_id"), count=3,
            customer_id=user.id, exclude_booking_id=exclude_booking_id,
        )
        card = {
            "type": "reschedule_conflict" if proposal.action_type == "reschedule_booking" else "slot_picker",
            "reason": reason,
            "title": "That time is no longer free. Nearest alternatives",
            "service_id": service.id,
            "service_name": service.name,
            "suggested_slots": alternatives,
            "slots": alternatives,
        }
        return _failed(
            proposal, proposal.action_type,
            {"success": False, "error": reason, "suggested_alternatives": alternatives, "card": card},
            f"That time is no longer available. {reason}",
        )
    return None


async def _execute(db, user, proposal, payload) -> Dict[str, Any]:
    org_id = user.org_id
    user_id = user.id
    action = proposal.action_type
    if action == "create_order":
        return await AgentATools.create_order(
            db, org_id, user_id,
            items=payload.get("items"),
            shipping_address=payload.get("shipping_address"),
            proposal_id=proposal.id,
            conversation_id=proposal.conversation_id,
            manage_transaction=False,
        )
    if action == "update_order":
        return await AgentATools.update_order(
            db, org_id, user_id, payload["order_id"],
            items=payload.get("items"),
            shipping_address=payload.get("shipping_address"),
            manage_transaction=False,
        )
    if action == "cancel_order":
        return await AgentATools.cancel_order(
            db, org_id, user_id, payload["order_id"], manage_transaction=False
        )
    if action == "create_booking":
        return await AgentBTools.create_booking(
            db, org_id, user_id,
            payload["service_id"], payload["practitioner_id"], payload["start_time"],
            proposal_id=proposal.id,
            conversation_id=proposal.conversation_id,
            stage_proposal=False,
            manage_transaction=False,
        )
    if action == "reschedule_booking":
        return await AgentBTools.reschedule_booking(
            db, org_id, user_id, payload["booking_id"], payload["start_time"],
            manage_transaction=False,
        )
    if action == "cancel_booking":
        return await AgentBTools.cancel_booking(
            db, org_id, user_id, payload["booking_id"], manage_transaction=False
        )
    return {"success": False, "error": f"Unsupported action type: {action}"}
