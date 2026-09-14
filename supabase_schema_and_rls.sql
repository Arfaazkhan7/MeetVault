-- ============================================================================
-- Supabase Schema & Row Level Security (RLS) Policies
-- MeetVault Permanent Account-Based Cloud Meeting History System
-- ============================================================================

-- 1. Profiles Table (Linked to Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    account_type TEXT DEFAULT 'personal',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on Profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update their own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- 2. Meetings Table
CREATE TABLE IF NOT EXISTS public.meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    host_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    meeting_type TEXT DEFAULT 'PERSONAL',
    status TEXT DEFAULT 'SCHEDULED',
    invite_code TEXT UNIQUE,
    scheduled_start_time TIMESTAMP WITH TIME ZONE,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS on Meetings
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;

-- Host can view their hosted meetings
CREATE POLICY "Host can view meetings they hosted"
    ON public.meetings FOR SELECT
    USING (auth.uid() = host_user_id);

-- Host can create meetings
CREATE POLICY "Host can create meetings"
    ON public.meetings FOR INSERT
    WITH CHECK (auth.uid() = host_user_id);

-- Host can update their meetings
CREATE POLICY "Host can update their meetings"
    ON public.meetings FOR UPDATE
    USING (auth.uid() = host_user_id);

-- Participants can view meetings they participated in
CREATE POLICY "Participants can view meetings they attended"
    ON public.meetings FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.meeting_participants mp
            WHERE mp.meeting_id = public.meetings.id
            AND mp.user_id = auth.uid()
        )
    );

-- 3. Meeting Participants Table
CREATE TABLE IF NOT EXISTS public.meeting_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES public.meetings(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'ATTENDEE',
    status TEXT NOT NULL DEFAULT 'INVITED',
    join_time TIMESTAMP WITH TIME ZONE,
    leave_time TIMESTAMP WITH TIME ZONE,
    attendance_duration_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(meeting_id, user_id)
);

-- Enable RLS on Meeting Participants
ALTER TABLE public.meeting_participants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view participants for meetings they hosted or attended"
    ON public.meeting_participants FOR SELECT
    USING (
        auth.uid() = user_id OR
        EXISTS (
            SELECT 1 FROM public.meetings m
            WHERE m.id = public.meeting_participants.meeting_id
            AND (m.host_user_id = auth.uid() OR EXISTS (
                SELECT 1 FROM public.meeting_participants mp_inner
                WHERE mp_inner.meeting_id = m.id AND mp_inner.user_id = auth.uid()
            ))
        )
    );

CREATE POLICY "Users can insert their own participation"
    ON public.meeting_participants FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own participation"
    ON public.meeting_participants FOR UPDATE
    USING (auth.uid() = user_id);

-- Indexes for optimal performance
CREATE INDEX IF NOT EXISTS idx_meetings_host ON public.meetings(host_user_id);
CREATE INDEX IF NOT EXISTS idx_meetings_code ON public.meetings(invite_code);
CREATE INDEX IF NOT EXISTS idx_participants_user ON public.meeting_participants(user_id);
CREATE INDEX IF NOT EXISTS idx_participants_meeting ON public.meeting_participants(meeting_id);
