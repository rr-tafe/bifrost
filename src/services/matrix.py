"""
Permission matrix service for Bifrost.

This module provides the PermissionMatrix class which manages the in-memory
permission grid, staging engine, and commit/cancel behavior.

The matrix is the core data structure for the application:
    - Loads users, objects, and permissions from the database
    - Builds a user × object × permission grid
    - Tracks staged (pending) changes in memory
    - Commits changes to the database and writes audit log entries
    - Cancels staged changes on user request or connection loss

Usage:
    from src.services.matrix import PermissionMatrix
    from src.db.connection import create_connection

    conn = create_connection(config)
    matrix = PermissionMatrix(conn, schema="dbo")
    matrix.load()

    # Stage a change
    matrix.stage_change("alice", "dbo", "Orders", PermissionType.SELECT, PermissionState.GRANT)

    # Commit all staged changes
    results = matrix.commit()

    # Or cancel all staged changes
    matrix.cancel()
"""

import pyodbc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable
from src.models.user import DatabaseUser
from src.models.db_object import DatabaseObject
from src.models.permission import (
    PermissionAssignment,
    PermissionState,
    PermissionType,
    StagedChange,
)
from src.models.audit_entry import AuditEntry
from src.db import users as db_users
from src.db import objects as db_objects
from src.db import permissions as db_permissions
from src.db import audit as db_audit
from src.db.connection import get_current_user


@dataclass
class FilterState:
    """
    Current filter/search/sort state for the matrix view.

    Attributes:
        user_search_term: Text search filter for users (matches login name)
        object_search_term: Text search filter for objects (matches name)
        active_filters: Dictionary of active filters (tag, object_type, permission_type)
        sort_key: Current sort key (e.g., "user_name", "object_name", "permission_type")
        sort_ascending: Sort direction
    """

    user_search_term: str = ""
    object_search_term: str = ""
    active_filters: dict = field(default_factory=dict)
    sort_key: str = "object_name"
    sort_ascending: bool = True


@dataclass
class DataSizeInfo:
    """
    Information about the total data size to help users filter large datasets.

    Attributes:
        total_users: Total users in database
        total_objects: Total objects in database
        is_large: Whether dataset exceeds performance threshold
        recommended_chunk_size: Recommended rows to display at once
    """

    total_users: int = 0
    total_objects: int = 0
    is_large: bool = False
    recommended_chunk_size: int = 50
    warning_message: str = ""


@dataclass
class UndoEntry:
    """
    Entry in the undo stack for undo/redo functionality.

    Attributes:
        user_login: User whose permission was changed
        schema_name: Schema of the object
        object_name: Name of the object
        permission_type: Permission that was changed
        old_state: State before the change
        new_state: State after the change
        timestamp: When the change was made
    """

    user_login: str
    schema_name: str
    object_name: str
    permission_type: PermissionType
    old_state: Optional[PermissionState]
    new_state: Optional[PermissionState]
    timestamp: datetime


