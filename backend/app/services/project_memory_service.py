import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.project import Project
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_summary import MeetingSummary
from app.models.decision import Decision
from app.models.task import Task
from app.models.topic import Topic, MeetingTopic
from app.models.document import Document
from app.models.user import User

from app.schemas.project_memory import (
    ProjectMemoryDashboardResponse,
    ProjectMemorySummary,
    RecentDiscussion,
    ImportantDecision,
    OpenTask,
    RecurringTopic,
    ProjectDocument,
    ProjectParticipant,
    TimelineItem,
)


def parse_json_list(raw_val: Optional[str]) -> List[str]:
    """Helper to parse JSON string or return list."""
    if not raw_val:
        return []
    try:
        parsed = json.loads(raw_val)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return [str(parsed)]
    except Exception:
        return [raw_val]


def get_project_discussions(db: Session, meeting_map: Dict[str, Meeting]) -> List[RecentDiscussion]:
    """Retrieve recent discussions/summaries from meetings in the project."""
    if not meeting_map:
        return []

    meeting_ids = list(meeting_map.keys())
    summaries = db.query(MeetingSummary).filter(
        MeetingSummary.meeting_id.in_(meeting_ids)
    ).all()

    discussions = []
    for s in summaries:
        meet = meeting_map.get(s.meeting_id)
        if not meet:
            continue
        takeaways = parse_json_list(s.key_takeaways)
        discussions.append(
            RecentDiscussion(
                meeting_id=meet.public_id,
                meeting_title=meet.title,
                start_time=meet.start_time or meet.created_at,
                summary_text=s.summary_text,
                key_takeaways=takeaways,
            )
        )

    # Sort discussions by meeting time descending
    discussions.sort(key=lambda d: d.start_time or datetime.min, reverse=True)
    return discussions


def get_project_decisions(db: Session, meeting_map: Dict[str, Meeting]) -> List[ImportantDecision]:
    """Retrieve decisions made across project meetings."""
    if not meeting_map:
        return []

    meeting_ids = list(meeting_map.keys())
    decisions = db.query(Decision).filter(
        Decision.meeting_id.in_(meeting_ids)
    ).all()

    results = []
    for d in decisions:
        meet = meeting_map.get(d.meeting_id)
        meeting_title = meet.title if meet else "Project Meeting"
        results.append(
            ImportantDecision(
                decision_id=str(d.id),
                meeting_id=d.meeting_id,
                meeting_title=meeting_title,
                title=d.title,
                description=d.description,
                status=d.status,
                decision_type=d.decision_type,
                confidence_level=d.confidence_level,
                created_at=d.created_at,
            )
        )
    return results


def get_project_tasks(db: Session, meeting_map: Dict[str, Meeting]) -> Tuple[List[OpenTask], List[OpenTask]]:
    """Retrieve open tasks and upcoming deadlines across project meetings."""
    if not meeting_map:
        return [], []

    meeting_ids = list(meeting_map.keys())
    tasks = db.query(Task).filter(
        Task.meeting_id.in_(meeting_ids)
    ).all()

    open_tasks = []
    upcoming_deadlines = []

    for t in tasks:
        meet = meeting_map.get(t.meeting_id)
        meeting_title = meet.title if meet else "Project Meeting"
        due_dt = t.due_date or t.deadline

        item = OpenTask(
            task_id=str(t.id),
            meeting_id=t.meeting_id,
            meeting_title=meeting_title,
            title=t.title,
            description=t.description,
            status=t.status,
            priority=t.priority,
            due_date=due_dt,
            assignee_id=t.assignee_id,
        )

        if t.status.lower() in ["open", "in_progress", "proposed", "pending"]:
            open_tasks.append(item)
            if due_dt:
                upcoming_deadlines.append(item)

    # Sort upcoming deadlines by due date ascending
    upcoming_deadlines.sort(key=lambda t: t.due_date or datetime.max)
    return open_tasks, upcoming_deadlines


