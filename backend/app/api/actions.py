import json
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, ActionProposal
from app.models.schemas import ActionProposalOut, ActionProposalConfirmResponse
from app.services.agent_a import AgentATools
from app.services.agent_b import AgentBTools

router = APIRouter(prefix="/actions", tags=["Action Proposals & Confirmation Gate"])

@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ActionProposal).where(
        ActionProposal.id == proposal_id,
        ActionProposal.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    prop = res.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if prop.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this action proposal")

    return {
        "id": prop.id,
        "org_id": prop.org_id,
        "user_id": prop.user_id,
        "action_type": prop.action_type,
        "status": prop.status,
        "summary_text": prop.summary_text,
        "payload": json.loads(prop.payload_json),
        "created_at": prop.created_at
    }

@router.post("/proposals/{proposal_id}/confirm", response_model=ActionProposalConfirmResponse)
async def confirm_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-side Confirmation Gate:
    1. Authenticates user and verifies org_id boundary.
    2. Enforces idempotency: rejects duplicate confirmation attempts.
    3. Re-checks stock/slot availability atomically.
    4. Executes the database mutation in an isolated transaction.
    5. Marks proposal as 'confirmed'.
    """
    stmt = select(ActionProposal).where(
        ActionProposal.id == proposal_id,
        ActionProposal.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    prop = res.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if prop.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this action proposal")

    if prop.status == "confirmed":
        raise HTTPException(status_code=400, detail="Proposal has already been confirmed and executed.")
    if prop.status == "rejected":
        raise HTTPException(status_code=400, detail="Proposal was previously rejected.")
    if prop.expires_at and datetime.datetime.utcnow() > prop.expires_at:
        prop.status = "expired"
        await db.commit()
        raise HTTPException(status_code=400, detail="Proposal has expired. Please request a new summary.")

    payload = json.loads(prop.payload_json)
    action_type = prop.action_type

    if action_type == "create_order":
        items = payload.get("items", [])
        shipping_address = payload.get("shipping_address", "Kathmandu, Nepal")
        result = await AgentATools.create_order(
            db=db,
            org_id=current_user.org_id,
            user_id=current_user.id,
            items=items,
            shipping_address=shipping_address,
            confirmed=True,
            proposal_id=prop.id,
            conversation_id=prop.conversation_id
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message") or result.get("error"))

        prop.status = "confirmed"
        await db.commit()
        return ActionProposalConfirmResponse(
            proposal_id=prop.id,
            status="confirmed",
            action_type=action_type,
            result=result,
            message="Order successfully confirmed and placed."
        )

    elif action_type == "create_booking":
        service_id = payload.get("service_id")
        practitioner_id = payload.get("practitioner_id")
        start_time_str = payload.get("start_time")
        notes = payload.get("notes")

        result = await AgentBTools.create_booking(
            db=db,
            org_id=current_user.org_id,
            user_id=current_user.id,
            service_id=service_id,
            practitioner_id=practitioner_id,
            start_time_str=start_time_str,
            notes=notes,
            proposal_id=prop.id,
            conversation_id=prop.conversation_id
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("message") or result.get("error"))

        prop.status = "confirmed"
        await db.commit()
        return ActionProposalConfirmResponse(
            proposal_id=prop.id,
            status="confirmed",
            action_type=action_type,
            result=result,
            message="Booking successfully confirmed."
        )

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action type: {action_type}")

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ActionProposal).where(
        ActionProposal.id == proposal_id,
        ActionProposal.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    prop = res.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if prop.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this action proposal")

    if prop.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot reject proposal in status '{prop.status}'.")

    prop.status = "rejected"
    await db.commit()
    return {"success": True, "proposal_id": prop.id, "status": "rejected"}
