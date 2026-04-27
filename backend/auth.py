from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
from settings import settings
import models

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expiration_minutes)
    )
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _get_user_from_token(token: str, db: Session) -> models.User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.get(models.User, user_id)
    if user is None:
        raise credentials_exc
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    return _get_user_from_token(token, db)


def get_current_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """
    Platform-admin gate. Requires `is_admin=True` on the calling user.

    What `is_admin=True` permits today:
      - Run `/api/admin/audit` (filterable audit log; ballot content redacted)
      - Run `/api/admin/audit/ballots/{id}` to elevate and view individual
        ballot contents (self-logs the elevation with required reason)
      - Run `/api/admin/delegation-graph` (system-wide delegation graph;
        access is itself audited)
      - Run `/api/admin/users` (system user list; access is itself audited)
      - PATCH `/api/admin/users/{id}/make-admin` to grant the role to others
      - Debug-only: `/api/admin/seed`, `/api/admin/time-simulation` (require
        `DEBUG=true`; never reachable in production)

    What `is_admin=True` does NOT permit:
      - Bypass the elevation/audit requirement when viewing ballot content
      - Change another user's password (no admin password-set endpoint)
      - Impersonate users (no impersonation flow exists)
      - Read or write outside the audit/elevation/admin endpoints listed
        above

    See `SECURITY_REVIEW.md` (Privileged Access Tiers) for the full role
    boundary and the org-admin role for contrast.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def get_optional_user(
    token: Optional[str] = Depends(OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    if token is None:
        return None
    try:
        return _get_user_from_token(token, db)
    except HTTPException:
        return None
