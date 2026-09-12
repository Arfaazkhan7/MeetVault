# MeetVault Deployment

## Current Target Architecture

```text
Firebase Hosting
  -> Flutter Web
  -> Render Web Service
  -> FastAPI backend
  -> Supabase, LiveKit, AI worker
```

Render is used for the backend because the `ai-meet-f8fd0` Firebase project does not have paid Google infrastructure enabled.

## Render Backend

The repository includes `render.yaml` for a Render Blueprint.

Backend service:

- Name: `meetvault-api`
- Runtime: Docker
- Root directory: `backend`
- Dockerfile: `backend/Dockerfile`
- Health check: `/health`
- Start command inside container: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}`

The Render backend image installs `backend/requirements-render.txt`, which excludes local AI runtime packages such as `torch`, `openai-whisper`, and `pyannote.audio`. Those remain in the AI worker.

## Render Environment Variables

Set these in Render. Do not commit their real values:

```text
JWT_SECRET
DATABASE_URL
REDIS_URL
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
OPENAI_API_KEY
```

The blueprint already includes non-secret values:

```text
ENVIRONMENT=production
BACKEND_CORS_ORIGINS=https://ai-meet-f8fd0.web.app,https://ai-meet-f8fd0.firebaseapp.com
FIREBASE_PROJECT_ID=ai-meet-f8fd0
SUPABASE_STORAGE_BUCKET=meeting-recordings
```

## Deploy Backend To Render

1. Open Render Dashboard.
2. Connect GitHub repository `GOKUL5731/meetvault`.
3. Choose Blueprint deployment.
4. Select `render.yaml`.
5. Use the free plan only.
6. Enter the required secret environment variables in Render.
7. Deploy.

After Render deploys, verify:

```text
https://ACTUAL-RENDER-URL/health
https://ACTUAL-RENDER-URL/docs
https://ACTUAL-RENDER-URL/api/v1/health
```

## Firebase Hosting

After the Render backend URL is verified, run the GitHub Actions workflow:

```text
Deploy Flutter Web to Firebase Hosting
```

Provide:

```text
api_base_url=https://ACTUAL-RENDER-URL/api/v1
```

Do not deploy the frontend with localhost or placeholder backend URLs.

## AI Worker

The AI worker lives in `ai_worker/` and uses Celery with Redis.

The worker Dockerfile is `ai_worker/Dockerfile` and starts with:

```text
python -m ai_worker
```

Render background workers are separate from web services: they do not receive HTTP traffic; they poll Redis-compatible queue storage through `REDIS_URL`.

Deploy the worker separately only when the selected Render account/plan supports background workers and Redis/Key Value without violating the no-paid-plan requirement. If the account does not offer a free background worker, the web API can still deploy, but production AI processing remains blocked until a no-cost worker runtime is available.

Worker environment variables:

```text
REDIS_URL
OPENAI_API_KEY
LLM_MODEL
WHISPER_MODEL
TRANSCRIPTION_PROVIDER
LLM_PROVIDER
AI_WORKER_CALLBACK_URL
```

## Verification Checklist

- Render `/health` returns `{"status":"ok"}`
- Render `/docs` loads Swagger via redirect to `/api/v1/docs`
- Firebase Hosting serves Flutter web
- Browser network calls use Render `/api/v1`
- No production frontend request goes to localhost
- Email/password login works
- Firebase Google login exchanges Firebase ID token for MeetVault JWT
- Workspace login remains server-side authorized
- LiveKit token generation works
- Supabase private storage and signed URLs work
