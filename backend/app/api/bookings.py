from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Booking, Service, Practitioner
from app.models.schemas import (
    BookingOut, BookingCreate, BookingReschedule, ServiceOut, PractitionerOut
)
from app.services.agent_b import AgentBTools
from app.services.scheduling import SchedulingEngine

router = APIRouter(prefix="/bookings", tags=["Bookings (Lotus Wellness Studio)"])

@router.get("/services", response_model=List[ServiceOut])
async def list_services(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Service).where(Service.org_id == current_user.org_id)
    res = await db.execute(stmt)
    return [ServiceOut.model_validate(s) for s in res.scalars().all()]

@router.get("/practitioners", response_model=List[PractitionerOut])
async def list_practitioners(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Practitioner).where(Practitioner.org_id == current_user.org_id)
    res = await db.execute(stmt)
    return [
        PractitionerOut(
            id=p.id,
            org_id=p.org_id,
            name=p.name,
            title=p.title,
            specialties=p.specialties,
            bio=p.bio
        )
        for p in res.scalars().all()
    ]

@router.get("/slots")
async def get_slots(
    service_id: str,
    date: str,
    practitioner_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    slots = await SchedulingEngine.find_available_slots(
        db, current_user.org_id, service_id, date, practitioner_id
    )
    return {"slots": slots}

@router.get("", response_model=List[BookingOut])
async def list_bookings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Booking).where(
        Booking.org_id == current_user.org_id,
        Booking.user_id == current_user.id
    ).order_by(desc(Booking.start_time))
    res = await db.execute(stmt)
    bookings = res.scalars().all()

    out = []
    for b in bookings:
        s_res = await db.execute(select(Service.name).where(Service.id == b.service_id))
        s_name = s_res.scalar()
        p_res = await db.execute(select(Practitioner.name).where(Practitioner.id == b.practitioner_id))
        p_name = p_res.scalar()

        out.append(
            BookingOut(
                id=b.id,
                org_id=b.org_id,
                user_id=b.user_id,
                service_id=b.service_id,
                practitioner_id=b.practitioner_id,
                start_time=b.start_time,
                end_time=b.end_time,
                status=b.status,
                cancellation_fee=b.cancellation_fee or 0.0,
                reschedule_count=b.reschedule_count or 0,
                notes=b.notes,
                service_name=s_name,
                practitioner_name=p_name,
                created_at=b.created_at
            )
        )
    return out

@router.post("", response_model=BookingOut)
async def create_booking_endpoint(
    payload: BookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Create a proposal in chat, then POST /api/actions/proposals/{proposal_id}/confirm.",
    )

@router.post("/{booking_id}/reschedule")
async def reschedule_booking_endpoint(
    booking_id: str,
    payload: BookingReschedule,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Create a proposal in chat, then POST /api/actions/proposals/{proposal_id}/confirm.",
    )

@router.post("/{booking_id}/cancel")
async def cancel_booking_endpoint(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Create a proposal in chat, then POST /api/actions/proposals/{proposal_id}/confirm.",
    )

