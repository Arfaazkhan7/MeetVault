from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, String
from fastapi import HTTPException, status

from app.models.project import Project
from app.models.meeting import Meeting, MeetingParticipant
from app.models.decision import Decision, DecisionHistory
from app.models.topic import Topic, MeetingTopic
from app.models.task import Task
from app.models.document import Document
from app.models.evidence import Evidence
from app.models.user import User

from app.schemas.cross_meeting import (
    DecisionEvolutionHistoryResponse,
    DecisionEvolutionNode,
    TopicEvolutionHistoryResponse,
    TopicEvolutionNode,
    TaskEvolutionHistoryResponse,
    CrossMeetingTimelineResponse,
    CrossMeetingTimelineNode,
)

REASON_NOT_FOUND = "Reason not found in available meeting evidence."


def get_decision_evolution_history(
    db: Session,
    project: Project,
    decision_identifier: str,
) -> DecisionEvolutionHistoryResponse:
    """Fetch decision evolution chain (Proposal -> Concern -> Alternative -> Final Decision) across meetings."""
    # Build query filter supporting both UUID casting and title matching
    decision_id_str = str(decision_identifier).strip()

    conds = [
        cast(Decision.id, String) == decision_id_str,
        Decision.title.ilike(decision_id_str),
        Decision.title.ilike(f"%{decision_id_str}%"),
    ]
    try:
        parsed_uuid = uuid.UUID(decision_id_str)
        conds.append(Decision.id == parsed_uuid)
    except Exception:
        pass

    decision = db.query(Decision).filter(
        Decision.company_id == project.company_id,
        or_(*conds)
    ).first()


    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision '{decision_identifier}' not found in project",
        )

    # Fetch all meetings for project to map meeting_id -> Meeting
    project_meetings = db.query(Meeting).filter(
        Meeting.project_id == project.public_id,
        Meeting.deleted_at.is_(None)
    ).all()
    meeting_map = {m.public_id: m for m in project_meetings}

    # Fetch DecisionHistory records
    histories = db.query(DecisionHistory).filter(
        DecisionHistory.decision_id == str(decision.id)
    ).order_by(DecisionHistory.timestamp.asc()).all()

    # Fetch related Evidence records
    evidences = db.query(Evidence).filter(
        Evidence.decision_id == str(decision.id)
    ).all()

    nodes: List[DecisionEvolutionNode] = []
    concerns: List[str] = []
    alternatives: List[str] = []
    source_meetings_dict: Dict[str, Dict[str, Any]] = {}
    found_reason: Optional[str] = decision.reason

    # Add initial proposal node if present
    initial_meeting = meeting_map.get(decision.meeting_id)
    initial_meeting_title = initial_meeting.title if initial_meeting else "Initial Meeting"
    if initial_meeting:
        source_meetings_dict[initial_meeting.public_id] = {
            "meeting_id": initial_meeting.public_id,
            "title": initial_meeting.title,
            "start_time": initial_meeting.start_time or initial_meeting.created_at,
        }

    proposal_content = decision.original_proposal or decision.title
    nodes.append(
        DecisionEvolutionNode(
            stage="PROPOSAL",
            meeting_id=decision.meeting_id,
            meeting_title=initial_meeting_title,
            timestamp=decision.created_at,
            speaker_label=decision.proposer_id or "Team",
            content=f"Proposal: {proposal_content}",
            reason=None,
        )
    )

    # Process history records
    for h in histories:
        meet = meeting_map.get(h.meeting_id)
        meet_title = meet.title if meet else "Meeting"
        if meet:
            source_meetings_dict[meet.public_id] = {
                "meeting_id": meet.public_id,
                "title": meet.title,
                "start_time": meet.start_time or meet.created_at,
            }

        stage = h.stage.upper() if h.stage else "STATUS_CHANGE"
        content = h.notes or h.evidence_text or f"Status changed to {h.new_status}"

        if "CONCERN" in stage or "concern" in content.lower():
            concerns.append(content)
        elif "ALTERNATIVE" in stage or "alternative" in content.lower():
            alternatives.append(content)

        if h.reason and not found_reason:
            found_reason = h.reason

        nodes.append(
            DecisionEvolutionNode(
                stage=stage,
                meeting_id=h.meeting_id,
                meeting_title=meet_title,
                timestamp=h.timestamp or h.created_at,
                speaker_label=h.speaker_label or h.changed_by or "Team Member",
                content=content,
                reason=h.reason,
            )
        )

    # Process evidence records
    for ev in evidences:
        meet = meeting_map.get(ev.meeting_id)
        meet_title = meet.title if meet else "Meeting"
        ev_type = ev.evidence_type.lower() if ev.evidence_type else ""

        if "concern" in ev_type or "concern" in ev.content.lower():
            if ev.content not in concerns:
                concerns.append(ev.content)
                nodes.append(
                    DecisionEvolutionNode(
                        stage="CONCERN",
                        meeting_id=ev.meeting_id,
                        meeting_title=meet_title,
                        timestamp=meet.start_time if meet else None,
                        speaker_label=ev.speaker_label or "Team Member",
                        content=f"Concern: {ev.content}",
                        reason=None,
                    )
                )
        elif "alternative" in ev_type or "alternative" in ev.content.lower():
            if ev.content not in alternatives:
                alternatives.append(ev.content)
                nodes.append(
                    DecisionEvolutionNode(
                        stage="ALTERNATIVE",
                        meeting_id=ev.meeting_id,
                        meeting_title=meet_title,
                        timestamp=meet.start_time if meet else None,
                        speaker_label=ev.speaker_label or "Team Member",
                        content=f"Alternative: {ev.content}",
                        reason=None,
                    )
                )

    # Add final decision node if agreed / selected
    final_node_exists = any(n.stage == "FINAL_DECISION" for n in nodes)
    if not final_node_exists and decision.status.lower() in ["agreed", "selected", "finalized", "approved"]:
        last_meet = meeting_map.get(decision.meeting_id)
        nodes.append(
            DecisionEvolutionNode(
                stage="FINAL_DECISION",
                meeting_id=decision.meeting_id,
                meeting_title=last_meet.title if last_meet else "Final Meeting",
                timestamp=decision.updated_at or decision.created_at,
                speaker_label="Team Lead",
                content=f"Final Decision: {decision.title}",
                reason=found_reason,
            )
        )

    # Strict compliance requirement: if no explicit reason was found, set to REASON_NOT_FOUND
    final_reason = found_reason.strip() if (found_reason and found_reason.strip()) else REASON_NOT_FOUND

    # Extract final decision text from FINAL_DECISION node if present
    final_decision_text = None
    latest_status = decision.status
    for n in reversed(nodes):
        if n.stage == "FINAL_DECISION":
            final_decision_text = n.content
            break
    if not final_decision_text:
        final_decision_text = f"{decision.title} ({decision.status.upper()})"

    return DecisionEvolutionHistoryResponse(
        decision_id=str(decision.id),
        project_id=project.public_id,
        title=decision.title,
        original_proposal=decision.original_proposal or proposal_content,
        concerns=concerns,
        alternatives=alternatives,
        final_decision=final_decision_text,
        status=latest_status,
        reason=final_reason,
        source_meetings=list(source_meetings_dict.values()),
        evolution_nodes=nodes,
    )



