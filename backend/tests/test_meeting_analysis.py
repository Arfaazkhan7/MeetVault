"""
Tests for meeting analysis service.
"""
import pytest
from sqlalchemy.orm import Session

from app.models.meeting import Meeting
from app.models.company import Company
from app.models.user import User
from app.models.company import CompanyMember
from app.models.transcript import TranscriptSegment
from app.services.meeting_analysis_service import MeetingAnalysisService
from app.services.llm_provider import MockLLMProvider
from tests.conftest import TestingSessionLocal


@pytest.fixture
def test_company(setup_db):
    """Create a test company."""
    db = TestingSessionLocal()
    try:
        company = Company(
            public_id="test-company-1",
            name="Test Company",
            domain="test.com"
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        yield company
    finally:
        db.close()


@pytest.fixture
def test_user(setup_db, test_company: Company):
    """Create a test user."""
    db = TestingSessionLocal()
    try:
        user = User(
            public_id="test-user-1",
            email="test@example.com",
            full_name="Test User",
            hashed_password="hashed_password"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Add user to company
        member = CompanyMember(
            company_id=test_company.public_id,
            user_id=user.public_id,
            role="COMPANY_ADMIN"
        )
        db.add(member)
        db.commit()
        
        yield user
    finally:
        db.close()


@pytest.fixture
def test_meeting_with_transcript(setup_db, test_company: Company, test_user: User):
    """Create a test meeting with transcript segments."""
    db = TestingSessionLocal()
    try:
        meeting = Meeting(
            public_id="test-meeting-with-transcript",
            company_id=test_company.public_id,
            project_id=None,
            title="Test Strategy Meeting",
            status="completed"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        
        # Add sample transcript segments
        segments = [
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label="SPEAKER_0",
                start_time=0.0,
                end_time=5.0,
                text="Welcome everyone to our strategy meeting. Today we need to discuss the Q4 goals.",
                language="en",
                confidence=0.95
            ),
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label="SPEAKER_1",
                start_time=5.0,
                end_time=10.0,
                text="I think we should focus on increasing customer retention as our primary goal.",
                language="en",
                confidence=0.92
            ),
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label="SPEAKER_0",
                start_time=10.0,
                end_time=15.0,
                text="That's a good point. Let's set a target of 15% improvement in retention rates.",
                language="en",
                confidence=0.94
            ),
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label="SPEAKER_2",
                start_time=15.0,
                end_time=20.0,
                text="I can take the lead on developing the retention strategy. Should be ready by next month.",
                language="en",
                confidence=0.91
            ),
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label="SPEAKER_1",
                start_time=20.0,
                end_time=25.0,
                text="Great! Let's also consider launching a new product feature in Q4.",
                language="en",
                confidence=0.93
            ),
        ]
        
        for segment in segments:
            db.add(segment)
        
        db.commit()
        yield meeting
    finally:
        db.close()


