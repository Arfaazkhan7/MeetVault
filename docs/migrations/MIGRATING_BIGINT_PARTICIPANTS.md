# MeetVault Manual Migration Guide: Legacy BIGINT to UUID Participant Schema

## Overview
MeetVault's backend application models ([backend/app/models/meeting.py](file:///backend/app/models/meeting.py)), transcription engine, LiveKit identity services, and Supabase Row Level Security (RLS) policies require `meeting_participants.id` and `transcript_segments.participant_id` to be of type `UUID`.

When executing migration `20261027120000_reconcile_participant_and_transcript_id_types.sql`, if the target database contains a legacy `meeting_participants.id` column of type `BIGINT`, `BIGSERIAL`, or `INTEGER`, the migration **intentionally halts** with an explicit exception:

```text
MeetVault migration halted: Table public.meeting_participants has column "id" of type "bigint".
The MeetVault application requires UUID IDs. Automatic conversion is halted to preserve existing
records and avoid guessing ID mappings.
```

This safety check prevents data loss, broken external integrations, and silent schema inconsistencies caused by automated guessing of ID remappings.

---

## Step-by-Step Manual Migration Procedure

Follow these steps during a scheduled maintenance window if you have a legacy database with integer participant IDs:

### Step 1: Create a Full Database Backup
Before performing schema alterations, export a full snapshot:
```bash
pg_dump -h <host> -U <user> -d <database> -F c -b -v -f meetvault_pre_uuid_migration.dump
```

### Step 2: Inspect Dependent Records
Verify current participant and transcript segment counts:
```sql
SELECT count(*) AS participant_count FROM public.meeting_participants;
SELECT count(*) AS transcript_count FROM public.transcript_segments WHERE participant_id IS NOT NULL;
```

### Step 3: Add Temporary UUID Column and Generate Mappings
Add a new UUID column to `meeting_participants` and assign a deterministic or unique UUID to each existing row:
```sql
BEGIN;

-- Add a new UUID column with default generator
ALTER TABLE public.meeting_participants
    ADD COLUMN uuid_id UUID DEFAULT gen_random_uuid();

-- Populate existing rows with unique UUIDs
UPDATE public.meeting_participants
    SET uuid_id = gen_random_uuid()
    WHERE uuid_id IS NULL;

ALTER TABLE public.meeting_participants
    ALTER COLUMN uuid_id SET NOT NULL;

COMMIT;
```

### Step 4: Map References in Dependent Tables
If `transcript_segments` or other tables contain legacy integer references to `meeting_participants.id`, update them using the newly mapped `uuid_id`:
```sql
BEGIN;

-- If transcript_segments has an old bigint participant reference column (e.g. legacy_part_id)
-- update participant_id UUID using the mapping:
UPDATE public.transcript_segments ts
SET participant_id = mp.uuid_id
FROM public.meeting_participants mp
WHERE ts.participant_id::text = mp.id::text;

COMMIT;
```

### Step 5: Switch Primary Key on `meeting_participants`
Swap the legacy `id` column with the new `uuid_id` column:
```sql
BEGIN;

-- Drop dependent constraints on old id if any
ALTER TABLE public.meeting_participants
    DROP CONSTRAINT IF EXISTS meeting_participants_pkey CASCADE;

-- Rename columns
ALTER TABLE public.meeting_participants
    RENAME COLUMN id TO legacy_bigint_id;

ALTER TABLE public.meeting_participants
    RENAME COLUMN uuid_id TO id;

-- Add new primary key
ALTER TABLE public.meeting_participants
    ADD PRIMARY KEY (id);

-- Ensure default UUID generation for all future inserts
ALTER TABLE public.meeting_participants
    ALTER COLUMN id SET DEFAULT gen_random_uuid();

COMMIT;
```

### Step 6: Add Foreign Key Constraint
Re-attach foreign key constraint from `transcript_segments(participant_id)` to `meeting_participants(id)`:
```sql
ALTER TABLE public.transcript_segments
    ADD CONSTRAINT fk_transcript_segments_participant_id
    FOREIGN KEY (participant_id)
    REFERENCES public.meeting_participants(id)
    ON DELETE SET NULL;
```

### Step 7: Verify Migration
Run the automated MeetVault backend test suite:
```bash
python -m pytest tests/test_migration_participant_id_reconciliation.py tests/test_stage6_end_to_end_and_performance.py
```
After confirming application functionality, the archived column `legacy_bigint_id` may be dropped or retained for auditing.
