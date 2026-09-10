from app.models.base import Base
from app.models.company import Company, CompanyMember
from app.models.user import User
from app.models.project import Project
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.topic import Topic, MeetingTopic
from app.models.decision import Decision, DecisionHistory
from app.models.task import Task
from app.models.document import Document, DocumentPage
from app.models.embedding import Embedding
from app.models.audit import AuditLog
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

def test_models_import():
    # If the models import successfully without circular dependency errors, this passes
    assert True

def test_relationships():
    # Test that relationships are properly configured
    assert hasattr(Company, 'members')
    assert hasattr(Company, 'projects')
    assert hasattr(User, 'company_memberships')
    assert hasattr(Project, 'meetings')
    assert hasattr(Meeting, 'participants')
    assert hasattr(Meeting, 'transcripts')
    assert hasattr(TranscriptSegment, 'user')
    
    # Assert table names
    assert Company.__tablename__ == 'companies'
    assert User.__tablename__ == 'users'
    assert Project.__tablename__ == 'projects'
    assert Meeting.__tablename__ == 'meetings'
    assert Embedding.__tablename__ == 'embeddings'
