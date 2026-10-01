"""
Database permissions data access for Bifrost.

This module provides functions to read object-level permissions from SQL Server
sys.database_permissions catalog view and apply permission changes via T-SQL
GRANT, DENY, and REVOKE statements.

Permissions are loaded at matrix initialization as a flat list of PermissionAssignments.
The matrix service builds the in-memory grid and handles staging/commit logic.

Usage:
    from src.db.permissions import (
        fetch_all_permissions,
        apply_permission_changes
    )
    from src.db.connection import create_connection
    from src.models.permission import StagedChange, PermissionState, PermissionType

    conn = create_connection(config)
    try:
        # Load all permissions
        assignments = fetch_all_permissions(conn)

        # Apply changes
        change = StagedChange(
            user_login="alice",
            schema_name="dbo",
            object_name="Orders",
            permission_type=PermissionType.SELECT,
            previous_state=PermissionState.NONE,
            new_state=PermissionState.GRANT
        )
        apply_permission_changes(conn, [change])
        conn.commit()
    finally:
        conn.close()
"""

import threading
from collections.abc import Callable, Sequence
from typing import Optional

import pyodbc

from src.db.sql import quote_ident
from src.models.permission import (
    PERMISSION_INDEX_BY_NAME,
    STATE_DENY,
    STATE_GRANT,
    PermissionAssignment,
    PermissionState,
    PermissionType,
    StagedChange,
)
from src.models.db_object import ObjectType


def fetch_all_permissions(conn: pyodbc.Connection) -> list[PermissionAssignment]:
    """
    Deprecated: use fetch_permission_rows(), which is faster at scale.
    Kept for existing callers and tests.

    Fetch all object-level permissions for all users and objects.

    Args:
        conn: Active database connection

    Returns:
        list[PermissionAssignment]: All permission assignments (committed state only)

    Query:
        Reads from sys.database_permissions JOIN sys.database_principals JOIN sys.objects
        where permission_name IN (SELECT, INSERT, UPDATE, DELETE, EXECUTE, ALTER, REFERENCES, VIEW DEFINITION).

    State Mapping:
        - state = 'G' (Grant) → PermissionState.GRANT
        - state = 'D' (Deny) → PermissionState.DENY
        - Missing row → PermissionState.NONE (handled by matrix service)

    Note:
        This returns only GRANT and DENY states. NONE states are implicit
        (absence of a row) and are filled by the matrix service when building
        the full user × object × permission grid.

    Example:
        >>> conn = create_connection(config)
        >>> assignments = fetch_all_permissions(conn)
        >>> len(assignments)
        1247  # Actual GRANT/DENY assignments (NONE states not included)
        >>> assignments[0].effective_state
        <PermissionState.GRANT: 'GRANT'>
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                pr.name AS user_login,
                s.name AS schema_name,
                o.name AS object_name,
                p.permission_name,
                p.state_desc
            FROM sys.database_permissions p
            JOIN sys.database_principals pr ON p.grantee_principal_id = pr.principal_id
            JOIN sys.objects o ON p.major_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE p.class = 1  -- Object or column permissions
              AND p.minor_id = 0  -- Object-level (not column-level)
              AND p.permission_name IN (
                  'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                  'EXECUTE', 'ALTER', 'REFERENCES', 'VIEW DEFINITION'
              )
              AND pr.type IN ('S', 'U', 'G')
              AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
            ORDER BY pr.name, s.name, o.name, p.permission_name
        """

        cursor.execute(query)

        assignments = []
        for row in cursor.fetchall():
            # Map state_desc to PermissionState
            # sys.database_permissions.state_desc values:
            # - 'GRANT' → PermissionState.GRANT
            # - 'DENY' → PermissionState.DENY
            # - 'GRANT_WITH_GRANT_OPTION' → treated as GRANT (grant option not tracked in v1)
            state_desc = row.state_desc.strip()
            if state_desc in ('GRANT', 'GRANT_WITH_GRANT_OPTION'):
                committed_state = PermissionState.GRANT
            elif state_desc == 'DENY':
                committed_state = PermissionState.DENY
            else:
                # Unexpected state; log warning and skip
                continue

            # Map permission_name to PermissionType enum
            try:
                permission_type = PermissionType(row.permission_name)
            except ValueError:
                # Unsupported permission type; skip
                continue

            assignment = PermissionAssignment(
                user_login=row.user_login,
                schema_name=row.schema_name,
                object_name=row.object_name,
                permission_type=permission_type,
                committed_state=committed_state,
                staged_state=None,  # No staged changes at load time
            )
            assignments.append(assignment)

        return assignments

    finally:
        cursor.close()


