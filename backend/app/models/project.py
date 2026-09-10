from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import expression

from app.models.base import Base


class Project(Base):
    __tablename__ = "projects"

    public_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE") # ACTIVE, ARCHIVED
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship(
        "Company",
        primaryjoin="foreign(Project.company_id) == Company.public_id",
        back_populates="projects",
    )
    members = relationship(
        "ProjectMember",
        primaryjoin="Project.public_id == foreign(ProjectMember.project_id)",
        back_populates="project",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    meetings = relationship(
        "Meeting",
        primaryjoin="Project.public_id == foreign(Meeting.project_id)",
        back_populates="project",
    )
    documents = relationship(
        "Document",
        primaryjoin="Project.public_id == foreign(Document.project_id)",
        back_populates="project",
    )



class ProjectMember(Base):
    __tablename__ = "project_members"

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_member_project"),
    )

    user_id = Column(String, nullable=False, index=True)
    project_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False, default="MEMBER")

    project = relationship(
        "Project",
        primaryjoin="foreign(ProjectMember.project_id) == Project.public_id",
        back_populates="members",
    )
    user = relationship(
        "User",
        primaryjoin="foreign(ProjectMember.user_id) == User.public_id",
    )
