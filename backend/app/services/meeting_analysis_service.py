import logging
import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment
from app.models.topic import Topic
from app.models.decision import Decision
from app.models.task import Task
from app.models.evidence import Evidence
from app.models.meeting_summary import MeetingSummary
from app.models.intelligence import Question, Risk, UnresolvedIssue, Commitment, Reminder
from app.services.llm_provider import LLMProvider, MockLLMProvider, get_llm_provider
from app.core.config import settings

logger = logging.getLogger(__name__)


class MeetingAnalysisService:
    """Service for AI-powered meeting analysis with evidence tracking."""
    
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        """
        Initialize meeting analysis service.
        
        Args:
            llm_provider: LLM provider to use (defaults to provider configured in settings)
        """
        self.llm_provider = llm_provider or get_llm_provider()
        self.max_retries = 3
        self.retry_delay = 2  # seconds
    
    def analyze_meeting(
        self,
        db: Session,
        meeting: Meeting,
        force_reanalysis: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze meeting transcript and extract structured information.
        
        Args:
            db: Database session
            meeting: Meeting instance
            force_reanalysis: Force re-analysis even if already analyzed
        
        Returns:
            Dictionary containing analysis results
        """
        # Check if already analyzed
        existing_summary = db.query(MeetingSummary).filter(
            MeetingSummary.meeting_id == meeting.public_id
        ).first()
        
        if existing_summary and not force_reanalysis:
            logger.info(f"Meeting {meeting.public_id} already analyzed, skipping")
            return self._get_existing_analysis(db, meeting)
        
        # Get transcript segments
        segments = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        ).order_by(TranscriptSegment.start_time).all()
        
        # Get fresh meeting instance from database
        meeting = db.query(Meeting).filter(Meeting.public_id == meeting.public_id).first()
        if not meeting:
            logger.error(f"Meeting not found: {meeting.public_id}")
            return {"error": "Meeting not found"}
        
        if not segments:
            logger.warning(f"No transcript segments found for meeting {meeting.public_id}")
            return {"error": "No transcript available for analysis"}
        
        # Prepare transcript for analysis
        transcript_text = self._prepare_transcript(segments)
        
        # Update meeting analysis status
        meeting.analysis_status = "processing"
        meeting.analysis_error = None
        db.commit()
        
        try:
            # Perform AI analysis
            analysis_result = self._perform_ai_analysis(transcript_text, meeting)
            
            # Validate analysis result
            validated_result = self._validate_analysis_result(analysis_result)
            
            # Store analysis results with evidence
            self._store_analysis_results(db, meeting, validated_result, segments)
            
            # Update meeting status
            meeting.analysis_status = "completed"
            meeting.analysis_error = None
            db.commit()
            
            logger.info(f"Successfully analyzed meeting {meeting.public_id}")
            return validated_result
            
        except Exception as e:
            # Update meeting status with error
            meeting.analysis_status = "failed"
            meeting.analysis_error = str(e)
            db.commit()
            logger.error(f"Analysis failed for meeting {meeting.public_id}: {e}")
            raise
    
    def _prepare_transcript(self, segments: List[TranscriptSegment]) -> str:
        """Prepare transcript text for AI analysis."""
        transcript_lines = []
        for segment in segments:
            timestamp_str = f"[{segment.start_time:.1f}s - {segment.end_time:.1f}s]"
            speaker_str = f"{segment.speaker_label}:"
            transcript_lines.append(f"{timestamp_str} {speaker_str} {segment.text}")
        
        return "\n".join(transcript_lines)
    
    def _perform_ai_analysis(self, transcript: str, meeting: Meeting) -> Dict[str, Any]:
        """Perform AI analysis using the configured LLM provider."""
        
        system_prompt = """You are an expert meeting analyst. Analyze the provided meeting transcript and extract structured information.
You must respond with valid JSON containing the following fields:
- summary: A comprehensive summary of the meeting (2-3 paragraphs)
- key_takeaways: Array of 3-5 key takeaways
- topics: Array of main topics discussed with importance level (high/medium/low)
- questions: Array of questions asked during the meeting
- answers: Array of answers provided to questions
- suggestions: Array of suggestions made
- proposals: Array of proposals put forward
- concerns: Array of concerns raised
- agreements: Array of agreements reached
- disagreements: Array of disagreements or conflicts
- decisions: Array of decisions made with status (proposed/agreed/rejected)
- action_items: Array of action items/tasks with assignee, description, priority, and deadline

Each item should include evidence information: timestamp_range and speaker who mentioned it."""

        user_prompt = f"""Analyze the following meeting transcript:

Meeting Title: {meeting.title}
Meeting ID: {meeting.public_id}

Transcript:
{transcript}

Please provide a comprehensive analysis following the JSON structure specified above."""

        try:
            return self.llm_provider.generate_structured_completion(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3  # Lower temperature for more consistent structured output
            )
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            raise
    
    def _validate_analysis_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate the analysis result structure."""
        required_fields = [
            "summary", "key_takeaways", "topics", "questions", "answers",
            "suggestions", "proposals", "concerns", "agreements", "disagreements",
            "decisions", "action_items"
        ]
        
        validated = {}
        for field in required_fields:
            if field in result:
                validated[field] = result[field]
            else:
                # Handle alternative field names
                if field == "action_items" and "tasks" in result:
                    validated[field] = result["tasks"]
                elif field == "tasks" and "action_items" in result:
                    validated[field] = result["action_items"]
                else:
                    logger.warning(f"Missing required field: {field}, using empty value")
                    validated[field] = [] if field != "summary" else ""
        
        # Ensure both action_items and tasks are present for compatibility
        if "action_items" in validated and "tasks" not in validated:
            validated["tasks"] = validated["action_items"]
        elif "tasks" in validated and "action_items" not in validated:
            validated["action_items"] = validated["tasks"]
        
        return validated
    
    def _store_analysis_results(
        self,
        db: Session,
        meeting: Meeting,
        analysis: Dict[str, Any],
        segments: List[TranscriptSegment]
    ):
        """Store analysis results in database with evidence tracking."""
        
        # Create or update meeting summary
        summary = db.query(MeetingSummary).filter(
            MeetingSummary.meeting_id == meeting.public_id
        ).first()
        
        if not summary:
            summary = MeetingSummary(
                meeting_id=meeting.public_id,
                company_id=meeting.company_id
            )
            db.add(summary)
        
        summary.summary_text = analysis["summary"]
        summary.key_takeaways = json.dumps(analysis["key_takeaways"])
        summary.questions = json.dumps(analysis["questions"])
        summary.answers = json.dumps(analysis["answers"])
        summary.suggestions = json.dumps(analysis["suggestions"])
        summary.proposals = json.dumps(analysis["proposals"])
        summary.concerns = json.dumps(analysis["concerns"])
        summary.agreements = json.dumps(analysis["agreements"])
        summary.disagreements = json.dumps(analysis["disagreements"])
        summary.extracted_by = self.llm_provider.model if hasattr(self.llm_provider, 'model') else 'unknown'
        
        # Store topics
        self._store_topics(db, meeting, analysis["topics"], segments)
        
        # Store decisions
        self._store_decisions(db, meeting, analysis["decisions"], segments)
        
        # Store tasks
        self._store_tasks(db, meeting, analysis["action_items"], segments)
        
        # Store questions
        self._store_questions(db, meeting, analysis.get("questions", []), segments)

        # Store risks
        self._store_risks(db, meeting, analysis.get("concerns", []) or analysis.get("risks", []), segments)

        # Store commitments
        self._store_commitments(db, meeting, analysis.get("commitments", []) or analysis["action_items"], segments)

        # Store evidence for summary
        self._store_summary_evidence(db, meeting, analysis, segments)
        
        db.commit()
    
    def _store_topics(
        self,
        db: Session,
        meeting: Meeting,
        topics: List[Dict[str, Any]],
        segments: List[TranscriptSegment]
    ):
        """Store topics with evidence."""
        # Clear existing topics for this meeting
        db.query(Topic).filter(Topic.meeting_id == meeting.public_id).delete()
        
        for topic_data in topics:
            if isinstance(topic_data, str):
                topic_data = {"name": topic_data, "importance": "medium"}
            
            topic = Topic(
                company_id=meeting.company_id,
                meeting_id=meeting.public_id,
                name=topic_data.get("name", "Unknown Topic"),
                description=topic_data.get("description"),
                importance=topic_data.get("importance", "medium"),
                extracted_by=self.llm_provider.model if hasattr(self.llm_provider, 'model') else 'unknown'
            )
            db.add(topic)
            db.flush()
            
            # Create evidence for this topic
            if "evidence" in topic_data:
                self._create_evidence_from_data(
                    db, meeting, topic_data["evidence"], segments, 
                    "topic", topic_id=str(getattr(topic, 'public_id', None) or topic.id)
                )
    
    def _store_decisions(
        self,
        db: Session,
        meeting: Meeting,
        decisions: List[Dict[str, Any]],
        segments: List[TranscriptSegment]
    ):
        """Store decisions with evidence."""
        # Clear existing decisions for this meeting
        db.query(Decision).filter(Decision.meeting_id == meeting.public_id).delete()
        
        for decision_data in decisions:
            if isinstance(decision_data, str):
                decision_data = {"title": decision_data, "status": "proposed"}
            
            decision = Decision(
                company_id=meeting.company_id,
                meeting_id=meeting.public_id,
                title=decision_data.get("title", "Unknown Decision"),
                description=decision_data.get("description"),
                status=decision_data.get("status", "proposed"),
                decision_type=decision_data.get("type"),
                confidence_level=decision_data.get("confidence", "medium"),
                extracted_by=self.llm_provider.model if hasattr(self.llm_provider, 'model') else 'unknown'
            )
            db.add(decision)
            db.flush()
            
            # Create evidence for this decision
            if "evidence" in decision_data:
                self._create_evidence_from_data(
                    db, meeting, decision_data["evidence"], segments,
                    "decision", decision_id=str(getattr(decision, 'public_id', None) or decision.id)
                )
    
    def _store_tasks(
        self,
        db: Session,
        meeting: Meeting,
        tasks: List[Dict[str, Any]],
        segments: List[TranscriptSegment]
    ):
        """Store tasks with evidence."""
        # Clear existing tasks for this meeting
        db.query(Task).filter(Task.meeting_id == meeting.public_id).delete()
        
        for task_data in tasks:
            if isinstance(task_data, str):
                task_data = {"title": task_data, "description": ""}
            
            task = Task(
                company_id=meeting.company_id,
                meeting_id=meeting.public_id,
                title=task_data.get("title", "Unknown Task"),
                description=task_data.get("description"),
                status="open",
                priority=task_data.get("priority", "medium"),
                deadline=self._parse_deadline(task_data.get("deadline")),
                extracted_by=self.llm_provider.model if hasattr(self.llm_provider, 'model') else 'unknown'
            )
            db.add(task)
            db.flush()
            
            # Create evidence for this task
            if "evidence" in task_data:
                self._create_evidence_from_data(
                    db, meeting, task_data["evidence"], segments,
                    "task", task_id=str(getattr(task, 'public_id', None) or task.id)
                )
    
    def _store_questions(
        self,
        db: Session,
        meeting: Meeting,
        questions: List[Any],
        segments: List[TranscriptSegment]
    ):
        db.query(Question).filter(Question.meeting_id == meeting.public_id).delete()
        for q_data in questions:
            q_text = q_data.get("question") if isinstance(q_data, dict) else str(q_data)
            if not q_text:
                continue
            question = Question(
                meeting_id=meeting.public_id,
                project_id=meeting.project_id,
                question=q_text,
                status="OPEN"
            )
            db.add(question)

    def _store_risks(
        self,
        db: Session,
        meeting: Meeting,
        risks: List[Any],
        segments: List[TranscriptSegment]
    ):
        db.query(Risk).filter(Risk.meeting_id == meeting.public_id).delete()
        for r_data in risks:
            r_title = r_data.get("title") or r_data.get("concern") if isinstance(r_data, dict) else str(r_data)
            if not r_title:
                continue
            risk = Risk(
                meeting_id=meeting.public_id,
                project_id=meeting.project_id,
                title=r_title,
                severity=r_data.get("severity", "medium") if isinstance(r_data, dict) else "medium",
                status="OPEN"
            )
            db.add(risk)

    def _store_commitments(
        self,
        db: Session,
        meeting: Meeting,
        commitments: List[Any],
        segments: List[TranscriptSegment]
    ):
        db.query(Commitment).filter(Commitment.meeting_id == meeting.public_id).delete()
        for c_data in commitments:
            if isinstance(c_data, dict):
                c_text = c_data.get("commitment") or c_data.get("action_item") or c_data.get("title")
                person = c_data.get("assignee") or c_data.get("speaker") or "Unassigned"
            else:
                c_text = str(c_data)
                person = "Unassigned"
            if not c_text:
                continue
            commitment = Commitment(
                meeting_id=meeting.public_id,
                project_id=meeting.project_id,
                person=person,
                commitment=c_text,
                status="OPEN"
            )
            db.add(commitment)
    
    def _store_summary_evidence(
        self,
        db: Session,
        meeting: Meeting,
        analysis: Dict[str, Any],
        segments: List[TranscriptSegment]
    ):
        """Store evidence for summary and other high-level analysis."""
        # Create evidence for summary
        if "summary_evidence" in analysis:
            self._create_evidence_from_data(
                db, meeting, analysis["summary_evidence"], segments,
                "summary"
            )
    
    def _create_evidence_from_data(
        self,
        db: Session,
        meeting: Meeting,
        evidence_data: List[Dict[str, Any]],
        segments: List[TranscriptSegment],
        evidence_type: str,
        topic_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        task_id: Optional[str] = None
    ):
        """Create evidence records from analysis data."""
        for ev_data in evidence_data:
            # Find matching transcript segment
            segment = self._find_matching_segment(segments, ev_data)
            
            evidence = Evidence(
                meeting_id=meeting.public_id,
                transcript_segment_id=str(getattr(segment, 'public_id', None) or segment.id) if segment else None,
                timestamp=ev_data.get("timestamp"),
                speaker_label=ev_data.get("speaker"),
                user_id=ev_data.get("user_id"),
                content=ev_data.get("content", ""),
                context=ev_data.get("context"),
                evidence_type=evidence_type,
                confidence=ev_data.get("confidence"),
                topic_id=topic_id,
                decision_id=decision_id,
                task_id=task_id,
                extracted_by=self.llm_provider.model if hasattr(self.llm_provider, 'model') else 'unknown'
            )
            db.add(evidence)
    
    def _find_matching_segment(
        self,
        segments: List[TranscriptSegment],
        evidence_data: Dict[str, Any]
    ) -> Optional[TranscriptSegment]:
        """Find transcript segment matching evidence data."""
        timestamp = evidence_data.get("timestamp")
        if timestamp is None:
            return None
        
        # Find segment containing this timestamp
        for segment in segments:
            if segment.start_time <= timestamp <= segment.end_time:
                return segment
        
        return None
    
    def _parse_deadline(self, deadline_str: Optional[str]) -> Optional[datetime]:
        """Parse deadline string to datetime."""
        if not deadline_str:
            return None
        try:
            # Simple parsing - can be enhanced with dateutil
            return datetime.fromisoformat(deadline_str)
        except:
            logger.warning(f"Failed to parse deadline: {deadline_str}")
            return None
    
    def _get_existing_analysis(self, db: Session, meeting: Meeting) -> Dict[str, Any]:
        """Get existing analysis results from database."""
        summary = db.query(MeetingSummary).filter(
            MeetingSummary.meeting_id == meeting.public_id
        ).first()
        
        if not summary:
            return {"error": "No analysis found"}
        
        return {
            "summary": summary.summary_text,
            "key_takeaways": json.loads(summary.key_takeaways) if summary.key_takeaways else [],
            "questions": json.loads(summary.questions) if summary.questions else [],
            "answers": json.loads(summary.answers) if summary.answers else [],
            "suggestions": json.loads(summary.suggestions) if summary.suggestions else [],
            "proposals": json.loads(summary.proposals) if summary.proposals else [],
            "concerns": json.loads(summary.concerns) if summary.concerns else [],
            "agreements": json.loads(summary.agreements) if summary.agreements else [],
            "disagreements": json.loads(summary.disagreements) if summary.disagreements else [],
            "topics": self._get_topics(db, meeting),
            "decisions": self._get_decisions(db, meeting),
            "tasks": self._get_tasks(db, meeting)
        }
    
    def _get_topics(self, db: Session, meeting: Meeting) -> List[Dict[str, Any]]:
        """Get topics for meeting."""
        topics = db.query(Topic).filter(Topic.meeting_id == meeting.public_id).all()
        return [
            {
                "id": str(topic.id),
                "name": topic.name,
                "description": topic.description,
                "importance": topic.importance
            }
            for topic in topics
        ]
    
    def _get_decisions(self, db: Session, meeting: Meeting) -> List[Dict[str, Any]]:
        """Get decisions for meeting."""
        decisions = db.query(Decision).filter(Decision.meeting_id == meeting.public_id).all()
        return [
            {
                "id": str(decision.id),
                "title": decision.title,
                "description": decision.description,
                "status": decision.status,
                "type": decision.decision_type,
                "confidence": decision.confidence_level
            }
            for decision in decisions
        ]
    
    def _get_tasks(self, db: Session, meeting: Meeting) -> List[Dict[str, Any]]:
        """Get tasks for meeting."""
        tasks = db.query(Task).filter(Task.meeting_id == meeting.public_id).all()
        return [
            {
                "id": str(task.id),
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "deadline": task.deadline.isoformat() if task.deadline else None
            }
            for task in tasks
        ]