def fetch_permissions_for_user(
    conn: pyodbc.Connection,
    user_login: str
) -> list[PermissionAssignment]:
    """
    Fetch all object-level permissions for a specific user.

    Args:
        conn: Active database connection
        user_login: Database principal login name

    Returns:
        list[PermissionAssignment]: User's permission assignments

    Example:
        >>> conn = create_connection(config)
        >>> alice_perms = fetch_permissions_for_user(conn, "alice")
        >>> len(alice_perms)
        84
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                pr.name AS user_login,
                s.name AS schema_name,
                o.name AS object_name,
                p.permission_name,
                p.state_desc
            FROM sys.database_permissions p
            JOIN sys.database_principals pr ON p.grantee_principal_id = pr.principal_id
            JOIN sys.objects o ON p.major_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE p.class = 1
              AND p.minor_id = 0
              AND p.permission_name IN (
                  'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                  'EXECUTE', 'ALTER', 'REFERENCES', 'VIEW DEFINITION'
              )
              AND pr.name = ?
              AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
            ORDER BY s.name, o.name, p.permission_name
        """

        cursor.execute(query, (user_login,))

        assignments = []
        for row in cursor.fetchall():
            state_desc = row.state_desc.strip()
            if state_desc in ('GRANT', 'GRANT_WITH_GRANT_OPTION'):
                committed_state = PermissionState.GRANT
            elif state_desc == 'DENY':
                committed_state = PermissionState.DENY
            else:
                continue

            try:
                permission_type = PermissionType(row.permission_name)
            except ValueError:
                continue

            assignment = PermissionAssignment(
                user_login=row.user_login,
                schema_name=row.schema_name,
                object_name=row.object_name,
                permission_type=permission_type,
                committed_state=committed_state,
                staged_state=None,
            )
            assignments.append(assignment)

        return assignments

    finally:
        cursor.close()


def apply_permission_changes(
    conn: pyodbc.Connection,
    changes: list[StagedChange]
) -> list[tuple[StagedChange, Optional[str]]]:
    """
    Apply a batch of permission changes to the database.

    Args:
        conn: Active database connection
        changes: List of StagedChanges to apply

    Returns:
        list[tuple[StagedChange, Optional[str]]]: List of (change, error_message) tuples.
            error_message is None for successful changes, contains error details for failures.

    Behavior:
        - Applies each change independently (per FR-018: partial commit support)
        - Continues applying changes even if some fail
        - Returns detailed error information for each failure
        - Caller must commit transaction (conn.commit())

    T-SQL Generation:
        - new_state = GRANT → GRANT {perm} ON {schema}.{object} TO [{user}]
        - new_state = DENY → DENY {perm} ON {schema}.{object} TO [{user}]
        - new_state = NONE → REVOKE {perm} ON {schema}.{object} FROM [{user}]

    Error Handling:
        - Each change is applied in a try/except block
        - Failures are collected but don't stop remaining changes
        - Common errors: insufficient privileges, object doesn't exist, user doesn't exist

    Example:
        >>> conn = create_connection(config)
        >>> changes = [
        ...     StagedChange(
        ...         user_login="alice",
        ...         schema_name="dbo",
        ...         object_name="Orders",
        ...         permission_type=PermissionType.SELECT,
        ...         previous_state=PermissionState.NONE,
        ...         new_state=PermissionState.GRANT
        ...     )
        ... ]
        >>> results = apply_permission_changes(conn, changes)
        >>> for change, error in results:
        ...     if error:
        ...         print(f"Failed: {error}")
        ...     else:
        ...         print(f"Success: {change.action} {change.permission_type.value}")
        Success: GRANT SELECT
        >>> conn.commit()
    """
    results = []
    cursor = conn.cursor()

    try:
        for change in changes:
            try:
                # Generate T-SQL statement based on action. Identifiers are quoted;
                # the permission name comes from the PermissionType enum.
                securable = f"{quote_ident(change.schema_name)}.{quote_ident(change.object_name)}"
                principal = quote_ident(change.user_login)
                if change.action == "GRANT":
                    stmt = f"GRANT {change.permission_type.value} ON {securable} TO {principal}"
                elif change.action == "DENY":
                    stmt = f"DENY {change.permission_type.value} ON {securable} TO {principal}"
                else:  # REVOKE
                    stmt = f"REVOKE {change.permission_type.value} ON {securable} FROM {principal}"

                cursor.execute(stmt)
                results.append((change, None))  # Success

            except pyodbc.Error as e:
                # Extract user-friendly error message
                error_msg = str(e)

                # Common error patterns
                if "permission denied" in error_msg.lower() or "insufficient privilege" in error_msg.lower():
                    friendly_error = (
                        f"Insufficient privileges to {change.action} {change.permission_type.value} "
                        f"on {change.schema_name}.{change.object_name}"
                    )
                elif "does not exist" in error_msg.lower():
                    friendly_error = (
                        f"Object or user does not exist: {change.schema_name}.{change.object_name} / "
                        f"{change.user_login}"
                    )
                else:
                    friendly_error = f"Database error: {error_msg}"

                results.append((change, friendly_error))  # Failure

        return results

    finally:
        cursor.close()


