from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.core.roles import Role
from app.db.session import get_db
from app.models.company import CompanyMember
from app.models.user import User
from app.schemas.document import (
    DocumentAssociateRequest,
    DocumentDetailRead,
    DocumentPageRead,
    DocumentRead,
    DocumentSearchResponse,
)
from app.services.document_service import (
    associate_document,
    delete_document,
    get_document,
    list_documents,
    process_and_create_document,
    search_documents_and_pages,
)

router = APIRouter(tags=["documents"])


@router.post(
    "/companies/{company_id}/documents/upload",
    response_model=DocumentDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    company_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    meeting_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Upload document (PDF, PPT, PPTX), extract text, segment pages/slides, and store in database."""
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    doc = process_and_create_document(
        db,
        company_id=company_id,
        file_name=file.filename or "uploaded_document",
        file_bytes=content,
        title=title,
        project_id=project_id,
        meeting_id=meeting_id,
        uploader_id=current_user.public_id,
    )
    return doc


@router.get(
    "/companies/{company_id}/documents",
    response_model=List[DocumentRead],
)
def get_company_documents(
    company_id: str,
    project_id: Optional[str] = Query(None),
    meeting_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """List documents for a company with optional filtering by project, meeting, or title search."""
    return list_documents(
        db,
        company_id=company_id,
        project_id=project_id,
        meeting_id=meeting_id,
        search=search,
    )


@router.get(
    "/companies/{company_id}/documents/search",
    response_model=DocumentSearchResponse,
)
def search_company_documents(
    company_id: str,
    q: str = Query(..., min_length=1),
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Search documents and segmented page text by query term."""
    matches = search_documents_and_pages(db, company_id=company_id, query_text=q)
    return DocumentSearchResponse(
        total=len(matches),
        results=matches,
    )


@router.get(
    "/companies/{company_id}/documents/{document_id}",
    response_model=DocumentDetailRead,
)
def get_document_details(
    company_id: str,
    document_id: str,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Get single document with page/slide breakdown."""
    return get_document(db, company_id=company_id, document_id=document_id)


@router.get(
    "/companies/{company_id}/documents/{document_id}/pages",
    response_model=List[DocumentPageRead],
)
def get_document_pages_list(
    company_id: str,
    document_id: str,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Get list of pages/slides for a document."""
    doc = get_document(db, company_id=company_id, document_id=document_id)
    return doc.pages


@router.patch(
    "/companies/{company_id}/documents/{document_id}/associate",
    response_model=DocumentRead,
)
def associate_document_to_entities(
    company_id: str,
    document_id: str,
    payload: DocumentAssociateRequest,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Associate document with a project or meeting."""
    return associate_document(
        db,
        company_id=company_id,
        document_id=document_id,
        project_id=payload.project_id,
        meeting_id=payload.meeting_id,
    )


@router.delete(
    "/companies/{company_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_company_document(
    company_id: str,
    document_id: str,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Soft delete document."""
    delete_document(db, company_id=company_id, document_id=document_id)


@router.get(
    "/companies/{company_id}/documents/{document_id}/download",
)
def download_private_document(
    company_id: str,
    document_id: str,
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Private document file download."""
    doc = get_document(db, company_id=company_id, document_id=document_id)
    import os
    if not os.path.exists(doc.file_url):
        raise HTTPException(status_code=404, detail="Document file binary not found in storage")

    return FileResponse(
        path=doc.file_url,
        filename=doc.file_name,
        media_type="application/octet-stream",
    )
