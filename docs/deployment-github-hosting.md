# GitHub and Hosting Deployment

## Frontend: GitHub Pages

The Flutter web frontend is deployed by `.github/workflows/deploy-frontend-pages.yml`.

Before the production site can work end-to-end, deploy the backend and then run the workflow manually with:

```text
api_base_url=https://YOUR_BACKEND_HOST/api/v1
```

The expected frontend URL after GitHub Pages is enabled for the repository is:

```text
https://GOKUL5731.github.io/meetvault/
```

## Backend: FastAPI Container

GitHub Pages cannot host the FastAPI backend. Deploy `backend/Dockerfile` to a container platform such as Cloud Run, Render, Fly.io, Railway, or Azure Container Apps.

Required production environment variables:

```text
ENVIRONMENT=production
BACKEND_CORS_ORIGINS=https://GOKUL5731.github.io
DATABASE_URL=
JWT_SECRET=
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=meeting-recordings
RECORDING_SIGNED_URL_EXPIRE_SECONDS=900
LLM_PROVIDER=openai
OPENAI_API_KEY=
```

Never put backend secrets into Flutter, GitHub Pages, or any `VITE_`/browser-exposed variable.

## Verification

After deployment:

1. Open `https://YOUR_BACKEND_HOST/api/v1/health`.
2. Open `https://GOKUL5731.github.io/meetvault/`.
3. Confirm browser network calls go to `https://YOUR_BACKEND_HOST/api/v1`.
4. Confirm login, workspace login, meeting creation, invite-code join, and LiveKit room token generation.
