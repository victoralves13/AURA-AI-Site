"""Integrações — camada HTTP: recebe o pedido, exige login e entrega ao serviço."""
from fastapi import APIRouter, Depends, Header

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.integrations import service
from aura.features.integrations.schemas import IntegrationCreate, IntegrationUpdate

router = APIRouter()


@router.get("/api/integrations")
def list_integrations(org_id: str | None = None, user=Depends(sec.current_user)):
    return service.list_integrations(require_user(user), org_id)


@router.post("/api/integrations")
def create_integration(payload: IntegrationCreate, user=Depends(sec.current_user)):
    return service.create_integration(require_user(user), payload)


@router.patch("/api/integrations/{integration_id}")
def update_integration(integration_id: str, payload: IntegrationUpdate, user=Depends(sec.current_user)):
    return service.update_integration(require_user(user), integration_id, payload)


@router.post("/api/integrations/{integration_id}/rotate-secret")
def rotate_secret(integration_id: str, user=Depends(sec.current_user)):
    return service.rotate_secret(require_user(user), integration_id)


@router.delete("/api/integrations/{integration_id}")
def delete_integration(integration_id: str, user=Depends(sec.current_user)):
    return service.delete_integration(require_user(user), integration_id)


@router.get("/api/integrations/{integration_id}/deliveries")
def list_deliveries(integration_id: str, limit: int = 50, user=Depends(sec.current_user)):
    return service.list_deliveries(require_user(user), integration_id, limit)


@router.post("/api/integrations/{integration_id}/test")
def test_integration(integration_id: str, user=Depends(sec.current_user)):
    return service.test_integration(require_user(user), integration_id)


@router.post("/api/integrations/{integration_id}/deliveries/{delivery_id}/retry")
def retry_delivery(integration_id: str, delivery_id: str, user=Depends(sec.current_user)):
    return service.retry_delivery(require_user(user), integration_id, delivery_id)


@router.post("/api/integrations/{integration_id}/flush")
def flush_integration(integration_id: str, user=Depends(sec.current_user)):
    return service.flush_integration(require_user(user), integration_id)


@router.get("/api/integrations/dispatch")
@router.post("/api/integrations/dispatch")
def dispatch_endpoint(authorization: str | None = Header(default=None), x_cron_secret: str | None = Header(default=None)):
    """Chamada pelo agendador (cron) da hospedagem: entrega o que está vencido e limpa eventos antigos."""
    return service.dispatch_scheduled(authorization, x_cron_secret)
