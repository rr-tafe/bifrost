"""
Audit log entry domain model for Bifrost.

This module defines the AuditEntry dataclass representing an immutable record
of a committed permission change.

Audit entries are stored in SQL Server (<schema>.Bifrost_audit_log) and shared
across all administrators connecting to the database.

Usage:
    entry = AuditEntry(
        id=1,
        administrator="DOMAIN\\alice",
        affected_user="bob",
        schema_name="dbo",
        object_name="Orders",
        permission_type="SELECT",
        action="GRANT",
        previous_state="NONE",
        new_state="GRANT",
        changed_at=datetime.now(timezone.utc),
        explanation="GRANT SELECT on dbo.Orders to bob"
    )
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditEntry:
    """
    Immutable record of a single committed permission change.

    Attributes:
        id: Auto-generated primary key (BIGINT IDENTITY)
        administrator: SQL Server identity of the connected admin (SYSTEM_USER)
        affected_user: Database principal whose permission changed
        schema_name: Schema of the target object
        object_name: Name of the target object
        permission_type: Permission that changed (e.g., SELECT, EXECUTE)
        action: T-SQL keyword applied (GRANT, DENY, or REVOKE)
        previous_state: State before the change (GRANT, DENY, or NONE)
        new_state: State after the change (GRANT, DENY, or NONE)
        changed_at: UTC timestamp when change was committed (set by SQL Server)
        explanation: Auto-generated description of the change

    Explanation format (FR-012):
        "{action} {permission_type} on {schema}.{object_name} to {affected_user}"

        Examples:
            "GRANT SELECT on dbo.Orders to alice"
            "REVOKE DELETE on dbo.Products from mjones"
            "DENY EXECUTE on dbo.GetReportData to guest"

    Table: <config.schema>.Bifrost_audit_log

    Action derivation:
        - new_state = GRANT → action = "GRANT"
        - new_state = DENY → action = "DENY"
        - new_state = NONE → action = "REVOKE"
    """

    id: int
    administrator: str
    affected_user: str
    schema_name: str
    object_name: str
    permission_type: str
    action: str  # GRANT | DENY | REVOKE
    previous_state: str  # GRANT | DENY | NONE
    new_state: str  # GRANT | DENY | NONE
    changed_at: datetime
    explanation: str

    @classmethod
    def generate_explanation(
        cls,
        action: str,
        permission_type: str,
        schema_name: str,
        object_name: str,
        affected_user: str,
    ) -> str:
        """
        Generate the explanation string for an audit entry per FR-012.

        Args:
            action: GRANT, DENY, or REVOKE
            permission_type: Permission name (e.g., SELECT, EXECUTE)
            schema_name: Schema of the target object
            object_name: Name of the target object
            affected_user: Database principal receiving the change

        Returns:
            str: Formatted explanation string

        Format:
            "{action} {permission_type} on {schema}.{object} to/from {user}"

        Examples:
            >>> AuditEntry.generate_explanation("GRANT", "SELECT", "dbo", "Orders", "alice")
            "GRANT SELECT on dbo.Orders to alice"

            >>> AuditEntry.generate_explanation("REVOKE", "DELETE", "dbo", "Products", "bob")
            "REVOKE DELETE on dbo.Products from bob"
        """
        # Use "to" for GRANT/DENY, "from" for REVOKE
        preposition = "to" if action in ("GRANT", "DENY") else "from"

        return (
            f"{action} {permission_type} on {schema_name}.{object_name} "
            f"{preposition} {affected_user}"
        )

    @classmethod
    def from_staged_change(
        cls,
        change: "StagedChange",  # noqa: F821
        administrator: str,
        entry_id: int,
        changed_at: datetime,
    ) -> "AuditEntry":
        """
        Create an AuditEntry from a committed StagedChange.

        Args:
            change: The StagedChange that was committed
            administrator: SYSTEM_USER identity of the committing admin
            entry_id: Auto-generated ID from the database
            changed_at: UTC timestamp from the database

        Returns:
            AuditEntry: New audit entry instance
        """
        explanation = cls.generate_explanation(
            action=change.action,
            permission_type=change.permission_type.value,
            schema_name=change.schema_name,
            object_name=change.object_name,
            affected_user=change.user_login,
        )

        return cls(
            id=entry_id,
            administrator=administrator,
            affected_user=change.user_login,
            schema_name=change.schema_name,
            object_name=change.object_name,
            permission_type=change.permission_type.value,
            action=change.action,
            previous_state=change.previous_state.value,
            new_state=change.new_state.value,
            changed_at=changed_at,
            explanation=explanation,
        )
