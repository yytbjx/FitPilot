"""API 路由聚合。"""

from fastapi import APIRouter

from app.api import (
    agent,
    auth,
    eval as eval_api,
    exercises,
    foods,
    health,
    knowledge,
    logs,
    memories,
    plans,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(foods.router)
api_router.include_router(exercises.router)
api_router.include_router(logs.router)
api_router.include_router(plans.router)
api_router.include_router(agent.router)
api_router.include_router(knowledge.router)
api_router.include_router(memories.router)
api_router.include_router(eval_api.router)
