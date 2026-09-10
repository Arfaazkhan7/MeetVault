from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_project_and_authorize
from app.db.session import get_db
from app.models.project import Project
from app.schemas.cross_meeting import (
    CrossMeetingTimelineResponse,
    DecisionEvolutionHistoryResponse,
    TopicEvolutionHistoryResponse,
)
from app.services.cross_meeting_service import (
    get_cross_meeting_timeline,
    get_decision_evolution_history,
    get_topic_evolution_history,
)

router = APIRouter(tags=["cross_meeting"])


@router.get(
    "/projects/{project_id}/decisions/{decision_id}/history",
    response_model=DecisionEvolutionHistoryResponse,
)
def get_decision_history(
    project_id: str,
    decision_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve complete decision evolution chain (Proposal -> Concern -> Alternative -> Final Decision) across meetings."""
    return get_decision_evolution_history(db, project=project, decision_identifier=decision_id)


@router.get(
    "/projects/{project_id}/topics/{topic_id}/history",
    response_model=TopicEvolutionHistoryResponse,
)
def get_topic_history(
    project_id: str,
    topic_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve topic evolution history across meetings, speakers, and related items."""
    return get_topic_evolution_history(db, project=project, topic_identifier=topic_id)


@router.get(
    "/projects/{project_id}/timeline",
    response_model=CrossMeetingTimelineResponse,
)
def get_cross_meeting_project_timeline(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve unified cross-meeting timeline with chronological evidence."""
    return get_cross_meeting_timeline(db, project=project)
