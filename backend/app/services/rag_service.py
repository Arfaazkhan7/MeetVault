"""
RAGService — Phase 15: Ask Meeting Memory.

Pipeline:
  Question
    → embed question (1536-dim)
    → hybrid search (Phase 14 SearchService)
    → filter evidence by minimum relevance score
    → build structured LLM context string
    → LLM generates grounded answer
    → detect insufficient evidence
    → run RAG evaluation metrics
    → return AskResponse with evidence citations
"""

import logging
from typing import List, Optional, Set
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.meeting import Meeting
from app.models.project import Project
from app.schemas.search import SearchFilterRequest, SearchModeEnum
from app.schemas.rag import AskRequest, AskResponse, EvidenceItem, RAGEvaluation
from app.services.search_service import SearchService
from app.services.embedding_service import EmbeddingService
from app.services.llm_provider import get_llm_provider

logger = logging.getLogger(__name__)

INSUFFICIENT_EVIDENCE_MESSAGE = (
    "I could not find enough evidence in the meeting memory to answer this confidently."
)

# System prompt injected into LLM — strict grounding rules
RAG_SYSTEM_PROMPT = """You are MeetVault AI, a meeting memory assistant.
Your ONLY job is to answer questions using the EVIDENCE CONTEXT provided below.
STRICT RULES you must ALWAYS follow:
1. NEVER fabricate, invent, or assume any information not explicitly present in the evidence.
2. ALWAYS reference specific meeting details (meeting title, speaker, decision) from the evidence.
3. If the evidence is insufficient to answer confidently, output exactly: __INSUFFICIENT_EVIDENCE__
4. Keep answers concise, factual, and grounded. Maximum 3 paragraphs.
5. Do not make up names, dates, or technical decisions not shown in the evidence."""


