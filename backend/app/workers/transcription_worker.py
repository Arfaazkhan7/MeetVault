import logging
import threading
import queue
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.transcription_service import TranscriptionService
from app.services.meeting_service import get_meeting_by_public_id

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionJob:
    """Data class for transcription jobs."""
    meeting_id: str
    audio_path: str
    language: Optional[str] = None
    priority: int = 0


class TranscriptionWorker:
    """Background worker for processing transcription jobs asynchronously."""
    
    def __init__(self, num_workers: int = 2):
        """
        Initialize transcription worker pool.
        
        Args:
            num_workers: Number of worker threads to run
        """
        self.num_workers = num_workers
        self.job_queue = queue.PriorityQueue()
        self.workers = []
        self.is_running = False
        self.transcription_service = TranscriptionService()
    
    def start(self):
        """Start the worker pool."""
        if self.is_running:
            logger.warning("Worker pool is already running")
            return
        
        self.is_running = True
        logger.info(f"Starting {self.num_workers} transcription workers")
        
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"TranscriptionWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
        
        logger.info("Transcription worker pool started")
    
    def stop(self):
        """Stop the worker pool gracefully."""
        if not self.is_running:
            return
        
        logger.info("Stopping transcription worker pool")
        self.is_running = False
        
        # Wait for workers to finish
        for worker in self.workers:
            worker.join(timeout=5)
        
        self.workers.clear()
        logger.info("Transcription worker pool stopped")
    
    def submit_job(self, job: TranscriptionJob) -> bool:
        """
        Submit a transcription job to the queue.
        
        Args:
            job: TranscriptionJob to process
        
        Returns:
            True if job was submitted successfully
        """
        if not self.is_running:
            logger.error("Cannot submit job: worker pool is not running")
            return False
        
        try:
            self.job_queue.put((job.priority, job))
            logger.info(f"Submitted transcription job for meeting {job.meeting_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to submit job: {e}")
            return False
    
    def _worker_loop(self):
        """Worker thread main loop."""
        logger.info(f"Worker {threading.current_thread().name} started")
        
        while self.is_running:
            try:
                # Get job from queue with timeout
                priority, job = self.job_queue.get(timeout=1)
                
                # Process the job
                self._process_job(job)
                
                # Mark task as done
                self.job_queue.task_done()
                
            except queue.Empty:
                # No jobs available, continue loop
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}")
                continue
        
        logger.info(f"Worker {threading.current_thread().name} stopped")
    
    def _process_job(self, job: TranscriptionJob):
        """
        Process a single transcription job.
        
        Args:
            job: TranscriptionJob to process
        """
        logger.info(f"Processing transcription job for meeting {job.meeting_id}")
        
        # Create new database session for this job
        db = SessionLocal()
        try:
            # Get meeting
            meeting = get_meeting_by_public_id(db, job.meeting_id)
            if not meeting:
                logger.error(f"Meeting not found: {job.meeting_id}")
                return
            
            # Process transcription with automatic cleanup
            self.transcription_service.transcribe_meeting(
                db=db,
                meeting=meeting,
                audio_path=job.audio_path,
                language=job.language,
                cleanup_audio_after=True,
            )
            
            logger.info(f"Successfully processed transcription for meeting {job.meeting_id}")
            
        except Exception as e:
            logger.error(f"Failed to process transcription job for meeting {job.meeting_id}: {e}")
        finally:
            # Enforce zero-retention audio policy: discard audio file on completion or failure
            if job.audio_path:
                try:
                    import os
                    if os.path.isfile(job.audio_path):
                        os.unlink(job.audio_path)
                        logger.info(f"[ZERO_RETENTION] Discarded worker audio {job.audio_path}")
                except Exception as cleanup_err:
                    logger.warning(f"[ZERO_RETENTION_WARN] Could not unlink {job.audio_path}: {cleanup_err}")
            if meeting and meeting.recording_url == job.audio_path:
                meeting.recording_url = None
                try:
                    db.commit()
                except Exception:
                    pass
            db.close()
    
    def get_queue_size(self) -> int:
        """Get current number of jobs in queue."""
        return self.job_queue.qsize()


# Global worker instance
transcription_worker = TranscriptionWorker(num_workers=2)


def start_transcription_worker():
    """Start the global transcription worker."""
    transcription_worker.start()


def stop_transcription_worker():
    """Stop the global transcription worker."""
    transcription_worker.stop()


def submit_transcription_job(meeting_id: str, audio_path: str, language: Optional[str] = None) -> bool:
    """
    Submit a transcription job to the global worker.
    
    Args:
        meeting_id: Meeting public ID
        audio_path: Path to audio file
        language: Optional language code
    
    Returns:
        True if job was submitted successfully
    """
    job = TranscriptionJob(
        meeting_id=meeting_id,
        audio_path=audio_path,
        language=language
    )
    return transcription_worker.submit_job(job)