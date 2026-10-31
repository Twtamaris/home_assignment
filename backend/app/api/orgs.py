from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.models import Organisation
from app.models.schemas import OrgOut

router = APIRouter(prefix="/orgs", tags=["Organisations"])

@router.get("", response_model=List[OrgOut])
async def list_organisations(db: AsyncSession = Depends(get_db)):
    stmt = select(Organisation)
    res = await db.execute(stmt)
    return [OrgOut.from_orm(o) for o in res.scalars().all()]

@router.get("/{slug_or_id}", response_model=OrgOut)
async def get_organisation(slug_or_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Organisation).where(
        (Organisation.id == slug_or_id) | (Organisation.slug == slug_or_id)
    )
    res = await db.execute(stmt)
    org = res.scalars().first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation '{slug_or_id}' not found."
        )
    return OrgOut.from_orm(org)
