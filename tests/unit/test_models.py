"""
Unit tests for Bifrost domain models.

Tests cover:
    - PermissionType enum
    - PermissionState enum with cycle logic
    - PermissionAssignment with derived fields
    - StagedChange with action derivation
    - DatabaseUser with tag management
    - DatabaseObject with permission applicability
    - AuditEntry with explanation generation
    - Configuration with validation

Run with: pytest tests/unit/test_models.py -v
"""

import pytest
from datetime import datetime, timezone
from src.models.permission import (
    PermissionType,
    PermissionState,
    PermissionAssignment,
    StagedChange,
)
from src.models.user import DatabaseUser
from src.models.db_object import DatabaseObject, ObjectType
from src.models.audit_entry import AuditEntry
from src.models.config import Configuration


class TestPermissionState:
    """Tests for PermissionState enum and cycle logic."""

    def test_state_values(self):
        """Verify all expected state values exist."""
        assert PermissionState.GRANT.value == "GRANT"
        assert PermissionState.DENY.value == "DENY"
        assert PermissionState.NONE.value == "NONE"

    def test_next_state_cycle(self):
        """Verify state cycle: NONE → GRANT → DENY → NONE."""
        assert PermissionState.NONE.next_state() == PermissionState.GRANT
        assert PermissionState.GRANT.next_state() == PermissionState.DENY
        assert PermissionState.DENY.next_state() == PermissionState.NONE

    def test_full_cycle(self):
        """Verify complete cycle returns to original state."""
        state = PermissionState.NONE
        state = state.next_state()  # GRANT
        state = state.next_state()  # DENY
        state = state.next_state()  # NONE
        assert state == PermissionState.NONE


class TestPermissionType:
    """Tests for PermissionType enum."""

    def test_all_permissions_exist(self):
        """Verify all 8 permission types are defined."""
        expected = [
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "EXECUTE",
            "ALTER",
            "REFERENCES",
            "VIEW DEFINITION",
        ]
        actual = [p.value for p in PermissionType]
        assert set(expected) == set(actual)

    def test_dml_permissions(self):
        """Verify DML permissions list."""
        dml = PermissionType.dml_permissions()
        assert PermissionType.SELECT in dml
        assert PermissionType.INSERT in dml
        assert PermissionType.UPDATE in dml
        assert PermissionType.DELETE in dml
        assert PermissionType.EXECUTE not in dml

    def test_executable_permissions(self):
        """Verify executable permissions list."""
        exe = PermissionType.executable_permissions()
        assert PermissionType.EXECUTE in exe
        assert PermissionType.ALTER in exe
        assert PermissionType.VIEW_DEFINITION in exe
        assert PermissionType.SELECT not in exe


class TestPermissionAssignment:
    """Tests for PermissionAssignment dataclass."""

    def test_basic_creation(self):
        """Test basic assignment creation."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=None,
        )
        assert assignment.user_login == "alice"
        assert assignment.committed_state == PermissionState.GRANT

    def test_has_pending_change_false(self):
        """Test has_pending_change when no staged change."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=None,
        )
        assert not assignment.has_pending_change

    def test_has_pending_change_true(self):
        """Test has_pending_change when staged differs from committed."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=PermissionState.DENY,
        )
        assert assignment.has_pending_change

    def test_has_pending_change_same_state(self):
        """Test has_pending_change when staged equals committed."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=PermissionState.GRANT,
        )
        assert not assignment.has_pending_change

    def test_cell_key(self):
        """Test cell_key tuple generation."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.NONE,
        )
        assert assignment.cell_key == ("alice", "dbo", "Orders", PermissionType.SELECT)

    def test_effective_state_committed(self):
        """Test effective_state returns committed when no staged."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=None,
        )
        assert assignment.effective_state == PermissionState.GRANT

    def test_effective_state_staged(self):
        """Test effective_state returns staged when present."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.GRANT,
            staged_state=PermissionState.DENY,
        )
        assert assignment.effective_state == PermissionState.DENY


class TestStagedChange:
    """Tests for StagedChange dataclass."""

    def test_action_grant(self):
        """Test action derivation for GRANT."""
        change = StagedChange(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            previous_state=PermissionState.NONE,
            new_state=PermissionState.GRANT,
        )
        assert change.action == "GRANT"

    def test_action_deny(self):
        """Test action derivation for DENY."""
        change = StagedChange(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            previous_state=PermissionState.GRANT,
            new_state=PermissionState.DENY,
        )
        assert change.action == "DENY"

    def test_action_revoke(self):
        """Test action derivation for REVOKE (new_state=NONE)."""
        change = StagedChange(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            previous_state=PermissionState.GRANT,
            new_state=PermissionState.NONE,
        )
        assert change.action == "REVOKE"

    def test_from_assignment(self):
        """Test StagedChange.from_assignment factory."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.NONE,
            staged_state=PermissionState.GRANT,
        )
        change = StagedChange.from_assignment(assignment)
        assert change.user_login == "alice"
        assert change.previous_state == PermissionState.NONE
        assert change.new_state == PermissionState.GRANT

    def test_from_assignment_no_staged(self):
        """Test from_assignment raises when no staged_state."""
        assignment = PermissionAssignment(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            committed_state=PermissionState.NONE,
            staged_state=None,
        )
        with pytest.raises(ValueError):
            StagedChange.from_assignment(assignment)


