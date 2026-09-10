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