def get_project_recurring_topics(db: Session, company_id: str, meeting_map: Dict[str, Meeting]) -> List[RecurringTopic]:
    """Retrieve topics and identify recurring topics across meetings."""
    if not meeting_map:
        return []

    meeting_ids = list(meeting_map.keys())

    # Query direct topics linked to meetings
    topics = db.query(Topic).filter(
        Topic.company_id == company_id,
        or_(Topic.meeting_id.in_(meeting_ids), Topic.meeting_id.is_(None))
    ).all()

    # Query MeetingTopic associations
    mt_links = db.query(MeetingTopic).filter(
        MeetingTopic.meeting_id.in_(meeting_ids)
    ).all()

    topic_meeting_map: Dict[str, set] = {}
    topic_info: Dict[str, Topic] = {}

    for t in topics:
        key = t.name.strip()
        topic_info[key] = t
        if key not in topic_meeting_map:
            topic_meeting_map[key] = set()
        if t.meeting_id in meeting_map:
            topic_meeting_map[key].add(t.meeting_id)

    # Link from MeetingTopic table
    for link in mt_links:
        t = db.query(Topic).filter(Topic.id == link.topic_id).first()
        if t:
            key = t.name.strip()
            if key not in topic_meeting_map:
                topic_meeting_map[key] = set()
            topic_meeting_map[key].add(link.meeting_id)

    recurring = []
    for name, m_ids in topic_meeting_map.items():
        m_titles = [meeting_map[mid].title for mid in m_ids if mid in meeting_map]
        t_obj = topic_info.get(name)
        importance = t_obj.importance if t_obj else "medium"
        recurring.append(
            RecurringTopic(
                topic_name=name,
                occurrence_count=len(m_ids) or 1,
                meeting_ids=list(m_ids),
                meeting_titles=m_titles,
                importance=importance,
            )
        )

    # Sort recurring topics by occurrence count descending
    recurring.sort(key=lambda rt: (rt.occurrence_count, rt.topic_name), reverse=True)
    return recurring


def get_project_documents(db: Session, project_id: str, meeting_map: Dict[str, Meeting]) -> List[ProjectDocument]:
    """Retrieve documents associated with project or project's meetings."""
    meeting_ids = list(meeting_map.keys()) if meeting_map else []
    
    docs = db.query(Document).filter(
        Document.deleted_at.is_(None),
        or_(
            Document.project_id == project_id,
            Document.meeting_id.in_(meeting_ids) if meeting_ids else False
        )
    ).all()

    results = []
    for d in docs:
        meet = meeting_map.get(d.meeting_id) if d.meeting_id else None
        results.append(
            ProjectDocument(
                public_id=d.public_id,
                title=d.title,
                file_name=d.file_name,
                file_type=d.file_type,
                file_url=d.file_url,
                page_count=d.page_count,
                meeting_id=d.meeting_id,
                meeting_title=meet.title if meet else None,
                created_at=d.created_at,
            )
        )
    return results


def get_project_participants(db: Session, meeting_map: Dict[str, Meeting]) -> List[ProjectParticipant]:
    """Aggregate unique participants across meetings in project."""
    if not meeting_map:
        return []

    meeting_ids = list(meeting_map.keys())
    participants = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id.in_(meeting_ids)
    ).all()

    user_map: Dict[str, Dict[str, Any]] = {}
    for p in participants:
        uid = p.user_id
        if uid not in user_map:
            user_map[uid] = {
                "user_id": uid,
                "meetings_attended": set(),
                "roles": set(),
            }
        user_map[uid]["meetings_attended"].add(p.meeting_id)
        if p.role:
            user_map[uid]["roles"].add(p.role)

    results = []
    for uid, data in user_map.items():
        u = db.query(User).filter(User.public_id == uid).first()
        results.append(
            ProjectParticipant(
                user_id=uid,
                email=u.email if u else None,
                full_name=u.full_name if u else None,
                meetings_attended_count=len(data["meetings_attended"]),
                roles=list(data["roles"]),
            )
        )
    return results


