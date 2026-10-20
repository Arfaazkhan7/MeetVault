"""
RAG Pydantic schemas for Phase 15: Ask Meeting Memory.
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class AskRequest(BaseModel):
    """Request payload for a natural-language question to meeting memory."""
    question: str
    scope: Optional[str] = "all"  # "all" | "current_meeting" | "selected_meetings" | "project" | "company"
    meeting_id: Optional[str] = None
    meeting_ids: Optional[List[str]] = None
    project_id: Optional[str] = None
    company_id: Optional[str] = None
    limit: Optional[int] = 12  # Max evidence items to retrieve


class EvidenceItem(BaseModel):
    """A single piece of grounding evidence cited in an answer."""
    source_type: str          # transcript_segment | meeting_summary | topic | decision | document_page
    source_id: str
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    meeting_date: Optional[datetime] = None
    speaker: Optional[str] = None
    timestamp: Optional[datetime] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    excerpt: str              # Relevant text segment
    document_ref: Optional[str] = None  # Document title + page if applicable
    score: float              # Cosine similarity / relevance score


class RAGEvaluation(BaseModel):
    """Automated RAG evaluation metrics for quality tracking."""
    avg_evidence_score: float          # Mean similarity score of retrieved evidence
    evidence_coverage_meetings: int    # Number of distinct meetings cited in evidence
    faithfulness_score: float          # 1.0 = no hallucination detected; 0.0 = potential hallucination
    retrieval_count: int               # Total pieces of evidence retrieved


class AskResponse(BaseModel):
    """Response from Ask Meeting Memory RAG pipeline."""
    question: str
    answer: str
    insufficient_evidence: bool        # True if system couldn't find enough evidence
    confidence: float                  # Normalised confidence 0.0–1.0 based on evidence score
    evidence_count: int
    evidence: List[EvidenceItem] = []
    rag_eval: Optional[RAGEvaluation] = None
    model_used: str
