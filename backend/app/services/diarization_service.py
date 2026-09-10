import logging
from typing import List, Dict, Any, Optional, Tuple
from abc import ABC, abstractmethod
import torch
import numpy as np

logger = logging.getLogger(__name__)


class DiarizationEngine(ABC):
    """Abstract base class for diarization engines."""
    
    @abstractmethod
    def diarize(self, audio_path: str, num_speakers: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Perform speaker diarization on audio file.
        
        Args:
            audio_path: Path to audio file
            num_speakers: Optional number of speakers (auto-detect if None)
        
        Returns:
            List of speaker segments with start_time, end_time, speaker
        """
        pass


class PyannoteDiarizationEngine(DiarizationEngine):
    """Pyannote.audio-based diarization engine."""
    
    def __init__(self, model_name: str = "pyannote/speaker-diarization-3.1"):
        """
        Initialize Pyannote diarization engine.
        
        Args:
            model_name: Hugging Face model name for diarization
        """
        try:
            from pyannote.audio import Pipeline
            from pyannote.core import Segment
            
            self.model_name = model_name
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            
            logger.info(f"Loading Pyannote model: {model_name} on {self.device}")
            self.pipeline = Pipeline.from_pretrained(
                model_name,
                use_auth_token=False  # Set to True if using private models
            )
            self.pipeline.to(self.device)
            logger.info("Pyannote model loaded successfully")
            
        except ImportError:
            logger.error("Pyannote.audio not installed")
            raise
        except Exception as e:
            logger.error(f"Failed to load Pyannote model: {e}")
            raise
    
    def diarize(self, audio_path: str, num_speakers: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Perform speaker diarization using Pyannote.audio.
        
        Args:
            audio_path: Path to audio file
            num_speakers: Optional number of speakers
        
        Returns:
            List of speaker segments with start_time, end_time, speaker
        """
        try:
            logger.info(f"Starting diarization for: {audio_path}")
            
            # Apply pipeline to audio file
            diarization = self.pipeline(audio_path, num_speakers=num_speakers)
            
            # Convert to list of segments
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start_time": turn.start,
                    "end_time": turn.end,
                    "speaker": str(speaker),
                    "duration": turn.end - turn.start
                })
            
            # Sort by start time
            segments.sort(key=lambda x: x["start_time"])
            
            logger.info(f"Diarization completed: {len(segments)} speaker segments found")
            return segments
            
        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            raise


class MockDiarizationEngine(DiarizationEngine):
    """Mock diarization engine for testing."""
    
    def diarize(self, audio_path: str, num_speakers: Optional[int] = None) -> List[Dict[str, Any]]:
        """Generate mock diarization segments for testing."""
        logger.warning("Using mock diarization engine - returning placeholder segments")
        
        # Generate mock segments simulating 2 speakers
        return [
            {"start_time": 0.0, "end_time": 5.0, "speaker": "SPEAKER_00", "duration": 5.0},
            {"start_time": 5.0, "end_time": 10.0, "speaker": "SPEAKER_01", "duration": 5.0},
            {"start_time": 10.0, "end_time": 15.0, "speaker": "SPEAKER_00", "duration": 5.0},
            {"start_time": 15.0, "end_time": 20.0, "speaker": "SPEAKER_01", "duration": 5.0},
            {"start_time": 20.0, "end_time": 25.0, "speaker": "SPEAKER_00", "duration": 5.0},
        ]


