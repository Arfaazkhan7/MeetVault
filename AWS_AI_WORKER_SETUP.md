# MeetVault AWS AI Worker Setup

CloudFront cannot run the MeetVault AI worker. CloudFront is a CDN/reverse proxy for web traffic. The worker needs compute because it downloads recordings, transcribes audio, performs diarization/analysis, writes transcripts, and updates Supabase/Postgres.

Use this setup:

```text
MeetVault frontend -> Render API -> Supabase Postgres ai_jobs table
                                   -> Supabase Storage recordings

EventBridge schedule -> AWS Lambda AI worker -> Supabase/Postgres + Supabase Storage

CloudFront -> optional CDN/custom domain for frontend/API, not the worker runner
```

## Recommended Free/Cheap Path

Use AWS Lambda on a schedule for the AI worker. This avoids Render's free-tier worker limitation and does not need a credit-card upgrade on Render.

This repository includes a Lambda handler:

```text
ai_worker/lambda_handler.handler
```

The handler processes queued database jobs and exits. It uses the same database queue that Render API already writes to when recordings are uploaded.

## Lambda Environment Variables

Set these in AWS Lambda Configuration -> Environment variables:

```text
DATABASE_URL=<Supabase pooler PostgreSQL URI>
AI_WORKER_QUEUE=database
AI_WORKER_LAMBDA_MAX_JOBS=1
AI_WORKER_LAMBDA_MAX_SECONDS=600
AI_WORKER_STALE_JOB_MINUTES=30
STORAGE_BACKEND=supabase
SUPABASE_URL=<your Supabase project URL>
SUPABASE_SERVICE_ROLE_KEY=<your Supabase service role key>
SUPABASE_STORAGE_BUCKET=meeting-recordings
TRANSCRIPTION_PROVIDER=openai
LLM_PROVIDER=openai
OPENAI_API_KEY=<your OpenAI key>
HF_TOKEN=<optional Hugging Face token if diarization uses Hugging Face>
```

Do not put these values in GitHub or source files.

## Deploy With a Lambda Container Image

The current AI worker uses the backend models and services, so the clean Lambda package is a container image.

Use the included Dockerfile:

```text
ai_worker/Dockerfile.lambda
```

Build and push it to Amazon ECR, then create the Lambda from that image.

## EventBridge Schedule

Create an EventBridge rule:

```text
Schedule: rate(1 minute)
Target: the MeetVault AI worker Lambda
Input:
{
  "max_jobs": 1,
  "max_seconds": 600
}
```

Use Lambda timeout `10 minutes` and memory `1024 MB` or `2048 MB`. If diarization is heavy, Lambda may not be enough; use Oracle Cloud Always Free VM or AWS ECS/EC2 instead.

## CloudFront Connection

CloudFront is optional and should not be connected to the worker directly.

Use CloudFront only for:

- a custom domain in front of Firebase Hosting, or
- a custom domain in front of the Render API.

The worker connects to MeetVault through shared data:

- queued jobs in Supabase/Postgres `ai_jobs`
- recordings in Supabase Storage `meeting-recordings`
- transcript/analysis tables in Supabase/Postgres

That is the correct connection point for cross-meeting analysis.

## Verify

1. Upload a meeting recording in MeetVault.
2. Confirm a row appears in `ai_jobs` with `QUEUED`.
3. Trigger the Lambda manually.
4. Confirm the job changes to `COMPLETED` or `FAILED`.
5. Confirm transcript rows and analysis rows are written for the meeting.
6. Confirm the dashboard can show the transcript, summary, topics, decisions, and tasks.
