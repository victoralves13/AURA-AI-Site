"""Onboarding — camada HTTP: só recebe o pedido, exige login e entrega ao serviço."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.onboarding import service

router = APIRouter()


@router.get("/api/onboarding")
def get_onboarding(user=Depends(sec.current_user)):
    return service.get_state(require_user(user))


@router.post("/api/onboarding/steps/{key}/skip")
def skip_step(key: str, user=Depends(sec.current_user)):
    return service.skip_step(require_user(user), key)


@router.post("/api/onboarding/dismiss")
def dismiss(user=Depends(sec.current_user)):
    return service.dismiss(require_user(user))


@router.post("/api/onboarding/reset")
def reset(user=Depends(sec.current_user)):
    return service.reset(require_user(user))
