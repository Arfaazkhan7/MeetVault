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


def test_cross_meeting_query_which_meetings_discussed_project(client, setup_db):
    """Test answering: 'Which meetings discussed Project X?' spanning multiple authorized meetings."""
    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    r = client.post(
        "/api/v1/cross-meeting/query",
        json={"question": "Which meetings discussed Project Compute Architecture Upgrade?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is False
    assert res["confidence"] > 0.8
    assert len(res["meetings_involved"]) == 4

    meet_ids = {m["meeting_id"] for m in res["meetings_involved"]}
    assert meet_ids == {m1_id, m2_id, m3_id, m4_id}
    assert "Compute Architecture Upgrade" in res["synthesis"]


def test_cross_meeting_query_decision_evolution_and_conflict(client, setup_db):
    """Test answering: 'What did we decide about Project X, and how did the decision change?' with conflict detection."""
    from tests.conftest import TestingSessionLocal
    from app.models.decision import Decision, DecisionHistory

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        # Decision proposed in M1, concerns in M2, alternative in M3, agreed in M4, reopened in M4 history
        decision = Decision(
            company_id=cid,
            meeting_id=m1_id,
            project_id=pid,
            title="Compute Platform Selection",
            description="Selecting backend compute platform",
            status="UNDER_REVIEW",
            original_proposal="The team proposes AWS Lambda.",
            proposer_id="Dev Lead",
            reason="Cold-start latency concerns prompted reconsideration.",
        )
        db.add(decision)
        db.flush()
        dec_id = str(decision.id)

        # Stage 1: Proposal
        dh1 = DecisionHistory(
            decision_id=dec_id, meeting_id=m1_id, stage="PROPOSAL",
            new_status="PROPOSED", notes="The team proposes AWS Lambda.",
            speaker_label="Dev Lead", timestamp=datetime.now(timezone.utc) - timedelta(days=4)
        )
        # Stage 2: Concern
        dh2 = DecisionHistory(
            decision_id=dec_id, meeting_id=m2_id, stage="CONCERN",
            previous_status="PROPOSED", new_status="UNDER_REVIEW",
            notes="Cold-start latency issues identified.",
            speaker_label="QA Engineer", timestamp=datetime.now(timezone.utc) - timedelta(days=3)
        )
        # Stage 3: Alternative
        dh3 = DecisionHistory(
            decision_id=dec_id, meeting_id=m3_id, stage="ALTERNATIVE",
            previous_status="UNDER_REVIEW", new_status="ALTERNATIVE_PROPOSED",
            notes="ECS containers proposed as alternative.",
            speaker_label="Architect", timestamp=datetime.now(timezone.utc) - timedelta(days=2)
        )
        # Stage 4: Agreed in Meeting 4
        dh4 = DecisionHistory(
            decision_id=dec_id, meeting_id=m4_id, stage="FINAL_DECISION",
            previous_status="ALTERNATIVE_PROPOSED", new_status="AGREED",
            notes="The team agrees on ECS.",
            speaker_label="Engineering Director", timestamp=datetime.now(timezone.utc) - timedelta(days=1)
        )
        # Stage 5: Conflict / Reopened due to new constraints
        dh5 = DecisionHistory(
            decision_id=dec_id, meeting_id=m4_id, stage="CONFLICT",
            previous_status="AGREED", new_status="UNDER_REVIEW",
            notes="Security policy mandates Fargate instead of standard ECS instances.",
            speaker_label="SecOps", timestamp=datetime.now(timezone.utc)
        )
        db.add_all([dh1, dh2, dh3, dh4, dh5])
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/v1/cross-meeting/query",
        json={"question": "What did we decide about Compute Architecture Upgrade, and how did the decision change?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is False
    assert len(res["decisions"]) >= 1
    d_summary = res["decisions"][0]

    assert d_summary["title"] == "Compute Platform Selection"
    assert d_summary["is_conflicted"] is True
    assert "previously AGREED" in d_summary["conflict_notes"]
    assert len(d_summary["stages"]) >= 5

    stages = [s["stage"] for s in d_summary["stages"]]
    assert "PROPOSAL" in stages
    assert "CONCERN" in stages
    assert "ALTERNATIVE" in stages
    assert "FINAL_DECISION" in stages


def test_cross_meeting_query_tasks_and_deadlines_for_person(client, setup_db):
    """Test answering: 'What tasks were assigned to Gokul, and what deadlines were discussed?'"""
    from tests.conftest import TestingSessionLocal
    from app.models.task import Task
    from app.models.user import User
    from app.models.company import CompanyMember

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        # Create user Gokul Krishnan and add to company
        gokul = User(
            public_id="usr_gokul_123",
            email="gokul@example.com",
            full_name="Gokul Krishnan",
            hashed_password="hashed_pw",
        )
        db.add(gokul)
        db.flush()

        member = CompanyMember(company_id=cid, user_id=gokul.public_id, role="MEMBER")
        db.add(member)

        deadline_1 = datetime.now(timezone.utc) + timedelta(days=5)
        deadline_2 = datetime.now(timezone.utc) + timedelta(days=12)

        # Task 1 in Meeting 1
        t1 = Task(
            company_id=cid,
            meeting_id=m1_id,
            project_id=pid,
            assignee_id=gokul.public_id,
            title="Benchmark Lambda cold start latencies",
            description="Run 1000 concurrent requests against staging Lambda",
            status="open",
            priority="high",
            due_date=deadline_1,
            deadline=deadline_1,
        )
        # Task 2 in Meeting 3
        t2 = Task(
            company_id=cid,
            meeting_id=m3_id,
            project_id=pid,
            assignee_id=gokul.public_id,
            title="Draft ECS container deployment manifest",
            description="Prepare Terraform configuration for ECS task definition",
            status="in_progress",
            priority="medium",
            due_date=deadline_2,
            deadline=deadline_2,
        )
        db.add_all([t1, t2])
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/v1/cross-meeting/query",
        json={"question": "What tasks were assigned to Gokul, and what deadlines were discussed?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is False
    assert len(res["tasks"]) == 2

    task_titles = [t["title"] for t in res["tasks"]]
    assert "Benchmark Lambda cold start latencies" in task_titles
    assert "Draft ECS container deployment manifest" in task_titles

    for t in res["tasks"]:
        assert t["assignee_name"] == "Gokul Krishnan"
        assert t["deadline"] is not None
        assert t["meeting_title"] is not None

    # Unresolved issues should list these open/in_progress tasks
    assert len(res["unresolved_issues"]) >= 2
    assert any("Benchmark Lambda" in ui for ui in res["unresolved_issues"])


def test_cross_meeting_query_speaker_attribution_with_timestamps(client, setup_db):
    """Test answering: 'What did Gokul say, and in which meeting and at what time?' with verified diarization."""
    from tests.conftest import TestingSessionLocal
    from app.models.transcript import TranscriptSegment
    from app.models.user import User

    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    db = TestingSessionLocal()
    try:
        # Find or create Gokul user
        gokul = db.query(User).filter(User.email == "gokul@example.com").first()
        if not gokul:
            gokul = User(
                public_id="usr_gokul_spk",
                email="gokul@example.com",
                full_name="Gokul Krishnan",
                hashed_password="pw",
            )
            db.add(gokul)
            db.flush()

        seg1 = TranscriptSegment(
            meeting_id=m1_id,
            segment_id="seg_gk_001",
            speaker_label="Gokul",
            user_id=gokul.public_id,
            speaker_confirmed=True,
            start_time=125.0,  # 02:05
            end_time=155.0,    # 02:35
            text="I will run the ECS performance benchmarks against the staging cluster tomorrow.",
            language="en",
        )
        seg2 = TranscriptSegment(
            meeting_id=m3_id,
            segment_id="seg_gk_002",
            speaker_label="Gokul",
            user_id=gokul.public_id,
            speaker_confirmed=True,
            start_time=360.0,  # 06:00
            end_time=395.0,    # 06:35
            text="The ECS cluster response time averaged 42 milliseconds with zero cold starts.",
            language="en",
        )
        db.add_all([seg1, seg2])
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/v1/cross-meeting/query",
        json={"question": "What did Gokul say, and in which meeting and at what time?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is False
    assert len(res["statements"]) >= 2

    s1 = next(s for s in res["statements"] if "benchmarks against the staging cluster" in s["text"])
    assert s1["speaker_name"] == "Gokul Krishnan"
    assert s1["is_verified_user"] is True
    assert s1["meeting_id"] == m1_id
    assert s1["timestamp_range"] == "02:05 - 02:35"
    assert s1["start_time"] == 125.0
    assert s1["end_time"] == 155.0

    s2 = next(s for s in res["statements"] if "42 milliseconds" in s["text"])
    assert s2["timestamp_range"] == "06:00 - 06:35"
    assert s2["meeting_id"] == m3_id


def test_cross_meeting_unauthorized_scope_forbidden(client, setup_db):
    """Test security: User cannot query unauthorized meetings (enforced pre-retrieval)."""
    # Setup meetings under User A
    token_a, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    # Setup User B (unauthorized third-party)
    user_b = register_user(client, email="mallory@evil.com", name="Mallory")
    token_b = login_user(client, email="mallory@evil.com")

    # Mallory attempts to query User A's meeting
    r = client.post(
        "/api/v1/cross-meeting/query",
        json={
            "question": "What did they decide about compute architecture?",
            "meeting_ids": [m1_id],
        },
        headers=auth_headers(token_b),
    )
    assert r.status_code == 403, r.text
    assert "not authorized" in r.json()["detail"].lower()


def test_cross_meeting_insufficient_evidence_no_hallucination(client, setup_db):
    """Test abstention: Unknown information is not fabricated and returns insufficient_evidence."""
    token, cid, pid, m1_id, m2_id, m3_id, m4_id = setup_4_connected_meetings(client)

    r = client.post(
        "/api/v1/cross-meeting/query",
        json={"question": "What were the results of the Quantum Warp Engine experiment?"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text
    res = r.json()

    assert res["insufficient_evidence"] is True
    assert res["confidence"] == 0.0
    assert len(res["decisions"]) == 0
    assert len(res["tasks"]) == 0
    assert len(res["statements"]) == 0
    assert "not find enough evidence" in res["synthesis"].lower() or "no authorized" in res["synthesis"].lower()

