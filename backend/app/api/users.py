"""当前用户档案。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_request_id, ok
from app.db.session import get_db
from app.models.user import User, UserProfile
from app.schemas.auth_biz import ProfileUpdate
from app.services.nutrition import estimate_tdee, target_macros_for_goal

router = APIRouter(prefix="/users", tags=["users"])


def _profile_payload(user: User, profile: UserProfile | None) -> dict:
    data = {
        "user_id": user.id,
        "email": user.email,
        "display_name": None,
        "sex": None,
        "age": None,
        "height_cm": None,
        "weight_kg": None,
        "goal": None,
        "activity_level": None,
        "equipment": None,
        "injuries": None,
        "diet_prefs": None,
        "restrictions": None,
        "experience_level": None,
        "weekly_sessions": None,
        "nutrition_estimate": None,
    }
    if profile is None:
        return data
    data.update(
        {
            "display_name": profile.display_name,
            "sex": profile.sex,
            "age": profile.age,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "goal": profile.goal,
            "activity_level": profile.activity_level,
            "equipment": profile.equipment,
            "injuries": profile.injuries,
            "diet_prefs": profile.diet_prefs,
            "restrictions": profile.restrictions,
            "experience_level": profile.experience_level,
            "weekly_sessions": profile.weekly_sessions,
        }
    )
    if (
        profile.weight_kg
        and profile.height_cm
        and profile.age
    ):
        energy = estimate_tdee(
            sex=profile.sex,
            weight_kg=profile.weight_kg,
            height_cm=profile.height_cm,
            age=profile.age,
            activity_level=profile.activity_level,
        )
        macros = target_macros_for_goal(energy["tdee"], profile.goal, profile.weight_kg)
        data["nutrition_estimate"] = {**energy, "targets": macros}
    return data


@router.get("/me/profile")
async def get_profile(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    return JSONResponse(ok(rid, _profile_payload(user, profile)))


@router.put("/me/profile")
async def update_profile(
    body: ProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return JSONResponse(ok(rid, _profile_payload(user, profile)))