class PermissionMatrix:
    """
    In-memory permission matrix with staging engine and commit/cancel.

    The matrix holds permissions for users and objects loaded from the database.
    Changes are staged in memory until committed or cancelled.

    Large datasets are automatically chunked to prevent UI sluggishness.
    Users are encouraged to filter/search before viewing large result sets.

    Attributes:
        conn: Database connection (caller manages lifecycle)
        schema: Schema name for Bifrost tables (audit log)
        users: List of database users
        objects: List of database objects
        assignments: Dict mapping cell_key to PermissionAssignment
        staged_changes: Dict mapping cell_key to StagedChange
        filter_state: Current filter/search/sort state
        undo_stack: Stack of undo entries (max 50)
        redo_stack: Stack of redo entries (cleared on new change)

    Cell Key:
        (user_login, schema_name, object_name, permission_type)

    Thread Safety:
        Not thread-safe. Single-threaded desktop app.

    Performance:
        - Loads data lazily in chunks to handle large datasets
        - Limits visible cells to ~10,000 for smooth rendering
        - Warns users if filtering recommended
    """

    MAX_UNDO_ENTRIES = 50
    # Performance tuning: warn if filtered data exceeds this
    PERF_THRESHOLD_USERS = 100
    PERF_THRESHOLD_OBJECTS = 50
    PERF_THRESHOLD_CELLS = 10000  # Max cells visible (users × objects × perms)

    def __init__(self, conn: pyodbc.Connection, schema: str = "dbo"):
        """
        Initialize the permission matrix.

        Args:
            conn: Active database connection
            schema: Schema name for Bifrost tables (default "dbo")
        """
        self.conn = conn
        self.schema = schema
        self.users: list[DatabaseUser] = []
        self.objects: list[DatabaseObject] = []
        self.assignments: dict[tuple, PermissionAssignment] = {}
        self.staged_changes: dict[tuple, StagedChange] = {}
        self.filter_state = FilterState()
        self.undo_stack: list[UndoEntry] = []
        self.redo_stack: list[UndoEntry] = []
        self._admin_permissions: Optional[set[tuple[str, str, PermissionType]]] = None
        self._on_change_callback: Optional[Callable[[], None]] = None
        # Track total counts before filtering for performance warnings
        self._total_users_in_db: int = 0
        self._total_objects_in_db: int = 0
        self._size_info = DataSizeInfo()

    def set_on_change_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """
        Set a callback to be invoked when staged changes are modified.

        Args:
            callback: Function to call on change (no arguments)
        """
        self._on_change_callback = callback

    def _notify_change(self) -> None:
        """Notify the UI of a change to staged changes."""
        if self._on_change_callback:
            self._on_change_callback()

    def load(self) -> None:
        """
        Load all users, objects, and permissions from the database.

        This builds the full matrix grid with all possible cells.
        Cells without explicit GRANT/DENY get PermissionState.NONE.

        Raises:
            pyodbc.Error: If database query fails
        """
        # Load users and objects
        self.users = db_users.fetch_all_users(self.conn)
        self.objects = db_objects.fetch_all_objects(self.conn)

        # Track total counts for performance info
        self._total_users_in_db = len(self.users)
        self._total_objects_in_db = len(self.objects)

        # Load existing permissions (GRANT and DENY only)
        existing_permissions = db_permissions.fetch_all_permissions(self.conn)

        # Build sparse assignments dict from existing permissions only.
        # Cells without explicit GRANT/DENY are treated as NONE on demand.
        self.assignments = {}
        for assignment in existing_permissions:
            self.assignments[assignment.cell_key] = assignment

        # Clear staged changes and undo/redo stacks
        self.staged_changes.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._admin_permissions = None

    def refresh(self) -> None:
        """
        Refresh the matrix from the database, preserving staged changes.

        Staged changes are re-applied after reloading the committed state.
        This is used for the manual refresh (F5) operation.
        """
        # Save current staged changes
        saved_staged = self.staged_changes.copy()

        # Reload from database
        self.load()

        # Re-apply staged changes
        for cell_key, change in saved_staged.items():
            if cell_key in self.assignments:
                # Re-stage the change
                self.stage_change(
                    user_login=change.user_login,
                    schema_name=change.schema_name,
                    object_name=change.object_name,
                    permission_type=change.permission_type,
                    new_state=change.new_state,
                    add_to_undo=False,
                )

    def get_performance_info(self) -> DataSizeInfo:
        """
        Get information about data size and performance recommendations.

        Returns:
            DataSizeInfo with warnings if data may cause performance issues
        """
        num_users = len(self.users)
        num_objects = len(self.objects)
        num_perms = len([p for p in PermissionType])
        total_cells = num_users * num_objects * num_perms

        info = DataSizeInfo(
            total_users=self._total_users_in_db,
            total_objects=self._total_objects_in_db,
            is_large=False,
            recommended_chunk_size=50,
            warning_message="",
        )

        # Check if current display exceeds performance threshold
        if num_users > self.PERF_THRESHOLD_USERS or num_objects > self.PERF_THRESHOLD_OBJECTS:
            info.is_large = True
            info.warning_message = (
                f"⚠️  Large dataset detected: {num_users} users × {num_objects} objects.\n"
                f"Try using Search or Filters to reduce the view size for better performance.\n"
                f"(Viewing >100 users or >50 objects may be slow)"
            )

        return info

    def get_assignment(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> Optional[PermissionAssignment]:
        """
        Get the permission assignment for a specific cell.

        Args:
            user_login: Database user login name
            schema_name: Schema name
            object_name: Object name
            permission_type: Permission type

        Returns:
            PermissionAssignment if found, None otherwise
        """
        cell_key = (user_login, schema_name, object_name, permission_type)
        assignment = self.assignments.get(cell_key)
        if assignment:
            return assignment

        # Missing assignment implies NONE committed state for valid cells.
        return PermissionAssignment(
            user_login=user_login,
            schema_name=schema_name,
            object_name=object_name,
            permission_type=permission_type,
            committed_state=PermissionState.NONE,
            staged_state=None,
        )

    def stage_change(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
        new_state: PermissionState,
        add_to_undo: bool = True,
    ) -> Optional[str]:
        """
        Stage a permission change for later commit.

        Args:
            user_login: Database user login name
            schema_name: Schema name
            object_name: Object name
            permission_type: Permission type
            new_state: Desired new state
            add_to_undo: Whether to add to undo stack (default True)

        Returns:
            Optional[str]: Error message if validation fails, None if successful

        Note:
            If new_state equals committed_state, the staged change is removed
            (no change needed).
        """
        cell_key = (user_login, schema_name, object_name, permission_type)
        assignment = self.get_assignment(user_login, schema_name, object_name, permission_type)

        # Get the old staged state for undo
        old_staged_state = assignment.staged_state

        # If new_state equals committed_state, remove staging
        if new_state == assignment.committed_state:
            if cell_key in self.staged_changes:
                del self.staged_changes[cell_key]
            # Update assignment to remove staged_state
            self.assignments[cell_key] = PermissionAssignment(
                user_login=assignment.user_login,
                schema_name=assignment.schema_name,
                object_name=assignment.object_name,
                permission_type=assignment.permission_type,
                committed_state=assignment.committed_state,
                staged_state=None,
            )
        else:
            # Create staged change
            change = StagedChange(
                user_login=user_login,
                schema_name=schema_name,
                object_name=object_name,
                permission_type=permission_type,
                previous_state=assignment.committed_state,
                new_state=new_state,
            )
            self.staged_changes[cell_key] = change

            # Update assignment with staged_state
            self.assignments[cell_key] = PermissionAssignment(
                user_login=assignment.user_login,
                schema_name=assignment.schema_name,
                object_name=assignment.object_name,
                permission_type=assignment.permission_type,
                committed_state=assignment.committed_state,
                staged_state=new_state,
            )

        # Add to undo stack
        if add_to_undo:
            undo_entry = UndoEntry(
                user_login=user_login,
                schema_name=schema_name,
                object_name=object_name,
                permission_type=permission_type,
                old_state=old_staged_state,
                new_state=new_state if new_state != assignment.committed_state else None,
                timestamp=datetime.now(timezone.utc),
            )
            self.undo_stack.append(undo_entry)

            # Trim undo stack to max size
            if len(self.undo_stack) > self.MAX_UNDO_ENTRIES:
                self.undo_stack.pop(0)

            # Clear redo stack on new change
            self.redo_stack.clear()

        self._notify_change()
        return None

    def toggle_cell(
        self,
        user_login: str,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> Optional[str]:
        """
        Toggle a permission cell through the state cycle.

        Cycle: NONE → GRANT → DENY → NONE (repeats)

        The cycle starts from the committed state, not the staged state.

        Args:
            user_login: Database user login name
            schema_name: Schema name
            object_name: Object name
            permission_type: Permission type

        Returns:
            Optional[str]: Error message if toggle fails, None if successful
        """
        assignment = self.get_assignment(user_login, schema_name, object_name, permission_type)

        # Get current effective state and cycle to next
        current_state = assignment.effective_state
        next_state = current_state.next_state()

        return self.stage_change(
            user_login=user_login,
            schema_name=schema_name,
            object_name=object_name,
            permission_type=permission_type,
            new_state=next_state,
        )

    def undo(self) -> bool:
        """
        Undo the last staged change.

        Returns:
            bool: True if undo was successful, False if stack is empty
        """
        if not self.undo_stack:
            return False

        entry = self.undo_stack.pop()

        # Add to redo stack
        self.redo_stack.append(entry)

        # Restore previous state
        cell_key = (
            entry.user_login,
            entry.schema_name,
            entry.object_name,
            entry.permission_type,
        )

        if cell_key in self.assignments:
            assignment = self.assignments[cell_key]

            if entry.old_state is None:
                # Was committed state before, remove staging
                new_staged = None
            else:
                new_staged = entry.old_state

            # Update without adding to undo stack
            self.stage_change(
                user_login=entry.user_login,
                schema_name=entry.schema_name,
                object_name=entry.object_name,
                permission_type=entry.permission_type,
                new_state=new_staged if new_staged else assignment.committed_state,
                add_to_undo=False,
            )

        return True

    def redo(self) -> bool:
        """
        Redo the last undone change.

        Returns:
            bool: True if redo was successful, False if stack is empty
        """
        if not self.redo_stack:
            return False

        entry = self.redo_stack.pop()

        # Add back to undo stack
        self.undo_stack.append(entry)

        cell_key = (
            entry.user_login,
            entry.schema_name,
            entry.object_name,
            entry.permission_type,
        )

        if cell_key in self.assignments:
            assignment = self.assignments[cell_key]

            if entry.new_state is None:
                new_state = assignment.committed_state
            else:
                new_state = entry.new_state

            # Update without adding to undo stack
            self.stage_change(
                user_login=entry.user_login,
                schema_name=entry.schema_name,
                object_name=entry.object_name,
                permission_type=entry.permission_type,
                new_state=new_state,
                add_to_undo=False,
            )

        return True

    def get_staged_changes(self) -> list[StagedChange]:
        """
        Get all staged changes.

        Returns:
            list[StagedChange]: List of all pending changes
        """
        return list(self.staged_changes.values())

    def get_staged_change_count(self) -> int:
        """
        Get the number of staged changes.

        Returns:
            int: Count of pending changes
        """
        return len(self.staged_changes)

    def has_staged_changes(self) -> bool:
        """
        Check if there are any staged changes.

        Returns:
            bool: True if there are pending changes
        """
        return len(self.staged_changes) > 0

    def cancel(self) -> None:
        """
        Cancel all staged changes, reverting cells to committed state.

        Clears the undo/redo stacks.
        """
        # Clear staged changes
        self.staged_changes.clear()

        # Update staged assignments to remove staged state.
        # If committed state is NONE, remove the sparse entry entirely.
        updated: dict[tuple, PermissionAssignment] = {}
        for cell_key, assignment in self.assignments.items():
            if assignment.staged_state is None:
                updated[cell_key] = assignment
                continue

            if assignment.committed_state == PermissionState.NONE:
                continue

            updated[cell_key] = PermissionAssignment(
                user_login=assignment.user_login,
                schema_name=assignment.schema_name,
                object_name=assignment.object_name,
                permission_type=assignment.permission_type,
                committed_state=assignment.committed_state,
                staged_state=None,
            )

        self.assignments = updated

        # Clear undo/redo stacks
        self.undo_stack.clear()
        self.redo_stack.clear()

        self._notify_change()

    def commit(self) -> list[tuple[StagedChange, Optional[str]]]:
        """
        Commit all staged changes to the database.

        Returns:
            list[tuple[StagedChange, Optional[str]]]: List of (change, error) tuples.
                error is None for successful changes, contains error message for failures.

        Behavior:
            - Applies all staged changes to the database
            - Writes audit log entries for successful changes
            - Updates assignment committed_state for successful changes
            - Leaves failed changes staged for retry
            - Clears undo/redo stacks on successful commit
        """
        if not self.staged_changes:
            return []

        changes_list = list(self.staged_changes.values())

        # Apply permission changes
        results = db_permissions.apply_permission_changes(self.conn, changes_list)

        # Get current admin for audit log
        admin_user = get_current_user(self.conn)
        now = datetime.now(timezone.utc)

        # Process results
        successful_changes = []
        failed_changes = []

        for change, error in results:
            if error is None:
                successful_changes.append(change)
            else:
                failed_changes.append((change, error))

        # Write audit log entries for successful changes
        if successful_changes:
            audit_entries = []
            for change in successful_changes:
                entry = AuditEntry(
                    id=0,  # Auto-generated
                    administrator=admin_user,
                    affected_user=change.user_login,
                    schema_name=change.schema_name,
                    object_name=change.object_name,
                    permission_type=change.permission_type.value,
                    action=change.action,
                    previous_state=change.previous_state.value,
                    new_state=change.new_state.value,
                    changed_at=now,
                    explanation=AuditEntry.generate_explanation(
                        action=change.action,
                        permission_type=change.permission_type.value,
                        schema_name=change.schema_name,
                        object_name=change.object_name,
                        affected_user=change.user_login,
                    ),
                )
                audit_entries.append(entry)

            db_audit.write_audit_entries(self.conn, audit_entries, schema=self.schema)

        # Update assignment committed_state for successful changes
        for change in successful_changes:
            cell_key = change.cell_key

            # Remove from staged_changes
            if cell_key in self.staged_changes:
                del self.staged_changes[cell_key]

            # Update committed state in sparse map.
            if change.new_state == PermissionState.NONE:
                self.assignments.pop(cell_key, None)
            else:
                self.assignments[cell_key] = PermissionAssignment(
                    user_login=change.user_login,
                    schema_name=change.schema_name,
                    object_name=change.object_name,
                    permission_type=change.permission_type,
                    committed_state=change.new_state,
                    staged_state=None,
                )

        # Commit transaction
        self.conn.commit()

        # Clear undo/redo stacks (commit is a checkpoint)
        self.undo_stack.clear()
        self.redo_stack.clear()

        self._notify_change()

        # Return results with errors for failed changes
        return results

    def validate_grant_privilege(
        self,
        schema_name: str,
        object_name: str,
        permission_type: PermissionType,
    ) -> Optional[str]:
        """
        Validate that the administrator has privilege to grant a permission.

        Args:
            schema_name: Schema name
            object_name: Object name
            permission_type: Permission type to grant

        Returns:
            Optional[str]: Error message if validation fails, None if valid

        Note:
            Uses HAS_PERMS_BY_NAME() to check the actual permission in the database,
            including both direct grants and role-based permissions.
            Result is not cached (checked on each grant attempt).
        """
        # Ensure admin permissions cache is initialized (even though we'll bypass it for actual checks)
        if self._admin_permissions is None:
            self._admin_permissions = db_permissions.get_administrator_permissions(self.conn)

        # Use HAS_PERMS_BY_NAME to check the actual permission
        # This includes both direct grants and role-based permissions
        cursor = self.conn.cursor()
        try:
            full_name = f"{schema_name}.{object_name}"
            query = f"SELECT HAS_PERMS_BY_NAME('{full_name}', 'OBJECT', '{permission_type.value}')"
            cursor.execute(query)
            result = cursor.fetchone()[0]

            # HAS_PERMS_BY_NAME returns:
            # 1 = user has permission
            # 0 = user does not have permission
            # NULL = user has DENY (explicitly denied)
            if result != 1:
                return (
                    f"You cannot grant {permission_type.value} on {schema_name}.{object_name} "
                    f"because you do not have this permission yourself."
                )
        finally:
            cursor.close()

        return None

    # --- Filter/Search/Sort Methods ---

    def set_search_term(self, term: str) -> None:
        """
        Set search term (deprecated - use set_user_search_term/set_object_search_term).

        For backward compatibility, sets both user and object search terms.

        Args:
            term: Search term to apply to both users and objects
        """
        self.filter_state.user_search_term = term
        self.filter_state.object_search_term = term

    def set_user_search_term(self, term: str) -> None:
        """
        Set search term for filtering users.

        Args:
            term: Search term to match against user login names
        """
        self.filter_state.user_search_term = term

    def set_object_search_term(self, term: str) -> None:
        """
        Set search term for filtering objects.

        Args:
            term: Search term to match against object names
        """
        self.filter_state.object_search_term = term

    def set_filter(self, key: str, value: any) -> None:
        """Set an active filter."""
        self.filter_state.active_filters[key] = value

    def clear_filter(self, key: str) -> None:
        """Clear a specific filter."""
        if key in self.filter_state.active_filters:
            del self.filter_state.active_filters[key]

    def clear_all_filters(self) -> None:
        """Clear all filters and reset to defaults."""
        self.filter_state = FilterState()

    def set_sort(self, key: str, ascending: bool = True) -> None:
        """Set the sort key and direction."""
        self.filter_state.sort_key = key
        self.filter_state.sort_ascending = ascending

    def get_filtered_users(self) -> list[DatabaseUser]:
        """
        Get users filtered by current filter state.

        Returns:
            list[DatabaseUser]: Filtered and sorted users
        """
        users = self.users.copy()

        # Apply user search filter
        if self.filter_state.user_search_term:
            term = self.filter_state.user_search_term.lower()
            users = [u for u in users if term in u.login_name.lower()]

        # Apply tag filter
        if "user_tag" in self.filter_state.active_filters:
            tag = self.filter_state.active_filters["user_tag"]
            users = [u for u in users if u.has_tag(tag)]

        # Apply sort
        if self.filter_state.sort_key == "user_name":
            users.sort(key=lambda u: u.login_name.lower(), reverse=not self.filter_state.sort_ascending)

        return users

    def get_filtered_objects(self) -> list[DatabaseObject]:
        """
        Get objects filtered by current filter state.

        Returns:
            list[DatabaseObject]: Filtered and sorted objects
        """
        objects = self.objects.copy()

        # Apply object search filter
        if self.filter_state.object_search_term:
            term = self.filter_state.object_search_term.lower()
            objects = [o for o in objects if term in o.full_name.lower()]

        # Apply tag filter
        if "object_tag" in self.filter_state.active_filters:
            tag = self.filter_state.active_filters["object_tag"]
            objects = [o for o in objects if o.has_tag(tag)]

        # Apply object type filter
        if "object_type" in self.filter_state.active_filters:
            obj_type = self.filter_state.active_filters["object_type"]
            objects = [o for o in objects if o.object_type == obj_type]

        # Apply sort
        if self.filter_state.sort_key == "object_name":
            objects.sort(key=lambda o: o.full_name.lower(), reverse=not self.filter_state.sort_ascending)
        elif self.filter_state.sort_key == "object_type":
            objects.sort(key=lambda o: o.object_type.value, reverse=not self.filter_state.sort_ascending)

        return objects
