import datetime
import uuid
from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.models.models import User, RevokedToken

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_BAD_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials or token expired",
    headers={"WWW-Authenticate": "Bearer"},
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.datetime.now(datetime.timezone.utc)
    lifetime = expires_delta or datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # jti lets a single token be revoked at logout without invalidating the user's other sessions.
    to_encode.update({"exp": now + lifetime, "iat": now, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise _BAD_TOKEN

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    if user_id is None or org_id is None:
        raise _BAD_TOKEN

    jti = payload.get("jti")
    if jti and (await db.execute(select(RevokedToken.jti).where(RevokedToken.jti == jti))).first():
        raise _BAD_TOKEN

    # The role is read from the database, not trusted from the token.
    stmt = select(User).where(User.id == user_id, User.org_id == org_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if user is None:
        raise _BAD_TOKEN
    return user

async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access required for this organisation"
        )
    return current_user
