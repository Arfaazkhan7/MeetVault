-- ============================================================================
-- Supabase Migration: Ensure Transcript Segments Schema & Row Level Security
-- MeetVault Live Transcription & Speaker Attribution Architecture
-- ============================================================================

SET lock_timeout = '5s';

-- 1. Create transcript_segments table if not already present
CREATE TABLE IF NOT EXISTS public.transcript_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id VARCHAR(255) NOT NULL,
    recording_id VARCHAR(255),
    segment_id VARCHAR(255),
    speaker_label VARCHAR(50) NOT NULL,
    user_id VARCHAR(255),
    speaker_user_id VARCHAR(255),
    participant_id UUID,
    speaker_confirmed BOOLEAN NOT NULL DEFAULT false,
    attribution_status VARCHAR(50) NOT NULL DEFAULT 'unknown',
    start_time DOUBLE PRECISION NOT NULL,
    end_time DOUBLE PRECISION NOT NULL,
    text TEXT NOT NULL,
    translated_text TEXT,
    language VARCHAR(50),
    confidence DOUBLE PRECISION,
    words JSONB,
    processing_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Ensure all columns exist on pre-existing tables (idempotent additions)
ALTER TABLE public.transcript_segments
    ADD COLUMN IF NOT EXISTS recording_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS segment_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS user_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS speaker_user_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS participant_id UUID,
    ADD COLUMN IF NOT EXISTS speaker_confirmed BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS attribution_status VARCHAR(50) NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS translated_text TEXT,
    ADD COLUMN IF NOT EXISTS language VARCHAR(50),
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS words JSONB,
    ADD COLUMN IF NOT EXISTS processing_metadata JSONB,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL;

-- 3. Indexes and Unique Constraints
CREATE UNIQUE INDEX IF NOT EXISTS uq_transcript_segment_meeting_segid
    ON public.transcript_segments(meeting_id, segment_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_meeting_id
    ON public.transcript_segments(meeting_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_recording_id
    ON public.transcript_segments(recording_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_segment_id
    ON public.transcript_segments(segment_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_user_id
    ON public.transcript_segments(user_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_user_id
    ON public.transcript_segments(speaker_user_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant_id
    ON public.transcript_segments(participant_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_meeting_start
    ON public.transcript_segments(meeting_id, start_time);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_speaker_user
    ON public.transcript_segments(meeting_id, speaker_user_id);

CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant
    ON public.transcript_segments(meeting_id, participant_id);

-- 4. Row Level Security (RLS)
ALTER TABLE public.transcript_segments ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'transcript_segments'
        AND policyname = 'Users can view transcripts for meetings they hosted or attended'
    ) THEN
        CREATE POLICY "Users can view transcripts for meetings they hosted or attended"
            ON public.transcript_segments FOR SELECT
            USING (
                EXISTS (
                    SELECT 1 FROM public.meetings m
                    WHERE m.public_id = public.transcript_segments.meeting_id
                    AND (
                        m.owner_id = current_setting('request.jwt.claim.sub', true)
                        OR EXISTS (
                            SELECT 1 FROM public.meeting_participants mp
                            WHERE mp.meeting_id = m.public_id
                            AND mp.user_id = current_setting('request.jwt.claim.sub', true)
                        )
                    )
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'transcript_segments'
        AND policyname = 'Meeting participants and hosts can insert transcripts'
    ) THEN
        CREATE POLICY "Meeting participants and hosts can insert transcripts"
            ON public.transcript_segments FOR INSERT
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM public.meetings m
                    WHERE m.public_id = public.transcript_segments.meeting_id
                    AND (
                        m.owner_id = current_setting('request.jwt.claim.sub', true)
                        OR EXISTS (
                            SELECT 1 FROM public.meeting_participants mp
                            WHERE mp.meeting_id = m.public_id
                            AND mp.user_id = current_setting('request.jwt.claim.sub', true)
                        )
                    )
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'transcript_segments'
        AND policyname = 'Meeting participants and hosts can update transcripts'
    ) THEN
        CREATE POLICY "Meeting participants and hosts can update transcripts"
            ON public.transcript_segments FOR UPDATE
            USING (
                EXISTS (
                    SELECT 1 FROM public.meetings m
                    WHERE m.public_id = public.transcript_segments.meeting_id
                    AND (
                        m.owner_id = current_setting('request.jwt.claim.sub', true)
                        OR EXISTS (
                            SELECT 1 FROM public.meeting_participants mp
                            WHERE mp.meeting_id = m.public_id
                            AND mp.user_id = current_setting('request.jwt.claim.sub', true)
                        )
                    )
                )
            );
    END IF;
END
$$;
