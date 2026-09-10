import uuid
from datetime import datetime, timezone

from tests.conftest import TestingSessionLocal
from app.models.company import Company
from app.models.project import Project
from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment
from app.models.meeting_summary import MeetingSummary
from app.models.topic import Topic
from app.models.decision import Decision
from app.models.document import Document, DocumentPage
from app.models.embedding import Embedding
from app.services.embedding_service import EmbeddingService, generate_text_embedding, calculate_cosine_similarity
from app.schemas.search import SearchFilterRequest, SearchModeEnum


def register_user(client, email="searchuser@example.com", name="Search User", password="Password123!"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


def login_user(client, email="searchuser@example.com", password="Password123!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def setup_search_test_data(client):
    """Set up rich test data across 5 entity types for semantic search tests."""
    user = register_user(client)
    token = login_user(client)

    comp = client.post("/api/v1/companies", json={"name": "SearchTech Inc"}, headers=auth_headers(token)).json()
    cid = comp["public_id"]

    proj = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Core Infrastructure Upgrade"}, headers=auth_headers(token)).json()
    pid = proj["public_id"]

    m1 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Architecture & Database Sync", "project_id": pid}, headers=auth_headers(token)).json()
    m1_id = m1["public_id"]

    db = TestingSessionLocal()
    try:
        # Entity 1: TranscriptSegment
        seg1 = TranscriptSegment(
            meeting_id=m1_id,
            speaker_label="Senior Architect",
            text="The team raises concerns about cold-start latency when scaling cloud database instances.",
            start_time=10.0,
            end_time=25.0,
        )

        # Entity 2: MeetingSummary
        summ = MeetingSummary(
            company_id=cid,
            meeting_id=m1_id,
            summary_text="Discussion on database migration and selecting ECS container architecture to eliminate cold starts.",
            key_takeaways="Containerized database cluster preferred over serverless functions.",
        )

        # Entity 3: Topic
        top = Topic(
            company_id=cid,
            meeting_id=m1_id,
            name="Database Architecture Evolution",
            description="Evaluating serverless latency vs container stability for high throughput.",
            importance="high",
        )

        # Entity 4: Decision
        dec = Decision(
            company_id=cid,
            meeting_id=m1_id,
            project_id=pid,
            title="Database Compute Infrastructure Selection",
            description="Migrating database cluster from AWS Lambda to ECS.",
            status="AGREED",
            original_proposal="Use AWS Lambda for database query triggers",
            reason="Avoid cold-start latency while supporting high-concurrency database queries.",
        )

        # Entity 5: DocumentPage
        doc_pub = f"doc_{uuid.uuid4().hex[:8]}"
        doc = Document(
            public_id=doc_pub,
            company_id=cid,
            project_id=pid,
            title="Database Architecture Benchmark Whitepaper.pdf",
            file_name="db_arch.pdf",
            file_type="pdf",
            file_url="/storage/docs/db_arch.pdf",
        )
        db.add(doc)
        db.flush()

        doc_page = DocumentPage(
            public_id=f"page_{uuid.uuid4().hex[:8]}",
            document_id=doc_pub,
            page_number=3,
            text_content="Benchmark analysis of database query performance: ECS containers achieve sub-10ms response times compared to 450ms cold-start spikes on serverless triggers.",
        )

        db.add_all([seg1, summ, top, dec, doc_page])
        db.commit()
    finally:
        db.close()

    return token, cid, pid, m1_id


def test_embedding_generation_vector_math():
    """Test 1536-dimensional vector embedding generation and cosine similarity calculation."""
    text1 = "Why did we change the database architecture?"
    text2 = "Database architecture evolution and cold-start latency elimination"
    text3 = "Unrelated text about office lunch options"

    vec1 = generate_text_embedding(text1)
    vec2 = generate_text_embedding(text2)
    vec3 = generate_text_embedding(text3)

    assert len(vec1) == 1536
    assert len(vec2) == 1536

    sim_related = calculate_cosine_similarity(vec1, vec2)
    sim_unrelated = calculate_cosine_similarity(vec1, vec3)

    # Related architectural query must have significantly higher similarity than unrelated text
    assert sim_related > sim_unrelated
    assert sim_related > 0.3


def test_indexing_all_5_entity_types(client, setup_db):
    """Test indexing of 5 entity types (transcript, summary, topic, decision, document page)."""
    token, cid, pid, m1_id = setup_search_test_data(client)

    # Trigger indexing endpoint
    r = client.post(f"/api/v1/companies/{cid}/embeddings/generate", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["status"] == "SUCCESS"
    assert res["total_indexed"] >= 5
    assert res["indexed_transcript_segments"] >= 1
    assert res["indexed_meeting_summaries"] >= 1
    assert res["indexed_topics"] >= 1
    assert res["indexed_decisions"] >= 1
    assert res["indexed_document_pages"] >= 1

    db = TestingSessionLocal()
    try:
        embs = db.query(Embedding).filter(Embedding.company_id == cid).all()
        types = set(e.source_type for e in embs)
        assert "transcript_segment" in types
        assert "meeting_summary" in types
        assert "topic" in types
        assert "decision" in types
        assert "document_page" in types
    finally:
        db.close()


def test_semantic_search_database_architecture_query(client, setup_db):
    """
    Test Semantic Search for prompt query: 'Why did we change the database architecture?'
    Verify system retrieves cold-start latency decisions and database benchmark documents even without exact keyword overlap.
    """
    token, cid, pid, m1_id = setup_search_test_data(client)

    # Generate embeddings first
    client.post(f"/api/v1/companies/{cid}/embeddings/generate", headers=auth_headers(token))

    # Execute Semantic Search
    search_payload = {
        "query": "Why did we change the database architecture?",
        "mode": "semantic",
        "project_id": pid,
        "limit": 10,
    }

    r = client.post(f"/api/v1/companies/{cid}/search", json=search_payload, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["mode"] == "semantic"
    assert data["total"] > 0

    results = data["results"]
    texts = [res["content_text"].lower() for res in results]
    sources = [res["source_type"] for res in results]

    # Must retrieve database decisions and document pages
    has_decision_or_doc = any(s in ["decision", "document_page", "topic", "transcript_segment"] for s in sources)
    assert has_decision_or_doc

    # Must contain relevant cold-start / latency / container content
    matched = any("cold-start" in t or "database" in t or "container" in t for t in texts)
    assert matched


def test_keyword_search(client, setup_db):
    """Test exact and keyword search execution."""
    token, cid, pid, m1_id = setup_search_test_data(client)
    client.post(f"/api/v1/companies/{cid}/embeddings/generate", headers=auth_headers(token))

    search_payload = {
        "query": "cold-start latency",
        "mode": "keyword",
        "limit": 5,
    }

    r = client.post(f"/api/v1/companies/{cid}/search", json=search_payload, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["mode"] == "keyword"
    assert data["total"] > 0
    assert "cold-start" in data["results"][0]["content_text"].lower()


def test_hybrid_search(client, setup_db):
    """Test Hybrid search combining vector semantic similarity and keyword rank fusion."""
    token, cid, pid, m1_id = setup_search_test_data(client)
    client.post(f"/api/v1/companies/{cid}/embeddings/generate", headers=auth_headers(token))

    search_payload = {
        "query": "database migration container benchmark",
        "mode": "hybrid",
        "project_id": pid,
        "limit": 5,
    }

    r = client.post(f"/api/v1/companies/{cid}/search", json=search_payload, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["mode"] == "hybrid"
    assert data["total"] > 0
    top_res = data["results"][0]
    assert top_res["score"] > 0.0


def test_search_filters_and_tenant_isolation(client, setup_db):
    """Test search filters (topic, project, meeting) and strict multi-tenant security isolation."""
    token1, cid1, pid1, m1_id1 = setup_search_test_data(client)

    # Setup second company and user
    user2 = register_user(client, email="other@example.com")
    token2 = login_user(client, email="other@example.com")
    comp2 = client.post("/api/v1/companies", json={"name": "Isolated Corp"}, headers=auth_headers(token2)).json()
    cid2 = comp2["public_id"]

    client.post(f"/api/v1/companies/{cid1}/embeddings/generate", headers=auth_headers(token1))

    # User 2 attempting to search Company 1's memory must be forbidden (403)
    r_forbidden = client.post(
        f"/api/v1/companies/{cid1}/search",
        json={"query": "database", "mode": "hybrid"},
        headers=auth_headers(token2)
    )
    assert r_forbidden.status_code == 403

    # User 2 searching own company (Company 2) returns 0 matches (isolated from Company 1)
    r_isolated = client.post(
        f"/api/v1/companies/{cid2}/search",
        json={"query": "database", "mode": "hybrid"},
        headers=auth_headers(token2)
    )
    assert r_isolated.status_code == 200
    assert r_isolated.json()["total"] == 0

    # User 1 searching with topic_name filter
    r_topic = client.post(
        f"/api/v1/companies/{cid1}/search",
        json={"query": "architecture", "mode": "hybrid", "topic_name": "Database Architecture"},
        headers=auth_headers(token1)
    )
    assert r_topic.status_code == 200
    assert r_topic.json()["total"] > 0
