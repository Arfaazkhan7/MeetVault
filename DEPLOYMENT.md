# MeetVault Deployment

## Architecture

```text
GitHub
  -> Render Web Service: FastAPI backend
  -> Firebase Hosting: Flutter Web frontend
  -> Supabase: PostgreSQL database and private recording storage
  -> LiveKit: meeting rooms and participant media
  -> Render-compatible worker: Celery AI processing
```

This project is configured for Render because the Firebase project does not have paid Google infrastructure enabled.

## Render Backend

The backend is deployed from `render.yaml`.

Service:

```text
meetvault-api
```

Runtime:

```text
Docker
```

Dockerfile:

```text
backend/Dockerfile
```

Health check:

```text
/health
```

Production command:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Render Blueprint

Open this Render Blueprint URL after the latest commit is pushed:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/GOKUL5731/meetvault
```

Use the free plan only for the web service.

Set the `sync: false` variables directly in Render. Do not paste real secrets into chat or commit them to GitHub.

Required backend secrets:

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

### Supabase database setup

The application SQL data and recording files use two different Supabase connections:

1. In Supabase, open **Connect** and copy a PostgreSQL connection string. Use the Session Pooler connection when direct connections are unavailable. Add `sslmode=require` if it is not already present.
2. In Render, set the same `DATABASE_URL` on both `meetvault-api` and `meetvault-ai-worker`. This must be a PostgreSQL URI such as `postgresql://...`; do not use the Supabase project URL here.
3. Set `SUPABASE_URL` to the project API URL (`https://<project-ref>.supabase.co`) and set `SUPABASE_SERVICE_ROLE_KEY` only in Render. Keep the `meeting-recordings` bucket private.
4. Redeploy the API. Its startup creates the complete current ORM schema and seeds the application. Refresh Supabase **Database > Tables** and confirm tables appear.

If Render logs show `FATAL: (ENOTFOUND) tenant/user postgres.<project-ref> not found`, do not reset the database password first. Supabase could not match the shared pooler host and username. Reopen Supabase **Connect**, choose **Session pooler** or **Transaction pooler**, copy the whole URI exactly, replace only the password placeholder, and paste that exact value into Render. Do not compose the `aws-...pooler.supabase.com` host manually.

The committed `supabase_schema_and_rls.sql` is not the application bootstrap and should not be used as a substitute for the backend schema. The FastAPI service owns schema creation through SQLAlchemy/Alembic and uses its server-side database credentials.

For recordings, the existing bucket currently has a 50 MB limit. Either raise that bucket limit to at least 500 MB or set `MAX_RECORDING_UPLOAD_BYTES=52428800` in Render so the application limit matches the bucket. Storage policies are not required for the server upload because the service-role key is server-side; do not make recordings public.

Backend non-secret config is already in `render.yaml`:

```text
ENVIRONMENT=production
BACKEND_CORS_ORIGINS=https://ai-meet-f8fd0.web.app,https://ai-meet-f8fd0.firebaseapp.com
FIREBASE_PROJECT_ID=ai-meet-f8fd0
SUPABASE_STORAGE_BUCKET=meeting-recordings
RECORDING_SIGNED_URL_EXPIRE_SECONDS=900
MAX_RECORDING_UPLOAD_BYTES=524288000
LLM_PROVIDER=openai
```

## AI Worker

The worker code is in `ai_worker/` and uses Celery with `REDIS_URL`.

`REDIS_URL` must be a Redis protocol broker URL such as `redis://...` or `rediss://...`.
Do not paste an Upstash REST SDK snippet (`Redis(url="https://...", token="...")`) into `REDIS_URL`; that HTTP URL/token pair is not a Celery broker.

Dockerfile:

```text
ai_worker/Dockerfile
```

Start command:

```text
python -m ai_worker
```

Do not run heavy transcription or diarization inside normal FastAPI requests. The worker should run as a separate Render worker service when the selected Render plan supports background workers and Redis/Key Value without violating the no-paid-plan requirement.

## Firebase Hosting

Firebase project:

```text
ai-meet-f8fd0
```

Firebase files:

```text
firebase.json
.firebaserc
.github/workflows/deploy-firebase-hosting.yml
```

After Render deploys successfully, run the GitHub Actions workflow:

```text
Deploy Flutter Web to Firebase Hosting
```

Workflow input:

```text
api_base_url=https://ACTUAL-RENDER-URL/api/v1
```

Do not use localhost or a placeholder URL in the Firebase production build.

## Verification

After Render deploys, verify:

```text
https://ACTUAL-RENDER-URL/health
https://ACTUAL-RENDER-URL/docs
https://ACTUAL-RENDER-URL/api/v1/health
```

After Firebase deploys, verify:

```text
https://ai-meet-f8fd0.web.app
https://ai-meet-f8fd0.firebaseapp.com
```

Check the browser network tab and confirm all API calls go to:

```text
https://ACTUAL-RENDER-URL/api/v1
```

## Security

Never commit:

- `.env`
- Firebase Admin private keys
- service account JSON
- Supabase service-role keys
- LiveKit API secrets
- JWT secrets
- OpenAI API keys
- admin passwords

Frontend Firebase browser config is allowed, but backend secrets must stay only in Render/Supabase/LiveKit/Firebase dashboards.
