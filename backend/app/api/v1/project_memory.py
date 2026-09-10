from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_project_and_authorize
from app.db.session import get_db
from app.models.project import Project
from app.schemas.project_memory import (
    ImportantDecision,
    OpenTask,
    ProjectDocument,
    ProjectMemoryDashboardResponse,
    ProjectParticipant,
    RecentDiscussion,
    RecurringTopic,
    TimelineItem,
)
from app.services.project_memory_service import (
    get_project_memory_dashboard,
)

router = APIRouter(tags=["project_memory"])


@router.get(
    "/projects/{project_id}/memory",
    response_model=ProjectMemoryDashboardResponse,
)
def get_project_memory(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve full aggregated Project Memory Dashboard for a project across all its meetings."""
    return get_project_memory_dashboard(db, project)


@router.get(
    "/projects/{project_id}/memory/discussions",
    response_model=List[RecentDiscussion],
)
def get_project_memory_discussions(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve recent discussions & summaries from all meetings in the project."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.recent_discussions


@router.get(
    "/projects/{project_id}/memory/decisions",
    response_model=List[ImportantDecision],
)
def get_project_memory_decisions(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve decisions made across project meetings."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.important_decisions


@router.get(
    "/projects/{project_id}/memory/tasks",
    response_model=List[OpenTask],
)
def get_project_memory_tasks(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve open tasks across project meetings."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.open_tasks


@router.get(
    "/projects/{project_id}/memory/topics",
    response_model=List[RecurringTopic],
)
def get_project_memory_topics(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve topics & recurring topics across project meetings."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.recurring_topics


@router.get(
    "/projects/{project_id}/memory/timeline",
    response_model=List[TimelineItem],
)
def get_project_memory_timeline(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve chronological project memory timeline."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.meeting_timeline


@router.get(
    "/projects/{project_id}/memory/documents",
    response_model=List[ProjectDocument],
)
def get_project_memory_documents(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve documents associated with the project or its meetings."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.related_documents


@router.get(
    "/projects/{project_id}/memory/participants",
    response_model=List[ProjectParticipant],
)
def get_project_memory_participants(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """Retrieve aggregated participants across project meetings."""
    dashboard = get_project_memory_dashboard(db, project)
    return dashboard.participants
