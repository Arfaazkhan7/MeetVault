import json
import math
import re
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.embedding import Embedding
from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment
from app.models.meeting_summary import MeetingSummary
from app.models.topic import Topic
from app.models.decision import Decision
from app.models.document import Document, DocumentPage

import hashlib

EMBEDDING_DIM = 1536


def generate_text_embedding(text: str) -> List[float]:
    """Generate normalized 1536-dimensional semantic vector embedding for text using OpenAI."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM

    from app.core.config import settings
    
    if not settings.OPENAI_API_KEY:
        # Fallback for local tests without an API key
        import hashlib
        import math
        def _det_hash(token: str, max_dim: int = EMBEDDING_DIM) -> int:
            return int(hashlib.md5(token.encode('utf-8')).hexdigest()[:8], 16) % max_dim
        
        words = text.lower().split()
        vector = [0.0] * EMBEDDING_DIM
        for word in words:
            vector[_det_hash(f"w_{word}")] += 1.0
        magnitude = math.sqrt(sum(val * val for val in vector))
        if magnitude > 0:
            vector = [val / magnitude for val in vector]
        return vector

    import openai
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        dimensions=EMBEDDING_DIM
    )
    return response.data[0].embedding


def calculate_cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two 1536-dim unit vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    return max(0.0, min(1.0, dot_product))


class EmbeddingService:
    """Service for generating and storing vector embeddings for 5 entity types."""

    @staticmethod
    def create_or_update_embedding(
        db: Session,
        *,
        company_id: Optional[str] = None,
        source_type: str,
        source_id: str,
        content_text: str,
        project_id: Optional[str] = None,
        meeting_id: Optional[str] = None,
        speaker_label: Optional[str] = None,
        participant_id: Optional[str] = None,
    ) -> Embedding:
        """Generate embedding vector and persist in Embedding table."""
        cid = company_id or "personal"
        vec = generate_text_embedding(content_text)
        vec_json = json.dumps(vec)

        existing = db.query(Embedding).filter(
            Embedding.company_id == cid,
            Embedding.source_type == source_type,
            Embedding.source_id == source_id,
        ).first()

        if existing:
            existing.content_text = content_text
            existing.project_id = project_id
            existing.meeting_id = meeting_id
            existing.speaker_label = speaker_label
            existing.participant_id = participant_id
            existing.vector_data = vec_json
            rec = existing
        else:
            pub_id = f"emb_{uuid.uuid4().hex[:12]}"
            rec = Embedding(
                public_id=pub_id,
                company_id=cid,
                project_id=project_id,
                meeting_id=meeting_id,
                source_type=source_type,
                source_id=source_id,
                content_text=content_text,
                speaker_label=speaker_label,
                participant_id=participant_id,
                vector_data=vec_json,
            )
            db.add(rec)

        db.commit()
        db.refresh(rec)
        return rec

    @classmethod
    def index_transcript_segments(cls, db: Session, company_id: str) -> int:
        """Index all transcript segments for company."""
        meetings = db.query(Meeting).filter(Meeting.company_id == company_id, Meeting.deleted_at.is_(None)).all()
        meeting_map = {}
        meeting_ids = set()
        for m in meetings:
            if m.public_id:
                meeting_map[str(m.public_id)] = m
                meeting_ids.add(str(m.public_id))
            if m.id is not None:
                meeting_map[str(m.id)] = m
                meeting_ids.add(str(m.id))

        if not meeting_ids:
            return 0

        all_segments = db.query(TranscriptSegment).all()
        segments = [s for s in all_segments if str(s.meeting_id) in meeting_ids]
        count = 0
        for seg in segments:
            meet = meeting_map.get(str(seg.meeting_id))
            cls.create_or_update_embedding(
                db,
                company_id=company_id,
                source_type="transcript_segment",
                source_id=str(seg.id),
                content_text=seg.text,
                project_id=meet.project_id if meet else None,
                meeting_id=str(seg.meeting_id),
                speaker_label=seg.speaker_label,
                participant_id=str(seg.user_id) if seg.user_id else None,
            )
            count += 1
        return count

    @classmethod
    def index_meeting_summaries(cls, db: Session, company_id: str) -> int:
        """Index all meeting summaries for company."""
        meetings = db.query(Meeting).filter(Meeting.company_id == company_id, Meeting.deleted_at.is_(None)).all()
        meeting_map = {}
        for m in meetings:
            if m.public_id:
                meeting_map[m.public_id] = m
            if m.id:
                meeting_map[str(m.id)] = m

        summaries = db.query(MeetingSummary).filter(MeetingSummary.company_id == company_id).all()
        count = 0
        for s in summaries:
            meet = meeting_map.get(s.meeting_id)
            text = f"{s.summary_text} Takeaways: {s.key_takeaways or ''}"
            cls.create_or_update_embedding(
                db,
                company_id=company_id,
                source_type="meeting_summary",
                source_id=str(s.id),
                content_text=text,
                project_id=meet.project_id if meet else None,
                meeting_id=s.meeting_id,
            )
            count += 1
        return count

    @classmethod
    def index_topics(cls, db: Session, company_id: str) -> int:
        """Index all topics for company."""
        topics = db.query(Topic).filter(Topic.company_id == company_id).all()
        count = 0
        for t in topics:
            text = f"Topic: {t.name}. {t.description or ''}"
            meet_id = t.meeting_id
            meet = db.query(Meeting).filter(Meeting.public_id == meet_id).first() if meet_id else None
            cls.create_or_update_embedding(
                db,
                company_id=company_id,
                source_type="topic",
                source_id=str(t.id),
                content_text=text,
                project_id=meet.project_id if meet else None,
                meeting_id=meet_id,
            )
            count += 1
        return count

    @classmethod
    def index_decisions(cls, db: Session, company_id: str) -> int:
        """Index all decisions for company."""
        decisions = db.query(Decision).filter(Decision.company_id == company_id).all()
        count = 0
        for d in decisions:
            text = f"Decision: {d.title}. Status: {d.status}. Proposal: {d.original_proposal or ''}. Reason: {d.reason or ''}. {d.description or ''}"
            cls.create_or_update_embedding(
                db,
                company_id=company_id,
                source_type="decision",
                source_id=str(d.id),
                content_text=text,
                project_id=d.project_id,
                meeting_id=d.meeting_id,
                speaker_label=d.proposer_id,
            )
            count += 1
        return count

    @classmethod
    def index_document_pages(cls, db: Session, company_id: str) -> int:
        """Index all document pages for company."""
        docs = db.query(Document).filter(Document.company_id == company_id, Document.deleted_at.is_(None)).all()
        doc_map = {d.public_id: d for d in docs}
        doc_ids = list(doc_map.keys())

        if not doc_ids:
            return 0

        pages = db.query(DocumentPage).filter(DocumentPage.document_id.in_(doc_ids)).all()
        count = 0
        for p in pages:
            doc = doc_map.get(p.document_id)
            if not doc:
                continue
            text = f"Document: {doc.title} Page {p.page_number}. Content: {p.text_content or ''}"
            cls.create_or_update_embedding(
                db,
                company_id=company_id,
                source_type="document_page",
                source_id=p.public_id,
                content_text=text,
                project_id=doc.project_id,
                meeting_id=doc.meeting_id,
            )
            count += 1
        return count

    @classmethod
    def index_meeting_entities(cls, db: Session, company_id: Optional[str], meeting_id: str) -> int:
        """Index all entities (segments, summaries, etc.) specifically for one meeting."""
        count = 0
        meeting = db.query(Meeting).filter(Meeting.public_id == meeting_id).first()
        if not meeting:
            return 0
            
        project_id = meeting.project_id
        effective_cid = company_id or meeting.company_id or (f"personal_{meeting.owner_id}" if meeting.owner_id else "personal")

        # 1. Transcript segments
        segments = db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == meeting_id).all()
        for seg in segments:
            cls.create_or_update_embedding(
                db, company_id=effective_cid, source_type="transcript_segment", source_id=str(seg.id),
                content_text=seg.text, project_id=project_id, meeting_id=meeting_id,
                speaker_label=seg.speaker_label, participant_id=str(seg.user_id) if seg.user_id else None
            )
            count += 1

        # 2. Summary
        summary = db.query(MeetingSummary).filter(MeetingSummary.meeting_id == meeting_id).first()
        if summary:
            text = f"{summary.summary_text} Takeaways: {summary.key_takeaways or ''}"
            cls.create_or_update_embedding(
                db, company_id=effective_cid, source_type="meeting_summary", source_id=str(summary.id),
                content_text=text, project_id=project_id, meeting_id=meeting_id
            )
            count += 1

        # 3. Questions
        from app.models.intelligence import Question, Commitment, Risk
        questions = db.query(Question).filter(Question.meeting_id == meeting_id).all()
        for q in questions:
            cls.create_or_update_embedding(
                db, company_id=effective_cid, source_type="question", source_id=str(q.id),
                content_text=q.question, project_id=project_id, meeting_id=meeting_id
            )
            count += 1

        # 4. Commitments
        commitments = db.query(Commitment).filter(Commitment.meeting_id == meeting_id).all()
        for c in commitments:
            cls.create_or_update_embedding(
                db, company_id=effective_cid, source_type="commitment", source_id=str(c.id),
                content_text=f"{c.person} committed to: {c.commitment}", project_id=project_id, meeting_id=meeting_id
            )
            count += 1

        # 5. Risks
        risks = db.query(Risk).filter(Risk.meeting_id == meeting_id).all()
        for r in risks:
            cls.create_or_update_embedding(
                db, company_id=effective_cid, source_type="risk", source_id=str(r.id),
                content_text=f"Risk: {r.title}", project_id=project_id, meeting_id=meeting_id
            )
            count += 1

        return count

    @classmethod
    def index_all_company_entities(cls, db: Session, company_id: str) -> Dict[str, int]:
        """Index all 5 entity types for company."""
        c_seg = cls.index_transcript_segments(db, company_id)
        c_sum = cls.index_meeting_summaries(db, company_id)
        c_top = cls.index_topics(db, company_id)
        c_dec = cls.index_decisions(db, company_id)
        c_doc = cls.index_document_pages(db, company_id)

        total = c_seg + c_sum + c_top + c_dec + c_doc
        return {
            "indexed_transcript_segments": c_seg,
            "indexed_meeting_summaries": c_sum,
            "indexed_topics": c_top,
            "indexed_decisions": c_dec,
            "indexed_document_pages": c_doc,
            "total_indexed": total,
        }

    @classmethod
    def index_user_meetings(cls, db: Session, current_user) -> Dict[str, int]:
        """Index all meetings authorized for current user."""
        from app.services.rag_service import RAGService
        meetings = RAGService._get_all_authorized_meetings(db, current_user)
        total_segments = 0
        for m in meetings:
            cnt = cls.index_meeting_entities(db, m.company_id, m.public_id)
            total_segments += cnt

        return {
            "indexed_transcript_segments": total_segments,
            "indexed_meeting_summaries": 0,
            "indexed_topics": 0,
            "indexed_decisions": 0,
            "indexed_document_pages": 0,
            "total_indexed": total_segments,
        }
