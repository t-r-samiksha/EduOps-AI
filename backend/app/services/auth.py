import json
import os
import time
import urllib.request
import uuid

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.role import Role
from app.models.user import User

load_dotenv()

# Supabase signs access tokens with a per-project asymmetric key (ES256) by
# default; verify against its published JWKS rather than a shared secret.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_JWKS_TTL_SECONDS = 3600

bearer_scheme = HTTPBearer(auto_error=False)

_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}


def _fetch_jwks() -> list[dict]:
    with urllib.request.urlopen(JWKS_URL, timeout=5) as resp:
        return json.load(resp).get("keys", [])


def _get_signing_key(kid: str) -> dict:
    now = time.time()
    if not _jwks_cache["keys"] or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS:
        _jwks_cache["keys"] = _fetch_jwks()
        _jwks_cache["fetched_at"] = now

    for key in _jwks_cache["keys"]:
        if key.get("kid") == kid:
            return key

    # kid not found - keys may have rotated since our last fetch, refresh once.
    _jwks_cache["keys"] = _fetch_jwks()
    _jwks_cache["fetched_at"] = time.time()
    for key in _jwks_cache["keys"]:
        if key.get("kid") == kid:
            return key

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown signing key")


class CurrentUser:
    def __init__(self, id: int, sub: str, email: str | None, role: str | None, school_id: int | None = None):
        self.id = id
        self.sub = sub
        self.email = email
        self.role = role
        self.school_id = school_id


def _get_or_create_user(db: Session, supabase_id: uuid.UUID, email: str | None, role: str | None) -> User:
    user = db.query(User).filter(User.supabase_id == supabase_id).one_or_none()
    if user is not None:
        return user

    role_row = db.query(Role).filter(Role.name == role).one_or_none()
    if role_row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown role")

    user = User(supabase_id=supabase_id, email=email, role_id=role_row.id)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Another concurrent request for the same user won the race - use their row.
        db.rollback()
        user = db.query(User).filter(User.supabase_id == supabase_id).one()
    else:
        db.refresh(user)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        signing_key = _get_signing_key(header["kid"])
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[header.get("alg", "ES256")],
            audience="authenticated",
        )
    except (JWTError, KeyError, OSError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    role = payload.get("app_metadata", {}).get("role") or payload.get("user_metadata", {}).get("role")
    supabase_id = uuid.UUID(payload["sub"])
    email = payload.get("email")

    user = _get_or_create_user(db, supabase_id, email, role)
    return CurrentUser(id=user.id, sub=str(user.supabase_id), email=user.email, role=role, school_id=user.school_id)


def require_role(*allowed_roles: str):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dependency