def build_project_timeline(
    meetings: List[Meeting],
    decisions: List[ImportantDecision],
    tasks: List[OpenTask],
    documents: List[ProjectDocument],
) -> List[TimelineItem]:
    """Build chronological timeline of project knowledge events."""
    timeline = []

    for m in meetings:
        timeline.append(
            TimelineItem(
                event_type="MEETING",
                timestamp=m.start_time or m.created_at,
                title=f"Meeting: {m.title}",
                description=m.description or f"Status: {m.status}",
                entity_id=m.public_id,
                meeting_id=m.public_id,
                meeting_title=m.title,
            )
        )

    for d in decisions:
        timeline.append(
            TimelineItem(
                event_type="DECISION",
                timestamp=d.created_at,
                title=f"Decision: {d.title}",
                description=d.description or f"Status: {d.status}",
                entity_id=d.decision_id,
                meeting_id=d.meeting_id,
                meeting_title=d.meeting_title,
            )
        )

    for t in tasks:
        if t.due_date:
            timeline.append(
                TimelineItem(
                    event_type="TASK_DUE",
                    timestamp=t.due_date,
                    title=f"Task Due: {t.title}",
                    description=t.description or f"Status: {t.status}",
                    entity_id=t.task_id,
                    meeting_id=t.meeting_id,
                    meeting_title=t.meeting_title,
                )
            )

    for doc in documents:
        timeline.append(
            TimelineItem(
                event_type="DOCUMENT_ADDED",
                timestamp=doc.created_at,
                title=f"Document: {doc.title}",
                description=f"File: {doc.file_name} ({doc.file_type.upper()})",
                entity_id=doc.public_id,
                meeting_id=doc.meeting_id,
                meeting_title=doc.meeting_title,
            )
        )

    # Sort timeline descending by timestamp
    timeline.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
    return timeline


def get_project_memory_dashboard(db: Session, project: Project) -> ProjectMemoryDashboardResponse:
    """Aggregate knowledge from all project meetings into Project Memory Dashboard."""
    # 1. Fetch meetings for project
    meetings = db.query(Meeting).filter(
        Meeting.project_id == project.public_id,
        Meeting.deleted_at.is_(None)
    ).order_by(Meeting.start_time.desc()).all()

    meeting_map = {m.public_id: m for m in meetings}

    # 2. Extract components
    discussions = get_project_discussions(db, meeting_map)
    decisions = get_project_decisions(db, meeting_map)
    open_tasks, upcoming_deadlines = get_project_tasks(db, meeting_map)
    topics = get_project_recurring_topics(db, project.company_id, meeting_map)
    documents = get_project_documents(db, project.public_id, meeting_map)
    participants = get_project_participants(db, meeting_map)

    # 3. Build Timeline
    timeline = build_project_timeline(meetings, decisions, open_tasks, documents)

    # 4. Summary metrics
    recurring_count = sum(1 for t in topics if t.occurrence_count > 1)
    summary = ProjectMemorySummary(
        total_meetings=len(meetings),
        total_summaries=len(discussions),
        total_decisions=len(decisions),
        open_tasks_count=len(open_tasks),
        upcoming_deadlines_count=len(upcoming_deadlines),
        total_topics=len(topics),
        recurring_topics_count=recurring_count,
        total_documents=len(documents),
        total_participants=len(participants),
    )

    notice = (
        f"Project Memory is knowledge aggregated from {len(meetings)} meeting(s) "
        f"in project '{project.name}'."
    )

    return ProjectMemoryDashboardResponse(
        project_id=project.public_id,
        project_name=project.name,
        company_id=project.company_id,
        summary=summary,
        recent_discussions=discussions,
        important_decisions=decisions,
        open_tasks=open_tasks,
        upcoming_deadlines=upcoming_deadlines,
        recurring_topics=topics,
        meeting_timeline=timeline,
        related_documents=documents,
        participants=participants,
        source_meetings_count=len(meetings),
        memory_source_notice=notice,
    )
