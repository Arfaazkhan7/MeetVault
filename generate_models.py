import os

models_dir = 'backend/app/models'
os.makedirs(models_dir, exist_ok=True)

base_py = '''from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
import uuid
import datetime

class CustomBase:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

Base = declarative_base(cls=CustomBase)
'''

with open(f'{models_dir}/base.py', 'w') as f: f.write(base_py)

company_py = '''from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class Company(Base):
    __tablename__ = 'companies'
    public_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    members = relationship("CompanyMember", back_populates="company")
    projects = relationship("Project", back_populates="company")

class CompanyMember(Base):
    __tablename__ = 'company_members'
    user_id = Column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    role = Column(String, nullable=False, default='member')

    company = relationship("Company", back_populates="members")
    user = relationship("User", back_populates="company_memberships")
'''
with open(f'{models_dir}/company.py', 'w') as f: f.write(company_py)

user_py = '''from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class User(Base):
    __tablename__ = 'users'
    public_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    company_memberships = relationship("CompanyMember", back_populates="user")
'''
with open(f'{models_dir}/user.py', 'w') as f: f.write(user_py)

project_py = '''from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class Project(Base):
    __tablename__ = 'projects'
    public_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    company = relationship("Company", back_populates="projects")
    meetings = relationship("Meeting", back_populates="project")
'''
with open(f'{models_dir}/project.py', 'w') as f: f.write(project_py)

meeting_py = '''from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class Meeting(Base):
    __tablename__ = 'meetings'
    public_id = Column(String, unique=True, index=True, nullable=False)
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    project_id = Column(ForeignKey('projects.id', ondelete='SET NULL'), nullable=True)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default='scheduled')
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="meetings")
    participants = relationship("MeetingParticipant", back_populates="meeting")
    transcripts = relationship("TranscriptSegment", back_populates="meeting")

class MeetingParticipant(Base):
    __tablename__ = 'meeting_participants'
    meeting_id = Column(ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role = Column(String, nullable=False, default='attendee')
    join_time = Column(DateTime(timezone=True), nullable=True)
    leave_time = Column(DateTime(timezone=True), nullable=True)

    meeting = relationship("Meeting", back_populates="participants")
    user = relationship("User")
'''
with open(f'{models_dir}/meeting.py', 'w') as f: f.write(meeting_py)

transcript_py = '''from sqlalchemy import Column, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class TranscriptSegment(Base):
    __tablename__ = 'transcript_segments'
    meeting_id = Column(ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False)
    speaker_label = Column(String, nullable=False)
    user_id = Column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(String, nullable=False)
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)

    meeting = relationship("Meeting", back_populates="transcripts")
    user = relationship("User")
'''
with open(f'{models_dir}/transcript.py', 'w') as f: f.write(transcript_py)

topic_py = '''from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Topic(Base):
    __tablename__ = 'topics'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)

class MeetingTopic(Base):
    __tablename__ = 'meeting_topics'
    meeting_id = Column(ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False)
    topic_id = Column(ForeignKey('topics.id', ondelete='CASCADE'), nullable=False)
'''
with open(f'{models_dir}/topic.py', 'w') as f: f.write(topic_py)

decision_py = '''from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base

class Decision(Base):
    __tablename__ = 'decisions'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    meeting_id = Column(ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, nullable=False, default='proposed')

class DecisionHistory(Base):
    __tablename__ = 'decision_history'
    decision_id = Column(ForeignKey('decisions.id', ondelete='CASCADE'), nullable=False)
    meeting_id = Column(ForeignKey('meetings.id', ondelete='SET NULL'), nullable=True)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    notes = Column(String, nullable=True)
'''
with open(f'{models_dir}/decision.py', 'w') as f: f.write(decision_py)

task_py = '''from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class Task(Base):
    __tablename__ = 'tasks'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    meeting_id = Column(ForeignKey('meetings.id', ondelete='CASCADE'), nullable=False)
    assignee_id = Column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, nullable=False, default='open')
    due_date = Column(DateTime(timezone=True), nullable=True)
'''
with open(f'{models_dir}/task.py', 'w') as f: f.write(task_py)

document_py = '''from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from .base import Base

class Document(Base):
    __tablename__ = 'documents'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    meeting_id = Column(ForeignKey('meetings.id', ondelete='SET NULL'), nullable=True)
    title = Column(String, nullable=False)
    file_url = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

class DocumentPage(Base):
    __tablename__ = 'document_pages'
    document_id = Column(ForeignKey('documents.id', ondelete='CASCADE'), nullable=False)
    page_number = Column(Integer, nullable=False)
    text_content = Column(String, nullable=True)
'''
with open(f'{models_dir}/document.py', 'w') as f: f.write(document_py)

embedding_py = '''from sqlalchemy import Column, String, ForeignKey
from pgvector.sqlalchemy import Vector
from .base import Base

class Embedding(Base):
    __tablename__ = 'embeddings'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    source_type = Column(String, nullable=False, index=True) # e.g., 'transcript', 'document'
    source_id = Column(String, nullable=False, index=True)
    embedding = Column(Vector(1536), nullable=False) # e.g. OpenAI dimensions
'''
with open(f'{models_dir}/embedding.py', 'w') as f: f.write(embedding_py)

audit_py = '''from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from .base import Base

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    company_id = Column(ForeignKey('companies.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    details = Column(JSONB, nullable=True)
'''
with open(f'{models_dir}/audit.py', 'w') as f: f.write(audit_py)

init_py = '''from .base import Base
from .company import Company, CompanyMember
from .user import User
from .project import Project
from .meeting import Meeting, MeetingParticipant
from .transcript import TranscriptSegment
from .topic import Topic, MeetingTopic
from .decision import Decision, DecisionHistory
from .task import Task
from .document import Document, DocumentPage
from .embedding import Embedding
from .audit import AuditLog
'''
with open(f'{models_dir}/__init__.py', 'w') as f: f.write(init_py)