def get_topic_evolution_history(
    db: Session,
    project: Project,
    topic_identifier: str,
) -> TopicEvolutionHistoryResponse:
    """Fetch topic evolution history across meetings, speakers, and related items."""
    topic_id_str = str(topic_identifier).strip()
    topic_conds = [
        cast(Topic.id, String) == topic_id_str,
        Topic.name.ilike(topic_id_str),
        Topic.name.ilike(f"%{topic_id_str}%"),
    ]
    try:
        topic_uuid = uuid.UUID(topic_id_str)
        topic_conds.append(Topic.id == topic_uuid)
    except Exception:
        pass

    topic = db.query(Topic).filter(
        Topic.company_id == project.company_id,
        or_(*topic_conds)
    ).first()



    if not topic:
        # Create virtual topic history response if topic name was referenced
        topic_name = topic_identifier
        topic_id = f"topic_{topic_identifier.lower().replace(' ', '_')}"
    else:
        topic_name = topic.name
        topic_id = str(topic.id)

    # Fetch project meetings
    project_meetings = db.query(Meeting).filter(
        Meeting.project_id == project.public_id,
        Meeting.deleted_at.is_(None)
    ).order_by(Meeting.start_time.asc()).all()
    meeting_map = {m.public_id: m for m in project_meetings}
    meeting_ids = list(meeting_map.keys())

    # Find MeetingTopic entries
    meeting_topics = db.query(MeetingTopic).filter(
        MeetingTopic.meeting_id.in_(meeting_ids)
    ).all()

    # Find Evidence associated with topic
    evidences = db.query(Evidence).filter(
        Evidence.meeting_id.in_(meeting_ids),
        or_(
            Evidence.topic_id == topic_id,
            Evidence.content.ilike(f"%{topic_name}%")
        )
    ).order_by(Evidence.timestamp.asc()).all()

    meetings_involved_dict: Dict[str, Dict[str, Any]] = {}
    speakers_set: set = set()
    evolution_steps: List[TopicEvolutionNode] = []

    for ev in evidences:
        meet = meeting_map.get(ev.meeting_id)
        if meet:
            meetings_involved_dict[meet.public_id] = {
                "meeting_id": meet.public_id,
                "title": meet.title,
                "start_time": meet.start_time or meet.created_at,
            }

        if ev.speaker_label:
            speakers_set.add(ev.speaker_label)

        stage = "INTRODUCTION" if len(evolution_steps) == 0 else "DISCUSSION"
        evolution_steps.append(
            TopicEvolutionNode(
                meeting_id=ev.meeting_id,
                meeting_title=meet.title if meet else "Meeting",
                timestamp=meet.start_time if meet else None,
                speaker_label=ev.speaker_label or "Team Member",
                discussion_point=ev.content,
                stage=stage,
            )
        )

    # If no explicit evidence steps, populate from project meetings
    if not evolution_steps and project_meetings:
        for m in project_meetings:
            meetings_involved_dict[m.public_id] = {
                "meeting_id": m.public_id,
                "title": m.title,
                "start_time": m.start_time or m.created_at,
            }
            evolution_steps.append(
                TopicEvolutionNode(
                    meeting_id=m.public_id,
                    meeting_title=m.title,
                    timestamp=m.start_time or m.created_at,
                    speaker_label="Team",
                    discussion_point=f"Topic '{topic_name}' discussed during {m.title}",
                    stage="DISCUSSION",
                )
            )

    meetings_involved = list(meetings_involved_dict.values())
    first_discussed = meetings_involved[0] if meetings_involved else None

    # Find related decisions
    related_decisions_objs = db.query(Decision).filter(
        Decision.meeting_id.in_(meeting_ids),
        or_(
            Decision.title.ilike(f"%{topic_name}%"),
            Decision.description.ilike(f"%{topic_name}%")
        )
    ).all()
    related_decisions = [
        {"decision_id": str(d.id), "title": d.title, "status": d.status, "meeting_id": d.meeting_id}
        for d in related_decisions_objs
    ]

    # Find related tasks
    related_tasks_objs = db.query(Task).filter(
        Task.meeting_id.in_(meeting_ids),
        or_(
            Task.title.ilike(f"%{topic_name}%"),
            Task.description.ilike(f"%{topic_name}%")
        )
    ).all()
    related_tasks = [
        {"task_id": str(t.id), "title": t.title, "status": t.status, "meeting_id": t.meeting_id}
        for t in related_tasks_objs
    ]

    return TopicEvolutionHistoryResponse(
        topic_id=topic_id,
        topic_name=topic_name,
        project_id=project.public_id,
        first_discussed=first_discussed,
        meetings_involved=meetings_involved,
        speakers=list(speakers_set) if speakers_set else ["Team Members"],
        related_decisions=related_decisions,
        related_tasks=related_tasks,
        evolution_steps=evolution_steps,
    )


