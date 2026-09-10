from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    public_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    account_type = Column(String, nullable=False, default="personal")

    company_memberships = relationship(
        "CompanyMember",
        primaryjoin="User.public_id == foreign(CompanyMember.user_id)",
        back_populates="user",
    )
