-- ============================================================================
-- Supabase Migration: Reconcile MeetingParticipant and TranscriptSegment ID types
-- Safely aligns meeting_participants.id (UUID) with transcript_segments.participant_id (UUID)
-- Preserves existing rows, handles both fresh setups and pre-existing tables.
-- ============================================================================

SET lock_timeout = '5s';

DO $$
DECLARE
    part_id_type text;
BEGIN
    -- Check the data type of meeting_participants.id if table exists
    SELECT data_type INTO part_id_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'meeting_participants'
      AND column_name = 'id';

    -- If meeting_participants table exists and id is uuid, ensure default is gen_random_uuid()
    IF part_id_type = 'uuid' THEN
        ALTER TABLE public.meeting_participants
            ALTER COLUMN id SET DEFAULT gen_random_uuid();
    END IF;

    -- Ensure transcript_segments has participant_id column of type UUID
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'transcript_segments'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'transcript_segments'
              AND column_name = 'participant_id'
        ) THEN
            ALTER TABLE public.transcript_segments
                ADD COLUMN participant_id UUID;
        END IF;

        -- Ensure index on participant_id
        CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant_id
            ON public.transcript_segments(participant_id);

        CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant
            ON public.transcript_segments(meeting_id, participant_id);

        -- Safely add foreign key constraint only if meeting_participants.id is UUID and constraint does not exist
        IF part_id_type = 'uuid' AND NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name = 'transcript_segments'
              AND constraint_name = 'fk_transcript_segments_participant_id'
        ) THEN
            ALTER TABLE public.transcript_segments
                ADD CONSTRAINT fk_transcript_segments_participant_id
                FOREIGN KEY (participant_id)
                REFERENCES public.meeting_participants(id)
                ON DELETE SET NULL;
        END IF;
    END IF;
END $$;
