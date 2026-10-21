# MeetVault: Render API to Cloudflare candidate

## Status

This branch prepares the existing FastAPI API for Python Workers. It is not a
production cutover. Firebase Hosting, the existing AI worker, LiveKit, and
Supabase remain in place. Do not delete Render or its files yet.

The API dependency set resolves for Pyodide and Wrangler's dry-run package build
has passed. Native regression tests are recorded in the PR. A local workerd
runtime test could not start in the build environment because its Pyodide
runtime download hostname could not resolve. No production endpoint or full
free-tier workload has been verified.

## What changes

- Existing `/api/v1` routes and SQLAlchemy models are reused.
- Hyperdrive and pg8000 replace the API's psycopg2 driver on Workers. Connections
  use NullPool and open only during requests, never while snapshotting imports.
- Worker settings come from bindings rather than `.env` files.
- Cost-12 bcrypt runs in the existing PostgreSQL `extensions.pgcrypto` extension
  on Workers, keeping the SHA-256/base64 prehash and stored password hashes.
  MeetVault's database already has pgcrypto. A synthetic `$2b$` hash verified
  successfully after normalizing its prefix to `$2a$`; no real passwords were
  read or changed. ASCII prehashes make this prefix normalization compatible.
- Firebase ID tokens use Google's signing certificates on Workers, without
  importing Firebase Admin's server-only dependency stack. Signature, audience,
  issuer, expiry, issued-at, authentication time, and subject are checked.
  Workers verify RS256 using Web Crypto through a python-jose Key adapter;
  asn1crypto extracts the certificate's public key. JWT signature verification
  remains enabled. Native Firebase Admin verification is unchanged.
- Document uploads use a private `meeting-documents` bucket on Workers. Existing
  local files must be copied before switching; database metadata is not a copy
  of the binaries. Downloads still require company membership.
- Jobs use the existing `meetvault-ai-jobs` Queue binding on Workers.
- `LLM_PROVIDER=cloudflare` uses a Workers AI binding for summaries/RAG. Provider
  errors do not silently become mock results. The Worker artifact excludes the
  optional OpenAI SDK to reduce snapshot memory. Keep `LLM_PROVIDER=cloudflare`
  and leave `OPENAI_API_KEY` unset on this Worker. Native deployments retain
  their existing optional OpenAI integration.
- Firebase's deploy workflow reads the optional `MEETVAULT_API_BASE_URL`
  repository variable. Its default remains the existing Render URL until cutover.
- Email-only development tokens are rejected when ENVIRONMENT is production.

## Free-tier boundaries

Cloudflare Free currently permits 100,000 Worker requests/day with 10 ms of CPU
per HTTP request. Network waiting is excluded. Workers AI and Queues have
separate daily allowances. Quotas apply across the account.

The old bcrypt path used about 273 ms of native CPU for one hash in a local
benchmark. The Worker path delegates it to PostgreSQL; it does not reduce the
cost factor. Database compute still consumes the existing database's quota.

Python ORM serialization, PDF/PPT extraction, transcript ingestion, and indexing
still need actual Worker CPU measurements. The candidate is not evidence that
all features fit Free. If those exceed 10 ms, move parsing to the browser and
split/index jobs off the HTTP path, or port those routes to leaner handlers.
Do not enable a paid Workers plan as an automatic workaround.

Both the initial upload and the OpenAI-trimmed build were rejected with code
10021, "Python startup exceeded memory limits". Successful dry runs did not
validate startup. The next build removes cryptography/OpenSSL and the
python-pptx/lxml/Pillow dependency stack from the Worker artifact, retaining
Web Crypto RSA verification and using a bounded stdlib OOXML text reader.
LiveKit's protobuf/API imports remain deferred until needed. Run
`pywrangler sync --force` after pulling to remove stale vendored packages.
This reduction is not a verified fix until Cloudflare accepts the upload and
real requests pass the runtime memory and CPU checks.

Worker PPTX extraction reads slide order, text runs, and speaker notes without
rendering images. It rejects XML declarations, more than 200 slides, XML parts
larger than 2 MiB, or more than 16 MiB of total uncompressed XML. Invalid or
oversized PPTX requests return 400. Native PowerPoint extraction is unchanged.

The candidate caps recording uploads at 20 MiB. Existing large recordings need
a signed direct-upload/chunked flow rather than the old 500 MiB buffered route.
Document extraction remains synchronous and is a CPU validation gate. Existing
OpenAI embeddings are not replaced with a new vector model here: do not mix
embedding dimensions or call hashed fallback vectors semantic embeddings.
LiveKit media, optional diarization, Firebase, and Supabase retain their own
quotas and billing rules.