class RAGService:
    """Retrieval-Augmented Generation service for meeting memory Q&A."""

    @classmethod
    def answer_question(
        cls,
        db: Session,
        company_id: str,
        request: AskRequest,
    ) -> AskResponse:
        """
        Execute the full RAG pipeline for a natural-language question.

        Steps:
          1. Retrieve top-K evidence via hybrid search (Phase 14)
          2. Filter evidence by minimum similarity score
          3. Build structured LLM context
          4. Generate grounded answer via LLMProvider
          5. Detect insufficient evidence
          6. Run RAG evaluation metrics
          7. Package and return AskResponse with evidence citations
        """
        question = request.question.strip()
        top_k = request.limit or settings.RAG_TOP_K
        min_score = settings.RAG_MIN_SCORE

        # ── Phase 1: Index + Retrieve Evidence ─────────────────────────────
        EmbeddingService.index_all_company_entities(db, company_id)

        meetings = db.query(Meeting).filter(Meeting.company_id == company_id).all()
        meeting_map = {}
        for m in meetings:
            if m.public_id:
                meeting_map[m.public_id] = m
            if m.id is not None:
                meeting_map[str(m.id)] = m

        search_filters = SearchFilterRequest(
            query=question,
            mode=SearchModeEnum.HYBRID,
            project_id=request.project_id,
            limit=top_k,
        )
        raw_results = SearchService.hybrid_search(db, company_id, search_filters, meeting_map)

        # ── Phase 2: Filter by minimum relevance score ──────────────────────
        qualified = [r for r in raw_results if r.score >= min_score]

        # ── Phase 3: Build structured LLM context ──────────────────────────
        context_str = cls._build_context(qualified, meeting_map)

        # ── Phase 4: Generate LLM answer ────────────────────────────────────
        llm = get_llm_provider()
        prompt = cls._build_prompt(question, context_str)
        
        try:
            raw_answer = llm.generate_completion(
                prompt=prompt,
                system_prompt=RAG_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=600,
            )
        except Exception as e:
            logger.error(f"LLM completion failed: {e}")
            raw_answer = "__INSUFFICIENT_EVIDENCE__"

        # ── Phase 5: Detect insufficient evidence ──────────────────────────
        insufficient = (
            not qualified
            or "__INSUFFICIENT_EVIDENCE__" in raw_answer
        )
        if insufficient:
            answer = INSUFFICIENT_EVIDENCE_MESSAGE
        else:
            answer = raw_answer.replace("__INSUFFICIENT_EVIDENCE__", "").strip()

        # ── Phase 6: Build evidence citations ──────────────────────────────
        evidence_items = cls._build_evidence_items(qualified, meeting_map)

        # ── Phase 7: RAG evaluation metrics ────────────────────────────────
        rag_eval = cls._evaluate_rag(qualified, answer, question)

        confidence = rag_eval.avg_evidence_score if not insufficient else 0.0

        return AskResponse(
            question=question,
            answer=answer,
            insufficient_evidence=insufficient,
            confidence=round(confidence, 4),
            evidence_count=len(evidence_items),
            evidence=evidence_items,
            rag_eval=rag_eval,
            model_used=llm.model,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @classmethod
    def _build_context(cls, results, meeting_map) -> str:
        """Format retrieved evidence items as a structured LLM context string."""
        if not results:
            return "No relevant evidence found in meeting memory."

        lines = ["EVIDENCE CONTEXT (use ONLY this to answer):", ""]
        for i, r in enumerate(results, 1):
            meet = meeting_map.get(r.meeting_id) if r.meeting_id else None
            meet_title = meet.title if meet else r.meeting_title or "Meeting"
            meet_date = meet.start_time.strftime("%Y-%m-%d") if (meet and meet.start_time) else "Unknown date"

            lines.append(f"[Evidence {i}]")
            lines.append(f"  Source: {r.source_type.replace('_', ' ').title()}")
            lines.append(f"  Meeting: {meet_title} ({meet_date})")
            if r.speaker_label:
                lines.append(f"  Speaker: {r.speaker_label}")
            lines.append(f"  Relevance Score: {r.score:.3f}")
            lines.append(f"  Excerpt: {r.content_text[:500]}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def _build_prompt(cls, question: str, context: str) -> str:
        """Build the full LLM prompt combining question and evidence context."""
        return f"""{context}

USER QUESTION:
{question}

ANSWER (strictly grounded in the evidence above):"""

    @classmethod
    def _build_evidence_items(cls, results, meeting_map) -> List[EvidenceItem]:
        """Convert search result items into structured EvidenceItem citations."""
        items = []
        for r in results:
            meet = meeting_map.get(r.meeting_id) if r.meeting_id else None
            doc_ref = None
            if r.source_type == "document_page" and r.title:
                doc_ref = r.title

            items.append(EvidenceItem(
                source_type=r.source_type,
                source_id=r.source_id,
                meeting_id=r.meeting_id,
                meeting_title=meet.title if meet else r.meeting_title,
                meeting_date=meet.start_time if meet else r.timestamp,
                speaker=r.speaker_label,
                timestamp=r.timestamp,
                excerpt=r.content_text[:400],
                document_ref=doc_ref,
                score=r.score,
            ))
        return items

    @classmethod
    def _evaluate_rag(cls, results, answer: str, question: str) -> RAGEvaluation:
        """Compute automated RAG quality metrics."""
        if not results:
            return RAGEvaluation(
                avg_evidence_score=0.0,
                evidence_coverage_meetings=0,
                faithfulness_score=0.0,
                retrieval_count=0,
            )

        avg_score = sum(r.score for r in results) / len(results)

        distinct_meetings: Set[str] = set()
        for r in results:
            if r.meeting_id:
                distinct_meetings.add(r.meeting_id)

        # Faithfulness: check answer doesn't invent content absent in all evidence
        # Simple heuristic: if answer is grounded (not insufficient), score 1.0.
        # If INSUFFICIENT_EVIDENCE signal appears, score 0.5 (uncertain).
        if "__INSUFFICIENT_EVIDENCE__" in answer or not answer:
            faithfulness = 0.5
        else:
            # Check if answer words are covered by evidence words (simple lexical check)
            evidence_words = set()
            for r in results:
                evidence_words.update(r.content_text.lower().split())
            answer_words = set(answer.lower().split())
            # Remove common stopwords from check
            stopwords = {"the", "a", "an", "is", "was", "were", "are", "in", "on", "of", "to", "and", "or", "it", "that"}
            meaningful_answer_words = answer_words - stopwords
            if meaningful_answer_words:
                covered = sum(1 for w in meaningful_answer_words if w in evidence_words)
                faithfulness = min(1.0, covered / len(meaningful_answer_words))
            else:
                faithfulness = 1.0

        return RAGEvaluation(
            avg_evidence_score=round(avg_score, 4),
            evidence_coverage_meetings=len(distinct_meetings),
            faithfulness_score=round(faithfulness, 4),
            retrieval_count=len(results),
        )
