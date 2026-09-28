from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.ai_job import AIJob
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment
from app.services.meeting_analysis_service import MeetingAnalysisService
from app.services.storage_service import get_storage_service

router = APIRouter(prefix="/ai-jobs", tags=["cloudflare-ai"])


class CloudflareSegment(BaseModel):
    text: str
    start_time: float = 0.0
    end_time: float = 0.0
    speaker_label: str = "SPEAKER_0"
    confidence: float | None = None


class CloudflareResultRequest(BaseModel):
    provider: str = "cloudflare"
    transcription_text: str = ""
    segments: list[CloudflareSegment] = Field(default_factory=list)
    raw_result: dict[str, Any] = Field(default_factory=dict)


def _verify_worker_secret(secret: str | None) -> None:
    expected = settings.CLOUDFLARE_AI_CALLBACK_SECRET or settings.CLOUDFLARE_AI_QUEUE_SECRET
    if not expected or secret != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker secret")


def _load_job_context(db: Session, job_id: str) -> tuple[AIJob, MeetingRecording, Meeting]:
    job = db.query(AIJob).filter(AIJob.public_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")
    recording = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(job.recording_id)).first()
    meeting = db.query(Meeting).filter(Meeting.public_id == job.meeting_id).first()
    if not recording or not meeting:
        raise HTTPException(status_code=404, detail="AI job context not found")
    return job, recording, meeting


@router.get("/{job_id}/cloudflare/context")
def get_cloudflare_job_context(
    job_id: str,
    x_meetvault_worker_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _verify_worker_secret(x_meetvault_worker_secret)
    job, recording, meeting = _load_job_context(db, job_id)

    job.status = "RUNNING"
    job.current_stage = "FETCHING_AUDIO"
    job.started_at = job.started_at or datetime.now(timezone.utc)
    recording.processing_status = "PROCESSING"
    meeting.transcription_status = "processing"
    meeting.analysis_status = "processing"
    db.commit()

    storage = get_storage_service()
    return {
        "job_id": job.public_id,
        "meeting_id": meeting.public_id,
        "meeting_title": meeting.title,
        "recording_id": str(recording.id),
        "recording_url": storage.create_signed_url(
            path=recording.storage_path,
            expires_in_seconds=settings.RECORDING_SIGNED_URL_EXPIRE_SECONDS,
        ),
        "file_type": recording.file_type,
        "duration_seconds": recording.duration_seconds,
    }


@router.post("/{job_id}/cloudflare/result")
def submit_cloudflare_job_result(
    job_id: str,
    payload: CloudflareResultRequest,
    x_meetvault_worker_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _verify_worker_secret(x_meetvault_worker_secret)
    job, recording, meeting = _load_job_context(db, job_id)

    segments = payload.segments
    if not segments and payload.transcription_text.strip():
        segments = [CloudflareSegment(text=payload.transcription_text.strip())]
    if not segments:
        raise HTTPException(status_code=400, detail="No transcript segments returned")

    db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == meeting.public_id).delete()
    for segment in segments:
        db.add(
            TranscriptSegment(
                meeting_id=meeting.public_id,
                speaker_label=segment.speaker_label or "SPEAKER_0",
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                language=None,
                confidence=segment.confidence,
            )
        )

    job.current_stage = "EXTRACTING_INTELLIGENCE"
    db.commit()

    try:
        MeetingAnalysisService().analyze_meeting(db=db, meeting=meeting, force_reanalysis=True)
        meeting.transcription_status = "completed"
        meeting.transcription_error = None
        meeting.analysis_status = "completed"
        meeting.analysis_error = None
        recording.processing_status = "COMPLETED"
        recording.processing_error = None
        job.status = "COMPLETED"
        job.current_stage = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = None
        db.commit()
    except Exception as exc:
        meeting.analysis_status = "failed"
        meeting.analysis_error = str(exc)
        recording.processing_status = "FAILED"
        recording.processing_error = str(exc)
        job.status = "FAILED"
        job.failed_at = datetime.now(timezone.utc)
        job.error_message = str(exc)[:4000]
        db.commit()
        raise

    return {"ok": True, "job_id": job.public_id, "segments": len(segments)}


@router.post("/{job_id}/cloudflare/fail")
def fail_cloudflare_job(
    job_id: str,
    payload: dict[str, Any],
    x_meetvault_worker_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _verify_worker_secret(x_meetvault_worker_secret)
    job, recording, meeting = _load_job_context(db, job_id)
    error = str(payload.get("error") or "Cloudflare AI worker failed")

    meeting.transcription_status = "failed"
    meeting.transcription_error = error
    meeting.analysis_status = "failed"
    meeting.analysis_error = error
    recording.processing_status = "FAILED"
    recording.processing_error = error
    job.status = "FAILED"
    job.failed_at = datetime.now(timezone.utc)
    job.error_message = error[:4000]
    db.commit()
    return {"ok": True, "job_id": job.public_id}