class DiarizationService:
    """Service for speaker diarization and speaker mapping."""
    
    def __init__(self, engine: Optional[DiarizationEngine] = None):
        """
        Initialize diarization service.
        
        Args:
            engine: Diarization engine to use (defaults to Mock for development)
        """
        self.engine = engine or MockDiarizationEngine()
        self.max_retries = 3
        self.retry_delay = 2  # seconds
    
    def diarize_meeting(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform diarization on meeting audio.
        
        Args:
            audio_path: Path to audio file
            num_speakers: Optional number of speakers
        
        Returns:
            List of speaker segments
        """
        try:
            return self._diarize_with_retry(audio_path, num_speakers)
        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            raise
    
    def _diarize_with_retry(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Perform diarization with retry logic."""
        import time
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return self.engine.diarize(audio_path, num_speakers)
            except Exception as e:
                last_error = e
                logger.warning(f"Diarization attempt {attempt + 1} failed: {e}")
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        raise Exception(f"Diarization failed after {self.max_retries} attempts: {last_error}")
    
    def align_transcript_with_speakers(
        self,
        transcript_segments: List[Dict[str, Any]],
        diarization_segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Align transcript segments with speaker diarization.
        
        Args:
            transcript_segments: Whisper transcript segments
            diarization_segments: Pyannote speaker segments
        
        Returns:
            Transcript segments with speaker labels
        """
        aligned_segments = []
        
        for trans_seg in transcript_segments:
            trans_start = trans_seg["start_time"]
            trans_end = trans_seg["end_time"]
            
            # Find dominant speaker for this transcript segment
            speaker = self._find_dominant_speaker(
                trans_start, trans_end, diarization_segments
            )
            
            aligned_segment = trans_seg.copy()
            aligned_segment["speaker_label"] = speaker
            aligned_segments.append(aligned_segment)
        
        return aligned_segments
    
    def _find_dominant_speaker(
        self,
        start_time: float,
        end_time: float,
        diarization_segments: List[Dict[str, Any]]
    ) -> str:
        """
        Find the dominant speaker for a time interval.
        
        Args:
            start_time: Start of interval
            end_time: End of interval
            diarization_segments: Speaker segments from diarization
        
        Returns:
            Speaker label with most overlap
        """
        speaker_durations = {}
        
        for seg in diarization_segments:
            seg_start = seg["start_time"]
            seg_end = seg["end_time"]
            speaker = seg["speaker"]
            
            # Calculate overlap
            overlap_start = max(start_time, seg_start)
            overlap_end = min(end_time, seg_end)
            
            if overlap_start < overlap_end:
                duration = overlap_end - overlap_start
                speaker_durations[speaker] = speaker_durations.get(speaker, 0) + duration
        
        if not speaker_durations:
            return "SPEAKER_UNKNOWN"
        
        # Return speaker with maximum duration
        return max(speaker_durations, key=speaker_durations.get)
    
    def normalize_speaker_labels(
        self,
        segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize speaker labels to SPEAKER_00, SPEAKER_01, etc.
        
        Args:
            segments: Segments with speaker labels
        
        Returns:
            Segments with normalized speaker labels
        """
        # Get unique speakers
        speakers = set(seg["speaker"] for seg in segments)
        
        # Create mapping from original to normalized labels
        speaker_mapping = {}
        normalized_segments = []
        
        for i, speaker in enumerate(sorted(speakers)):
            normalized_label = f"SPEAKER_{i:02d}"
            speaker_mapping[speaker] = normalized_label
        
        # Apply mapping
        for seg in segments:
            normalized_seg = seg.copy()
            original_speaker = seg["speaker"]
            normalized_seg["speaker"] = speaker_mapping.get(original_speaker, "SPEAKER_UNKNOWN")
            normalized_seg["original_speaker"] = original_speaker
            normalized_segments.append(normalized_seg)
        
        return normalized_segments
    
    def handle_overlapping_speech(
        self,
        diarization_segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Handle overlapping speech by splitting segments.
        
        Args:
            diarization_segments: Original speaker segments
        
        Returns:
            Processed segments with overlap handling
        """
        # Sort by start time
        sorted_segments = sorted(diarization_segments, key=lambda x: x["start_time"])
        
        processed_segments = []
        
        for i, seg in enumerate(sorted_segments):
            # Check for overlap with next segment
            if i < len(sorted_segments) - 1:
                next_seg = sorted_segments[i + 1]
                
                if seg["end_time"] > next_seg["start_time"]:
                    # Split at overlap point
                    overlap_point = next_seg["start_time"]
                    
                    # First part (non-overlapping)
                    processed_segments.append({
                        "start_time": seg["start_time"],
                        "end_time": overlap_point,
                        "speaker": seg["speaker"],
                        "duration": overlap_point - seg["start_time"]
                    })
                    
                    # Overlapping part (keep both speakers)
                    processed_segments.append({
                        "start_time": overlap_point,
                        "end_time": min(seg["end_time"], next_seg["end_time"]),
                        "speaker": seg["speaker"],
                        "duration": min(seg["end_time"], next_seg["end_time"]) - overlap_point,
                        "overlapping": True
                    })
                    
                    continue
            
            # No overlap or last segment
            processed_segments.append(seg)
        
        return processed_segments
    
    def create_speaker_mapping(
        self,
        segments: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Create initial speaker mapping from normalized labels.
        
        Args:
            segments: Segments with normalized speaker labels
        
        Returns:
            Dictionary mapping SPEAKER_XX to empty strings (for user mapping)
        """
        speakers = set(seg["speaker"] for seg in segments)
        
        return {
            speaker: ""  # Empty = unmapped
            for speaker in sorted(speakers)
            if speaker != "SPEAKER_UNKNOWN"
        }