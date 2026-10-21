import asyncio

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException

from app.core.workers_routes import configure_worker_routes


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_worker_dependency_endpoint_and_cleanup_share_request_task(monkeypatch, fail):
    app = FastAPI()
    events = []

    def session():
        events.append(("open", asyncio.current_task()))
        try:
            yield "session"
        finally:
            events.append(("close", asyncio.current_task()))

    @app.post("/meeting")
    def create_meeting(db=Depends(session)):
        assert db == "session"
        events.append(("create", asyncio.current_task()))
        if fail:
            raise HTTPException(409, "test conflict")
        return {"created": True}

    async def forbid_thread(*args, **kwargs):
        raise AssertionError("Worker routing must not dispatch to a thread")

    monkeypatch.setattr("fastapi.routing.run_in_threadpool", forbid_thread)
    monkeypatch.setattr("fastapi.dependencies.utils.run_in_threadpool", forbid_thread)
    configure_worker_routes(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/meeting")
    assert response.status_code == (409 if fail else 200)
    assert [name for name, _ in events] == ["open", "create", "close"]
    assert all(task is asyncio.current_task() for _, task in events)
