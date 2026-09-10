from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class SearchModeEnum(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SearchFilterRequest(BaseModel):
    query: str
    mode: Optional[SearchModeEnum] = SearchModeEnum.HYBRID
    project_id: Optional[str] = None
    meeting_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    participant_id: Optional[str] = None
    topic_name: Optional[str] = None
    document_id: Optional[str] = None
    limit: Optional[int] = 20


class SearchResultItem(BaseModel):
    source_type: str  # transcript_segment, meeting_summary, topic, decision, document_page
    source_id: str
    title: str
    content_text: str
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    project_id: Optional[str] = None
    speaker_label: Optional[str] = None
    timestamp: Optional[datetime] = None
    score: float
    search_mode: str

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    query: str
    mode: str
    total: int
    results: List[SearchResultItem] = []


class IndexingResponse(BaseModel):
    indexed_transcript_segments: int
    indexed_meeting_summaries: int
    indexed_topics: int
    indexed_decisions: int
    indexed_document_pages: int
    total_indexed: int
    status: str
