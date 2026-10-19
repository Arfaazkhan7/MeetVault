from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TranscriptSegment:
    start_time: float
    end_time: float
    text: str
    speaker_label: Optional[str] = None
    language: Optional[str] = None
    confidence: Optional[float] = None
    translated_text: Optional[str] = None
    segment_id: Optional[str] = None
    words: Optional[List[Dict[str, Any]]] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MeetingAnalysis:
    summary: str
    key_takeaways: List[Any] = field(default_factory=list)
    topics: List[Any] = field(default_factory=list)
    questions: List[Any] = field(default_factory=list)
    answers: List[Any] = field(default_factory=list)
    suggestions: List[Any] = field(default_factory=list)
    proposals: List[Any] = field(default_factory=list)
    concerns: List[Any] = field(default_factory=list)
    agreements: List[Any] = field(default_factory=list)
    disagreements: List[Any] = field(default_factory=list)
    decisions: List[Any] = field(default_factory=list)
    action_items: List[Any] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
