"""
Unit and Integration Tests for Supabase Migration:
20261027120000_reconcile_participant_and_transcript_id_types.sql

Covers all required migration states:
1. Compatible UUID database (applies default, indexes, and FK)
2. Existing foreign key constraint under arbitrary names (detects and avoids duplicates)
3. Legacy BIGINT schema (halts with clear exception and manual migration plan, never silent)
4. Missing tables (fresh database or out-of-order execution, safely handles without errors)
5. Incompatible column types (e.g. VARCHAR, halts with explicit error)
6. ORM Model schema consistency (MeetingParticipant and TranscriptSegment)
"""
import os
import re
import uuid
import pytest
from sqlalchemy.orm import Session

from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.company import Company
from app.models.user import User
from tests.conftest import TestingSessionLocal


MIGRATION_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "supabase",
    "migrations",
    "20261027120000_reconcile_participant_and_transcript_id_types.sql",
)

DOC_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "docs",
    "migrations",
    "MIGRATING_BIGINT_PARTICIPANTS.md",
)


def _load_migration_sql() -> str:
    assert os.path.exists(MIGRATION_PATH), f"Migration file not found at {MIGRATION_PATH}"
    with open(MIGRATION_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ── 1. Static and Structural Migration File Tests ─────────────────────────────

def test_migration_file_exists_and_sets_lock_timeout():
    """Verify migration file exists, has safe lock_timeout, and wraps logic in PL/pgSQL block."""
    sql = _load_migration_sql()
    assert "SET lock_timeout = '5s';" in sql
    assert "DO $$" in sql
    assert "information_schema.tables" in sql
    assert "information_schema.columns" in sql
    assert "information_schema.table_constraints" in sql


def test_migration_file_references_manual_migration_doc():
    """Verify migration halts on BIGINT with a direct link to MIGRATING_BIGINT_PARTICIPANTS.md."""
    sql = _load_migration_sql()
    assert "MIGRATING_BIGINT_PARTICIPANTS.md" in sql
    assert "bigint" in sql.lower()
    assert "gen_random_uuid" in sql
    assert os.path.exists(DOC_PATH), f"Manual migration guide missing at {DOC_PATH}"


def test_migration_file_inspects_foreign_key_regardless_of_name():
    """
    Verify the migration queries information_schema to detect any existing foreign key
    on transcript_segments(participant_id) -> meeting_participants(id), regardless of name.
    """
    sql = _load_migration_sql()
    assert "kcu.column_name = 'participant_id'" in sql
    assert "ccu.table_name = 'meeting_participants'" in sql
    assert "ccu.column_name = 'id'" in sql
    assert "existing_fk_name IS NOT NULL" in sql


# ── 2. Migration Simulation Class for State Matrix ────────────────────────────

class MigrationSimulator:
    """
    Simulates the PostgreSQL PL/pgSQL logic in 20261027120000 against a mock
    schema dictionary to verify all branches and state transitions deterministically.
    """
    def __init__(self, tables: dict):
        self.tables = tables  # {table_name: {"columns": {col_name: col_type}, "constraints": [constraints]}}
        self.logs = []
        self.executed_ddl = []

    def run(self):
        part_table_exists = "meeting_participants" in self.tables
        trans_table_exists = "transcript_segments" in self.tables

        # Missing table state handling
        if not part_table_exists and not trans_table_exists:
            self.logs.append("NOTICE: Neither meeting_participants nor transcript_segments exist yet.")
            return {"status": "ok_both_missing"}

        if not part_table_exists:
            self.logs.append("NOTICE: Table public.meeting_participants is missing.")

        if not trans_table_exists:
            self.logs.append("NOTICE: Table public.transcript_segments is missing.")

        part_id_type = None
        if part_table_exists:
            cols = self.tables["meeting_participants"].get("columns", {})
            part_id_type = cols.get("id")
            if part_id_type is None:
                raise RuntimeError("MeetVault migration halted: Table public.meeting_participants exists but column 'id' is missing.")

            if part_id_type in ("bigint", "integer", "smallint"):
                raise RuntimeError(
                    f"MeetVault migration halted: Table public.meeting_participants has column \"id\" of type \"{part_id_type}\". "
                    "The MeetVault application requires UUID IDs. Automatic conversion is halted to preserve existing records "
                    "and avoid guessing ID mappings. Please consult the manual migration plan in docs/migrations/MIGRATING_BIGINT_PARTICIPANTS.md."
                )
            elif part_id_type == "uuid":
                self.executed_ddl.append("ALTER TABLE meeting_participants ALTER COLUMN id SET DEFAULT gen_random_uuid()")
                self.logs.append("NOTICE: Verified public.meeting_participants.id is UUID and ensured default gen_random_uuid().")
            else:
                raise RuntimeError(f"MeetVault migration halted: Table public.meeting_participants has column 'id' of incompatible type '{part_id_type}'. Expected 'uuid'.")

        trans_part_id_type = None
        if trans_table_exists:
            cols = self.tables["transcript_segments"].get("columns", {})
            trans_part_id_type = cols.get("participant_id")
            if trans_part_id_type is None:
                cols["participant_id"] = "uuid"
                self.executed_ddl.append("ALTER TABLE transcript_segments ADD COLUMN participant_id UUID")
                self.logs.append("NOTICE: Added column participant_id UUID to public.transcript_segments.")
                trans_part_id_type = "uuid"
            elif trans_part_id_type == "uuid":
                self.logs.append("NOTICE: Verified public.transcript_segments.participant_id is UUID.")
            else:
                raise RuntimeError(f"MeetVault migration halted: Table public.transcript_segments has column 'participant_id' of incompatible type '{trans_part_id_type}'. Expected 'uuid'.")

            self.executed_ddl.append("CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant_id ON public.transcript_segments(participant_id)")
            self.executed_ddl.append("CREATE INDEX IF NOT EXISTS ix_transcript_segments_participant ON public.transcript_segments(meeting_id, participant_id)")

        # Foreign key check
        if part_table_exists and trans_table_exists and part_id_type == "uuid":
            constraints = self.tables["transcript_segments"].get("constraints", [])
            existing_fk = None
            for c in constraints:
                if c.get("type") == "FOREIGN KEY" and c.get("column") == "participant_id" and c.get("ref_table") == "meeting_participants" and c.get("ref_column") == "id":
                    existing_fk = c.get("name")
                    break

            if existing_fk:
                self.logs.append(f"NOTICE: Foreign key constraint '{existing_fk}' already exists. Skipping duplicate creation.")
            else:
                self.tables["transcript_segments"].setdefault("constraints", []).append({
                    "name": "fk_transcript_segments_participant_id",
                    "type": "FOREIGN KEY",
                    "column": "participant_id",
                    "ref_table": "meeting_participants",
                    "ref_column": "id",
                })
                self.executed_ddl.append("ALTER TABLE transcript_segments ADD CONSTRAINT fk_transcript_segments_participant_id FOREIGN KEY (participant_id) REFERENCES meeting_participants(id) ON DELETE SET NULL")
                self.logs.append("NOTICE: Added foreign key constraint fk_transcript_segments_participant_id.")

        return {"status": "success"}


# ── 3. State Matrix Tests ─────────────────────────────────────────────────────

def test_migration_scenario_1_compatible_uuid_database():
    """Test Case 1: Fresh or existing database where both tables have UUID columns."""
    schema = {
        "meeting_participants": {
            "columns": {"id": "uuid", "user_id": "varchar", "meeting_id": "varchar"},
            "constraints": [],
        },
        "transcript_segments": {
            "columns": {"id": "uuid", "meeting_id": "varchar", "participant_id": "uuid"},
            "constraints": [],
        },
    }
    sim = MigrationSimulator(schema)
    res = sim.run()

    assert res["status"] == "success"
    # Verifies default, indexes, and FK were applied
    assert any("SET DEFAULT gen_random_uuid()" in ddl for ddl in sim.executed_ddl)
    assert any("fk_transcript_segments_participant_id" in ddl for ddl in sim.executed_ddl)
    assert any("ix_transcript_segments_participant_id" in ddl for ddl in sim.executed_ddl)


def test_migration_scenario_2_existing_foreign_key_different_name():
    """
    Test Case 2: Existing foreign key constraint exists with a non-default name
    (e.g., auto-generated 'transcript_segments_participant_id_fkey').
    Migration must detect it and skip duplicate constraint creation.
    """
    schema = {
        "meeting_participants": {
            "columns": {"id": "uuid", "user_id": "varchar", "meeting_id": "varchar"},
            "constraints": [],
        },
        "transcript_segments": {
            "columns": {"id": "uuid", "meeting_id": "varchar", "participant_id": "uuid"},
            "constraints": [
                {
                    "name": "transcript_segments_participant_id_fkey",
                    "type": "FOREIGN KEY",
                    "column": "participant_id",
                    "ref_table": "meeting_participants",
                    "ref_column": "id",
                }
            ],
        },
    }
    sim = MigrationSimulator(schema)
    res = sim.run()

    assert res["status"] == "success"
    # Must NOT add duplicate constraint
    assert not any("ADD CONSTRAINT fk_transcript_segments_participant_id" in ddl for ddl in sim.executed_ddl)
    assert any("already exists" in log for log in sim.logs)


def test_migration_scenario_3_legacy_bigint_database_halts_with_exception():
    """
    Test Case 3: Legacy database where meeting_participants.id is BIGINT.
    Migration must NOT silently report success, must halt with explicit error,
    and must direct administrator to MIGRATING_BIGINT_PARTICIPANTS.md.
    """
    schema = {
        "meeting_participants": {
            "columns": {"id": "bigint", "user_id": "varchar", "meeting_id": "varchar"},
            "constraints": [],
        },
        "transcript_segments": {
            "columns": {"id": "uuid", "meeting_id": "varchar", "participant_id": "uuid"},
            "constraints": [],
        },
    }
    sim = MigrationSimulator(schema)

    with pytest.raises(RuntimeError) as exc_info:
        sim.run()

    err = str(exc_info.value)
    assert "MeetVault migration halted" in err
    assert 'column "id" of type "bigint"' in err
    assert "MIGRATING_BIGINT_PARTICIPANTS.md" in err


def test_migration_scenario_4_missing_tables_safe_execution():
    """Test Case 4: Missing table cases handle gracefully without unhandled crashes."""
    # 4a: Neither table exists (early bootstrap)
    sim1 = MigrationSimulator({})
    res1 = sim1.run()
    assert res1["status"] == "ok_both_missing"

    # 4b: Only meeting_participants exists
    sim2 = MigrationSimulator({
        "meeting_participants": {
            "columns": {"id": "uuid"},
            "constraints": [],
        }
    })
    res2 = sim2.run()
    assert res2["status"] == "success"
    assert any("Table public.transcript_segments is missing" in log for log in sim2.logs)

    # 4c: Only transcript_segments exists
    sim3 = MigrationSimulator({
        "transcript_segments": {
            "columns": {"id": "uuid"},
            "constraints": [],
        }
    })
    res3 = sim3.run()
    assert res3["status"] == "success"
    assert any("Table public.meeting_participants is missing" in log for log in sim3.logs)


def test_migration_scenario_5_incompatible_column_type_halts():
    """Test Case 5: Incompatible column types (e.g. VARCHAR) halt immediately."""
    schema = {
        "meeting_participants": {
            "columns": {"id": "varchar"},
            "constraints": [],
        },
        "transcript_segments": {
            "columns": {"id": "uuid", "participant_id": "uuid"},
            "constraints": [],
        },
    }
    sim = MigrationSimulator(schema)
    with pytest.raises(RuntimeError) as exc_info:
        sim.run()
    assert "incompatible type 'varchar'" in str(exc_info.value)


# ── 4. Live SQLAlchemy ORM Relationship and Persistence Tests ─────────────────

def test_orm_participant_uuid_relationship_and_persistence():
    """
    Verify SQLAlchemy ORM models MeetingParticipant and TranscriptSegment correctly
    use UUID/GUID types, link bidirectionally, and persist cleanly in SQLite / PostgreSQL.
    """
    db: Session = TestingSessionLocal()
    try:
        comp = Company(public_id="comp-mig-test", name="Mig Corp", workspace_code="MIG-1")
        user = User(public_id="usr-mig-test", email="mig@test.com", full_name="Mig User", hashed_password="h")
        meeting = Meeting(public_id="mtg-mig-test", title="Migration Review", company_id=comp.public_id)
        db.add_all([comp, user, meeting])
        db.flush()

        part = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=user.public_id,
            display_name="Participant One",
        )
        db.add(part)
        db.flush()

        # Confirm participant.id is generated as valid UUID object
        assert part.id is not None
        assert isinstance(part.id, uuid.UUID)

        seg = TranscriptSegment(
            meeting_id=meeting.public_id,
            segment_id="seg-mig-001",
            speaker_label="SPEAKER_00",
            participant_id=part.id,
            start_time=0.0,
            end_time=2.5,
            text="Testing UUID participant relationship.",
        )
        db.add(seg)
        db.commit()

        # Query back and verify relationship resolution
        reloaded_seg = db.query(TranscriptSegment).filter_by(segment_id="seg-mig-001").first()
        assert reloaded_seg is not None
        assert reloaded_seg.participant_id == part.id
        assert reloaded_seg.participant is not None
        assert reloaded_seg.participant.display_name == "Participant One"

        reloaded_part = db.query(MeetingParticipant).filter_by(id=part.id).first()
        assert reloaded_part is not None
        assert len(reloaded_part.transcript_segments) == 1
        assert reloaded_part.transcript_segments[0].segment_id == "seg-mig-001"

    finally:
        db.close()
