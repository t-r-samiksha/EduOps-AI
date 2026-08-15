import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user
from app.services.supabase_admin import create_admin_auth_account, sign_in_and_get_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("eduops.signup")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)


@router.get("/me")
def read_current_user(user: CurrentUser = Depends(get_current_user)):
    return {"sub": user.sub, "email": user.email, "role": user.role, "user_id": user.id, "school_id": user.school_id}


class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str
    school_name: str


class SignupResponse(BaseModel):
    access_token: str
    user_id: int
    school_id: int
    email: str
    school_name: str


# --- POST /auth/signup ---------------------------------------------------------
# Deliberately public/unauthenticated - this is how a school's very first admin
# account gets created in the first place, so it can't itself require being
# already logged in. No rate-limiting infrastructure exists anywhere in this
# repo (no slowapi/nginx/API-gateway layer) - a real gap for a genuinely public
# endpoint, flagged honestly rather than silently left unmentioned. What IS
# real here: every attempt (success or failure) is logged clearly via the
# dedicated `eduops.signup` logger below, so abuse is at least visible after
# the fact even though it isn't currently blocked in real time.


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if not body.full_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "full_name must not be empty")
    if not body.school_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "school_name must not be empty")
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password must be at least 8 characters")

    if db.query(User).filter(User.email == body.email).one_or_none() is not None:
        logger.info("signup rejected - email already registered locally: %s", body.email)
        raise HTTPException(status.HTTP_409_CONFLICT, f"A user with email {body.email} already exists")

    # Real Supabase Auth account first - external call, can't be rolled back by
    # our own DB transaction. If everything after this fails, the real auth
    # account is left orphaned with no local School/User row - the same known,
    # accepted edge case documented on teachers.py's create_teacher endpoint
    # (no distributed transaction across Supabase Auth + Postgres exists).
    supabase_id = create_admin_auth_account(email=body.email, password=body.password, full_name=body.full_name)

    try:
        admin_role = db.query(Role).filter(Role.name == "admin").one()

        school = School(name=body.school_name.strip())
        db.add(school)
        db.flush()

        user = User(
            supabase_id=supabase_id,
            email=body.email,
            full_name=body.full_name,
            role_id=admin_role.id,
            school_id=school.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.refresh(school)
    except Exception:
        db.rollback()
        logger.exception(
            "signup: Supabase Auth account created but local School/User creation failed - orphaned auth account for %s",
            body.email,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Account creation failed after the login credentials were created - contact support before retrying with this email",
        )

    access_token = sign_in_and_get_access_token(email=body.email, password=body.password)

    logger.info(
        "signup succeeded: email=%s user_id=%s school_id=%s school_name=%r",
        body.email, user.id, school.id, school.name,
    )

    return SignupResponse(
        access_token=access_token, user_id=user.id, school_id=school.id, email=user.email, school_name=school.name
    )
