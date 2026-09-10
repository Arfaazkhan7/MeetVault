"""
RetrievalService for MeetVault.
Coordinates SearchService execution, enforces multi-tenant access control,
and formats search results into structured evidence context for verification and downstream RAG operations.
"""

from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.meeting import Meeting
from app.models.project import Project
from app.schemas.search import SearchFilterRequest, SearchResultItem, SearchResponse, SearchModeEnum
from app.services.search_service import SearchService


class RetrievalService:
    """Service retrieving structured evidence with access control and detailed metadata citations."""

    @classmethod
    def retrieve_evidence(
        cls,
        db: Session,
        company_id: str,
        filters: SearchFilterRequest,
    ) -> SearchResponse:
        """
        Execute search across embeddings and return formatted evidence with meeting and project context.
        Enforces tenant level security (company_id).
        """
        # Build meeting cache map for efficient metadata lookups
        meetings = db.query(Meeting).filter(Meeting.company_id == company_id).all()
        meeting_map = {str(m.id): m for m in meetings}
        for m in meetings:
            if m.public_id:
                meeting_map[m.public_id] = m

        # Build project cache map if project context is needed
        projects = db.query(Project).filter(Project.company_id == company_id).all()
        project_map = {str(p.id): p for p in projects}
        for p in projects:
            if p.public_id:
                project_map[p.public_id] = p

        # Select search mode
        mode = filters.mode or SearchModeEnum.HYBRID
        if mode == SearchModeEnum.KEYWORD:
            results = SearchService.keyword_search(db, company_id, filters, meeting_map)
        elif mode == SearchModeEnum.SEMANTIC:
            results = SearchService.semantic_search(db, company_id, filters, meeting_map)
        else:
            # Default to HYBRID search
            results = SearchService.hybrid_search(db, company_id, filters, meeting_map)

        # Enrich results with project title if missing or available
        for res in results:
            if res.project_id and str(res.project_id) in project_map:
                proj = project_map[str(res.project_id)]
                if not res.title.startswith("["):
                    res.title = f"[{proj.name}] {res.title}"

        mode_str = mode.value if isinstance(mode, SearchModeEnum) else str(mode)

        return SearchResponse(
            query=filters.query,
            mode=mode_str,
            total=len(results),
            results=results,
        )