def get_administrator_permissions(conn: pyodbc.Connection) -> set[tuple[str, str, PermissionType]]:
    """
    Get the set of permissions the current administrator possesses.

    Args:
        conn: Active database connection

    Returns:
        set[tuple[str, str, PermissionType]]: Set of (schema_name, object_name, permission_type)
            tuples representing permissions the administrator holds.

    Used for privilege validation at staging time (FR-017a):
        - Before staging a GRANT, validate the administrator possesses that permission
        - Cached in memory after first query
        - Refreshed on manual refresh (F5)

    Note:
        This function returns all objects in the database and relies on lazy validation
        (validate_grant_privilege) to check specific permissions as needed via HAS_PERMS_BY_NAME.
        This avoids querying permissions for every object upfront, which is slow and often
        unnecessary since most users don't try to grant all permissions.

    Example:
        >>> conn = create_connection(config)
        >>> admin_perms = get_administrator_permissions(conn)
        >>> # Note: Result contains all objects; specific permissions checked on-demand
    """
    cursor = conn.cursor()
    try:
        # Return all objects in the database as a placeholder set
        # Actual permission validation happens in validate_grant_privilege()
        # which uses HAS_PERMS_BY_NAME() to check the specific permission on-demand
        query = """
            SELECT
                s.name AS schema_name,
                o.name AS object_name
            FROM sys.objects o
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
        """

        cursor.execute(query)

        # Return all objects with all permission types
        # This is a placeholder set; actual permission checking happens
        # in validate_grant_privilege() via HAS_PERMS_BY_NAME()
        permissions = set()
        for row in cursor.fetchall():
            schema_name = row.schema_name
            object_name = row.object_name

            # Add all permission types for all objects
            # The validate_grant_privilege() method will actually check
            # each specific permission using HAS_PERMS_BY_NAME()
            for perm_type in PermissionType:
                permissions.add((schema_name, object_name, perm_type))

        return permissions

    finally:
        cursor.close()


# sys.database_permissions.state: G = GRANT, W = GRANT WITH GRANT OPTION, D = DENY.
# Grant option is not tracked in v1, so W is treated as GRANT.
_STATE_CODE_BY_DB_STATE = {"G": STATE_GRANT, "W": STATE_GRANT, "D": STATE_DENY}

# SQL Server allows at most 2,100 parameters per statement; each target uses 3.
PRIVILEGE_CHECK_CHUNK = 600


class LoadCancelledError(Exception):
    """Raised when a long-running read is cancelled through its cancel event."""


