import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, ActionProposal
from app.models.schemas import ActionProposalConfirmResponse
from app.services.actions_service import ActionService

router = APIRouter(prefix="/actions", tags=["Action Proposals & Confirmation Gate"])

@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Scoped to tenant and owner: another customer's or another organisation's proposal is a 404.
    stmt = select(ActionProposal).where(
        ActionProposal.id == proposal_id,
        ActionProposal.org_id == current_user.org_id,
        ActionProposal.user_id == current_user.id,
    )
    res = await db.execute(stmt)
    prop = res.scalars().first()
    if not prop:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return {
        "id": prop.id,
        "org_id": prop.org_id,
        "user_id": prop.user_id,
        "action_type": prop.action_type,
        "status": prop.status,
        "summary_text": prop.summary_text,
        "payload": json.loads(prop.payload_json),
        "created_at": prop.created_at,
        "expires_at": prop.expires_at,
    }

@router.post("/proposals/{proposal_id}/confirm", response_model=ActionProposalConfirmResponse)
async def confirm_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Claims the proposal, rechecks price, stock or the slot, and writes in one transaction.
    """
    return await ActionService.confirm(db, current_user, proposal_id)

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await ActionService.reject(db, current_user, proposal_id)
