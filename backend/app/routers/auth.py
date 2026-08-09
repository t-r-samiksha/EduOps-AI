from fastapi import APIRouter, Depends

from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def read_current_user(user: CurrentUser = Depends(get_current_user)):
    return {"sub": user.sub, "email": user.email, "role": user.role}
