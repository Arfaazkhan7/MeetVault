import io
import os
import re
import uuid
import zipfile
from xml.etree.ElementTree import ParseError
from typing import List, Optional, Tuple, Dict, Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentPage
from app.models.meeting import Meeting
from app.models.project import Project
from app.core.config import settings
from app.core.runtime import IS_WORKERS

ALLOWED_EXTENSIONS = {"pdf", "ppt", "pptx"}

# Base path for local private document storage
STORAGE_BASE_DIR = os.path.join(os.getcwd(), "storage", "documents")


def validate_document_filename(filename: str) -> str:
    """Extract and validate extension for PDF, PPT, and PPTX."""
    if not filename or "." not in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File has no extension. Only PDF, PPT, and PPTX formats are supported.",
        )
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '.{ext}'. Only PDF, PPT, and PPTX formats are supported.",
        )
    return ext


def extract_pdf_pages(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract text page-by-page from PDF."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append({
                "page_number": idx,
                "text_content": text.strip(),
            })
        return pages
    except Exception as e:
        # Fallback or empty if PDF parsing fails
        return [{"page_number": 1, "text_content": f"[PDF extraction failed: {str(e)}]"}]


def extract_pptx_slides(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract text slide-by-slide from PPTX."""
    if IS_WORKERS:
        from app.services.pptx_text import extract_slides
        try:
            return extract_slides(file_bytes)
        except (ValueError, KeyError, OSError, EOFError, RuntimeError, ParseError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=400, detail="Invalid or oversized PPTX presentation") from exc
    try:
        import pptx
        prs = pptx.Presentation(io.BytesIO(file_bytes))
        slides = []
        for idx, slide in enumerate(prs.slides, start=1):
            text_parts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        if paragraph.text:
                            text_parts.append(paragraph.text.strip())
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes = slide.notes_slide.notes_text_frame.text
                if notes:
                    text_parts.append(f"Notes: {notes.strip()}")
            slide_text = "\n".join(t for t in text_parts if t)
            slides.append({
                "page_number": idx,
                "text_content": slide_text,
            })
        return slides
    except Exception as e:
        return [{"page_number": 1, "text_content": f"[PPTX extraction failed: {str(e)}]"}]


def extract_ppt_slides(file_bytes: bytes) -> List[Dict[str, Any]]:
    """Extract text slide-by-slide from legacy binary PPT format."""
    # First try parsing with pptx in case it's a pptx with .ppt extension
    if IS_WORKERS and file_bytes.startswith(b"PK"):
        return extract_pptx_slides(file_bytes)
    try:
        import pptx
        prs = pptx.Presentation(io.BytesIO(file_bytes))
        return extract_pptx_slides(file_bytes)
    except Exception:
        pass

    # Olefile / text-stream binary extraction for PPT
    try:
        import olefile
        if olefile.isOleFile(io.BytesIO(file_bytes)):
            ole = olefile.OleFileIO(io.BytesIO(file_bytes))
            streams = ole.listdir()
            text_chunks = []
            for stream_path in streams:
                if "PowerPoint Document" in stream_path or "Current User" in stream_path:
                    try:
                        stream_bytes = ole.openstream(stream_path).read()
                        # Extract printable text strings
                        strings = re.findall(rb'[\x20-\x7E\s]{4,}', stream_bytes)
                        decoded = [s.decode('latin-1', errors='ignore').strip() for s in strings if len(s.strip()) > 3]
                        if decoded:
                            text_chunks.extend(decoded)
                    except Exception:
                        continue
            ole.close()
            if text_chunks:
                # Segment text into logical slides (~ 200 chars per slide chunk)
                full_text = "\n".join(text_chunks)
                lines = [line for line in full_text.splitlines() if line.strip()]
                slides = []
                chunk = []
                slide_num = 1
                for line in lines:
                    chunk.append(line)
                    if len("\n".join(chunk)) > 300:
                        slides.append({"page_number": slide_num, "text_content": "\n".join(chunk)})
                        slide_num += 1
                        chunk = []
                if chunk:
                    slides.append({"page_number": slide_num, "text_content": "\n".join(chunk)})
                return slides or [{"page_number": 1, "text_content": full_text}]
    except Exception:
        pass

    # Generic string extraction fallback
    strings = re.findall(rb'[\x20-\x7E\s]{5,}', file_bytes)
    raw_text = "\n".join([s.decode('latin-1', errors='ignore').strip() for s in strings if len(s.strip()) > 4])
    if not raw_text:
        raw_text = "Presentation text content"
    return [{"page_number": 1, "text_content": raw_text}]


def extract_document_pages(file_bytes: bytes, file_type: str) -> List[Dict[str, Any]]:
    """Route document to format-specific text extraction & segmentation."""
    ext = file_type.lower()
    if ext == "pdf":
        return extract_pdf_pages(file_bytes)
    elif ext == "pptx":
        return extract_pptx_slides(file_bytes)
    elif ext == "ppt":
        return extract_ppt_slides(file_bytes)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported document format: {file_type}",
        )


def save_private_file(company_id: str, doc_public_id: str, file_name: str, content: bytes) -> str:
    """Save document in private storage directory."""
    if settings.DOCUMENT_STORAGE_BACKEND == "supabase":
        from app.services.storage_service import SupabaseStorageService
        ext = validate_document_filename(file_name)
        object_path = f"{company_id}/{doc_public_id}.{ext}"
        storage = SupabaseStorageService(
            supabase_url=settings.SUPABASE_URL,
            service_role_key=settings.SUPABASE_SERVICE_ROLE_KEY,
            bucket=settings.SUPABASE_DOCUMENTS_BUCKET,
        )
        storage.upload_private_file(
            path=object_path, content=content, content_type="application/octet-stream",
        )
        return f"supabase://{settings.SUPABASE_DOCUMENTS_BUCKET}/{object_path}"
    target_dir = os.path.join(STORAGE_BASE_DIR, company_id)
    os.makedirs(target_dir, exist_ok=True)
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
    file_path = os.path.join(target_dir, f"{doc_public_id}.{ext}")
    with open(file_path, "wb") as f:
        f.write(content)
    return file_path


def process_and_create_document(
    db: Session,
    *,
    company_id: str,
    file_name: str,
    file_bytes: bytes,
    title: Optional[str] = None,
    project_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    uploader_id: Optional[str] = None,
) -> Document:
    """Pipeline: Validation -> Storage -> Text extraction -> Segmentation -> Database."""
    # 1. Validation
    file_type = validate_document_filename(file_name)

    # Validate project and meeting if provided
    if project_id:
        proj = db.query(Project).filter(
            Project.public_id == project_id,
            Project.company_id == company_id,
            Project.deleted_at.is_(None)
        ).first()
        if not proj:
            raise HTTPException(status_code=404, detail="Associated project not found in this company")

    if meeting_id:
        meet = db.query(Meeting).filter(
            Meeting.public_id == meeting_id,
            Meeting.company_id == company_id,
            Meeting.deleted_at.is_(None)
        ).first()
        if not meet:
            raise HTTPException(status_code=404, detail="Associated meeting not found in this company")

    # Generate document public_id
    doc_public_id = f"doc_{uuid.uuid4().hex[:12]}"

    # 2. Private Storage
    file_path = save_private_file(company_id, doc_public_id, file_name, file_bytes)

    # 3 & 4. Text Extraction & Slide/Page Segmentation
    extracted_pages = extract_document_pages(file_bytes, file_type)
    if not extracted_pages:
        extracted_pages = [{"page_number": 1, "text_content": ""}]

    doc_title = title.strip() if (title and title.strip()) else file_name

    # 5. Database Record Creation
    document = Document(
        public_id=doc_public_id,
        company_id=company_id,
        project_id=project_id,
        meeting_id=meeting_id,
        uploader_id=uploader_id,
        title=doc_title,
        file_name=file_name,
        file_type=file_type,
        file_size=len(file_bytes),
        file_url=file_path,
        status="PROCESSED",
        page_count=len(extracted_pages),
    )
    db.add(document)

    for p in extracted_pages:
        page_rec = DocumentPage(
            public_id=f"doc_page_{uuid.uuid4().hex[:12]}",
            document_id=doc_public_id,
            page_number=p["page_number"],
            text_content=p["text_content"],
        )
        db.add(page_rec)

    db.commit()
    db.refresh(document)
    return document


def list_documents(
    db: Session,
    company_id: str,
    project_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Document]:
    """Query documents for a company with optional filters."""
    query = db.query(Document).filter(
        Document.company_id == company_id,
        Document.deleted_at.is_(None)
    )

    if project_id:
        query = query.filter(Document.project_id == project_id)
    if meeting_id:
        query = query.filter(Document.meeting_id == meeting_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Document.title.ilike(pattern),
                Document.file_name.ilike(pattern),
            )
        )

    return query.order_by(Document.created_at.desc()).all()


def get_document(db: Session, company_id: str, document_id: str) -> Document:
    """Fetch single document by ID."""
    doc = db.query(Document).filter(
        Document.public_id == document_id,
        Document.company_id == company_id,
        Document.deleted_at.is_(None)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def associate_document(
    db: Session,
    company_id: str,
    document_id: str,
    project_id: Optional[str] = None,
    meeting_id: Optional[str] = None,
) -> Document:
    """Associate or update document relationships with project and/or meeting."""
    doc = get_document(db, company_id, document_id)

    if project_id is not None:
        if project_id == "":
            doc.project_id = None
        else:
            proj = db.query(Project).filter(
                Project.public_id == project_id,
                Project.company_id == company_id,
                Project.deleted_at.is_(None)
            ).first()
            if not proj:
                raise HTTPException(status_code=404, detail="Project not found")
            doc.project_id = project_id

    if meeting_id is not None:
        if meeting_id == "":
            doc.meeting_id = None
        else:
            meet = db.query(Meeting).filter(
                Meeting.public_id == meeting_id,
                Meeting.company_id == company_id,
                Meeting.deleted_at.is_(None)
            ).first()
            if not meet:
                raise HTTPException(status_code=404, detail="Meeting not found")
            doc.meeting_id = meeting_id

    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, company_id: str, document_id: str) -> None:
    """Soft delete document."""
    doc = get_document(db, company_id, document_id)
    import datetime
    doc.deleted_at = datetime.datetime.utcnow()
    db.commit()


def search_documents_and_pages(
    db: Session,
    company_id: str,
    query_text: str,
) -> List[Dict[str, Any]]:
    """Search documents and pages by keyword query."""
    pattern = f"%{query_text}%"

    # Find matching documents by title or filename
    docs = db.query(Document).filter(
        Document.company_id == company_id,
        Document.deleted_at.is_(None),
        or_(
            Document.title.ilike(pattern),
            Document.file_name.ilike(pattern),
        )
    ).all()

    # Find matching pages by text_content
    matching_pages = db.query(DocumentPage).join(
        Document, DocumentPage.document_id == Document.public_id
    ).filter(
        Document.company_id == company_id,
        Document.deleted_at.is_(None),
        DocumentPage.text_content.ilike(pattern),
    ).all()

    doc_map: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        doc_map[d.public_id] = {
            "document": d,
            "matching_pages": [],
        }

    for page in matching_pages:
        if page.document_id not in doc_map:
            doc = get_document(db, company_id, page.document_id)
            doc_map[page.document_id] = {
                "document": doc,
                "matching_pages": [],
            }
        doc_map[page.document_id]["matching_pages"].append(page)

    return list(doc_map.values())

