from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_membership
from app.db.session import get_db
from app.models.user import User
from app.schemas.search import SearchFilterRequest, SearchResponse, IndexingResponse
from app.services.embedding_service import EmbeddingService
from app.services.retrieval_service import RetrievalService

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
)
def search_user_memory(
    filters: SearchFilterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Perform search across meeting memory and documents authorized for current_user.
    Supports keyword, semantic, and hybrid search modes.
    """
    return RetrievalService.retrieve_user_evidence(db, current_user, filters)


@router.post(
    "/search/embeddings/generate",
    response_model=IndexingResponse,
)
def generate_user_embeddings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate and index vector embeddings for all meetings authorized for current_user.
    """
    breakdown = EmbeddingService.index_user_meetings(db, current_user)
    total_indexed = breakdown.get("total_indexed", 0)

    return IndexingResponse(
        indexed_transcript_segments=breakdown.get("indexed_transcript_segments", 0),
        indexed_meeting_summaries=breakdown.get("indexed_meeting_summaries", 0),
        indexed_topics=breakdown.get("indexed_topics", 0),
        indexed_decisions=breakdown.get("indexed_decisions", 0),
        indexed_document_pages=breakdown.get("indexed_document_pages", 0),
        total_indexed=total_indexed,
        status="SUCCESS",
    )


@router.post(
    "/companies/{company_id}/embeddings/generate",
    response_model=IndexingResponse,
)
def generate_company_embeddings(
    company_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate and index vector embeddings for all 5 entity types
    (transcript segments, meeting summaries, topics, decisions, document pages)
    belonging to the specified company.
    """
    get_membership(db, current_user.public_id, company_id)
    breakdown = EmbeddingService.index_all_company_entities(db, company_id)
    total_indexed = breakdown.get("total_indexed", 0)

    return IndexingResponse(
        indexed_transcript_segments=breakdown.get("indexed_transcript_segments", 0),
        indexed_meeting_summaries=breakdown.get("indexed_meeting_summaries", 0),
        indexed_topics=breakdown.get("indexed_topics", 0),
        indexed_decisions=breakdown.get("indexed_decisions", 0),
        indexed_document_pages=breakdown.get("indexed_document_pages", 0),
        total_indexed=total_indexed,
        status="SUCCESS",
    )


@router.post(
    "/companies/{company_id}/search",
    response_model=SearchResponse,
)
def search_company_memory(
    company_id: str,
    filters: SearchFilterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Perform search across meeting memory and documents using keyword, semantic, or hybrid search modes.
    Enforces tenant access controls and supports 7 distinct search filters.
    """
    get_membership(db, current_user.public_id, company_id)
    return RetrievalService.retrieve_evidence(db, company_id, filters)


@router.post(
    "/companies/{company_id}/retrieval",
    response_model=SearchResponse,
)
def retrieve_evidence_context(
    company_id: str,
    filters: SearchFilterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve contextual evidence results formatted with structured citations for visual inspection or RAG context.
    """
    get_membership(db, current_user.public_id, company_id)
    return RetrievalService.retrieve_evidence(db, company_id, filters)
