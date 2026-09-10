from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.company import UpdateProfileRequest, UserProfileResponse
from app.services.user_service import update_user_profile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(current_user: User = Depends(get_current_user)):
    """Return the current user's profile."""
    return current_user


@router.patch("/me", response_model=UserProfileResponse)
def update_my_profile(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's profile fields."""
    return update_user_profile(
        db,
        current_user,
        payload.full_name,
        payload.phone,
        payload.avatar_url,
    )
