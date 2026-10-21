"""Secret bindings supplied after snapshot must reach existing service imports."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core import config


@pytest.fixture
def bindings(monkeypatch):
    # Restore every changed setting and the binding cache after each test.
    for name in config.Settings.model_fields:
        monkeypatch.setattr(config.settings, name, getattr(config.settings, name))
    monkeypatch.setattr(config, "_request_binding_values", None)
    return SimpleNamespace(
        HYPERDRIVE=object(), ENVIRONMENT="production", JWT_SECRET="synthetic-new-secret" * 3,
        SUPABASE_URL="https://example.supabase.co", SUPABASE_SERVICE_ROLE_KEY="synthetic-service-key",
        LIVEKIT_URL="wss://example.livekit.cloud", LIVEKIT_API_KEY="synthetic-api-key",
        LIVEKIT_API_SECRET="synthetic-api-secret", CLOUDFLARE_AI_CALLBACK_SECRET="synthetic-callback",
    )


def test_snapshot_defaults_refresh_without_replacing_service_settings(bindings):
    from app.core.tokens import settings as token_settings
    original = config.settings
    config.settings.JWT_SECRET = config.Settings.model_fields["JWT_SECRET"].default
    config.refresh_worker_settings(bindings)
    assert config.settings is original is token_settings
    assert token_settings.JWT_SECRET == bindings.JWT_SECRET
    assert config.settings.SUPABASE_SERVICE_ROLE_KEY == bindings.SUPABASE_SERVICE_ROLE_KEY


def test_rotation_and_removal_do_not_keep_previous_secret(bindings):
    config.refresh_worker_settings(bindings)
    bindings.JWT_SECRET = "synthetic-rotated-secret" * 3
    config.refresh_worker_settings(bindings)
    assert config.settings.JWT_SECRET == bindings.JWT_SECRET
    del bindings.JWT_SECRET
    config.refresh_worker_settings(bindings)
    assert config.settings.JWT_SECRET == config.Settings.model_fields["JWT_SECRET"].default


@pytest.mark.asyncio
async def test_health_uses_live_secrets_before_readiness_and_database_check(bindings, monkeypatch):
    response = SimpleNamespace(json=lambda data, status=200: SimpleNamespace(data=data, status=status))
    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(
        WorkerEntrypoint=object, Response=response, asgi=SimpleNamespace(),
    ))
    spec = importlib.util.spec_from_file_location(
        "candidate_settings_test", Path(__file__).parents[1] / "worker.py",
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    db = MagicMock()
    monkeypatch.setattr(worker, "SessionLocal", db)
    instance = worker.Default()
    instance.env = bindings
    config.settings.JWT_SECRET = config.Settings.model_fields["JWT_SECRET"].default
    result = await instance.fetch(SimpleNamespace(url="https://example.invalid/health"))
    assert result.status == 200
    assert result.data == {"status": "ok", "runtime": "cloudflare"}
    db.return_value.__enter__.return_value.execute.assert_called_once()
