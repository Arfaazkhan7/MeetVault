from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class DecisionEvolutionNode(BaseModel):
    stage: str  # PROPOSAL, CONCERN, ALTERNATIVE, FINAL_DECISION, STATUS_CHANGE
    meeting_id: str
    meeting_title: str
    timestamp: Optional[datetime] = None
    speaker_label: Optional[str] = None
    content: str
    reason: Optional[str] = None

    model_config = {"from_attributes": True}


class DecisionEvolutionHistoryResponse(BaseModel):
    decision_id: str
    project_id: str
    title: str
    original_proposal: Optional[str] = None
    concerns: List[str] = []
    alternatives: List[str] = []
    final_decision: str
    status: str
    reason: str  # Explicit evidence reason or "Reason not found in available meeting evidence."
    source_meetings: List[Dict[str, Any]] = []
    evolution_nodes: List[DecisionEvolutionNode] = []

    model_config = {"from_attributes": True}


class TopicEvolutionNode(BaseModel):
    meeting_id: str
    meeting_title: str
    timestamp: Optional[datetime] = None
    speaker_label: Optional[str] = None
    discussion_point: str
    stage: str  # INTRODUCTION, DISCUSSION, DECISION_LINKED

    model_config = {"from_attributes": True}


class TopicEvolutionHistoryResponse(BaseModel):
    topic_id: str
    topic_name: str
    project_id: str
    first_discussed: Optional[Dict[str, Any]] = None
    meetings_involved: List[Dict[str, Any]] = []
    speakers: List[str] = []
    related_decisions: List[Dict[str, Any]] = []
    related_tasks: List[Dict[str, Any]] = []
    evolution_steps: List[TopicEvolutionNode] = []

    model_config = {"from_attributes": True}


class TaskEvolutionHistoryResponse(BaseModel):
    task_id: str
    title: str
    project_id: str
    created_in_meeting: Optional[Dict[str, Any]] = None
    status_history: List[Dict[str, Any]] = []
    source_meetings: List[Dict[str, Any]] = []

    model_config = {"from_attributes": True}


class CrossMeetingTimelineNode(BaseModel):
    event_type: str  # MEETING, PROPOSAL, CONCERN, ALTERNATIVE, FINAL_DECISION, TASK_UPDATE, DOCUMENT_ADDED
    timestamp: Optional[datetime] = None
    title: str
    description: Optional[str] = None
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    evidence_text: Optional[str] = None
    speaker_label: Optional[str] = None
    entity_id: str

    model_config = {"from_attributes": True}


class CrossMeetingTimelineResponse(BaseModel):
    project_id: str
    total_events: int
    timeline: List[CrossMeetingTimelineNode] = []


# ─── Cross-Meeting Intelligence Natural-Language QA Schemas ─────────────────

class CrossMeetingQueryRequest(BaseModel):
    """Natural-language question spanning multiple authorized meetings, projects, decisions, and people."""
    question: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    person_name: Optional[str] = None
    meeting_ids: Optional[List[str]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    scope: Optional[str] = "all"  # "all" | "project" | "selected_meetings"
    limit: Optional[int] = 20


class DecisionEvolutionSummary(BaseModel):
    """Structured decision evolution chain across meetings."""
    decision_id: str
    title: str
    original_proposal: Optional[str] = None
    current_status: str
    final_decision: Optional[str] = None
    reason: Optional[str] = None
    is_conflicted: bool = False
    conflict_notes: Optional[str] = None
    stages: List[DecisionEvolutionNode] = []
    source_meetings: List[Dict[str, Any]] = []

    model_config = {"from_attributes": True}


class TaskAssignmentSummary(BaseModel):
    """Structured task assignment with deadlines and meeting origins."""
    task_id: str
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_name: Optional[str] = None
    status: str
    priority: Optional[str] = None
    deadline: Optional[datetime] = None
    meeting_id: str
    meeting_title: str

    model_config = {"from_attributes": True}


class SpeakerStatement(BaseModel):
    """Direct statement attributed to a speaker with genuine timestamps."""
    meeting_id: str
    meeting_title: str
    speaker_name: str
    user_id: Optional[str] = None
    is_verified_user: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    timestamp_range: Optional[str] = None
    text: str

    model_config = {"from_attributes": True}


class CrossMeetingQueryResponse(BaseModel):
    """Synthesized cross-meeting intelligence response with traceable source references."""
    question: str
    synthesis: str
    insufficient_evidence: bool = False
    confidence: float = 1.0
    meetings_involved: List[Dict[str, Any]] = []
    decisions: List[DecisionEvolutionSummary] = []
    tasks: List[TaskAssignmentSummary] = []
    statements: List[SpeakerStatement] = []
    unresolved_issues: List[str] = []
    evidence_citations: List[Dict[str, Any]] = []
    model_used: str = "MeetVault Cross-Meeting Intelligence"

    model_config = {"from_attributes": True}

