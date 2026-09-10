def register(client, email, name="Test User", password="StrongPass1"):
    response = client.post("/api/v1/auth/register", json={
        "full_name": name,
        "email": email,
        "password": password,
    })
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email, password="StrongPass1"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_analytics_are_database_backed(client):
    register(client, "analytics@example.com", "Analytics User")
    token = login(client, "analytics@example.com")
    company = client.post("/api/v1/companies", json={"name": "Analytics Co"}, headers=auth_headers(token)).json()
    project = client.post(
        f"/api/v1/companies/{company['public_id']}/projects",
        json={"name": "Metrics"},
        headers=auth_headers(token),
    ).json()
    meeting = client.post(
        f"/api/v1/companies/{company['public_id']}/meetings",
        json={"title": "Metrics Review", "project_id": project["public_id"]},
        headers=auth_headers(token),
    )
    assert meeting.status_code == 201, meeting.text

    response = client.get("/api/v1/analytics/dashboard", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["meeting_count"] == 1
    project_act = next(p for p in body["project_activity"] if p["project_id"] == project["public_id"])
    assert project_act["meeting_count"] == 1
    assert body["recent_meetings"][0]["title"] == "Metrics Review"
