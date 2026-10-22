# MeetVault organization translation pilot

The hosted `web/` frontend now has a **Meeting translation** panel in a connected
LiveKit room. It supports English, Tamil and Hindi. All AI transcription and
translation are centralized in the existing Cloudflare API. Users do not install
models. This is short-segment, near-live translation, not simultaneous interpreting:
speech is collected until a pause or roughly six seconds, then processed.

## Use

1. Host creates/joins a meeting and opens **Meeting translation**.
2. Host chooses whether to save original speech to Vault, then enables meeting
   translation. The host can stop it for everyone at any time.
3. Each listener selects a target caption language. A participant who wants
   their own speech translated chooses their spoken language and explicitly
   checks **Send my microphone audio for translation**.
4. Captions show the original text, translated text and account display name.
   The account is the audio sender; speaker identity is not biometrically verified.
5. Output defaults to captions. **Device voice** uses an installed matching
   browser/OS voice, when available. **Shared standard voice** requires the
   separately hosted service in `translation_speech/`; it is unavailable until
   the API's speech URL/key are configured. No voice cloning is enabled.

The browser captures only the local microphone, downsamples to 16 kHz mono
PCM16, and sends independently valid WAV utterances. It never sends mixed room
audio or translated playback. A silent AudioWorklet output prevents direct
loopback; headphones are still needed to prevent acoustic speaker echo.

## Server behavior and caps

- Authenticated meeting membership is required for reads; joined attendance
  plus fresh explicit consent is required for microphone submission. Only the
  host can enable/disable translation and select Vault persistence.
- Supported languages are allowlisted. WAV headers, sample rate, byte length
  and actual audio duration are validated. Maximum eight seconds per request.
- Requests are idempotent by meeting, sender, UUID and audio hash. AI runs once
  per source segment, then once per distinct active target language. Same-language
  captions reuse the original transcript without a translation-model call.
- Private server-originated LiveKit data delivers captions; authenticated polling
  recovers missed updates. Ordinary participants cannot forge the server topic.
- Pilot caps: **300 audio seconds per meeting**, **600 audio seconds per workspace
  per UTC day**, and **12 submissions per sender per minute**. Personal meetings
  share the owner's daily cap. PostgreSQL advisory transaction locks serialize
  reservations across concurrent requests. Failed attempts still consume the
  reserved allowance, preventing retry storms from spending the AI allocation.
- Caps are application limits, not guarantees of free capacity. Translation shares
  Workers AI allocation with recordings and cross-meeting analysis. Provider quota
  failures pause microphone translation and leave original meeting audio working.

The pilot does not add a paid model or upgrade any account. Keep it opt-in.
Increasing `TRANSLATION_MEETING_AUDIO_SECONDS` / `TRANSLATION_DAILY_AUDIO_SECONDS`
requires measuring real usage first (maximum configured values 3,600 / 7,200).

## Data and deployment

Apply `supabase/migrations/20261022065236_organization_translation.sql` before
deploying the native Worker. Its three new tables use RLS and revoke browser-role
access; the API accesses them through the existing server database connection.
No existing table grants/constraints are changed. Host options and participant
preferences are meeting-scoped.

`meeting_translation_segments` stores delivery captions/translations, status,
an audio hash and duration; it does **not** store raw microphone audio. These
delivery rows remain in the database until an administrator applies the chosen
retention policy; a scheduled cleanup is not enabled by this pilot. The host's
**Save original speech** checkbox controls additional `transcript_segments`
records used by Vault, not the delivery rows. Original text is preserved and
translations are metadata; synthetic speech is never treated as original evidence.

Set `LIVE_TRANSLATION_ENABLED=true` to expose the host enable action. The API
feature flag can disable new microphone requests globally. Disabling a session
does not delete its saved original transcripts. Optional shared speech setup is
documented in `translation_speech/README.md` and requires an HTTPS host, gated
model download and a private key. These resources are not provisioned automatically.

## Validation and remaining rollout checks

Native tests cover host/member isolation, explicit consent and withdrawal,
WAV/duration bounds, deduplication, unique-language inference, quota reservation,
original transcript separation, browser-role denial and AudioWorklet resampling.
Speech-service tests cover bearer auth and cache reuse across concurrent listeners.
Real Cloudflare M2M100 inference returned English-to-Tamil and English-to-Hindi
translations during implementation. No real-camera/microphone two-device test,
Tamil/Hindi recognition accuracy benchmark, or GPU speech performance test is
claimed by those unit/integration checks.

Supabase's existing security advisor also reports 27 pre-existing application
tables without RLS and the `vector` extension in `public`. The three new pilot
tables have RLS and no browser grants. Existing grants/policies were not changed
by this feature. Review the older tables' direct Data API exposure before a
broader organization rollout:
https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public
