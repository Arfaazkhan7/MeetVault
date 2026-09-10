from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class DocumentPageRead(BaseModel):
    public_id: str
    document_id: str
    page_number: int
    text_content: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentRead(BaseModel):
    public_id: str
    company_id: str
    project_id: Optional[str] = None
    meeting_id: Optional[str] = None
    uploader_id: Optional[str] = None
    title: str
    file_name: str
    file_type: str
    file_size: Optional[int] = None
    file_url: str
    status: str
    page_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DocumentDetailRead(DocumentRead):
    pages: List[DocumentPageRead] = []


class DocumentAssociateRequest(BaseModel):
    project_id: Optional[str] = None
    meeting_id: Optional[str] = None


class DocumentSearchMatch(BaseModel):
    document: DocumentRead
    matching_pages: List[DocumentPageRead] = []


class DocumentSearchResponse(BaseModel):
    total: int
    results: List[DocumentSearchMatch] = []