def get_cross_meeting_timeline(
    db: Session,
    project: Project,
) -> CrossMeetingTimelineResponse:
    """Build unified cross-meeting timeline with preserved chronological evidence."""
    meetings = db.query(Meeting).filter(
        Meeting.project_id == project.public_id,
        Meeting.deleted_at.is_(None)
    ).order_by(Meeting.start_time.asc()).all()

    meeting_map = {m.public_id: m for m in meetings}
    meeting_ids = list(meeting_map.keys())

    timeline: List[CrossMeetingTimelineNode] = []

    # 1. Meetings
    for m in meetings:
        timeline.append(
            CrossMeetingTimelineNode(
                event_type="MEETING",
                timestamp=m.start_time or m.created_at,
                title=f"Meeting: {m.title}",
                description=m.description or f"Status: {m.status}",
                meeting_id=m.public_id,
                meeting_title=m.title,
                entity_id=m.public_id,
            )
        )

    # 2. Decisions & Decision Histories
    if meeting_ids:
        decisions = db.query(Decision).filter(Decision.meeting_id.in_(meeting_ids)).all()
        for d in decisions:
            meet = meeting_map.get(d.meeting_id)
            timeline.append(
                CrossMeetingTimelineNode(
                    event_type="PROPOSAL",
                    timestamp=d.created_at,
                    title=f"Proposal: {d.title}",
                    description=d.description or f"Initial status: {d.status}",
                    meeting_id=d.meeting_id,
                    meeting_title=meet.title if meet else None,
                    speaker_label=d.proposer_id or "Proposer",
                    entity_id=str(d.id),
                )
            )

        histories = db.query(DecisionHistory).filter(DecisionHistory.meeting_id.in_(meeting_ids)).all()
        for h in histories:
            meet = meeting_map.get(h.meeting_id)
            ev_type = h.stage.upper() if h.stage else "DECISION_UPDATE"
            timeline.append(
                CrossMeetingTimelineNode(
                    event_type=ev_type,
                    timestamp=h.timestamp or h.created_at,
                    title=f"Decision Progression ({h.new_status}): {h.notes or ''}",
                    description=h.reason or h.evidence_text,
                    meeting_id=h.meeting_id,
                    meeting_title=meet.title if meet else None,
                    evidence_text=h.evidence_text,
                    speaker_label=h.speaker_label or h.changed_by,
                    entity_id=str(h.id),
                )
            )

        # 3. Tasks
        tasks = db.query(Task).filter(Task.meeting_id.in_(meeting_ids)).all()
        for t in tasks:
            meet = meeting_map.get(t.meeting_id)
            timeline.append(
                CrossMeetingTimelineNode(
                    event_type="TASK_CREATED",
                    timestamp=t.created_at,
                    title=f"Task: {t.title}",
                    description=t.description or f"Status: {t.status}",
                    meeting_id=t.meeting_id,
                    meeting_title=meet.title if meet else None,
                    entity_id=str(t.id),
                )
            )

        # 4. Documents
        docs = db.query(Document).filter(
            Document.deleted_at.is_(None),
            or_(
                Document.project_id == project.public_id,
                Document.meeting_id.in_(meeting_ids)
            )
        ).all()
        for doc in docs:
            meet = meeting_map.get(doc.meeting_id) if doc.meeting_id else None
            timeline.append(
                CrossMeetingTimelineNode(
                    event_type="DOCUMENT_ADDED",
                    timestamp=doc.created_at,
                    title=f"Document: {doc.title}",
                    description=f"File: {doc.file_name} ({doc.file_type.upper()})",
                    meeting_id=doc.meeting_id,
                    meeting_title=meet.title if meet else None,
                    entity_id=doc.public_id,
                )
            )

    # Sort timeline by timestamp ascending
    timeline.sort(key=lambda x: x.timestamp or datetime.min)

    return CrossMeetingTimelineResponse(
        project_id=project.public_id,
        total_events=len(timeline),
        timeline=timeline,
    )
