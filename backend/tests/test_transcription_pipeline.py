"""
Comprehensive tests for multilingual transcription, transactional persistence,
idempotent reprocessing, error metrics (WER/CER), and boundary handling.
"""
import math
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient

from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.models.ai_job import AIJob
from app.services.transcription_service import TranscriptionService, TranscriptionEngine
from ai_worker.providers import (
    LANGUAGE_SUPPORT_MATRIX,
    evaluate_language_support,
    _extract_confidence,
    _parse_hf_transcription_response,
    _chunk_wav_file,
    _merge_chunk_segments,
    transcribe,
)
from ai_worker.schemas import TranscriptSegment as WorkerSegment
from ai_worker.tasks.pipeline import process_meeting_intelligence
from tests.conftest import TestingSessionLocal


# ---------------------------------------------------------------------------
# Metric helpers: WER (Word Error Rate) & CER (Character Error Rate)
# ---------------------------------------------------------------------------

def compute_wer(reference: str, hypothesis: str) -> float:
    """Calculate Word Error Rate (WER) using Levenshtein distance on words."""
    ref_words = reference.strip().split()
    hyp_words = hypothesis.strip().split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j - 1] + 1,  # substitution
                    d[i][j - 1] + 1,      # insertion
                    d[i - 1][j] + 1       # deletion
                )

    return d[len(ref_words)][len(hyp_words)] / float(len(ref_words))


