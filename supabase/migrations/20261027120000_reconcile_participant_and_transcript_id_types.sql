-- ============================================================================
-- Supabase Migration: Reconcile MeetingParticipant and TranscriptSegment ID types
-- Safely aligns meeting_participants.id (UUID) with transcript_segments.participant_id (UUID)
-- Explicitly handles:
--   1. Compatible UUID database (applies gen_random_uuid default, indexes, and FK)
--   2. Existing foreign key constraints under any name (detects and avoids duplicates)
--   3. Missing tables (fresh DB or out-of-order execution, safely handles without errors)
--   4. Legacy BIGINT schema (halts with clear exception and manual migration plan)
--   5. Incompatible column types (halts with clear exception)
-- ============================================================================

SET lock_timeout = '5s';

DO $$
DECLARE
    part_table_exists boolean;
    trans_table_exists boolean;
    part_id_type text;
    trans_part_id_type text;
    existing_fk_name text;
BEGIN
    -- 1. Check existence of tables
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'meeting_participants'
    ) INTO part_table_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'transcript_segments'
    ) INTO trans_table_exists;

    -- 2. Handle missing table states safely (safe for fresh database / out-of-order runs)
    IF NOT part_table_exists AND NOT trans_table_exists THEN
        RAISE NOTICE 'MeetVault migration notice: Neither meeting_participants nor transcript_segments exist yet. Tables will be created with UUID schema by base DDL.';
        RETURN;
    END IF;

    IF NOT part_table_exists THEN
        RAISE NOTICE 'MeetVault migration notice: Table public.meeting_participants is missing. Skipping participant reconciliation until table is created.';
    END IF;

    IF NOT trans_table_exists THEN
        RAISE NOTICE 'MeetVault migration notice: Table public.transcript_segments is missing. Skipping transcript reconciliation until table is created.';
    END IF;

    -- 3. If meeting_participants exists, inspect and reconcile its id column
    IF part_table_exists THEN
        SELECT data_type INTO part_id_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'meeting_participants'
          AND column_name = 'id';

        IF part_id_type IS NULL THEN
            RAISE EXCEPTION 'MeetVault migration halted: Table public.meeting_participants exists but column "id" is missing.';
        END IF;

        -- Explicitly detect legacy BIGINT / integer schema and halt with manual migration plan
        IF part_id_type IN ('bigint', 'integer', 'smallint') THEN
            RAISE EXCEPTION 'MeetVault migration halted: Table public.meeting_participants has column "id" of type "%". The MeetVault application requires UUID IDs. Automatic conversion is halted to preserve existing records and avoid guessing ID mappings. Please consult the manual migration plan in docs/migrations/MIGRATING_BIGINT_PARTICIPANTS.md to migrate legacy integer IDs.', part_id_type;
        ELSIF part_id_type = 'uuid' THEN
            -- Ensure default generator is set to gen_random_uuid()
            ALTER TABLE public.meeting_participants
                ALTER COLUMN id SET DEFAULT gen_random_uuid();
            RAISE NOTICE 'MeetVault migration info: Verified public.meeting_participants.id is UUID and ensured default gen_random_uuid().';
        ELSE
            -- Incompatible / unsupported column type (e.g. varchar, text)
            RAISE EXCEPTION 'MeetVault migration halted: Table public.meeting_participants has column "id" of incompatible type "%". Expected "uuid".', part_id_type;
        END IF;
    END IF;

    -- 4. If transcript_segments exists, inspect and reconcile its participant_id column
    IF trans_table_exists THEN
        SELECT data_type INTO trans_part_id_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'transcript_segments'
          AND column_name = 'participant_id';

        IF trans_part_id_type IS NULL THEN
            ALTER TABLE public.transcript_segments
                ADD COLUMN participant_id UUID;
            RAISE NOTICE 'MeetVault migration info: Added column participant_id UUID to public.transcript_segments.';
        ELSIF trans_part_id_type = 'uuid' THEN
            RAISE NOTICE 'MeetVault migration info: Verified public.transcript_segments.participant_id is UUID.';
        ELSE
            RAISE EXCEPTION 'MeetVault migration halted: Table public.transcript_segments has column "participant_id" of incompatible type "%". Expected "uuid".', trans_part_id_type;
        END IF;

        -- Ensure indexes on participant_id exist
        CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant_id
            ON public.transcript_segments(participant_id);

        CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant
            ON public.transcript_segments(meeting_id, participant_id);
    END IF;

    -- 5. If both tables exist with UUID columns, check for existing foreign key (regardless of name)
    IF part_table_exists AND trans_table_exists AND part_id_type = 'uuid' THEN
        SELECT tc.constraint_name INTO existing_fk_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND tc.table_name = 'transcript_segments'
          AND kcu.column_name = 'participant_id'
          AND ccu.table_name = 'meeting_participants'
          AND ccu.column_name = 'id'
        LIMIT 1;

        IF existing_fk_name IS NOT NULL THEN
            RAISE NOTICE 'MeetVault migration info: Foreign key constraint "%" already exists on public.transcript_segments(participant_id) -> public.meeting_participants(id). Skipping duplicate creation.', existing_fk_name;
        ELSE
            ALTER TABLE public.transcript_segments
                ADD CONSTRAINT fk_transcript_segments_participant_id
                FOREIGN KEY (participant_id)
                REFERENCES public.meeting_participants(id)
                ON DELETE SET NULL;
            RAISE NOTICE 'MeetVault migration success: Added foreign key constraint fk_transcript_segments_participant_id on public.transcript_segments(participant_id) -> public.meeting_participants(id).';
        END IF;
    END IF;
END $$;