Sources:
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/hyperdrive/examples/python-workers/
- https://developers.cloudflare.com/workers/languages/python/packages/fastapi/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://www.postgresql.org/docs/current/pgcrypto.html

## Configuration required before a candidate deployment

Use Cloudflare account `a203e2da11445fcb2d0a2d88cfdc6000` (the account containing
`meetvault-ai-worker`). Keep Workers on the Free plan.

1. In Cloudflare Hyperdrive, create a PostgreSQL connection using the existing
   Render `DATABASE_URL` credentials. Disable Hyperdrive query caching for
   authentication and transactional application reads; do not cache these.
   Record the Hyperdrive ID. No database contents are moved.
2. In Supabase Storage, create `meeting-documents` as a **private** bucket. Keep
   `meeting-recordings` private. No anon/public storage policies are required;
   only the backend holds the service key.
3. From a checkout of this branch:

   ```powershell
   python cloudflare_backend/prepare.py
   cd cloudflare_backend
   Copy-Item wrangler.jsonc.example wrangler.jsonc
   ```

   Replace `REPLACE_WITH_HYPERDRIVE_ID` in the local configuration. Review the
   candidate worker name and account before deploying. The generated `src/`
   folder deliberately contains only application source and the entrypoint.
4. Install uv and Node.js if needed. Authenticate the CLI:

   ```powershell
   npx wrangler login
   uvx --from workers-py==1.17.8 pywrangler deploy --dry-run
   ```

   Prepare again whenever backend source changes. `pywrangler` owns dependency
   vendoring; native Render requirements must not be copied into this folder.
5. Set these Worker secrets from Render using interactive prompts or the
   Cloudflare dashboard. Never commit values or paste them into a PR:

   | Setting | Value source |
   |---|---|
   | `JWT_SECRET` | Same value as Render, to preserve valid MeetVault sessions |
   | `SUPABASE_URL` | Existing Supabase project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | Existing server-only storage service key |
   | `LIVEKIT_URL` | Existing LiveKit server URL |
   | `LIVEKIT_API_KEY` | Existing LiveKit API key |
   | `LIVEKIT_API_SECRET` | Existing LiveKit API secret |
   | `CLOUDFLARE_AI_CALLBACK_SECRET` | Same value as the AI worker's `BACKEND_WORKER_CALLBACK_SECRET` |

   ```powershell
   uvx --from workers-py==1.17.8 pywrangler secret put JWT_SECRET
   ```

   Repeat for the remaining names. A backend credential is not recoverable from
   its Cloudflare secret binding. Reconnection alone does not expose those values
   to this development environment. No Firebase service-account private key is
   needed by the candidate's token verification path.
6. Deploy the candidate and test health:

   ```powershell
   uvx --from workers-py==1.17.8 pywrangler deploy
   curl.exe https://meetvault-api-candidate.aeris-cloud.workers.dev/health
   ```

   Health returns 503 for missing required configuration or an unreachable DB.
   A successful package upload or a 200 health response does not prove the full
   application works.

## Verification and cutover

Before updating production, verify all of these on the candidate:

- Existing personal/workspace passwords and Firebase Google login work.
- Unauthenticated requests and cross-company access are rejected.
- Two users join the same meeting code, receive tokens for the same LiveKit
  room, and record valid join/leave attendance.
- Existing document binaries have been copied; new private uploads and downloads
  work. Restore a sample file and compare bytes before marking the copy complete.
- An upload produces a queued job that reaches completed transcript and analysis
  states. The AI worker still points to Render until this verification switch.
- Measure CPU and memory on login, document extraction, large meeting responses,
  transcript ingestion, and indexing. Stay inside Free rather than upgrading.
- Check quotas and errors in Cloudflare before switching the frontend.

For the final switch:

1. Set the AI worker's `BACKEND_API_BASE_URL` to the candidate `/api/v1` URL,
   keeping its Queue, AI binding, and all existing secrets intact.
2. Set GitHub repository variable `MEETVAULT_API_BASE_URL` to that same URL.
3. Run the existing Firebase Hosting workflow and verify the hosted pages use
   the new backend. `firebase.json` currently serves `web/`, not Flutter output.
4. Repeat the login, two-user meeting, file, and completed-AI-job checks from
   Firebase Hosting. Only then retire Render and retain a database/file backup.

Rollback: restore the repository variable and AI worker callback URL to
`https://meetvault-api.onrender.com/api/v1`, then redeploy Firebase Hosting.
This assumes Render and the shared database remain available.