class TestDatabaseUser:
    """Tests for DatabaseUser dataclass."""

    def test_basic_creation(self):
        """Test basic user creation."""
        user = DatabaseUser(
            login_name="alice",
            display_name="alice",
            principal_type="S",
            is_disabled=False,
        )
        assert user.login_name == "alice"
        assert user.tags == []

    def test_empty_login_name_raises(self):
        """Test that empty login_name raises ValueError."""
        with pytest.raises(ValueError):
            DatabaseUser(login_name="", display_name="alice", principal_type="S")

    def test_add_tag_valid(self):
        """Test adding valid tag."""
        user = DatabaseUser(login_name="alice", display_name="alice", principal_type="S")
        user.add_tag("finance")
        assert "finance" in user.tags

    def test_add_tag_invalid_format(self):
        """Test adding invalid tag raises ValueError."""
        user = DatabaseUser(login_name="alice", display_name="alice", principal_type="S")
        with pytest.raises(ValueError):
            user.add_tag("bad tag!")

    def test_add_tag_case_insensitive_duplicate(self):
        """Test case-insensitive duplicate detection."""
        user = DatabaseUser(login_name="alice", display_name="alice", principal_type="S")
        user.add_tag("Finance")
        user.add_tag("finance")  # Should not add duplicate
        assert len(user.tags) == 1
        assert user.tags[0] == "Finance"  # Original case preserved

    def test_remove_tag_case_insensitive(self):
        """Test case-insensitive tag removal."""
        user = DatabaseUser(login_name="alice", display_name="alice", principal_type="S")
        user.add_tag("Finance")
        user.remove_tag("FINANCE")
        assert len(user.tags) == 0

    def test_has_tag_case_insensitive(self):
        """Test case-insensitive tag check."""
        user = DatabaseUser(login_name="alice", display_name="alice", principal_type="S")
        user.add_tag("Finance")
        assert user.has_tag("finance")
        assert user.has_tag("FINANCE")


class TestDatabaseObject:
    """Tests for DatabaseObject dataclass."""

    def test_basic_creation(self):
        """Test basic object creation."""
        obj = DatabaseObject(
            schema_name="dbo",
            object_name="Orders",
            object_type=ObjectType.TABLE,
        )
        assert obj.full_name == "dbo.Orders"

    def test_empty_schema_raises(self):
        """Test empty schema_name raises ValueError."""
        with pytest.raises(ValueError):
            DatabaseObject(schema_name="", object_name="Orders", object_type=ObjectType.TABLE)

    def test_empty_object_name_raises(self):
        """Test empty object_name raises ValueError."""
        with pytest.raises(ValueError):
            DatabaseObject(schema_name="dbo", object_name="", object_type=ObjectType.TABLE)

    def test_description_max_length(self):
        """Test description exceeding max length raises ValueError."""
        with pytest.raises(ValueError):
            DatabaseObject(
                schema_name="dbo",
                object_name="Orders",
                object_type=ObjectType.TABLE,
                description="x" * 7501,
            )

    def test_supports_permission_table(self):
        """Test permission applicability for TABLE."""
        obj = DatabaseObject(schema_name="dbo", object_name="Orders", object_type=ObjectType.TABLE)
        assert obj.supports_permission(PermissionType.SELECT)
        assert obj.supports_permission(PermissionType.INSERT)
        assert not obj.supports_permission(PermissionType.EXECUTE)

    def test_supports_permission_procedure(self):
        """Test permission applicability for PROCEDURE."""
        obj = DatabaseObject(
            schema_name="dbo", object_name="GetReport", object_type=ObjectType.PROCEDURE
        )
        assert obj.supports_permission(PermissionType.EXECUTE)
        assert obj.supports_permission(PermissionType.ALTER)
        assert not obj.supports_permission(PermissionType.SELECT)


