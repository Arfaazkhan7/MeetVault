# MeetVault Cloudflare AI Worker Setup

This is the recommended low-cost worker architecture for MeetVault:

```text
Firebase Hosting / Flutter Web
        |
        v
Render FastAPI
        |
        +--> Supabase Postgres
        +--> LiveKit
        +--> Cloudflare Worker producer
                 |
                 v
          Cloudflare Queues
                 |
                 v
          Cloudflare Worker consumer
                 |
                 v
       Workers AI transcription + backend analysis callback
                 |
                 v
          MeetVault Analytics
```

Cloudflare replaces the always-on Render background worker. It does not replace Firebase Hosting, Render FastAPI, Supabase Postgres, or LiveKit.

## What Was Added

- `AI_WORKER_QUEUE=cloudflare` support in the FastAPI recording upload flow.
- `CLOUDFLARE_AI_QUEUE_URL` and `CLOUDFLARE_AI_QUEUE_SECRET` backend settings.
- `cloudflare_ai_worker/` with a Worker producer plus Queue consumer scaffold.

The existing database queue remains the safe default:

```text
AI_WORKER_QUEUE=database
```

## Step 1: Create Cloudflare Resources

Install Wrangler:

```powershell
cd C:\Users\gokul\Downloads\meetvault\cloudflare_ai_worker
npm install
npx wrangler login
npx wrangler queues create meetvault-ai-jobs
npx wrangler r2 bucket create meetvault-recordings
copy wrangler.toml.example wrangler.toml
```

Set secrets:

```powershell
npx wrangler secret put MEETVAULT_WORKER_SECRET
npx wrangler secret put BACKEND_WORKER_CALLBACK_SECRET
```

Use the same strong random value for:

- Cloudflare `MEETVAULT_WORKER_SECRET`
- Render `CLOUDFLARE_AI_QUEUE_SECRET`

Use another strong random value for:

- Cloudflare `BACKEND_WORKER_CALLBACK_SECRET`
- Render backend callback secret, once the callback route is enabled.

## Step 2: Deploy the Cloudflare Worker

```powershell
cd C:\Users\gokul\Downloads\meetvault\cloudflare_ai_worker
npm run deploy
```

After deploy, Cloudflare gives a Worker URL like:

```text
https://meetvault-ai-worker.<your-subdomain>.workers.dev
```

Use that as:

```text
CLOUDFLARE_AI_QUEUE_URL=https://meetvault-ai-worker.<your-subdomain>.workers.dev
```

## Step 3: Update Render API Environment

In Render -> `meetvault-api` -> Environment:

```text
AI_WORKER_QUEUE=cloudflare
CLOUDFLARE_AI_QUEUE_URL=<your Worker URL>
CLOUDFLARE_AI_QUEUE_SECRET=<same value as MEETVAULT_WORKER_SECRET>
```

Keep these existing values:

```text
DATABASE_URL=<Supabase pooler URI>
SUPABASE_URL=<Supabase URL>
SUPABASE_SERVICE_ROLE_KEY=<Supabase service role key>
SUPABASE_STORAGE_BUCKET=meeting-recordings
```

## Step 4: How Processing Works

The included Cloudflare Worker:

- receives the queued job id;
- requests job context from `GET /api/v1/ai-jobs/{job_id}/cloudflare/context`;
- downloads the signed recording URL returned by the backend;
- transcribes audio using Workers AI `@cf/openai/whisper-large-v3-turbo`;
- posts transcript segments to `POST /api/v1/ai-jobs/{job_id}/cloudflare/result`;
- marks the job failed through `POST /api/v1/ai-jobs/{job_id}/cloudflare/fail` if processing fails.

The backend owns Supabase/Postgres writes and runs the existing meeting analysis service after transcript segments arrive.

Speaker diarization is not yet implemented in the Cloudflare path. Segments are stored as `SPEAKER_0` until diarization is added through pyannoteAI or another Cloudflare-compatible provider.
