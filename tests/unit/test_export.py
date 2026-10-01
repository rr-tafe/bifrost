"""
Unit tests for Bifrost export service.

Tests cover:
    - export_permissions_csv()
    - export_audit_csv()
    - get_suggested_filename()
    - Progress callback invocation
    - Error handling

Run with: pytest tests/unit/test_export.py -v
"""

import pytest
import csv
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from src.services.export import (
    export_permissions_csv,
    export_audit_csv,
    get_suggested_filename,
)
from src.models.user import DatabaseUser
from src.models.db_object import DatabaseObject, ObjectType
from src.models.permission import (
    PermissionType,
    PermissionState,
    PermissionAssignment,
)
from src.models.audit_entry import AuditEntry


class TestExportPermissionsCsv:
    """Tests for permission matrix CSV export."""

    def test_export_basic(self):
        """Test basic CSV export with GRANT permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "permissions.csv"

            users = [DatabaseUser(login_name="alice", display_name="alice", principal_type="S")]
            objects = [
                DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
            ]

            # Create assignment with GRANT
            cell_key = ("alice", "dbo", "Orders", PermissionType.SELECT)
            assignments = {
                cell_key: PermissionAssignment(
                    user_login="alice",
                    schema_name="dbo",
                    object_name="Orders",
                    permission_type=PermissionType.SELECT,
                    committed_state=PermissionState.GRANT,
                )
            }

            result = export_permissions_csv(
                file_path=path,
                users=users,
                objects=objects,
                assignments=assignments,
                include_none=False,
            )

            assert result is None  # No error
            assert path.exists()

            # Verify CSV content
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have the GRANT row
            assert len(rows) >= 1
            grant_row = next((r for r in rows if r["Permission"] == "SELECT"), None)
            assert grant_row is not None
            assert grant_row["User"] == "alice"
            assert grant_row["State"] == "GRANT"

    def test_export_exclude_none(self):
        """Test that NONE states are excluded by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "permissions.csv"

            users = [DatabaseUser(login_name="alice", display_name="alice", principal_type="S")]
            objects = [
                DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
            ]

            # Create assignment with NONE state
            cell_key = ("alice", "dbo", "Orders", PermissionType.SELECT)
            assignments = {
                cell_key: PermissionAssignment(
                    user_login="alice",
                    schema_name="dbo",
                    object_name="Orders",
                    permission_type=PermissionType.SELECT,
                    committed_state=PermissionState.NONE,
                )
            }

            export_permissions_csv(
                file_path=path,
                users=users,
                objects=objects,
                assignments=assignments,
                include_none=False,
            )

            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should be empty (NONE excluded)
            assert len(rows) == 0

    def test_export_include_none(self):
        """Test that NONE states can be included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "permissions.csv"

            users = [DatabaseUser(login_name="alice", display_name="alice", principal_type="S")]
            objects = [
                DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
            ]

            # Create assignment with NONE state
            cell_key = ("alice", "dbo", "Orders", PermissionType.SELECT)
            assignments = {
                cell_key: PermissionAssignment(
                    user_login="alice",
                    schema_name="dbo",
                    object_name="Orders",
                    permission_type=PermissionType.SELECT,
                    committed_state=PermissionState.NONE,
                )
            }

            export_permissions_csv(
                file_path=path,
                users=users,
                objects=objects,
                assignments=assignments,
                include_none=True,
            )

            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Should have the NONE row
            none_row = next((r for r in rows if r["Permission"] == "SELECT"), None)
            assert none_row is not None
            assert none_row["State"] == "NONE"

    def test_export_staged_change_indicator(self):
        """Test that staged changes are indicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "permissions.csv"

            users = [DatabaseUser(login_name="alice", display_name="alice", principal_type="S")]
            objects = [
                DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
            ]

            # Create assignment with staged change
            cell_key = ("alice", "dbo", "Orders", PermissionType.SELECT)
            assignments = {
                cell_key: PermissionAssignment(
                    user_login="alice",
                    schema_name="dbo",
                    object_name="Orders",
                    permission_type=PermissionType.SELECT,
                    committed_state=PermissionState.NONE,
                    staged_state=PermissionState.GRANT,
                )
            }

            export_permissions_csv(
                file_path=path,
                users=users,
                objects=objects,
                assignments=assignments,
                include_none=True,
            )

            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            select_row = next((r for r in rows if r["Permission"] == "SELECT"), None)
            assert select_row is not None
            # State should show effective state (staged)
            assert select_row["State"] == "GRANT"
            assert select_row["HasStagedChange"] == "True"

    def test_export_progress_callback(self):
        """Test that progress callback is invoked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "permissions.csv"

            users = [DatabaseUser(login_name="alice", display_name="alice", principal_type="S")]
            objects = [
                DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
            ]

            progress_calls = []

            def callback(current, total):
                progress_calls.append((current, total))

            export_permissions_csv(
                file_path=path,
                users=users,
                objects=objects,
                assignments={},
                progress_callback=callback,
            )

            # Should have progress calls
            assert len(progress_calls) > 0


class TestExportAuditCsv:
    """Tests for audit log CSV export."""

    def test_export_audit_basic(self):
        """Test basic audit log export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.csv"

            entries = [
                AuditEntry(
                    id=1,
                    administrator="DOMAIN\\admin",
                    affected_user="alice",
                    schema_name="dbo",
                    object_name="Orders",
                    permission_type="SELECT",
                    action="GRANT",
                    previous_state="NONE",
                    new_state="GRANT",
                    changed_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
                    explanation="GRANT SELECT on dbo.Orders to alice",
                )
            ]

            result = export_audit_csv(file_path=path, entries=entries)

            assert result is None  # No error
            assert path.exists()

            # Verify CSV content
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 1
            row = rows[0]
            assert row["Administrator"] == "DOMAIN\\admin"
            assert row["AffectedUser"] == "alice"
            assert row["Action"] == "GRANT"
            assert row["Permission"] == "SELECT"

    def test_export_audit_empty(self):
        """Test exporting empty audit log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.csv"

            result = export_audit_csv(file_path=path, entries=[])

            assert result is None
            assert path.exists()

            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Header only, no data rows
            assert len(rows) == 0


class TestGetSuggestedFilename:
    """Tests for suggested filename generation."""

    def test_permissions_filename(self):
        """Test permissions export filename format."""
        filename = get_suggested_filename("permissions", "TestDB")
        assert "Bifrost" in filename
        assert "permissions" in filename
        assert "TestDB" in filename
        assert filename.endswith(".csv")

    def test_audit_filename(self):
        """Test audit export filename format."""
        filename = get_suggested_filename("audit", "ProdDB")
        assert "audit" in filename
        assert "ProdDB" in filename

    def test_filename_contains_date(self):
        """Test filename contains current date."""
        filename = get_suggested_filename("permissions", "TestDB")
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in filename
