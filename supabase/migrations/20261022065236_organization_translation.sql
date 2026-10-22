-- Server-only translation state. Firebase application tokens are checked by
-- the native API; Supabase browser roles receive no direct access.
CREATE TABLE public.meeting_translation_settings (
  meeting_id varchar PRIMARY KEY REFERENCES public.meetings(public_id),
  enabled boolean NOT NULL DEFAULT false,
  save_transcripts boolean NOT NULL DEFAULT false,
  updated_by varchar NOT NULL REFERENCES public.users(public_id),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.meeting_translation_preferences (
  meeting_id varchar NOT NULL REFERENCES public.meetings(public_id),
  user_id varchar NOT NULL REFERENCES public.users(public_id),
  source_language varchar NOT NULL CHECK(source_language IN ('en','ta','hi')),
  target_language varchar CHECK(target_language IN ('en','ta','hi')),
  share_audio boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(meeting_id,user_id)
);
CREATE INDEX translation_preferences_active_idx ON public.meeting_translation_preferences(meeting_id,updated_at);
CREATE TABLE public.meeting_translation_segments (
  id uuid PRIMARY KEY,
  meeting_id varchar NOT NULL REFERENCES public.meetings(public_id),
  user_id varchar NOT NULL REFERENCES public.users(public_id),
  request_id uuid NOT NULL,
  budget_scope varchar NOT NULL,
  speaker_name varchar NOT NULL,
  source_language varchar NOT NULL CHECK(source_language IN ('en','ta','hi')),
  duration_seconds double precision NOT NULL CHECK(duration_seconds BETWEEN 0.4 AND 8),
  audio_hash varchar NOT NULL,
  original_text text NOT NULL DEFAULT '',
  translations jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar NOT NULL CHECK(status IN ('PROCESSING','COMPLETED','FAILED')),
  error_code varchar,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(meeting_id,user_id,request_id)
);
CREATE INDEX translation_segments_delivery_idx ON public.meeting_translation_segments(meeting_id,created_at);
CREATE INDEX translation_segments_budget_idx ON public.meeting_translation_segments(budget_scope,created_at);
ALTER TABLE public.meeting_translation_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.meeting_translation_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.meeting_translation_segments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.meeting_translation_settings,public.meeting_translation_preferences,public.meeting_translation_segments FROM anon,authenticated;
GRANT ALL ON public.meeting_translation_settings,public.meeting_translation_preferences,public.meeting_translation_segments TO service_role;
