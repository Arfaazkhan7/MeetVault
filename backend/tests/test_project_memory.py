import io
from datetime import datetime, timezone, timedelta
import pypdf

def register_user(client, email="pmuser@example.com", name="PM User", password="Password123!"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()

def login_user(client, email="pmuser@example.com", password="Password123!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

def create_sample_pdf_bytes() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def setup_project_memory_scenario(client):
    user = register_user(client)
    token = login_user(client)
    comp = client.post("/api/v1/companies", json={"name": "MemoryCorp"}, headers=auth_headers(token)).json()
    cid = comp["public_id"]

    # Create Project A
    proj_a = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Project Alpha"}, headers=auth_headers(token)).json()
    pid_a = proj_a["public_id"]

    # Create Project B (for isolation test)
    proj_b = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Project Beta"}, headers=auth_headers(token)).json()
    pid_b = proj_b["public_id"]

    # Create 2 meetings for Project A
    m1 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Sprint 1 Planning", "project_id": pid_a}, headers=auth_headers(token)).json()
    m2 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Architecture Sync", "project_id": pid_a}, headers=auth_headers(token)).json()

    # Create 1 meeting for Project B
    m3 = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "Beta Intro", "project_id": pid_b}, headers=auth_headers(token)).json()

    mid_1, mid_2, mid_3 = m1["public_id"], m2["public_id"], m3["public_id"]

    return token, cid, pid_a, pid_b, mid_1, mid_2, mid_3


