-- ============================================================================
-- Supabase Schema & Row Level Security (RLS) Policies
-- MeetVault Permanent Account-Based Cloud Meeting History System
-- ============================================================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    public_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    full_name VARCHAR(255),
    phone VARCHAR(255),
    avatar_url TEXT,
    account_type VARCHAR(50) NOT NULL DEFAULT 'personal',
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on Users
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own record"
    ON public.users FOR SELECT
    USING (public_id = current_setting('request.jwt.claim.sub', true) OR email = current_setting('request.jwt.claim.email', true));

CREATE POLICY "Users can update their own record"
    ON public.users FOR UPDATE
    USING (public_id = current_setting('request.jwt.claim.sub', true));

-- 2. Meetings Table
CREATE TABLE IF NOT EXISTS public.meetings (
    id BIGSERIAL PRIMARY KEY,
    public_id VARCHAR(255) UNIQUE NOT NULL,
    company_id VARCHAR(255),
    project_id VARCHAR(255),
    owner_id VARCHAR(255) REFERENCES public.users(public_id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    meeting_type VARCHAR(50) NOT NULL DEFAULT 'PERSONAL',
    status VARCHAR(50) NOT NULL DEFAULT 'SCHEDULED',
    invite_code VARCHAR(50) UNIQUE,
    scheduled_start_time TIMESTAMP WITH TIME ZONE,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    transcription_status VARCHAR(50) DEFAULT 'pending',
    transcription_error TEXT,
    recording_url TEXT,
    analysis_status VARCHAR(50) DEFAULT 'pending',
    analysis_error TEXT,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on Meetings
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;

-- Owner or Participant can view meeting history
CREATE POLICY "Users can view meetings they hosted or participated in"
    ON public.meetings FOR SELECT
    USING (
        owner_id = current_setting('request.jwt.claim.sub', true) OR
        EXISTS (
            SELECT 1 FROM public.meeting_participants mp
            WHERE mp.meeting_id = public.meetings.public_id
            AND mp.user_id = current_setting('request.jwt.claim.sub', true)
        )
    );

CREATE POLICY "Owners can insert their meetings"
    ON public.meetings FOR INSERT
    WITH CHECK (owner_id = current_setting('request.jwt.claim.sub', true));

CREATE POLICY "Owners can update their meetings"
    ON public.meetings FOR UPDATE
    USING (owner_id = current_setting('request.jwt.claim.sub', true));

-- 3. Meeting Participants Table
CREATE TABLE IF NOT EXISTS public.meeting_participants (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES public.users(public_id) ON DELETE CASCADE,
    meeting_id VARCHAR(255) NOT NULL REFERENCES public.meetings(public_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'ATTENDEE',
    status VARCHAR(50) NOT NULL DEFAULT 'INVITED',
    join_time TIMESTAMP WITH TIME ZONE,
    leave_time TIMESTAMP WITH TIME ZONE,
    attendance_duration_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    CONSTRAINT uq_participant_meeting UNIQUE(user_id, meeting_id)
);

-- Enable RLS on Meeting Participants
ALTER TABLE public.meeting_participants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view participants for meetings they hosted or attended"
    ON public.meeting_participants FOR SELECT
    USING (
        user_id = current_setting('request.jwt.claim.sub', true) OR
        EXISTS (
            SELECT 1 FROM public.meetings m
            WHERE m.public_id = public.meeting_participants.meeting_id
            AND (m.owner_id = current_setting('request.jwt.claim.sub', true) OR EXISTS (
                SELECT 1 FROM public.meeting_participants mp_inner
                WHERE mp_inner.meeting_id = m.public_id AND mp_inner.user_id = current_setting('request.jwt.claim.sub', true)
            ))
        )
    );

CREATE POLICY "Users can insert their participation"
    ON public.meeting_participants FOR INSERT
    WITH CHECK (user_id = current_setting('request.jwt.claim.sub', true));

CREATE POLICY "Users can update their participation"
    ON public.meeting_participants FOR UPDATE
    USING (user_id = current_setting('request.jwt.claim.sub', true));

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_users_public_id ON public.users(public_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_meetings_owner ON public.meetings(owner_id);
CREATE INDEX IF NOT EXISTS idx_meetings_invite_code ON public.meetings(invite_code);
CREATE INDEX IF NOT EXISTS idx_participants_user ON public.meeting_participants(user_id);
CREATE INDEX IF NOT EXISTS idx_participants_meeting ON public.meeting_participants(meeting_id);
