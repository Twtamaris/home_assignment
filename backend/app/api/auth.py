import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import RateLimiter
from app.core.security import (
    verify_password, get_password_hash, create_access_token, get_current_user, decode_token, oauth2_scheme,
)
from app.models.models import User, Organisation, RevokedToken
from app.models.schemas import UserLogin, UserRegister, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Slows down password guessing. Keyed by client address and email so one noisy client
# cannot lock a real customer out of their own account.
auth_rate_limiter = RateLimiter(limit=settings.AUTH_RATE_LIMIT_PER_MINUTE, window_seconds=60)


def _throttle(request: Request, email: str) -> None:
    client = request.client.host if request.client else "unknown"
    auth_rate_limiter.check(f"{client}:{email.lower()}")


async def _find_org(db: AsyncSession, ref: str):
    stmt = select(Organisation).where((Organisation.id == ref) | (Organisation.slug == ref))
    return (await db.execute(stmt)).scalars().first()


def _token_for(user: User) -> TokenResponse:
    token = create_access_token({
        "sub": user.id,
        "org_id": user.org_id,
        "role": user.role,
        "email": user.email,
        "name": user.name
    })
    return TokenResponse(access_token=token, token_type="bearer", user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse)
async def register(payload: UserRegister, request: Request = None, db: AsyncSession = Depends(get_db)):
    if request is not None:
        _throttle(request, payload.email)

    # The organisation comes from the entry point the form was submitted on.
    org = await _find_org(db, payload.org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organisation '{payload.org_id}' not found."
        )

    user_stmt = select(User).where(User.org_id == org.id, User.email == payload.email)
    if (await db.execute(user_stmt)).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists in this organisation."
        )

    # Public sign-up always assigns the customer role to prevent privilege escalation
    new_user = User(
        id=f"user_{uuid.uuid4().hex[:8]}",
        org_id=org.id,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        name=payload.name,
        role="customer"
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return _token_for(new_user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    _throttle(request, payload.email)
    if not payload.org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in from your organisation's entry point.",
        )
    org = await _find_org(db, payload.org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown organisation.",
        )
    stmt = select(User).where(User.email == payload.email, User.org_id == org.id)
    user = (await db.execute(stmt)).scalars().first()

    # One message for "no such user" and "wrong password", and for a user from a different organisation.
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password for this organisation entry point."
        )
    return _token_for(user)


@router.post("/logout")
async def logout(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revokes this token. Other sessions of the same user stay signed in."""
    payload = decode_token(token)
    jti = payload.get("jti")
    if jti:
        expires = datetime.datetime.fromtimestamp(payload["exp"], datetime.timezone.utc).replace(tzinfo=None)
        db.add(RevokedToken(jti=jti, user_id=current_user.id, expires_at=expires))
    # Rows for tokens that have expired anyway can go.
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.datetime.utcnow()))
    await db.commit()
    return {"success": True, "message": "Signed out."}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)
