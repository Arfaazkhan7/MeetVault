from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_membership, get_project_and_authorize
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.cross_meeting import (
    CrossMeetingTimelineResponse,
    DecisionEvolutionHistoryResponse,
    TopicEvolutionHistoryResponse,
    CrossMeetingQueryRequest,
    CrossMeetingQueryResponse,
)
from app.services.cross_meeting_service import (
    get_cross_meeting_timeline,
    get_decision_evolution_history,
    get_topic_evolution_history,
    answer_cross_meeting_query,
)

router = APIRouter(tags=["cross_meeting"])


@router.post(
    "/cross-meeting/query",
    response_model=CrossMeetingQueryResponse,
)
def query_cross_meeting_intelligence(
    request: CrossMeetingQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask natural-language questions spanning multiple meetings, people, projects,
    decisions, tasks, deadlines, and unresolved issues.
    """
    return answer_cross_meeting_query(db, request, current_user)


@router.post(
    "/projects/{project_id}/cross-meeting/query",
    response_model=CrossMeetingQueryResponse,
)
def query_project_cross_meeting(
    project_id: str,
    request: CrossMeetingQueryRequest,
    current_user: User = Depends(get_current_user),
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """
    Ask natural-language questions scoped to a specific project across all its meetings.
    """
    scoped_request = CrossMeetingQueryRequest(
        question=request.question,
        project_id=project_id,
        project_name=project.name,
        person_name=request.person_name,
        meeting_ids=request.meeting_ids,
        date_from=request.date_from,
        date_to=request.date_to,
        scope="project",
        limit=request.limit,
    )
    return answer_cross_meeting_query(db, scoped_request, current_user)


@router.post(
    "/companies/{company_id}/cross-meeting/query",
    response_model=CrossMeetingQueryResponse,
)
def query_company_cross_meeting(
    company_id: str,
    request: CrossMeetingQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask natural-language questions across meetings within a company workspace.
    """
    get_membership(db, current_user.public_id, company_id)
    return answer_cross_meeting_query(db, request, current_user)


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
