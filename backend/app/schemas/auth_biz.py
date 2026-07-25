"""鉴权与业务相关 Schema。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _normalize_email(value: str) -> str:
    """开发环境允许 demo@fitpilot.local 等特殊域名。"""
    email = (value or "").strip().lower()
    if "@" not in email:
        raise ValueError("邮箱格式无效")
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError("邮箱格式无效")
    if len(email) > 255:
        raise ValueError("邮箱过长")
    return email


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=10, max_length=72)

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        """密码策略：至少 10 位，且同时包含字母和数字。"""
        if not any(c.isalpha() for c in v):
            raise ValueError("密码需至少包含一个字母（建议字母+数字组合，长度 ≥ 10 位）")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码需至少包含一个数字（建议字母+数字组合，长度 ≥ 10 位）")
        return v


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str

    @field_validator("email")
    @classmethod
    def email_ok(cls, v: str) -> str:
        return _normalize_email(v)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


class ProfileOut(BaseModel):
    user_id: int
    display_name: str | None = None
    sex: str | None = None
    age: int | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    goal: str | None = None
    activity_level: str | None = None
    equipment: str | None = None
    injuries: str | None = None
    diet_prefs: str | None = None
    restrictions: str | None = None
    experience_level: str | None = None
    weekly_sessions: int | None = None
    nutrition_estimate: dict[str, Any] | None = None


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    sex: str | None = None
    age: int | None = Field(default=None, ge=10, le=100)
    height_cm: float | None = Field(default=None, gt=0, le=250)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    goal: str | None = None
    activity_level: str | None = None
    equipment: str | None = None
    injuries: str | None = None
    diet_prefs: str | None = None
    restrictions: str | None = None
    experience_level: str | None = None
    weekly_sessions: int | None = Field(default=None, ge=0, le=14)


class FoodOut(BaseModel):
    id: int
    name: str
    brand: str | None = None
    category: str | None = None
    serving_g: float
    kcal_per_100g: float
    protein_g_per_100g: float
    carb_g_per_100g: float
    fat_g_per_100g: float


class FoodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    brand: str | None = None
    category: str | None = None
    serving_g: float = 100.0
    kcal_per_100g: float = Field(ge=0)
    protein_g_per_100g: float = Field(default=0, ge=0)
    carb_g_per_100g: float = Field(default=0, ge=0)
    fat_g_per_100g: float = Field(default=0, ge=0)


class WorkoutLogCreate(BaseModel):
    log_date: date
    exercise: str = Field(min_length=1, max_length=128)
    exercise_id: int | None = None
    sets: int | None = None
    reps: int | None = None
    weight_kg: float | None = None
    duration_min: float | None = None
    rpe: float | None = None
    notes: str | None = None


class WorkoutLogOut(WorkoutLogCreate):
    id: int
    user_id: int
    created_at: datetime | None = None


class ExerciseOut(BaseModel):
    id: int
    external_id: str
    name_en: str
    name_zh: str | None = None
    display_name: str | None = None
    body_part: str | None = None
    equipment: str | None = None
    primary_muscle: str | None = None
    secondary_muscles: list[str] = []
    instructions_zh: str | None = None
    steps_zh: list[str] = []
    tags: list[str] = []


class DietLogCreate(BaseModel):
    log_date: date
    food_item_id: int | None = None
    food_name: str | None = None
    amount_g: float = Field(gt=0)
    meal: str | None = None
    notes: str | None = None


class DietLogOut(BaseModel):
    id: int
    user_id: int
    log_date: date
    food_item_id: int | None
    food_name: str
    amount_g: float
    meal: str | None
    kcal: float
    protein_g: float
    carb_g: float
    fat_g: float
    notes: str | None = None
    created_at: datetime | None = None


class BodyMetricCreate(BaseModel):
    log_date: date
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    waist_cm: float | None = None
    notes: str | None = None


class BodyMetricOut(BodyMetricCreate):
    id: int
    user_id: int
    created_at: datetime | None = None


class AgentTaskCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class AgentResumeRequest(BaseModel):
    message: str | None = Field(default=None, max_length=4000)
    checkpoint_id: str | None = None


class AgentApproveRequest(BaseModel):
    approve: bool = True
    comment: str | None = None


class PlanPreviewRequest(BaseModel):
    goal_override: str | None = None
    notes: str | None = None


class PlanApproveRequest(BaseModel):
    approve: bool = True
    comment: str | None = None
    pending: dict[str, Any] | None = Field(
        default=None,
        description="可选：直接提交已暂存的 pending（避免重新生成预览）",
    )


class MealSwapRequest(BaseModel):
    meal_index: int = Field(ge=0, le=2, description="餐次索引 0=早餐 1=午餐 2=晚餐")
    swap_food_id: int | None = Field(default=None, description="指定替换食物 ID；空则自动重选")
    meals: list[dict[str, Any]] = Field(description="当前餐次列表")
    daily_targets: dict[str, Any] = Field(description="每日营养目标")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=512)
