"""Ações — camada HTTP."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.actions import service
from aura.features.actions.schemas import ActionCreate, ActionUpdate, FeedbackBody, OutcomeCreate

router = APIRouter()


@router.get("/api/actions")
def list_actions(org_id: str | None = None, status: str | None = None, meeting_id: str | None = None,
                 client_id: str | None = None, assignee: str | None = None, overdue: bool = False,
                 limit: int = 200, user=Depends(sec.current_user)):
    return service.list_actions(require_user(user), org_id, status, meeting_id, client_id, assignee, overdue, limit)


@router.get("/api/actions/stats")
def action_stats(org_id: str | None = None, client_id: str | None = None, user=Depends(sec.current_user)):
    return service.action_stats(require_user(user), org_id, client_id)


@router.post("/api/actions/sync")
def sync_space(org_id: str | None = None, user=Depends(sec.current_user)):
    return service.sync_space(require_user(user), org_id)


@router.get("/api/meetings/{meeting_id}/actions")
def meeting_actions(meeting_id: str, user=Depends(sec.current_user)):
    return service.meeting_actions(require_user(user), meeting_id)


@router.post("/api/meetings/{meeting_id}/actions/sync")
def sync_meeting(meeting_id: str, user=Depends(sec.current_user)):
    return service.sync_meeting(require_user(user), meeting_id)


@router.post("/api/meetings/{meeting_id}/actions")
def create_action(meeting_id: str, payload: ActionCreate, user=Depends(sec.current_user)):
    return service.create_action(require_user(user), meeting_id, payload)


@router.patch("/api/actions/{action_id}")
def update_action(action_id: str, payload: ActionUpdate, user=Depends(sec.current_user)):
    return service.update_action(require_user(user), action_id, payload)


@router.delete("/api/actions/{action_id}")
def delete_action(action_id: str, user=Depends(sec.current_user)):
    return service.delete_action(require_user(user), action_id)


@router.get("/api/actions/{action_id}/events")
def action_events(action_id: str, user=Depends(sec.current_user)):
    return service.action_events(require_user(user), action_id)


@router.post("/api/actions/{action_id}/outcomes")
def add_outcome(action_id: str, payload: OutcomeCreate, user=Depends(sec.current_user)):
    return service.add_outcome(require_user(user), action_id, payload)


@router.get("/api/actions/{action_id}/outcomes")
def list_outcomes(action_id: str, user=Depends(sec.current_user)):
    return service.list_outcomes(require_user(user), action_id)


@router.put("/api/actions/{action_id}/feedback")
def set_feedback(action_id: str, payload: FeedbackBody, user=Depends(sec.current_user)):
    return service.set_feedback(require_user(user), action_id, payload)


@router.delete("/api/actions/{action_id}/feedback")
def clear_feedback(action_id: str, user=Depends(sec.current_user)):
    return service.clear_feedback(require_user(user), action_id)
