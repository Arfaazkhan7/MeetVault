from datetime import datetime, timezone, timedelta

def register_user(client, email="cmuser@example.com", name="CM User", password="Password123!"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()

def login_user(client, email="cmuser@example.com", password="Password123!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def setup_4_connected_meetings(client):
    """Set up a project with 4 connected meetings modeling the evolution sequence."""
    user = register_user(client)
    token = login_user(client)

    comp = client.post("/api/v1/companies", json={"name": "EvolutionCorp"}, headers=auth_headers(token)).json()
    cid = comp["public_id"]

    proj = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Compute Architecture Upgrade"}, headers=auth_headers(token)).json()
    pid = proj["public_id"]

    # Meeting 1: Proposal ("The team proposes AWS Lambda.")
    m1 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Meeting 1: Architecture Proposal", "project_id": pid}, headers=auth_headers(token)).json()

    # Meeting 2: Concern ("The team raises concerns about cold-start latency.")
    m2 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Meeting 2: Performance Evaluation", "project_id": pid}, headers=auth_headers(token)).json()

    # Meeting 3: Alternative ("The team proposes ECS as an alternative.")
    m3 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Meeting 3: Alternative Exploration", "project_id": pid}, headers=auth_headers(token)).json()

    # Meeting 4: Final Decision ("The team selects ECS.")
    m4 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Meeting 4: Architecture Finalization", "project_id": pid}, headers=auth_headers(token)).json()

    return token, cid, pid, m1["public_id"], m2["public_id"], m3["public_id"], m4["public_id"]


def test_4_meeting_decision_evolution_chain(client, setup_db):
    """Test decision evolution chain across 4 connected meetings: Proposal -> Concern -> Alternative -> Final Decision."""
    from tests.conftest import TestingSessionLocal
    from app.models.decision import Decision, DecisionHistory
    from app.models.evidence import Evidence
    from app.models.topic import Topic

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        # Create initial Decision record in Meeting 1
        decision = Decision(
            company_id=cid,
            meeting_id=m1_id,
            project_id=pid,
            title="Compute Platform Selection",
            description="Selecting backend compute platform for services",
            status="PROPOSED",
            original_proposal="The team proposes AWS Lambda.",
            proposer_id="Dev Lead",
            reason="Avoid cold-start latency while maintaining container portability.",
        )
        db.add(decision)
        db.flush()

        dec_id = str(decision.id)

        # Stage 1: Proposal in Meeting 1
        dh1 = DecisionHistory(
            decision_id=dec_id,
            meeting_id=m1_id,
            stage="PROPOSAL",
            previous_status=None,
            new_status="PROPOSED",
            notes="The team proposes AWS Lambda.",
            speaker_label="Dev Lead",
            timestamp=datetime.now(timezone.utc) - timedelta(days=4),
        )

        # Stage 2: Concern in Meeting 2
        dh2 = DecisionHistory(
            decision_id=dec_id,
            meeting_id=m2_id,
            stage="CONCERN",
            previous_status="PROPOSED",
            new_status="UNDER_REVIEW",
            notes="The team raises concerns about cold-start latency.",
            evidence_text="Cold-start latency spikes measured during spike test",
            speaker_label="QA Engineer",
            timestamp=datetime.now(timezone.utc) - timedelta(days=3),
        )

        # Stage 3: Alternative in Meeting 3
        dh3 = DecisionHistory(
            decision_id=dec_id,
            meeting_id=m3_id,
            stage="ALTERNATIVE",
            previous_status="UNDER_REVIEW",
            new_status="ALTERNATIVE_PROPOSED",
            notes="The team proposes ECS as an alternative.",
            evidence_text="ECS containers avoid cold start overhead",
            speaker_label="Architect",
            timestamp=datetime.now(timezone.utc) - timedelta(days=2),
        )

        # Stage 4: Final Decision in Meeting 4
        dh4 = DecisionHistory(
            decision_id=dec_id,
            meeting_id=m4_id,
            stage="FINAL_DECISION",
            previous_status="ALTERNATIVE_PROPOSED",
            new_status="AGREED",
            notes="The team selects ECS.",
            reason="Avoid cold-start latency while maintaining container portability.",
            speaker_label="Engineering Director",
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
        )

        db.add_all([dh1, dh2, dh3, dh4])

        # Link Topic "Compute Platform" across all 4 meetings
        t = Topic(company_id=cid, meeting_id=m1_id, name="Compute Platform", importance="high")
        db.add(t)

        db.commit()
    finally:
        db.close()

    # Query GET /api/v1/projects/{pid}/decisions/{dec_id}/history
    r = client.get(f"/api/v1/projects/{pid}/decisions/{dec_id}/history", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    hist = r.json()

    assert hist["decision_id"] == dec_id
    assert hist["project_id"] == pid
    assert hist["original_proposal"] == "The team proposes AWS Lambda."
    assert "The team raises concerns about cold-start latency." in hist["concerns"][0]
    assert "The team proposes ECS as an alternative." in hist["alternatives"][0]
    assert "ECS" in hist["final_decision"]
    assert hist["reason"] == "Avoid cold-start latency while maintaining container portability."
    assert len(hist["source_meetings"]) == 4

    # Verify chronological evolution nodes (4 stages)
    nodes = hist["evolution_nodes"]
    assert len(nodes) >= 4
    stages = [n["stage"] for n in nodes]
    assert "PROPOSAL" in stages
    assert "CONCERN" in stages
    assert "ALTERNATIVE" in stages
    assert "FINAL_DECISION" in stages


def test_missing_reason_explicit_message(client, setup_db):
    """Test that if no reason is found in available evidence, system explicitly indicates REASON_NOT_FOUND."""
    from tests.conftest import TestingSessionLocal
    from app.models.decision import Decision, DecisionHistory
    from app.services.cross_meeting_service import REASON_NOT_FOUND

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        # Create Decision with NO reason recorded
        decision = Decision(
            company_id=cid,
            meeting_id=m1_id,
            project_id=pid,
            title="Database Migration Choice",
            description="Choice without explicit reason in transcript",
            status="AGREED",
            original_proposal="Migrate to Redis",
            reason=None,  # No reason provided
        )
        db.add(decision)
        db.flush()

        dec_id = str(decision.id)

        dh1 = DecisionHistory(
            decision_id=dec_id, meeting_id=m1_id, stage="PROPOSAL",
            new_status="PROPOSED", notes="Migrate to Redis", reason=None
        )
        dh2 = DecisionHistory(
            decision_id=dec_id, meeting_id=m4_id, stage="FINAL_DECISION",
            new_status="AGREED", notes="Selected Postgres instead", reason=None
        )
        db.add_all([dh1, dh2])
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/v1/projects/{pid}/decisions/{dec_id}/history", headers=auth_headers(token))
    assert r.status_code == 200
    hist = r.json()

    # Explicit requirement: Must explicitly indicate reason was not found in meeting evidence
    assert hist["reason"] == REASON_NOT_FOUND
    assert hist["reason"] == "Reason not found in available meeting evidence."


def test_topic_evolution_history(client, setup_db):
    """Test topic evolution tracking across 4 connected meetings."""
    from tests.conftest import TestingSessionLocal
    from app.models.topic import Topic
    from app.models.evidence import Evidence

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        t = Topic(company_id=cid, meeting_id=m1_id, name="Cloud Architecture", importance="high")
        db.add(t)
        db.flush()

        # Add Evidence across 4 meetings
        e1 = Evidence(meeting_id=m1_id, topic_id=str(t.id), speaker_label="Alice", content="Cloud Architecture introduced: Lambda serverless", evidence_type="topic")
        e2 = Evidence(meeting_id=m2_id, topic_id=str(t.id), speaker_label="Bob", content="Cold-start latency discussion for Cloud Architecture", evidence_type="topic")
        e3 = Evidence(meeting_id=m3_id, topic_id=str(t.id), speaker_label="Charlie", content="ECS container alternative for Cloud Architecture", evidence_type="topic")
        e4 = Evidence(meeting_id=m4_id, topic_id=str(t.id), speaker_label="Dave", content="ECS selected for Cloud Architecture", evidence_type="topic")
        db.add_all([e1, e2, e3, e4])
        db.commit()

        top_id = str(t.id)
    finally:
        db.close()

    r = client.get(f"/api/v1/projects/{pid}/topics/{top_id}/history", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    topic_hist = r.json()

    assert topic_hist["topic_name"] == "Cloud Architecture"
    assert len(topic_hist["meetings_involved"]) == 4
    speakers = topic_hist["speakers"]
    assert "Alice" in speakers and "Bob" in speakers and "Charlie" in speakers and "Dave" in speakers
    assert len(topic_hist["evolution_steps"]) == 4


def test_cross_meeting_timeline(client, setup_db):
    """Test cross-meeting timeline with chronological evidence preservation across 4 meetings."""
    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    r = client.get(f"/api/v1/projects/{pid}/timeline", headers=auth_headers(token))
    assert r.status_code == 200
    res = r.json()

    assert res["project_id"] == pid
    assert res["total_events"] >= 4
    timeline = res["timeline"]
    m_titles = [item["meeting_title"] for item in timeline if item["event_type"] == "MEETING"]
    assert len(m_titles) == 4
