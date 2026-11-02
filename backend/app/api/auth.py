import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, get_current_user
from app.models.models import User, Organisation
from app.models.schemas import UserLogin, UserRegister, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=TokenResponse)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check organisation exists
    org_stmt = select(Organisation).where(
        (Organisation.id == payload.org_id) | (Organisation.slug == payload.org_id)
    )
    res = await db.execute(org_stmt)
    org = res.scalars().first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation '{payload.org_id}' not found."
        )

    # Check if user already exists in this organisation
    user_stmt = select(User).where(User.org_id == org.id, User.email == payload.email)
    u_res = await db.execute(user_stmt)
    if u_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists in this organisation."
        )

    user_id = f"user_{uuid.uuid4().hex[:8]}"
    # Public sign-up always assigns the customer role to prevent privilege escalation
    new_user = User(
        id=user_id,
        org_id=org.id,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        name=payload.name,
        role="customer"
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token({
        "sub": new_user.id,
        "org_id": new_user.org_id,
        "role": new_user.role,
        "email": new_user.email,
        "name": new_user.name
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut.from_orm(new_user)
    )

@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email == payload.email)
    if payload.org_id:
        # Resolve org slug or id
        org_stmt = select(Organisation).where(
            (Organisation.id == payload.org_id) | (Organisation.slug == payload.org_id)
        )
        o_res = await db.execute(org_stmt)
        org = o_res.scalars().first()
        if org:
            stmt = stmt.where(User.org_id == org.id)

    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password for this organisation entry point."
        )

    token = create_access_token({
        "sub": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "email": user.email,
        "name": user.name
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut.from_orm(user)
    )

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.from_orm(current_user)