def compute_cer(reference: str, hypothesis: str) -> float:
    """Calculate Character Error Rate (CER) using Levenshtein distance on characters."""
    ref_chars = list(reference.strip())
    hyp_chars = list(hypothesis.strip())

    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0

    d = [[0] * (len(hyp_chars) + 1) for _ in range(len(ref_chars) + 1)]
    for i in range(len(ref_chars) + 1):
        d[i][0] = i
    for j in range(len(hyp_chars) + 1):
        d[0][j] = j

    for i in range(1, len(ref_chars) + 1):
        for j in range(1, len(hyp_chars) + 1):
            if ref_chars[i - 1] == hyp_chars[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j - 1] + 1,
                    d[i][j - 1] + 1,
                    d[i - 1][j] + 1
                )

    return d[len(ref_chars)][len(hyp_chars)] / float(len(ref_chars))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_models(setup_db):
    """Seed test company, user, meeting, and recording."""
    db = TestingSessionLocal()
    try:
        company = Company(public_id="comp-multilingual", name="Multilingual Corp")
        db.add(company)

        user = User(
            public_id="usr-arfaaz",
            email="arfaaz@meetvault.com",
            full_name="Mohamed Arfaaz",
            hashed_password="pw",
        )
        db.add(user)
        db.flush()

        member = CompanyMember(
            company_id=company.public_id,
            user_id=user.public_id,
            role="COMPANY_ADMIN",
        )
        db.add(member)

        meeting = Meeting(
            public_id="mtg-pipeline-1",
            company_id=company.public_id,
            title="Tamil and English Tech Architecture Sync",
            status="completed",
        )
        db.add(meeting)
        db.flush()

        recording = MeetingRecording(
            meeting_id=meeting.public_id,
            company_id=company.public_id,
            uploaded_by_user_id=user.public_id,
            storage_backend="local",
            storage_path="recordings/mtg-pipeline-1.wav",
            original_filename="audio.wav",
            processing_status="RECORDED",
        )
        db.add(recording)
        db.commit()

        return {
            "company_id": company.public_id,
            "user_id": user.public_id,
            "meeting_id": meeting.public_id,
            "recording_id": str(recording.id),
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test Suite A: Multilingual Transcription & Support Evaluation
# ---------------------------------------------------------------------------

class TestMultilingualTranscription:
    def test_language_support_matrix_evaluation(self):
        """Verify model evaluation for English, Tamil, Hindi, Tanglish, and unsupported codes."""
        en_eval = evaluate_language_support("en")
        assert en_eval["supported"] is True
        assert en_eval["code_switching_capable"] is True

        ta_eval = evaluate_language_support("ta")
        assert ta_eval["supported"] is True
        assert ta_eval["tier"] == "Tier 1 Native"
        assert ta_eval["script"] == "Tamil"

        hi_eval = evaluate_language_support("hi")
        assert hi_eval["supported"] is True
        assert hi_eval["script"] == "Devanagari"

        auto_eval = evaluate_language_support(None)
        assert auto_eval["supported"] is True
        assert auto_eval["normalized_code"] == "auto"

        # Unsupported language
        unsupported = evaluate_language_support("xyz_unsupported")
        assert unsupported["supported"] is False
        assert "not verified" in unsupported["notes"]

    def test_hf_response_parsing_multilingual_tamil_hindi_tanglish(self):
        """Verify HF Whisper response parsing preserves Tamil, Hindi, Tanglish, and confidence."""
        mock_hf_data = {
            "text": "Full meeting transcription",
            "chunks": [
                {
                    "timestamp": [0.0, 4.2],
                    "text": "அனைவருக்கும் வணக்கம், இன்றைய மீட்டிங்கில் ஆர்க்கிடெக்சர் பற்றி பேசுவோம்.",
                    "language": "ta",
                    "avg_logprob": -0.12,
                    "words": [{"word": "வணக்கம்", "start": 1.0, "end": 2.0}],
                },
                {
                    "timestamp": [4.5, 9.8],
                    "text": "Meeting-la database schema and transcript integrity discuss pannalam, then migration run pannuvom.",
                    "language": "ta",  # Tanglish code-switched segment detected as Tamil acoustic base
                    "avg_logprob": -0.25,
                    "translation": "Let us discuss the database schema and transcript integrity in the meeting, then run migration.",
                },
                {
                    "timestamp": [10.0, 14.5],
                    "text": "आज की मीटिंग में हम डेटाबेस आर्किटेक्चर पर चर्चा करेंगे।",
                    "language": "hi",
                    "avg_logprob": -0.18,
                },
                {
                    "timestamp": [15.0, 19.2],
                    "text": "All segments must preserve genuine timestamps without duplicate keys.",
                    "language": "en",
                    "avg_logprob": -0.05,
                },
            ],
        }

        segments = _parse_hf_transcription_response(mock_hf_data)
        assert len(segments) == 4

        # Tamil segment
        assert segments[0].language == "ta"
        assert "வணக்கம்" in segments[0].text
        assert segments[0].confidence is not None
        assert 0.85 <= segments[0].confidence <= 0.95
        assert segments[0].words is not None

        # Tanglish code-switched segment: original text preserved, translation stored separately
        assert segments[1].language == "ta"
        assert "Meeting-la" in segments[1].text
        assert "migration run pannuvom" in segments[1].text
        assert segments[1].translated_text is not None
        assert "Let us discuss" in segments[1].translated_text
        assert segments[1].text != segments[1].translated_text  # Original text is not overwritten!

        # Hindi segment
        assert segments[2].language == "hi"
        assert "डेटाबेस" in segments[2].text

        # English segment
        assert segments[3].language == "en"
        assert 0.90 <= segments[3].confidence <= 1.0

    def test_genuine_confidence_vs_fabricated(self):
        """Ensure genuine confidence conversion from avg_logprob and no invented scores."""
        # avg_logprob: exp(-0.2) ≈ 0.8187
        conf = _extract_confidence(-0.2)
        assert conf == 0.8187

        # Probabilities already in [0, 1]
        assert _extract_confidence(0.95) == 0.95

        # Missing or invalid confidence returns None (no invented scores)
        assert _extract_confidence(None) is None
        assert _extract_confidence("invalid") is None

    def test_error_metrics_wer_and_cer(self):
        """Measure WER and CER on Tamil, English, and Tanglish reference and hypothesis."""
        # English
        ref_en = "Every segment must be preserved with genuine confidence and stable identifiers"
        hyp_en = "Every segment must be preserved with genuine confidence and stable identifiers"
        assert compute_wer(ref_en, hyp_en) == 0.0
        assert compute_cer(ref_en, hyp_en) == 0.0

        # Tamil character error rate
        ref_ta = "அனைவருக்கும் வணக்கம்"
        hyp_ta = "அனைவருக்கும் வணக்கம்"
        assert compute_cer(ref_ta, hyp_ta) == 0.0

        # Tamil slight phonetic variation
        hyp_ta_variant = "அனைவர்க்கும் வணக்கம்"
        cer = compute_cer(ref_ta, hyp_ta_variant)
        assert 0.0 < cer < 0.20  # Measured accurately


# ---------------------------------------------------------------------------
# Test Suite B: Long Audio Chunking & Boundary Alignment
# ---------------------------------------------------------------------------

class TestChunkingAndBoundaryHandling:
    def test_chunk_wav_and_merge_segments(self):
        """Test WAV splitting into overlapping chunks and reassembling with global offsets."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_wav = Path(f.name)

        try:
            # Create a 10-second test WAV file (44100Hz, 16-bit mono)
            sample_rate = 16000
            duration = 10
            nframes = sample_rate * duration
            with wave.open(str(temp_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(bytes(nframes * 2))

            # Split with small chunk duration for testing (e.g. 4s chunks with 1s overlap)
            chunks = _chunk_wav_file(temp_wav, chunk_duration_sec=4.0, overlap_sec=1.0)
            assert len(chunks) >= 3

            # Simulate transcription results per chunk
            chunk_results = [
                (
                    [
                        WorkerSegment(start_time=0.5, end_time=2.0, text="Chunk one introductory phrase."),
                        WorkerSegment(start_time=2.2, end_time=3.8, text="Continuing speech in first chunk."),
                    ],
                    0.0,  # Offset 0s
                ),
                (
                    [
                        # Overlapping segment from boundary
                        WorkerSegment(start_time=0.2, end_time=1.8, text="Continuing speech in first chunk."),
                        WorkerSegment(start_time=2.0, end_time=3.5, text="Second chunk distinct audio."),
                    ],
                    3.0,  # Offset 3s
                ),
            ]

            merged = _merge_chunk_segments(chunk_results)
            assert len(merged) == 3
            # Check timestamps are globally shifted and strictly monotonic
            assert merged[0].start_time == 0.5
            assert merged[1].start_time == 2.2
            # Duplicate boundary segment skipped, and third segment offset by 3s: 2.0 + 3.0 = 5.0
            assert merged[2].start_time == 5.0
            assert merged[2].text == "Second chunk distinct audio."
        finally:
            if temp_wav.exists():
                temp_wav.unlink()

    def test_empty_audio_and_silence_handling(self):
        """Ensure empty audio files (0 bytes) return empty list without crashing."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            empty_wav = Path(f.name)

        try:
            segments = transcribe(str(empty_wav))
            assert segments == []
        finally:
            if empty_wav.exists():
                empty_wav.unlink()


# ---------------------------------------------------------------------------
# Test Suite C: Database Integrity, Transactions & User Correction Guard
# ---------------------------------------------------------------------------

class TestDatabaseIntegrityAndPersistence:
    def test_idempotent_reprocessing_preserves_user_confirmed_speakers(self, mock_db_models):
        """
        Verify that re-running transcription persistence on a meeting:
        1. Does not duplicate segments (unique constraint / stable identity).
        2. Strictly preserves user-confirmed speaker mappings.
        """
        meeting_id = mock_db_models["meeting_id"]
        recording_id = mock_db_models["recording_id"]
        user_id = mock_db_models["user_id"]
        db = TestingSessionLocal()

        try:
            meeting = db.query(Meeting).filter(Meeting.public_id == meeting_id).first()

            # Seed an initial segment that the user confirmed via the UI
            initial_seg = TranscriptSegment(
                meeting_id=meeting_id,
                recording_id=recording_id,
                segment_id=f"{meeting_id}:0000",
                speaker_label="SPEAKER_00",
                user_id=user_id,
                speaker_confirmed=True,  # User confirmed this speaker!
                start_time=0.0,
                end_time=5.0,
                text="Initial recognized text",
                language="en",
            )
            # And an unconfirmed segment
            unconfirmed_seg = TranscriptSegment(
                meeting_id=meeting_id,
                recording_id=recording_id,
                segment_id=f"{meeting_id}:0001",
                speaker_label="SPEAKER_01",
                user_id=None,
                speaker_confirmed=False,
                start_time=5.5,
                end_time=10.0,
                text="Unconfirmed text",
                language="en",
            )
            db.add_all([initial_seg, unconfirmed_seg])
            db.commit()

            # Now simulate a re-run of transcription with newly recognized text
            mock_new_segments = {
                "segments": [
                    {
                        "start_time": 0.0,
                        "end_time": 5.2,
                        "text": "Refined recognized text with higher precision",
                        "language": "en",
                        "avg_logprob": -0.08,
                    },
                    {
                        "start_time": 5.5,
                        "end_time": 10.2,
                        "text": "Refined second segment text",
                        "language": "en",
                        "avg_logprob": -0.15,
                    },
                ]
            }

            class MockEngine(TranscriptionEngine):
                def transcribe(self, audio_path: str, language=None):
                    return mock_new_segments

            service = TranscriptionService(engine=MockEngine())
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp_wav:
                persisted = service.transcribe_meeting(
                    db=db,
                    meeting=meeting,
                    audio_path=tmp_wav.name,
                    recording_id=recording_id,
                )

            assert len(persisted) == 2

            # Query database directly to verify integrity
            saved_segments = (
                db.query(TranscriptSegment)
                .filter(TranscriptSegment.meeting_id == meeting_id)
                .order_by(TranscriptSegment.start_time)
                .all()
            )
            assert len(saved_segments) == 2

            # Segment 0: Text and confidence updated, BUT speaker_confirmed and user_id PRESERVED!
            seg0 = saved_segments[0]
            assert seg0.text == "Refined recognized text with higher precision"
            assert seg0.speaker_confirmed is True
            assert seg0.user_id == user_id
            assert seg0.speaker_label == "SPEAKER_00"
            assert seg0.segment_id == f"{meeting_id}:0000"

            # Segment 1: Updated cleanly
            seg1 = saved_segments[1]
            assert seg1.text == "Refined second segment text"
            assert seg1.speaker_confirmed is False
            assert seg1.segment_id == f"{meeting_id}:0001"

        finally:
            db.close()

    def test_silence_clean_completion_without_worker_crash(self, mock_db_models):
        """Verify silent recording completes cleanly with 0 segments and does not raise RuntimeError."""
        from uuid import UUID
        meeting_id = mock_db_models["meeting_id"]
        recording_id = mock_db_models["recording_id"]
        user_id = mock_db_models["user_id"]
        db = TestingSessionLocal()

        try:
            job = AIJob(
                public_id="job-silence-test",
                meeting_id=meeting_id,
                recording_id=recording_id,
                requested_by_user_id=user_id,
                status="QUEUED",
            )
            db.add(job)
            db.commit()

            # Execute pipeline with empty/silence
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp_wav:
                from unittest.mock import patch
                with patch("ai_worker.tasks.pipeline.get_storage_service") as mock_storage_factory:
                    mock_storage = mock_storage_factory.return_value
                    # Return 0 bytes (empty audio)
                    mock_storage.download_private_file.return_value = b""

                    # Override SessionLocal to use TestingSessionLocal factory
                    with patch("ai_worker.tasks.pipeline.SessionLocal", side_effect=TestingSessionLocal):
                        process_meeting_intelligence(job.public_id)

            check_db = TestingSessionLocal()
            try:
                refreshed_job = check_db.query(AIJob).filter(AIJob.public_id == job.public_id).first()
                refreshed_meeting = check_db.query(Meeting).filter(Meeting.public_id == meeting_id).first()
                refreshed_recording = check_db.query(MeetingRecording).filter(MeetingRecording.id == UUID(recording_id)).first()

                # Job and meeting are completed cleanly without error!
                assert refreshed_job.status == "COMPLETED"
                assert refreshed_meeting.transcription_status == "completed"
                assert refreshed_meeting.transcription_error is None
                assert refreshed_recording.processing_status == "COMPLETED"
            finally:
                check_db.close()

        finally:
            db.close()

    def test_api_retrieval_exposes_metadata(self, client: TestClient, mock_db_models):
        """Verify API GET /transcripts/meetings/{meeting_id} returns all enriched metadata."""
        meeting_id = mock_db_models["meeting_id"]
        recording_id = mock_db_models["recording_id"]
        user_id = mock_db_models["user_id"]
        db = TestingSessionLocal()

        try:
            seg = TranscriptSegment(
                meeting_id=meeting_id,
                recording_id=recording_id,
                segment_id=f"{meeting_id}:0000",
                speaker_label="SPEAKER_00",
                speaker_confirmed=True,
                start_time=0.0,
                end_time=3.5,
                text="வணக்கம்",
                translated_text="Greetings / Hello",
                language="ta",
                confidence=0.92,
                words=[{"word": "வணக்கம்", "start": 0.2, "end": 1.5}],
            )
            db.add(seg)
            db.commit()

            # Generate token for user
            from app.core.tokens import create_token
            token = create_token(subject=user_id, token_type="access")

            resp = client.get(
                f"/api/v1/transcripts/meetings/{meeting_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["meeting_id"] == meeting_id
            assert len(data["segments"]) == 1

            retrieved = data["segments"][0]
            assert retrieved["segment_id"] == f"{meeting_id}:0000"
            assert retrieved["recording_id"] == recording_id
            assert retrieved["language"] == "ta"
            assert retrieved["confidence"] == 0.92
            assert retrieved["text"] == "வணக்கம்"
            assert retrieved["translated_text"] == "Greetings / Hello"
            assert retrieved["words"] is not None
            assert retrieved["speaker_confirmed"] is True

        finally:
            db.close()
