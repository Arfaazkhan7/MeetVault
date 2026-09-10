"""Phase 5 file generator — writes all remaining backend files for Meeting Management."""
import pathlib, textwrap

ROOT = pathlib.Path("backend")

files = {}

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS / ENUMS
# ─────────────────────────────────────────────────────────────────────────────
files["app/core/enums.py"] = textwrap.dedent("""
    from enum import Enum

    class MeetingStatus(str, Enum):
        SCHEDULED = "SCHEDULED"
        LIVE      = "LIVE"
        COMPLETED = "COMPLETED"
        CANCELLED = "CANCELLED"

    class ParticipantStatus(str, Enum):
        INVITED = "INVITED"
        JOINED  = "JOINED"
        LEFT    = "LEFT"
        ABSENT  = "ABSENT"

    class MeetingRole(str, Enum):
        HOST     = "HOST"
        ATTENDEE = "ATTENDEE"
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────
files["app/models/meeting.py"] = textwrap.dedent("""
    from sqlalchemy import Column, String, DateTime, Text, Integer, UniqueConstraint
    from sqlalchemy.orm import relationship

    from app.models.base import Base


    class Meeting(Base):
        __tablename__ = "meetings"

        public_id = Column(String, unique=True, index=True, nullable=False)
        company_id = Column(String, nullable=False, index=True)
        project_id = Column(String, nullable=False, index=True)
        title = Column(String, nullable=False)
        description = Column(String, nullable=True)
        
        status = Column(String, nullable=False, default="SCHEDULED")
        
        scheduled_start_time = Column(DateTime(timezone=True), nullable=True)
        start_time = Column(DateTime(timezone=True), nullable=True)
        end_time = Column(DateTime(timezone=True), nullable=True)
        
        deleted_at = Column(DateTime(timezone=True), nullable=True)

        # Future phases
        transcription_status = Column(String, nullable=False, default='pending')
        transcription_error = Column(Text, nullable=True)
        recording_url = Column(String, nullable=True)

        company = relationship(
            "Company",
            primaryjoin="foreign(Meeting.company_id) == Company.public_id",
            viewonly=True,
        )
        project = relationship(
            "Project",
            primaryjoin="foreign(Meeting.project_id) == Project.public_id",
            back_populates="meetings",
        )
        participants = relationship(
            "MeetingParticipant",
            primaryjoin="Meeting.public_id == foreign(MeetingParticipant.meeting_id)",
            back_populates="meeting",
            lazy="dynamic",
            cascade="all, delete-orphan",
        )


    class MeetingParticipant(Base):
        __tablename__ = "meeting_participants"

        __table_args__ = (
            UniqueConstraint("user_id", "meeting_id", name="uq_participant_meeting"),
        )

        user_id = Column(String, nullable=False, index=True)
        meeting_id = Column(String, nullable=False, index=True)
        
        role = Column(String, nullable=False, default="ATTENDEE")
        status = Column(String, nullable=False, default="INVITED")
        
        join_time = Column(DateTime(timezone=True), nullable=True)
        leave_time = Column(DateTime(timezone=True), nullable=True)
        attendance_duration_seconds = Column(Integer, nullable=True)

        meeting = relationship(
            "Meeting",
            primaryjoin="foreign(MeetingParticipant.meeting_id) == Meeting.public_id",
            back_populates="participants",
        )
        user = relationship(
            "User",
            primaryjoin="foreign(MeetingParticipant.user_id) == User.public_id",
        )
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
files["app/schemas/meeting.py"] = textwrap.dedent("""
    from pydantic import BaseModel, field_validator
    from typing import Optional
    from datetime import datetime
    from app.core.enums import MeetingStatus, ParticipantStatus, MeetingRole


    class CreateMeetingRequest(BaseModel):
        title: str
        description: Optional[str] = None
        project_id: str
        scheduled_start_time: Optional[datetime] = None

        @field_validator("title")
        @classmethod
        def title_not_empty(cls, v: str) -> str:
            v = v.strip()
            if not v:
                raise ValueError("Meeting title cannot be blank")
            return v


    class UpdateMeetingRequest(BaseModel):
        title: Optional[str] = None
        description: Optional[str] = None
        status: Optional[MeetingStatus] = None
        scheduled_start_time: Optional[datetime] = None
        start_time: Optional[datetime] = None
        end_time: Optional[datetime] = None


    class MeetingResponse(BaseModel):
        public_id: str
        company_id: str
        project_id: str
        title: str
        description: Optional[str]
        status: str
        scheduled_start_time: Optional[datetime]
        start_time: Optional[datetime]
        end_time: Optional[datetime]
        model_config = {"from_attributes": True}


    class InviteParticipantRequest(BaseModel):
        user_public_id: str
        role: MeetingRole = MeetingRole.ATTENDEE


    class UpdateParticipantStatusRequest(BaseModel):
        status: ParticipantStatus
        join_time: Optional[datetime] = None
        leave_time: Optional[datetime] = None


    class MeetingParticipantResponse(BaseModel):
        user_public_id: str
        meeting_id: str
        role: str
        status: str
        join_time: Optional[datetime]
        leave_time: Optional[datetime]
        attendance_duration_seconds: Optional[int]
        
        # Joined fields
        email: Optional[str] = None
        full_name: Optional[str] = None
        model_config = {"from_attributes": True}
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────────────────────────────────────
files["app/core/meeting_dependencies.py"] = textwrap.dedent("""
    from fastapi import Depends, HTTPException, status
    from sqlalchemy.orm import Session

    from app.db.session import get_db
    from app.core.dependencies import get_current_user, get_membership
    from app.models.user import User
    from app.models.meeting import Meeting
    from app.models.project import Project

    def get_meeting_and_authorize(
        meeting_id: str,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Meeting:
        \"\"\"
        Fetch meeting by ID, ensure user is a member of its company.
        \"\"\"
        meeting = db.query(Meeting).filter(Meeting.public_id == meeting_id, Meeting.deleted_at.is_(None)).first()
        if not meeting:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

        # Must be member of the company to access any meeting within it
        get_membership(db, current_user.public_id, meeting.company_id)
        return meeting

    def require_meeting_host(
        meeting: Meeting = Depends(get_meeting_and_authorize),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Meeting:
        \"\"\"
        Ensure user is HOST of the meeting, or a higher level admin in company/project.
        For now, simply checking if they are HOST in participants.
        \"\"\"
        from app.models.meeting import MeetingParticipant
        participant = db.query(MeetingParticipant).filter(
            MeetingParticipant.meeting_id == meeting.public_id,
            MeetingParticipant.user_id == current_user.public_id
        ).first()

        if not participant or participant.role != "HOST":
            # Check company membership role as fallback? For now require explicit HOST.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires meeting host privileges")

        return meeting
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# SERVICES
# ─────────────────────────────────────────────────────────────────────────────
files["app/services/meeting_service.py"] = textwrap.dedent("""
    from sqlalchemy.orm import Session
    from fastapi import HTTPException, status
    from datetime import datetime, timezone

    from app.models.meeting import Meeting, MeetingParticipant
    from app.models.project import Project
    from app.models.user import User
    from app.core.enums import MeetingStatus, ParticipantStatus, MeetingRole


    def _next_meeting_id(db: Session) -> str:
        count = db.query(Meeting).count() + 1
        return f"MTG-{count:04d}"


    def create_meeting(
        db: Session, 
        company_id: str, 
        project_id: str, 
        title: str, 
        description: str | None, 
        scheduled_start_time: datetime | None,
        creator: User
    ) -> Meeting:
        # Validate project belongs to company
        project = db.query(Project).filter(Project.public_id == project_id, Project.company_id == company_id).first()
        if not project:
            raise HTTPException(status_code=400, detail="Project not found in this company")

        meeting = Meeting(
            public_id=_next_meeting_id(db),
            company_id=company_id,
            project_id=project_id,
            title=title.strip(),
            description=description.strip() if description else None,
            scheduled_start_time=scheduled_start_time,
            status=MeetingStatus.SCHEDULED.value
        )
        db.add(meeting)
        db.flush()

        # Creator becomes HOST and is INVITED/JOINED (let's say INVITED initially)
        member = MeetingParticipant(
            user_id=creator.public_id,
            meeting_id=meeting.public_id,
            role=MeetingRole.HOST.value,
            status=ParticipantStatus.INVITED.value,
        )
        db.add(member)
        db.commit()
        db.refresh(meeting)
        return meeting

    def list_meetings_for_project(db: Session, project_id: str) -> list[Meeting]:
        return db.query(Meeting).filter(
            Meeting.project_id == project_id,
            Meeting.deleted_at.is_(None)
        ).all()

    def update_meeting(db: Session, meeting: Meeting, data: dict) -> Meeting:
        for k, v in data.items():
            if v is not None:
                setattr(meeting, k, v.value if hasattr(v, 'value') else v)
        db.commit()
        db.refresh(meeting)
        return meeting

    def invite_participant(db: Session, meeting: Meeting, user_public_id: str, role: MeetingRole) -> MeetingParticipant:
        existing = db.query(MeetingParticipant).filter(
            MeetingParticipant.user_id == user_public_id,
            MeetingParticipant.meeting_id == meeting.public_id
        ).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already in meeting")
        
        member = MeetingParticipant(
            user_id=user_public_id,
            meeting_id=meeting.public_id,
            role=role.value,
            status=ParticipantStatus.INVITED.value
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    def update_participant_status(
        db: Session, 
        meeting: Meeting, 
        user_public_id: str, 
        status_val: ParticipantStatus,
        join_time: datetime | None,
        leave_time: datetime | None
    ) -> MeetingParticipant:
        participant = db.query(MeetingParticipant).filter(
            MeetingParticipant.user_id == user_public_id,
            MeetingParticipant.meeting_id == meeting.public_id
        ).first()
        
        if not participant:
            raise HTTPException(status_code=404, detail="Participant not found")
            
        participant.status = status_val.value
        if join_time:
            participant.join_time = join_time
        if leave_time:
            participant.leave_time = leave_time
            
        # Calculate duration if both are present
        if participant.join_time and participant.leave_time:
            diff = participant.leave_time - participant.join_time
            participant.attendance_duration_seconds = int(diff.total_seconds())

        db.commit()
        db.refresh(participant)
        return participant

    def list_meeting_participants(db: Session, meeting_id: str) -> list[dict]:
        members = db.query(MeetingParticipant).filter(MeetingParticipant.meeting_id == meeting_id).all()
        user_ids = [m.user_id for m in members]
        users = db.query(User).filter(User.public_id.in_(user_ids)).all()
        user_map = {u.public_id: u for u in users}

        res = []
        for m in members:
            u = user_map.get(m.user_id)
            res.append({
                "user_public_id": m.user_id,
                "meeting_id": m.meeting_id,
                "role": m.role,
                "status": m.status,
                "join_time": m.join_time,
                "leave_time": m.leave_time,
                "attendance_duration_seconds": m.attendance_duration_seconds,
                "email": u.email if u else None,
                "full_name": u.full_name if u else None,
            })
        return res
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
files["app/api/v1/meetings.py"] = textwrap.dedent("""
    from fastapi import APIRouter, Depends, HTTPException, status
    from sqlalchemy.orm import Session
    from typing import Optional

    from app.db.session import get_db
    from app.core.dependencies import get_current_user, require_role, get_membership
    from app.core.meeting_dependencies import get_meeting_and_authorize, require_meeting_host
    from app.core.roles import Role
    from app.models.user import User
    from app.models.meeting import Meeting
    from app.models.company import CompanyMember
    from app.schemas.meeting import (
        CreateMeetingRequest,
        UpdateMeetingRequest,
        MeetingResponse,
        InviteParticipantRequest,
        UpdateParticipantStatusRequest,
        MeetingParticipantResponse,
    )
    from app.services.meeting_service import (
        create_meeting,
        list_meetings_for_project,
        update_meeting,
        invite_participant,
        update_participant_status,
        list_meeting_participants
    )

    router = APIRouter(tags=["meetings"])


    # ── Meeting CRUD ─────────────────────────────────────────────────────────
    @router.post("/companies/{company_id}/meetings", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
    def create_new_meeting(
        company_id: str,
        payload: CreateMeetingRequest,
        current_user: User = Depends(get_current_user),
        membership: CompanyMember = Depends(require_role(Role.MEMBER)),
        db: Session = Depends(get_db),
    ):
        return create_meeting(db, company_id, payload.project_id, payload.title, payload.description, payload.scheduled_start_time, current_user)


    @router.get("/projects/{project_id}/meetings", response_model=list[MeetingResponse])
    def get_project_meetings(
        project_id: str,
        # To access project's meetings, ideally we check project access. For simplicity, we just use the project_id.
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        from app.models.project import Project
        project = db.query(Project).filter(Project.public_id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        get_membership(db, current_user.public_id, project.company_id)
        return list_meetings_for_project(db, project_id)


    @router.get("/meetings/{meeting_id}", response_model=MeetingResponse)
    def get_meeting(
        meeting_id: str,
        meeting: Meeting = Depends(get_meeting_and_authorize),
    ):
        return meeting


    @router.patch("/meetings/{meeting_id}", response_model=MeetingResponse)
    def update_meeting_details(
        meeting_id: str,
        payload: UpdateMeetingRequest,
        meeting: Meeting = Depends(require_meeting_host),
        db: Session = Depends(get_db),
    ):
        return update_meeting(db, meeting, payload.model_dump(exclude_unset=True))


    # ── Participants ─────────────────────────────────────────────────────────
    @router.get("/meetings/{meeting_id}/participants", response_model=list[MeetingParticipantResponse])
    def get_participants(
        meeting_id: str,
        meeting: Meeting = Depends(get_meeting_and_authorize),
        db: Session = Depends(get_db),
    ):
        return list_meeting_participants(db, meeting_id)


    @router.post("/meetings/{meeting_id}/participants", response_model=MeetingParticipantResponse, status_code=status.HTTP_201_CREATED)
    def invite_meeting_participant(
        meeting_id: str,
        payload: InviteParticipantRequest,
        meeting: Meeting = Depends(require_meeting_host),
        db: Session = Depends(get_db),
    ):
        # Validate that user belongs to the company
        try:
            get_membership(db, payload.user_public_id, meeting.company_id)
        except HTTPException:
            raise HTTPException(status_code=400, detail="Participant must belong to the company")
            
        invite_participant(db, meeting, payload.user_public_id, payload.role)
        return list_meeting_participants(db, meeting_id)[-1]


    @router.patch("/meetings/{meeting_id}/participants/{user_public_id}", response_model=MeetingParticipantResponse)
    def update_participant_status_route(
        meeting_id: str,
        user_public_id: str,
        payload: UpdateParticipantStatusRequest,
        meeting: Meeting = Depends(get_meeting_and_authorize),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        # A user can update their own status (e.g. JOINED, LEFT), or HOST can update anyone.
        if current_user.public_id != user_public_id:
            # Need HOST
            require_meeting_host(meeting, current_user, db)
            
        update_participant_status(db, meeting, user_public_id, payload.status, payload.join_time, payload.leave_time)
        
        # return updated record
        parts = list_meeting_participants(db, meeting_id)
        for p in parts:
            if p["user_public_id"] == user_public_id:
                return p
        raise HTTPException(status_code=404)
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — register new routers
# ─────────────────────────────────────────────────────────────────────────────
files["app/main.py"] = textwrap.dedent("""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.config import settings
    from app.api.v1 import health, auth, companies, users, projects, meetings

    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router,     prefix=settings.API_V1_PREFIX)
    app.include_router(auth.router,       prefix=settings.API_V1_PREFIX)
    app.include_router(companies.router,  prefix=settings.API_V1_PREFIX)
    app.include_router(users.router,      prefix=settings.API_V1_PREFIX)
    app.include_router(projects.router,   prefix=settings.API_V1_PREFIX)
    app.include_router(meetings.router,   prefix=settings.API_V1_PREFIX)
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────
files["tests/test_meetings.py"] = textwrap.dedent("""
    \"\"\"Phase 5 - Meeting Management Tests - test DB provided by conftest.py\"\"\"
    from datetime import datetime, timezone

    def register(client, email, name="Test User", password="StrongPass1"):
        r = client.post("/api/v1/auth/register", json={
            "full_name": name, "email": email, "password": password,
        })
        assert r.status_code == 201, r.text
        return r.json()

    def login(client, email, password="StrongPass1"):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def auth_headers(token):
        return {"Authorization": f"Bearer {token}"}

    def setup_scenario(client):
        # A: Company Admin
        admin = register(client, "admin@example.com")
        token = login(client, "admin@example.com")
        comp = client.post("/api/v1/companies", json={"name": "Acme Corp"}, headers=auth_headers(token)).json()
        cid = comp["public_id"]
        
        # B: Normal member
        mem1 = register(client, "mem1@example.com")
        client.post(f"/api/v1/companies/{cid}/members", json={"email": "mem1@example.com", "role": "MEMBER"}, headers=auth_headers(token))
        
        # Project
        proj = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
        
        return token, cid, admin, mem1, proj["public_id"]

    def test_create_meeting(client):
        token, cid, admin, _, pid = setup_scenario(client)
        r = client.post(f"/api/v1/companies/{cid}/meetings", json={
            "title": "Daily Standup",
            "project_id": pid
        }, headers=auth_headers(token))
        assert r.status_code == 201
        m = r.json()
        assert m["title"] == "Daily Standup"
        assert m["status"] == "SCHEDULED"
        assert m["public_id"].startswith("MTG-")
        
        # Creator is HOST
        parts = client.get(f"/api/v1/meetings/{m['public_id']}/participants", headers=auth_headers(token)).json()
        assert len(parts) == 1
        assert parts[0]["user_public_id"] == admin["public_id"]
        assert parts[0]["role"] == "HOST"
        assert parts[0]["status"] == "INVITED"

    def test_update_meeting_status(client):
        token, cid, _, _, pid = setup_scenario(client)
        m = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "M1", "project_id": pid}, headers=auth_headers(token)).json()
        
        r = client.patch(f"/api/v1/meetings/{m['public_id']}", json={"status": "LIVE"}, headers=auth_headers(token))
        assert r.status_code == 200
        assert r.json()["status"] == "LIVE"

    def test_invite_and_status(client):
        token, cid, admin, mem1, pid = setup_scenario(client)
        m = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "M1", "project_id": pid}, headers=auth_headers(token)).json()
        mid = m["public_id"]
        
        # Invite mem1
        r = client.post(f"/api/v1/meetings/{mid}/participants", json={
            "user_public_id": mem1["public_id"],
            "role": "ATTENDEE"
        }, headers=auth_headers(token))
        assert r.status_code == 201
        assert r.json()["status"] == "INVITED"
        
        # mem1 joins meeting
        token_mem1 = login(client, "mem1@example.com")
        now_str = datetime.now(timezone.utc).isoformat()
        
        r2 = client.patch(f"/api/v1/meetings/{mid}/participants/{mem1['public_id']}", json={
            "status": "JOINED",
            "join_time": now_str
        }, headers=auth_headers(token_mem1))
        assert r2.status_code == 200
        assert r2.json()["status"] == "JOINED"

    def test_cross_company_isolation_meetings(client):
        tokenA, cidA, _, _, pidA = setup_scenario(client)
        mA = client.post(f"/api/v1/companies/{cidA}/meetings", json={"title": "M1", "project_id": pidA}, headers=auth_headers(tokenA)).json()
        
        # User B makes Company B
        register(client, "userb@example.com")
        tokenB = login(client, "userb@example.com")
        
        # User B tries to access Meeting A
        r = client.get(f"/api/v1/meetings/{mA['public_id']}", headers=auth_headers(tokenB))
        assert r.status_code == 403

""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# FLUTTER UI (Mock Foundation)
# ─────────────────────────────────────────────────────────────────────────────
files["frontend/lib/features/meetings/meetings_screen.dart"] = textwrap.dedent("""
    // Placeholder for Phase 5 Flutter UI constraint
    import 'package:flutter/material.dart';

    class MeetingsScreen extends StatelessWidget {
      const MeetingsScreen({super.key});

      @override
      Widget build(BuildContext context) {
        return Scaffold(
          appBar: AppBar(title: const Text('Meetings')),
          body: const Center(
            child: Text('Meeting list and scheduling will be implemented here.'),
          ),
          floatingActionButton: FloatingActionButton(
            onPressed: () {},
            child: const Icon(Icons.videocam),
          ),
        );
      }
    }
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# Write all files
# ─────────────────────────────────────────────────────────────────────────────
for rel, content in files.items():
    path = ROOT.parent / rel if rel.startswith("frontend/") else ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote  {path}")

print("done")
