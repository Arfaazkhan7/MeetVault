import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.embedding import Embedding
from app.models.meeting import Meeting
from app.schemas.search import SearchFilterRequest, SearchResultItem, SearchModeEnum
from app.services.embedding_service import generate_text_embedding, calculate_cosine_similarity, EmbeddingService


class SearchService:
    """Service executing Keyword, Semantic, and Hybrid search over 5 entity types with 7 filters."""

    @classmethod
    def filter_query(cls, query, company_id: str, filters: SearchFilterRequest):
        """Apply security and contextual search filters to SQLAlchemy query."""
        query = query.filter(Embedding.company_id == company_id)

        if filters.project_id:
            query = query.filter(Embedding.project_id == filters.project_id)

        if filters.meeting_id:
            query = query.filter(Embedding.meeting_id == filters.meeting_id)

        if filters.participant_id:
            pattern = f"%{filters.participant_id}%"
            query = query.filter(
                or_(
                    Embedding.participant_id == filters.participant_id,
                    Embedding.speaker_label.ilike(pattern)
                )
            )

        if filters.document_id:
            query = query.filter(
                or_(
                    Embedding.source_id == filters.document_id,
                    Embedding.content_text.ilike(f"%{filters.document_id}%")
                )
            )

        if filters.topic_name:
            pattern = f"%{filters.topic_name}%"
            query = query.filter(Embedding.content_text.ilike(pattern))

        if filters.start_date:
            query = query.filter(Embedding.created_at >= filters.start_date)

        if filters.end_date:
            query = query.filter(Embedding.created_at <= filters.end_date)

        return query

    @classmethod
    def _build_result_item(
        cls,
        db: Session,
        emb: Embedding,
        score: float,
        mode: str,
        meeting_map: Dict[str, Meeting],
    ) -> SearchResultItem:
        """Format an Embedding database record into SearchResultItem with meeting metadata."""
        meet = meeting_map.get(emb.meeting_id) if emb.meeting_id else None
        meet_title = meet.title if meet else "Meeting"

        # Determine readable title based on source_type
        if emb.source_type == "transcript_segment":
            title = f"Transcript Segment ({emb.speaker_label or 'Speaker'})"
        elif emb.source_type == "meeting_summary":
            title = f"Meeting Summary ({meet_title})"
        elif emb.source_type == "topic":
            title = f"Topic Overview ({meet_title})"
        elif emb.source_type == "decision":
            title = f"Decision Record ({meet_title})"
        elif emb.source_type == "document_page":
            title = f"Document Page ({meet_title})"
        else:
            title = f"Evidence ({emb.source_type})"

        return SearchResultItem(
            source_type=emb.source_type,
            source_id=emb.source_id,
            title=title,
            content_text=emb.content_text or "",
            meeting_id=emb.meeting_id,
            meeting_title=meet_title,
            project_id=emb.project_id,
            speaker_label=emb.speaker_label,
            timestamp=emb.created_at,
            score=round(float(score), 4),
            search_mode=mode,
        )

    @classmethod
    def keyword_search(
        cls,
        db: Session,
        company_id: str,
        filters: SearchFilterRequest,
        meeting_map: Dict[str, Meeting],
    ) -> List[SearchResultItem]:
        """Execute Keyword search across embedded entities using exact and word matching."""
        # Ensure company embeddings exist
        EmbeddingService.index_all_company_entities(db, company_id)

        query_text = filters.query.strip()
        words = [w.lower() for w in re.findall(r'\b\w+\b', query_text) if len(w) > 2]
        if not words:
            words = [query_text.lower()]

        base_q = db.query(Embedding)
        base_q = cls.filter_query(base_q, company_id, filters)

        records = base_q.all()
        results = []

        for rec in records:
            text = (rec.content_text or "").lower()
            if not text:
                continue

            # Calculate keyword match score
            match_count = sum(1 for w in words if w in text)
            if match_count > 0 or query_text.lower() in text:
                exact_bonus = 0.3 if query_text.lower() in text else 0.0
                score = min(1.0, (match_count / len(words)) * 0.7 + exact_bonus)
                item = cls._build_result_item(db, rec, score, "keyword", meeting_map)
                results.append((score, item))

        results.sort(key=lambda x: x[0], reverse=True)
        limit = filters.limit or 20
        return [item for _, item in results[:limit]]

    @classmethod
    def semantic_search(
        cls,
        db: Session,
        company_id: str,
        filters: SearchFilterRequest,
        meeting_map: Dict[str, Meeting],
    ) -> List[SearchResultItem]:
        """Execute Semantic Vector search across 1536-dim vector embeddings using cosine similarity."""
        # Ensure company embeddings exist
        EmbeddingService.index_all_company_entities(db, company_id)

        query_vec = generate_text_embedding(filters.query)

        base_q = db.query(Embedding)
        base_q = cls.filter_query(base_q, company_id, filters)

        records = base_q.all()
        results = []

        for rec in records:
            if not rec.vector_data:
                continue
            try:
                rec_vec = json.loads(rec.vector_data)
                sim_score = calculate_cosine_similarity(query_vec, rec_vec)
                if sim_score > 0.01:
                    item = cls._build_result_item(db, rec, sim_score, "semantic", meeting_map)
                    results.append((sim_score, item))
            except Exception:
                continue

        results.sort(key=lambda x: x[0], reverse=True)
        limit = filters.limit or 20
        return [item for _, item in results[:limit]]

    @classmethod
    def hybrid_search(
        cls,
        db: Session,
        company_id: str,
        filters: SearchFilterRequest,
        meeting_map: Dict[str, Meeting],
    ) -> List[SearchResultItem]:
        """Execute Hybrid search combining keyword matching and vector semantic similarity with rank fusion."""
        keyword_results = cls.keyword_search(db, company_id, filters, meeting_map)
        semantic_results = cls.semantic_search(db, company_id, filters, meeting_map)

        kw_map = {item.source_id: item.score for item in keyword_results}
        sem_map = {item.source_id: item.score for item in semantic_results}
        item_map = {item.source_id: item for item in keyword_results + semantic_results}

        combined_results = []
        for sid, item in item_map.items():
            kw_score = kw_map.get(sid, 0.0)
            sem_score = sem_map.get(sid, 0.0)
            # Rank fusion formula: 50% keyword + 50% semantic
            hybrid_score = 0.5 * kw_score + 0.5 * sem_score

            hybrid_item = SearchResultItem(
                source_type=item.source_type,
                source_id=item.source_id,
                title=item.title,
                content_text=item.content_text,
                meeting_id=item.meeting_id,
                meeting_title=item.meeting_title,
                project_id=item.project_id,
                speaker_label=item.speaker_label,
                timestamp=item.timestamp,
                score=round(float(hybrid_score), 4),
                search_mode="hybrid",
            )
            combined_results.append(hybrid_item)

        combined_results.sort(key=lambda x: x.score, reverse=True)
        limit = filters.limit or 20
        return combined_results[:limit]
