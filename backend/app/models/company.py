from sqlalchemy import Column, String, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class Company(Base):
    __tablename__ = "companies"

    public_id = Column(String, unique=True, index=True, nullable=False)
    workspace_code = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships resolved via explicit primaryjoin on string columns
    members = relationship(
        "CompanyMember",
        primaryjoin="Company.public_id == foreign(CompanyMember.company_id)",
        back_populates="company",
        lazy="dynamic",
    )
    projects = relationship(
        "Project",
        primaryjoin="Company.public_id == foreign(Project.company_id)",
        back_populates="company",
    )


class CompanyMember(Base):
    __tablename__ = "company_members"

    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_member_company"),
    )

    # String IDs — not FK columns but logically reference companies.public_id / users.public_id
    user_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)

    # Valid values: SUPER_ADMIN | COMPANY_ADMIN | PROJECT_MANAGER | MEMBER
    role = Column(String, nullable=False, default="MEMBER")
    department = Column(String, nullable=True)
    job_title = Column(String, nullable=True)

    company = relationship(
        "Company",
        primaryjoin="foreign(CompanyMember.company_id) == Company.public_id",
        back_populates="members",
    )
    user = relationship(
        "User",
        primaryjoin="foreign(CompanyMember.user_id) == User.public_id",
        back_populates="company_memberships",
    )
