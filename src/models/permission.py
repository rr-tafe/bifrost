"""
Permission domain models for Bifrost.

This module defines the core permission-related data structures:
    - PermissionType: Enum of the 8 SQL Server object permissions supported in v1
    - PermissionState: Enum of the three possible permission states (GRANT, DENY, NONE)
    - PermissionAssignment: In-memory record of a single matrix cell
    - StagedChange: Pending permission change held until Commit or Cancel

State Transition Cycle:
    NONE → GRANT → DENY → NONE (repeats on each cell toggle)

Usage:
    assignment = PermissionAssignment(
        user_login="alice",
        schema_name="dbo",
        object_name="Orders",
        permission_type=PermissionType.SELECT,
        committed_state=PermissionState.NONE,
        staged_state=PermissionState.GRANT
    )
    
    if assignment.has_pending_change:
        change = StagedChange.from_assignment(assignment)
        # commit logic applies change.action to database
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PermissionType(Enum):
    """
    The 8 SQL Server object permissions supported in Bifrost v1.
    
    Attributes:
        SELECT: Read permission (tables, views)
        INSERT: Insert permission (tables, views)
        UPDATE: Update permission (tables, views)
        DELETE: Delete permission (tables, views)
        EXECUTE: Execute permission (procedures, functions)
        ALTER: Alter permission (all object types)
        REFERENCES: Foreign key reference permission (tables, views)
        VIEW_DEFINITION: View object definition permission (all types)
    """
    
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    ALTER = "ALTER"
    REFERENCES = "REFERENCES"
    VIEW_DEFINITION = "VIEW DEFINITION"
    
    @classmethod
    def dml_permissions(cls) -> list["PermissionType"]:
        """Return DML permissions applicable to tables and views."""
        return [cls.SELECT, cls.INSERT, cls.UPDATE, cls.DELETE]
    
    @classmethod
    def ddl_permissions(cls) -> list["PermissionType"]:
        """Return DDL permissions applicable to all object types."""
        return [cls.ALTER, cls.VIEW_DEFINITION]
    
    @classmethod
    def executable_permissions(cls) -> list["PermissionType"]:
        """Return permissions applicable to procedures and functions."""
        return [cls.EXECUTE, cls.ALTER, cls.VIEW_DEFINITION]


class PermissionState(Enum):
    """
    The three possible explicit states for a permission assignment.
    
    Attributes:
        GRANT: Explicitly permitted (green checkmark in UI)
        DENY: Explicitly blocked, overrides role grants (red X in UI)
        NONE: No explicit assignment; access determined by role membership (grey dash in UI)
    
    Cycle Order:
        NONE → GRANT → DENY → NONE (repeats on each toggle)
    """
    
    GRANT = "GRANT"
    DENY = "DENY"
    NONE = "NONE"
    
    def next_state(self) -> "PermissionState":
        """
        Return the next state in the toggle cycle.
        
        Returns:
            PermissionState: Next state (NONE → GRANT → DENY → NONE)
        
        Example:
            >>> state = PermissionState.NONE
            >>> state = state.next_state()  # GRANT
            >>> state = state.next_state()  # DENY
            >>> state = state.next_state()  # NONE
        """
        cycle = {
            PermissionState.NONE: PermissionState.GRANT,
            PermissionState.GRANT: PermissionState.DENY,
            PermissionState.DENY: PermissionState.NONE,
        }
        return cycle[self]


@dataclass(frozen=True)
class PermissionAssignment:
    """
    In-memory record of a single cell in the permission matrix.
    
    Represents the committed and optionally staged state of one permission
    (e.g., alice's SELECT on dbo.Orders).
    
    Attributes:
        user_login: Database principal login name (FK to DatabaseUser.login_name)
        schema_name: Schema name (part of object identifier)
        object_name: Object name (part of object identifier)
        permission_type: One of the 8 v1 permission types
        committed_state: Last state fetched from / committed to SQL Server
        staged_state: Pending state (None if no change staged)
    
    Derived:
        has_pending_change: True if staged_state differs from committed_state
        cell_key: Unique tuple key for this assignment
    """
    
    user_login: str
    schema_name: str
    object_name: str
    permission_type: PermissionType
    committed_state: PermissionState
    staged_state: Optional[PermissionState] = None
    
    @property
    def has_pending_change(self) -> bool:
        """
        Check if this assignment has an uncommitted change staged.
        
        Returns:
            bool: True if staged_state is not None and differs from committed_state
        """
        return (
            self.staged_state is not None
            and self.staged_state != self.committed_state
        )
    
    @property
    def cell_key(self) -> tuple[str, str, str, PermissionType]:
        """
        Return the unique key for this permission cell.
        
        Returns:
            tuple: (user_login, schema_name, object_name, permission_type)
        """
        return (self.user_login, self.schema_name, self.object_name, self.permission_type)
    
    @property
    def effective_state(self) -> PermissionState:
        """
        Return the current visible state (staged if present, else committed).
        
        Returns:
            PermissionState: Staged state if set, otherwise committed state
        """
        return self.staged_state if self.staged_state is not None else self.committed_state


@dataclass(frozen=True)
class StagedChange:
    """
    A pending permission change held in memory until Commit or Cancel.
    
    On commit, this generates the appropriate T-SQL statement (GRANT, DENY, or REVOKE)
    and creates one AuditEntry record.
    
    Attributes:
        user_login: Database principal whose permission is changing
        schema_name: Schema name of the target object
        object_name: Name of the target object
        permission_type: Permission being changed
        previous_state: Committed state before this change
        new_state: Desired state to apply on commit
    
    Derived:
        action: T-SQL keyword (GRANT, DENY, or REVOKE) based on new_state
        cell_key: Unique tuple key matching PermissionAssignment.cell_key
    """
    
    user_login: str
    schema_name: str
    object_name: str
    permission_type: PermissionType
    previous_state: PermissionState
    new_state: PermissionState
    
    @property
    def action(self) -> str:
        """
        Derive the T-SQL action keyword from the new_state.
        
        Returns:
            str: "GRANT", "DENY", or "REVOKE"
        
        Rules:
            - new_state = GRANT → action = "GRANT"
            - new_state = DENY → action = "DENY"
            - new_state = NONE → action = "REVOKE"
        """
        if self.new_state == PermissionState.GRANT:
            return "GRANT"
        elif self.new_state == PermissionState.DENY:
            return "DENY"
        else:  # PermissionState.NONE
            return "REVOKE"
    
    @property
    def cell_key(self) -> tuple[str, str, str, PermissionType]:
        """
        Return the unique key for this change's matrix cell.
        
        Returns:
            tuple: (user_login, schema_name, object_name, permission_type)
        """
        return (self.user_login, self.schema_name, self.object_name, self.permission_type)
    
    @classmethod
    def from_assignment(cls, assignment: PermissionAssignment) -> "StagedChange":
        """
        Create a StagedChange from a PermissionAssignment with a staged state.
        
        Args:
            assignment: PermissionAssignment with staged_state set
        
        Returns:
            StagedChange: New staged change instance
        
        Raises:
            ValueError: If assignment has no staged_state
        """
        if assignment.staged_state is None:
            raise ValueError(
                f"Cannot create StagedChange from assignment without staged_state: "
                f"{assignment.cell_key}"
            )
        
        return cls(
            user_login=assignment.user_login,
            schema_name=assignment.schema_name,
            object_name=assignment.object_name,
            permission_type=assignment.permission_type,
            previous_state=assignment.committed_state,
            new_state=assignment.staged_state,
        )
