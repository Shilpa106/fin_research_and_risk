from fastapi import APIRouter

from .endpoints import auth, copilot, evaluation, health, hitl, observability, research, risk

v1_router = APIRouter()

# Register sub-routers
v1_router.include_router(health.router)
v1_router.include_router(auth.router)
v1_router.include_router(copilot.router)
v1_router.include_router(research.router)
v1_router.include_router(risk.router)
v1_router.include_router(hitl.router)
v1_router.include_router(evaluation.router)
v1_router.include_router(observability.router)