def fetch_permission_rows(
    conn: pyodbc.Connection,
    batch_size: int = 10_000,
    on_batch: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[tuple[int, int, int, int]]:
    """
    Fetch every object-level GRANT/DENY as compact id tuples.

    Args:
        conn: Active database connection
        batch_size: Rows per fetchmany() call
        on_batch: Optional callback(total_rows_so_far) after each batch
        cancel: Optional event; when set, the fetch stops between batches

    Returns:
        list[tuple[int, int, int, int]]:
            (grantee_principal_id, object_id, permission index, state code).
            Permission index follows PERMISSION_ORDER; state code is STATE_GRANT
            or STATE_DENY.

    Raises:
        LoadCancelledError: If cancel is set between batches

    Note:
        No joins and no ORDER BY. Rows for principals or objects Bifrost does not
        manage are filtered out later by the matrix index.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT p.grantee_principal_id, p.major_id, p.permission_name, p.state
            FROM sys.database_permissions AS p
            WHERE p.class = 1
              AND p.minor_id = 0
              AND p.permission_name IN (
                  'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                  'EXECUTE', 'ALTER', 'REFERENCES', 'VIEW DEFINITION'
              )
              AND p.state IN ('G', 'W', 'D')
            """
        )

        rows: list[tuple[int, int, int, int]] = []
        perm_index = PERMISSION_INDEX_BY_NAME
        state_code = _STATE_CODE_BY_DB_STATE
        while True:
            if cancel is not None and cancel.is_set():
                raise LoadCancelledError("Loading permissions was cancelled")
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            for principal_id, object_id, permission_name, state in batch:
                perm_idx = perm_index.get(permission_name.strip())
                code = state_code.get(state.strip())
                if perm_idx is None or code is None:
                    continue
                rows.append((principal_id, object_id, perm_idx, code))
            if on_batch is not None:
                on_batch(len(rows))

        return rows

    finally:
        cursor.close()


def fetch_privilege_flags(conn: pyodbc.Connection) -> bool:
    """
    Check whether the connected account can grant anything in this database.

    Args:
        conn: Active database connection

    Returns:
        bool: True if the account is sysadmin, db_owner, or has CONTROL on the
            database. Grant privilege checks can then be skipped.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT
                IS_SRVROLEMEMBER('sysadmin'),
                IS_ROLEMEMBER('db_owner'),
                HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CONTROL')
            """
        )
        row = cursor.fetchone()
        return any(value == 1 for value in row)
    finally:
        cursor.close()


def check_grant_privileges(
    conn: pyodbc.Connection,
    targets: Sequence[tuple[str, str, PermissionType]],
) -> dict[tuple[str, str, PermissionType], bool]:
    """
    Check which permissions the connected account holds, in as few queries as possible.

    Used for FR-017a: an administrator may only GRANT a permission they hold.

    Args:
        conn: Active database connection
        targets: (schema_name, object_name, permission_type) tuples to check

    Returns:
        dict: Each target mapped to True if HAS_PERMS_BY_NAME returns 1

    Note:
        Names are passed as parameters and quoted with QUOTENAME in T-SQL, so
        names containing quotes, brackets or dots are handled safely. Targets are
        checked in chunks of PRIVILEGE_CHECK_CHUNK per statement.
    """
    unique_targets = list(dict.fromkeys(targets))
    results: dict[tuple[str, str, PermissionType], bool] = {}
    if not unique_targets:
        return results

    by_name = {(s, o, p.value): (s, o, p) for s, o, p in unique_targets}
    cursor = conn.cursor()
    try:
        for start in range(0, len(unique_targets), PRIVILEGE_CHECK_CHUNK):
            chunk = unique_targets[start : start + PRIVILEGE_CHECK_CHUNK]
            values = ", ".join(["(?, ?, ?)"] * len(chunk))
            params: list[str] = []
            for schema_name, object_name, permission_type in chunk:
                params.extend((schema_name, object_name, permission_type.value))
            cursor.execute(
                "SELECT t.s, t.o, t.perm, "
                "HAS_PERMS_BY_NAME(QUOTENAME(t.s) + '.' + QUOTENAME(t.o), 'OBJECT', t.perm) "
                f"FROM (VALUES {values}) AS t(s, o, perm)",
                params,
            )
            for schema_name, object_name, perm_name, has_perm in cursor.fetchall():
                key = by_name.get((schema_name, object_name, perm_name))
                if key is not None:
                    results[key] = has_perm == 1

        # Anything the server didn't return (should not happen) counts as not held
        for target in unique_targets:
            results.setdefault(target, False)
        return results

    finally:
        cursor.close()
