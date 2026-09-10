from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.meeting import Meeting
from app.services.meeting_analysis_service import MeetingAnalysisService
from app.services.meeting_service import get_meeting_by_public_id

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/meetings/{meeting_id}/analyze")
def analyze_meeting(
    meeting_id: str,
    force_reanalysis: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Analyze meeting transcript using AI.
    
    Triggers AI analysis of the meeting transcript to extract:
    - Summary, topics, decisions, tasks
    - Questions, answers, suggestions, proposals
    - Concerns, agreements, disagreements
    - All with evidence tracking
    """
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    try:
        analysis_service = MeetingAnalysisService()
        result = analysis_service.analyze_meeting(db, meeting, force_reanalysis)
        
        return {
            "meeting_id": meeting_id,
            "status": "completed",
            "analysis": result
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )


@router.get("/meetings/{meeting_id}/summary")
def get_meeting_summary(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get meeting summary and key takeaways."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    analysis_service = MeetingAnalysisService()
    try:
        analysis = analysis_service._get_existing_analysis(db, meeting)
        
        return {
            "meeting_id": meeting_id,
            "summary": analysis.get("summary", ""),
            "key_takeaways": analysis.get("key_takeaways", [])
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/meetings/{meeting_id}/topics")
def get_meeting_topics(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get topics discussed in the meeting."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    from app.models.topic import Topic
    
    topics = db.query(Topic).filter(Topic.meeting_id == meeting_id).all()
    
    return {
        "meeting_id": meeting_id,
        "topics": [
            {
                "id": topic.public_id,
                "name": topic.name,
                "description": topic.description,
                "importance": topic.importance
            }
            for topic in topics
        ]
    }


@router.get("/meetings/{meeting_id}/decisions")
def get_meeting_decisions(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get decisions made in the meeting."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    from app.models.decision import Decision
    
    decisions = db.query(Decision).filter(Decision.meeting_id == meeting_id).all()
    
    return {
        "meeting_id": meeting_id,
        "decisions": [
            {
                "id": decision.public_id,
                "title": decision.title,
                "description": decision.description,
                "status": decision.status,
                "type": decision.decision_type,
                "confidence": decision.confidence_level
            }
            for decision in decisions
        ]
    }


@router.get("/meetings/{meeting_id}/tasks")
def get_meeting_tasks(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get action items/tasks from the meeting."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    from app.models.task import Task
    
    tasks = db.query(Task).filter(Task.meeting_id == meeting_id).all()
    
    return {
        "meeting_id": meeting_id,
        "tasks": [
            {
                "id": task.public_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "deadline": task.deadline.isoformat() if task.deadline else None
            }
            for task in tasks
        ]
    }


@router.get("/meetings/{meeting_id}/evidence")
def get_meeting_evidence(
    meeting_id: str,
    evidence_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get evidence for meeting analysis."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    from app.models.evidence import Evidence
    
    query = db.query(Evidence).filter(Evidence.meeting_id == meeting_id)
    
    if evidence_type:
        query = query.filter(Evidence.evidence_type == evidence_type)
    
    evidence = query.order_by(Evidence.timestamp).all()
    
    return {
        "meeting_id": meeting_id,
        "evidence": [
            {
                "id": ev.public_id,
                "evidence_type": ev.evidence_type,
                "content": ev.content,
                "context": ev.context,
                "timestamp": ev.timestamp,
                "speaker_label": ev.speaker_label,
                "user_id": ev.user_id,
                "confidence": ev.confidence,
                "topic_id": ev.topic_id,
                "decision_id": ev.decision_id,
                "task_id": ev.task_id
            }
            for ev in evidence
        ]
    }


@router.get("/meetings/{meeting_id}/full-analysis")
def get_full_analysis(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get complete meeting analysis including all extracted information."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    analysis_service = MeetingAnalysisService()
    try:
        analysis = analysis_service._get_existing_analysis(db, meeting)
        
        return {
            "meeting_id": meeting_id,
            "analysis": analysis
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )