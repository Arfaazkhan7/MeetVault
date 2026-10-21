-- Reconcile the migrated database with the application's existing meeting
-- models. This project was initialized with create_all, which never adds
-- columns to existing tables. All additions are repeatable and preserve rows.
SET lock_timeout = '5s';

ALTER TABLE public.meeting_participants
  ADD COLUMN IF NOT EXISTS livekit_identity varchar,
  ADD COLUMN IF NOT EXISTS identity_mapping_status varchar NOT NULL DEFAULT 'unmapped',
  ADD COLUMN IF NOT EXISTS is_guest boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS display_name varchar;
CREATE INDEX IF NOT EXISTS ix_meeting_participants_livekit_identity ON public.meeting_participants(livekit_identity);
CREATE INDEX IF NOT EXISTS ix_meeting_participants_meeting_livekit ON public.meeting_participants(meeting_id, livekit_identity);

ALTER TABLE public.meeting_recordings
  ADD COLUMN IF NOT EXISTS session_id varchar,
  ADD COLUMN IF NOT EXISTS egress_id varchar,
  ADD COLUMN IF NOT EXISTS source varchar DEFAULT 'client_mixed_audio',
  ADD COLUMN IF NOT EXISTS is_audio_purged boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS audio_purged_at timestamptz,
  ADD COLUMN IF NOT EXISTS retention_policy varchar DEFAULT 'ephemeral_transcript_only',
  ADD COLUMN IF NOT EXISTS cleanup_error text,
  ADD COLUMN IF NOT EXISTS cleanup_retry_count integer NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS ix_meeting_recordings_session_id ON public.meeting_recordings(session_id);
CREATE INDEX IF NOT EXISTS ix_meeting_recordings_egress_id ON public.meeting_recordings(egress_id);

ALTER TABLE public.transcript_segments
  ADD COLUMN IF NOT EXISTS recording_id varchar,
  ADD COLUMN IF NOT EXISTS segment_id varchar,
  ADD COLUMN IF NOT EXISTS speaker_user_id varchar,
  ADD COLUMN IF NOT EXISTS participant_id uuid,
  ADD COLUMN IF NOT EXISTS attribution_status varchar NOT NULL DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS translated_text varchar,
  ADD COLUMN IF NOT EXISTS words json,
  ADD COLUMN IF NOT EXISTS processing_metadata json;
CREATE INDEX IF NOT EXISTS ix_transcript_segments_recording_id ON public.transcript_segments(recording_id);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_segment_id ON public.transcript_segments(segment_id);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_user_id ON public.transcript_segments(speaker_user_id);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant_id ON public.transcript_segments(participant_id);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_meeting_start ON public.transcript_segments(meeting_id, start_time);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_user ON public.transcript_segments(meeting_id, speaker_user_id);
CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant ON public.transcript_segments(meeting_id, participant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_transcript_segment_meeting_segid ON public.transcript_segments(meeting_id, segment_id);

