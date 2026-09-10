from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProjectMemorySummary(BaseModel):
    total_meetings: int
    total_summaries: int
    total_decisions: int
    open_tasks_count: int
    upcoming_deadlines_count: int
    total_topics: int
    recurring_topics_count: int
    total_documents: int
    total_participants: int


class RecentDiscussion(BaseModel):
    meeting_id: str
    meeting_title: str
    start_time: Optional[datetime] = None
    summary_text: str
    key_takeaways: List[str] = []

    model_config = {"from_attributes": True}


class ImportantDecision(BaseModel):
    decision_id: str
    meeting_id: str
    meeting_title: str
    title: str
    description: Optional[str] = None
    status: str
    decision_type: Optional[str] = None
    confidence_level: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OpenTask(BaseModel):
    task_id: str
    meeting_id: str
    meeting_title: str
    title: str
    description: Optional[str] = None
    status: str
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    assignee_id: Optional[str] = None

    model_config = {"from_attributes": True}


class RecurringTopic(BaseModel):
    topic_name: str
    occurrence_count: int
    meeting_ids: List[str] = []
    meeting_titles: List[str] = []
    importance: Optional[str] = None

    model_config = {"from_attributes": True}


class ProjectDocument(BaseModel):
    public_id: str
    title: str
    file_name: str
    file_type: str
    file_url: str
    page_count: int
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProjectParticipant(BaseModel):
    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    meetings_attended_count: int
    roles: List[str] = []

    model_config = {"from_attributes": True}


class TimelineItem(BaseModel):
    event_type: str  # MEETING, DECISION, TASK_DUE, DOCUMENT_ADDED
    timestamp: Optional[datetime] = None
    title: str
    description: Optional[str] = None
    entity_id: str
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None

    model_config = {"from_attributes": True}


class ProjectMemoryDashboardResponse(BaseModel):
    project_id: str
    project_name: str
    company_id: str
    summary: ProjectMemorySummary
    recent_discussions: List[RecentDiscussion] = []
    important_decisions: List[ImportantDecision] = []
    open_tasks: List[OpenTask] = []
    upcoming_deadlines: List[OpenTask] = []
    recurring_topics: List[RecurringTopic] = []
    meeting_timeline: List[TimelineItem] = []
    related_documents: List[ProjectDocument] = []
    participants: List[ProjectParticipant] = []
    source_meetings_count: int
    memory_source_notice: str