@pytest.fixture
def test_meeting_without_transcript(setup_db, test_company: Company, test_user: User):
    """Create a test meeting without transcript segments."""
    db = TestingSessionLocal()
    try:
        meeting = Meeting(
            public_id="test-meeting-no-transcript",
            company_id=test_company.public_id,
            project_id=None,
            title="Test Meeting Without Transcript",
            status="completed"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        yield meeting
    finally:
        db.close()


class TestMeetingAnalysisService:
    """Tests for MeetingAnalysisService."""
    
    def test_analysis_service_initialization(self):
        """Test that MeetingAnalysisService can be initialized."""
        mock_provider = MockLLMProvider()
        service = MeetingAnalysisService(llm_provider=mock_provider)
        
        assert service is not None
        assert service.llm_provider is not None
        assert service.max_retries == 3
    
    def test_analyze_meeting_with_transcript(self, test_meeting_with_transcript: Meeting):
        """Test analyzing a meeting with transcript segments."""
        db = TestingSessionLocal()
        try:
            # Verify transcript segments exist
            segments = db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == test_meeting_with_transcript.public_id
            ).all()
            assert len(segments) > 0, "No transcript segments found"
            
            mock_provider = MockLLMProvider()
            service = MeetingAnalysisService(llm_provider=mock_provider)
            
            # Analyze the meeting
            result = service.analyze_meeting(db, test_meeting_with_transcript)
            
            # Verify basic structure
            assert result is not None
            assert "summary" in result
            assert "key_takeaways" in result
            assert "topics" in result
            assert "decisions" in result
            # Check for either tasks or action_items
            assert "tasks" in result or "action_items" in result
            
            # Verify meeting status was updated
            from app.services.meeting_service import get_meeting_by_public_id
            updated_meeting = get_meeting_by_public_id(db, test_meeting_with_transcript.public_id)
            assert updated_meeting.analysis_status == "completed"
            assert updated_meeting.analysis_error is None
            
        finally:
            db.close()
    
    def test_analyze_meeting_without_transcript(self, test_meeting_without_transcript: Meeting):
        """Test analyzing a meeting without transcript segments."""
        db = TestingSessionLocal()
        try:
            mock_provider = MockLLMProvider()
            service = MeetingAnalysisService(llm_provider=mock_provider)
            
            # Analyze the meeting
            result = service.analyze_meeting(db, test_meeting_without_transcript)
            
            # Should return error
            assert "error" in result
            assert result["error"] == "No transcript available for analysis"
            
        finally:
            db.close()
    
    def test_re_analysis(self, test_meeting_with_transcript: Meeting):
        """Test re-analyzing a meeting with force_reanalysis flag."""
        db = TestingSessionLocal()
        try:
            mock_provider = MockLLMProvider()
            service = MeetingAnalysisService(llm_provider=mock_provider)
            
            # First analysis
            result1 = service.analyze_meeting(db, test_meeting_with_transcript, force_reanalysis=False)
            assert result1 is not None
            
            # Second analysis without force should return cached result
            result2 = service.analyze_meeting(db, test_meeting_with_transcript, force_reanalysis=False)
            assert result2 is not None
            
            # Force re-analysis
            result3 = service.analyze_meeting(db, test_meeting_with_transcript, force_reanalysis=True)
            assert result3 is not None
            
        finally:
            db.close()
    
    def test_get_existing_analysis(self, test_meeting_with_transcript: Meeting):
        """Test retrieving existing analysis results."""
        db = TestingSessionLocal()
        try:
            # Verify transcript segments exist
            segments = db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == test_meeting_with_transcript.public_id
            ).all()
            assert len(segments) > 0, "No transcript segments found"
            
            mock_provider = MockLLMProvider()
            service = MeetingAnalysisService(llm_provider=mock_provider)
            
            # First analyze the meeting
            service.analyze_meeting(db, test_meeting_with_transcript)
            
            # Retrieve existing analysis
            result = service._get_existing_analysis(db, test_meeting_with_transcript)
            
            assert result is not None
            assert "summary" in result
            assert "topics" in result
            assert "decisions" in result
            # Check for either tasks or action_items
            assert "tasks" in result or "action_items" in result
            
        finally:
            db.close()
    
    def test_prepare_transcript(self, test_meeting_with_transcript: Meeting):
        """Test transcript preparation for AI analysis."""
        db = TestingSessionLocal()
        try:
            segments = db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == test_meeting_with_transcript.public_id
            ).order_by(TranscriptSegment.start_time).all()
            
            mock_provider = MockLLMProvider()
            service = MeetingAnalysisService(llm_provider=mock_provider)
            
            transcript = service._prepare_transcript(segments)
            
            assert transcript is not None
            assert len(transcript) > 0
            assert "[0.0s - 5.0s]" in transcript  # Check timestamp format
            assert "SPEAKER_0:" in transcript  # Check speaker format
            
        finally:
            db.close()
    
    def test_validate_analysis_result(self):
        """Test validation of analysis result structure."""
        mock_provider = MockLLMProvider()
        service = MeetingAnalysisService(llm_provider=mock_provider)
        
        # Test with complete result
        complete_result = {
            "summary": "Test summary",
            "key_takeaways": ["point1", "point2"],
            "topics": [],
            "questions": [],
            "answers": [],
            "suggestions": [],
            "proposals": [],
            "concerns": [],
            "agreements": [],
            "disagreements": [],
            "decisions": [],
            "action_items": []
        }
        
        validated = service._validate_analysis_result(complete_result)
        assert "summary" in validated
        assert "key_takeaways" in validated
        
        # Test with incomplete result
        incomplete_result = {
            "summary": "Test summary"
        }
        
        validated = service._validate_analysis_result(incomplete_result)
        assert "summary" in validated
        assert "key_takeaways" in validated  # Should be empty array
        assert validated["key_takeaways"] == []


class TestLLMProvider:
    """Tests for LLM provider implementations."""
    
    def test_mock_provider_initialization(self):
        """Test MockLLMProvider initialization."""
        provider = MockLLMProvider()
        assert provider is not None
        assert provider.model == "mock-model"
    
    def test_mock_provider_completion(self):
        """Test MockLLMProvider text completion."""
        provider = MockLLMProvider()
        result = provider.generate_completion("test prompt")
        
        assert result is not None
        assert isinstance(result, str)
        assert "mock" in result.lower()
    
    def test_mock_provider_structured_completion(self):
        """Test MockLLMProvider structured completion."""
        provider = MockLLMProvider()
        result = provider.generate_structured_completion("test prompt")
        
        assert result is not None
        assert isinstance(result, dict)
        assert "summary" in result
        assert "topics" in result