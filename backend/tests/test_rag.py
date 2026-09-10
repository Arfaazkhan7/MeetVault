"""
Phase 15 Tests: ASK MEETING MEMORY (RAG)

Tests natural language question-answering over meeting history,
grounded evidence verification, insufficient evidence fallback,
RAG evaluation metrics, and tenant security scoping.
"""
import uuid
from datetime import datetime, timezone

from tests.conftest import TestingSessionLocal
from app.models.company import Company
from app.models.project import Project
from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment
from app.models.meeting_summary import MeetingSummary
from app.models.decision import Decision
from app.models.embedding import Embedding
from app.services.embedding_service import EmbeddingService, generate_text_embedding


def register_user(client, email="raguser@example.com", name="RAG User", password="Password123!"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


def login_user(client, email="raguser@example.com", password="Password123!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def setup_rag_test_data(client):
    """Set up rich multi-meeting test data with embeddings for RAG tests."""
    user = register_user(client)
    token = login_user(client)

    comp = client.post("/api/v1/companies", json={"name": "MemoryTech Inc"}, headers=auth_headers(token)).json()
    cid = comp["public_id"]

    proj = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Cloud Infrastructure Migration"}, headers=auth_headers(token)).json()
    pid = proj["public_id"]

    m1 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Cloud Architecture Proposals", "project_id": pid}, headers=auth_headers(token)).json()
    m1_id = m1["public_id"]

    m2 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Database Latency & Performance Review", "project_id": pid}, headers=auth_headers(token)).json()
    m2_id = m2["public_id"]

    db = TestingSessionLocal()
    try:
        # Meeting 1: AWS Lambda proposal
        t1 = TranscriptSegment(
            meeting_id=m1_id,
            speaker_label="Alice (Principal Engineer)",
            text="The team proposes AWS Lambda for serverless deployment to reduce infrastructure costs.",
            start_time=15.0,
            end_time=30.0,
        )
        db.add(t1)
        db.flush()
        EmbeddingService.create_or_update_embedding(
            db, company_id=cid, source_type="transcript_segment", source_id=str(t1.id),
            content_text=t1.text, project_id=pid, meeting_id=m1_id, speaker_label=t1.speaker_label
        )

        # Meeting 2: Cold start concern & ECS proposal
        t2 = TranscriptSegment(
            meeting_id=m2_id,
            speaker_label="Bob (DevOps Lead)",
            text="The team raises concerns about cold-start latency with AWS Lambda under high load.",
            start_time=45.0,
            end_time=60.0,
        )
        t3 = TranscriptSegment(
            meeting_id=m2_id,
            speaker_label="Charlie (Tech Lead)",
            text="The team proposes ECS container clusters as an alternative to mitigate cold-start issues.",
            start_time=75.0,
            end_time=90.0,
        )
        db.add_all([t2, t3])
        db.flush()
        EmbeddingService.create_or_update_embedding(
            db, company_id=cid, source_type="transcript_segment", source_id=str(t2.id),
            content_text=t2.text, project_id=pid, meeting_id=m2_id, speaker_label=t2.speaker_label
        )
        EmbeddingService.create_or_update_embedding(
            db, company_id=cid, source_type="transcript_segment", source_id=str(t3.id),
            content_text=t3.text, project_id=pid, meeting_id=m2_id, speaker_label=t3.speaker_label
        )

        # Decision
        d1 = Decision(
            company_id=cid,
            project_id=pid,
            meeting_id=m2_id,
            title="Deployment Platform Selection",
            description="The team selects ECS as the primary deployment platform for low latency requirements.",
            status="approved",
        )
        db.add(d1)
        db.flush()
        EmbeddingService.create_or_update_embedding(
            db, company_id=cid, source_type="decision", source_id=str(d1.id),
            content_text=d1.description, project_id=pid, meeting_id=m2_id
        )

        db.commit()
    finally:
        db.close()

    return {"cid": cid, "pid": pid, "token": token, "m1_id": m1_id, "m2_id": m2_id}


def test_ask_company_level_rag(client):
    """Test natural language question answering at company level with evidence citations."""
    data = setup_rag_test_data(client)
    cid, token = data["cid"], data["token"]

    r = client.post(
        f"/api/v1/companies/{cid}/ask",
        json={"question": "What did the team propose for infrastructure deployment?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert "answer" in res
    assert res["question"] == "What did the team propose for infrastructure deployment?"
    assert not res["insufficient_evidence"]
    assert len(res["evidence"]) > 0

    # Verify evidence structure
    ev = res["evidence"][0]
    assert "source_type" in ev
    assert "excerpt" in ev
    assert "meeting_id" in ev
    assert "score" in ev

    # Verify evaluation metrics
    eval_metrics = res["rag_eval"]
    assert "avg_evidence_score" in eval_metrics
    assert "evidence_coverage_meetings" in eval_metrics
    assert "faithfulness_score" in eval_metrics


def test_ask_project_scoped_rag(client):
    """Test project-scoped natural language QA."""
    data = setup_rag_test_data(client)
    pid, token = data["pid"], data["token"]

    r = client.post(
        f"/api/v1/projects/{pid}/ask",
        json={"question": "Why did we decide to use ECS instead of AWS Lambda?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert "answer" in res
    assert not res["insufficient_evidence"]
    assert len(res["evidence"]) >= 1


def test_ask_insufficient_evidence_fallback(client):
    """Test that asking questions about unmentioned topics returns insufficient evidence fallback."""
    data = setup_rag_test_data(client)
    cid, token = data["cid"], data["token"]

    r = client.post(
        f"/api/v1/companies/{cid}/ask",
        json={"question": "What is our company budget for quantum teleportation research?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is True
    assert "could not find enough evidence" in res["answer"].lower()
    assert len(res["evidence"]) == 0


def test_rag_tenant_isolation(client):
    """Verify that a user from Company B cannot retrieve evidence from Company A."""
    data_a = setup_rag_test_data(client)
    cid_a = data_a["cid"]

    # Register user in Company B
    register_user(client, email="userb@example.com", name="User B")
    token_b = login_user(client, email="userb@example.com")
    comp_b = client.post("/api/v1/companies", json={"name": "Company B"}, headers=auth_headers(token_b)).json()
    cid_b = comp_b["public_id"]

    # Try asking Company A's endpoint with User B's token (should be 403 Forbidden)
    r = client.post(
        f"/api/v1/companies/{cid_a}/ask",
        json={"question": "What did the team propose?"},
        headers=auth_headers(token_b),
    )
    assert r.status_code == 403, r.text

    # Ask Company B's endpoint with User B's token (should return insufficient evidence as Company B has no meetings)
    r2 = client.post(
        f"/api/v1/companies/{cid_b}/ask",
        json={"question": "What did the team propose?"},
        headers=auth_headers(token_b),
    )
    assert r2.status_code == 200, r2.text
    res2 = r2.json()
    assert res2["insufficient_evidence"] is True
    assert len(res2["evidence"]) == 0