class TestObjectType:
    """Tests for ObjectType enum."""

    def test_from_sql_type_table(self):
        """Test SQL type 'U' maps to TABLE."""
        assert ObjectType.from_sql_type("U") == ObjectType.TABLE

    def test_from_sql_type_view(self):
        """Test SQL type 'V' maps to VIEW."""
        assert ObjectType.from_sql_type("V") == ObjectType.VIEW

    def test_from_sql_type_procedure(self):
        """Test SQL type 'P' maps to PROCEDURE."""
        assert ObjectType.from_sql_type("P") == ObjectType.PROCEDURE

    def test_from_sql_type_function(self):
        """Test SQL function types map to FUNCTION."""
        assert ObjectType.from_sql_type("FN") == ObjectType.FUNCTION
        assert ObjectType.from_sql_type("IF") == ObjectType.FUNCTION
        assert ObjectType.from_sql_type("TF") == ObjectType.FUNCTION

    def test_from_sql_type_invalid(self):
        """Test invalid SQL type raises ValueError."""
        with pytest.raises(ValueError):
            ObjectType.from_sql_type("X")


class TestAuditEntry:
    """Tests for AuditEntry dataclass."""

    def test_generate_explanation_grant(self):
        """Test explanation generation for GRANT."""
        explanation = AuditEntry.generate_explanation(
            action="GRANT",
            permission_type="SELECT",
            schema_name="dbo",
            object_name="Orders",
            affected_user="alice",
        )
        assert explanation == "GRANT SELECT on dbo.Orders to alice"

    def test_generate_explanation_revoke(self):
        """Test explanation generation for REVOKE uses 'from'."""
        explanation = AuditEntry.generate_explanation(
            action="REVOKE",
            permission_type="DELETE",
            schema_name="dbo",
            object_name="Products",
            affected_user="bob",
        )
        assert explanation == "REVOKE DELETE on dbo.Products from bob"


class TestConfiguration:
    """Tests for Configuration dataclass."""

    def test_valid_config(self):
        """Test valid configuration passes validation."""
        config = Configuration(
            server="SQLSERVER01",
            port=1433,
            database="MyDB",
            schema="dbo",
            auth_type="windows",
        )
        assert config.is_valid()
        assert len(config.validate()) == 0

    def test_empty_server_fails(self):
        """Test empty server fails validation."""
        config = Configuration(server="", database="MyDB")
        errors = config.validate()
        assert any("server" in e for e in errors)

    def test_invalid_port_fails(self):
        """Test invalid port fails validation."""
        config = Configuration(server="localhost", port=99999, database="MyDB")
        errors = config.validate()
        assert any("port" in e for e in errors)

    def test_invalid_schema_format_fails(self):
        """Test invalid schema format fails validation."""
        config = Configuration(server="localhost", database="MyDB", schema="bad-schema")
        errors = config.validate()
        assert any("schema" in e.lower() for e in errors)

    def test_to_dict_excludes_credentials(self):
        """Test to_dict excludes username and password."""
        config = Configuration(
            server="localhost", database="MyDB", username="user", password="pass"
        )
        data = config.to_dict()
        assert "username" not in data
        assert "password" not in data

    def test_from_dict_roundtrip(self):
        """Test serialization round-trip."""
        original = Configuration(server="localhost", port=1433, database="MyDB", schema="dbo")
        data = original.to_dict()
        restored = Configuration.from_dict(data)
        assert restored.server == original.server
        assert restored.database == original.database

    def test_default_config(self):
        """Test default configuration factory."""
        config = Configuration.default()
        assert config.server == ""
        assert config.port == 1433
        assert config.schema == "dbo"
