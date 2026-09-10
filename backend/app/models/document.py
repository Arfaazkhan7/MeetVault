from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import relationship

from app.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    public_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    meeting_id = Column(String, nullable=True, index=True)
    uploader_id = Column(String, nullable=True, index=True)

    title = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # pdf, ppt, pptx
    file_size = Column(Integer, nullable=True)
    file_url = Column(String, nullable=False)

    status = Column(String, nullable=False, default="PROCESSED")
    page_count = Column(Integer, nullable=False, default=0)

    deleted_at = Column(DateTime(timezone=True), nullable=True)

    pages = relationship(
        "DocumentPage",
        primaryjoin="Document.public_id == foreign(DocumentPage.document_id)",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
    )
    company = relationship(
        "Company",
        primaryjoin="foreign(Document.company_id) == Company.public_id",
        viewonly=True,
    )
    project = relationship(
        "Project",
        primaryjoin="foreign(Document.project_id) == Project.public_id",
        back_populates="documents",
    )
    meeting = relationship(
        "Meeting",
        primaryjoin="foreign(Document.meeting_id) == Meeting.public_id",
        back_populates="documents",
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    public_id = Column(String, unique=True, index=True, nullable=False)
    document_id = Column(String, nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    text_content = Column(String, nullable=True)

    document = relationship(
        "Document",
        primaryjoin="foreign(DocumentPage.document_id) == Document.public_id",
        back_populates="pages",
    )

