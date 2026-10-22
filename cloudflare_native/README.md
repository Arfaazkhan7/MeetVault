# MeetVault native Cloudflare API

Production API: https://meetvault-api-candidate.aeris-cloud.workers.dev/api/v1

The opt-in English/Tamil/Hindi translation pilot is documented in
`../ORGANIZATION_TRANSLATION.md`. Its optional organization-owned standard
speech service is in `../translation_speech/`; shared voice is unavailable
until that separate host is configured. It does not enable voice cloning.

This is the active backend. The older Python Worker remains in `cloudflare_backend/`
for reference; its Python initialization and request CPU exceeded the Free plan.
Do not deploy that entrypoint over the native API.

## Local validation and deployment

```sh
cd cloudflare_native
npm ci
npm test
npx wrangler deploy --dry-run --minify
npx wrangler deploy --minify
```

Secrets are managed in Cloudflare, never in Git: `JWT_SECRET`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`,
`CLOUDFLARE_AI_CALLBACK_SECRET`. Preserve existing secrets and resource bindings
when deploying. `SYSTEM_ADMIN_PUBLIC_IDS` is an optional explicit comma-separated
allowlist for global administration; workspace ownership does not grant it.

Firebase Hosting serves `web/`, including `native-client.js`. Firebase authenticates
users; the API verifies Firebase signatures/project/time/email and issues its own
access and refresh tokens. Supabase holds the existing Postgres records and private
files. Hyperdrive supplies request-scoped database connections. LiveKit supplies
meeting audio/video; hosts record mixed audio in their browser. Camera/microphone
permissions and browser media support are required.

Recordings upload directly to signed private storage URLs, capped at 20 MB by
completion validation, then enqueue durable AI jobs. The queue worker runs Whisper
and calls the API for transcript persistence and grounded summary extraction.
Speaker labels are unverified until manually mapped; paid diarization is disabled.

Vault uses `/cross-meeting/query`: account-scoped SQL full-text retrieval over
transcripts, summaries, decisions, tasks and attached document pages, followed by
bounded Workers AI synthesis with source citations. Select meetings in Vault to
compare them. No evidence produces an explicit empty result. AI quota exhaustion
returns saved excerpts, not a fabricated answer. Analysis can be retried after its
free allocation recovers; saved transcripts remain available.

## Free usage boundaries

No paid plan or external paid model is enabled by this migration. Free usage is
limited by Cloudflare requests/CPU, Workers AI neurons, Queues, Hyperdrive,
Supabase storage/database and LiveKit media quotas. This is not unlimited free
hosting. Some cold or write-heavy requests can use more than the Free plan's
10 ms CPU allowance; monitor `exceededCpu` outcomes. Direct storage uploads and
bounded retrieval reduce work but cannot remove provider quotas.

Recordings remain private in Supabase; there is no automatic retention cleanup in
this native implementation. Manage storage before its free allocation fills.
Long transcripts are bounded for a single analysis window, and partial coverage
is recorded in summary metadata. Semantic vector indexing, automatic diarization,
guest access and every legacy administration endpoint are not ported. The existing
Flutter source is not the frontend deployed by Firebase Hosting.

`npm test` runs real PostgreSQL semantics in PGlite with synthetic fixtures. It
checks authentication, meeting isolation, roles, attendance, signed upload/job
creation, citations, analysis and browser invite normalization. A two-device live
media check remains necessary; these tests do not simulate cameras or LiveKit.

`test/live-canary.js` is a one-time isolated deployment check, excluded from the
production entrypoint. Never leave its temporary scheduled deployment enabled.
Remove its schedule and fixture accounts/files after validation.