def test_project_memory_dashboard_aggregation(client, setup_db):
    from tests.conftest import TestingSessionLocal
    from app.models.meeting_summary import MeetingSummary
    from app.models.decision import Decision
    from app.models.task import Task
    from app.models.topic import Topic, MeetingTopic

    token, cid, pid_a, pid_b, mid_1, mid_2, mid_3 = setup_project_memory_scenario(client)

    db = TestingSessionLocal()
    try:
        # Seed Summaries
        s1 = MeetingSummary(
            meeting_id=mid_1, company_id=cid,
            summary_text="Discussed Sprint 1 roadmap and user stories.",
            key_takeaways='["Finalized backlog", "Assigned initial tasks"]'
        )
        s2 = MeetingSummary(
            meeting_id=mid_2, company_id=cid,
            summary_text="Agreed on microservices structure.",
            key_takeaways='["Adopted FastAPI", "PostgreSQL database"]'
        )
        db.add_all([s1, s2])

        # Seed Decisions
        d1 = Decision(
            company_id=cid, meeting_id=mid_1,
            title="Use 2-week sprint cycles", description="Sprint duration standard",
            status="AGREED", decision_type="agreement"
        )
        d2 = Decision(
            company_id=cid, meeting_id=mid_2,
            title="Database choice: PostgreSQL", description="Use PG 15 for production",
            status="AGREED", decision_type="agreement"
        )
        db.add_all([d1, d2])

        # Seed Tasks
        now = datetime.now(timezone.utc)
        t1 = Task(
            company_id=cid, meeting_id=mid_1,
            title="Setup CI/CD pipeline", status="open",
            priority="high", due_date=now + timedelta(days=3)
        )
        t2 = Task(
            company_id=cid, meeting_id=mid_2,
            title="Design database schemas", status="in_progress",
            priority="high", due_date=now + timedelta(days=1)
        )
        db.add_all([t1, t2])

        # Seed Topics (recurring topic: "Architecture")
        top1 = Topic(company_id=cid, meeting_id=mid_1, name="Architecture", importance="high")
        top2 = Topic(company_id=cid, meeting_id=mid_2, name="Architecture", importance="high")
        top3 = Topic(company_id=cid, meeting_id=mid_1, name="Sprint Planning", importance="medium")
        db.add_all([top1, top2, top3])

        db.commit()
    finally:
        db.close()

    # Upload document for Project A
    pdf_bytes = create_sample_pdf_bytes()
    client.post(
        f"/api/v1/companies/{cid}/documents/upload",
        files={"file": ("architecture_spec.pdf", pdf_bytes, "application/pdf")},
        data={"title": "System Architecture Spec", "project_id": pid_a, "meeting_id": mid_2},
        headers=auth_headers(token)
    )

    # 1. Test full dashboard endpoint GET /api/v1/projects/{pid_a}/memory
    r = client.get(f"/api/v1/projects/{pid_a}/memory", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    dashboard = r.json()

    assert dashboard["project_id"] == pid_a
    assert dashboard["source_meetings_count"] == 2
    assert "aggregated from 2 meeting(s)" in dashboard["memory_source_notice"]

    # Verify summary metrics
    summary = dashboard["summary"]
    assert summary["total_meetings"] == 2
    assert summary["total_summaries"] == 2
    assert summary["total_decisions"] == 2
    assert summary["open_tasks_count"] == 2
    assert summary["total_documents"] == 1

    # Verify discussions
    discussions = dashboard["recent_discussions"]
    assert len(discussions) == 2
    titles = [d["meeting_title"] for d in discussions]
    assert "Sprint 1 Planning" in titles
    assert "Architecture Sync" in titles

    # Verify decisions
    decisions_list = dashboard["important_decisions"]
    assert len(decisions_list) == 2
    dec_titles = [d["title"] for d in decisions_list]
    assert "Use 2-week sprint cycles" in dec_titles
    assert "Database choice: PostgreSQL" in dec_titles

    # Verify open tasks & upcoming deadlines
    open_tasks = dashboard["open_tasks"]
    assert len(open_tasks) == 2
    upcoming = dashboard["upcoming_deadlines"]
    assert len(upcoming) == 2
    # Verify sorted ascending by due date (t2 due in 1 day comes before t1 due in 3 days)
    assert upcoming[0]["title"] == "Design database schemas"

    # Verify recurring topics
    recurring = dashboard["recurring_topics"]
    arch_topic = next((t for t in recurring if t["topic_name"] == "Architecture"), None)
    assert arch_topic is not None
    assert arch_topic["occurrence_count"] >= 2

    # Verify timeline
    timeline = dashboard["meeting_timeline"]
    assert len(timeline) >= 5 # 2 meetings + 2 decisions + 2 tasks + 1 doc
    event_types = {item["event_type"] for item in timeline}
    assert "MEETING" in event_types
    assert "DECISION" in event_types
    assert "TASK_DUE" in event_types
    assert "DOCUMENT_ADDED" in event_types

    # Verify related documents
    documents = dashboard["related_documents"]
    assert len(documents) == 1
    assert documents[0]["title"] == "System Architecture Spec"
    assert documents[0]["meeting_id"] == mid_2


def test_project_memory_sub_resource_endpoints(client, setup_db):
    token, cid, pid_a, _, mid_1, _, _ = setup_project_memory_scenario(client)

    # Discussions sub-endpoint
    r_disc = client.get(f"/api/v1/projects/{pid_a}/memory/discussions", headers=auth_headers(token))
    assert r_disc.status_code == 200

    # Decisions sub-endpoint
    r_dec = client.get(f"/api/v1/projects/{pid_a}/memory/decisions", headers=auth_headers(token))
    assert r_dec.status_code == 200

    # Tasks sub-endpoint
    r_tasks = client.get(f"/api/v1/projects/{pid_a}/memory/tasks", headers=auth_headers(token))
    assert r_tasks.status_code == 200

    # Topics sub-endpoint
    r_top = client.get(f"/api/v1/projects/{pid_a}/memory/topics", headers=auth_headers(token))
    assert r_top.status_code == 200

    # Timeline sub-endpoint
    r_time = client.get(f"/api/v1/projects/{pid_a}/memory/timeline", headers=auth_headers(token))
    assert r_time.status_code == 200

    # Documents sub-endpoint
    r_doc = client.get(f"/api/v1/projects/{pid_a}/memory/documents", headers=auth_headers(token))
    assert r_doc.status_code == 200

    # Participants sub-endpoint
    r_part = client.get(f"/api/v1/projects/{pid_a}/memory/participants", headers=auth_headers(token))
    assert r_part.status_code == 200


def test_project_memory_isolation(client, setup_db):
    from tests.conftest import TestingSessionLocal
    from app.models.meeting_summary import MeetingSummary

    token, cid, pid_a, pid_b, mid_1, mid_2, mid_3 = setup_project_memory_scenario(client)

    db = TestingSessionLocal()
    try:
        s1 = MeetingSummary(meeting_id=mid_1, company_id=cid, summary_text="Project Alpha discussion")
        s3 = MeetingSummary(meeting_id=mid_3, company_id=cid, summary_text="Project Beta discussion")
        db.add_all([s1, s3])
        db.commit()
    finally:
        db.close()

    r_a = client.get(f"/api/v1/projects/{pid_a}/memory", headers=auth_headers(token))
    r_b = client.get(f"/api/v1/projects/{pid_b}/memory", headers=auth_headers(token))

    dash_a = r_a.json()
    dash_b = r_b.json()

    assert dash_a["source_meetings_count"] == 2
    assert dash_b["source_meetings_count"] == 1
    assert dash_a["recent_discussions"][0]["summary_text"] == "Project Alpha discussion"
    assert dash_b["recent_discussions"][0]["summary_text"] == "Project Beta discussion"
    assert dash_b["recent_discussions"] != dash_a["recent_discussions"]
