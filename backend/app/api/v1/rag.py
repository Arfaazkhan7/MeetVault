from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_membership, get_project_and_authorize
from app.db.session import get_db
from app.models.user import User
from app.models.project import Project
from app.schemas.rag import AskRequest, AskResponse
from app.services.rag_service import RAGService

router = APIRouter(tags=["rag"])


@router.post(
    "/companies/{company_id}/ask",
    response_model=AskResponse,
)
def ask_company_memory(
    company_id: str,
    request: AskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask a natural-language question about the company's meeting history.

    The RAG pipeline:
    1. Embeds the question into a 1536-dim vector.
    2. Retrieves semantically relevant evidence via hybrid search.
    3. Builds a grounded LLM context from retrieved evidence.
    4. Returns an evidence-backed answer with citations.

    If insufficient evidence exists, returns:
      "I could not find enough evidence in the meeting memory to answer this confidently."
    """
    get_membership(db, current_user.public_id, company_id)
    return RAGService.answer_question(db, company_id, request)


@router.post(
    "/companies/{company_id}/projects/{project_id}/ask",
    response_model=AskResponse,
)
def ask_project_memory(
    company_id: str,
    project_id: str,
    request: AskRequest,
    current_user: User = Depends(get_current_user),
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """
    Ask a natural-language question about a specific project's meeting history.
    """
    get_membership(db, current_user.public_id, company_id)
    scoped_request = AskRequest(
        question=request.question,
        project_id=project_id,
        limit=request.limit,
    )
    return RAGService.answer_question(db, company_id, scoped_request)


@router.post(
    "/projects/{project_id}/ask",
    response_model=AskResponse,
)
def ask_project_memory_direct(
    project_id: str,
    request: AskRequest,
    current_user: User = Depends(get_current_user),
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    """
    Ask a natural-language question scoped to a project using project_id directly.
    """
    company_id = project.company_id
    get_membership(db, current_user.public_id, company_id)
    scoped_request = AskRequest(
        question=request.question,
        project_id=project_id,
        limit=request.limit,
    )
    return RAGService.answer_question(db, company_id, scoped_request)
