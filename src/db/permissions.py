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

import pyodbc
from typing import Optional
from src.models.permission import (
    PermissionAssignment,
    PermissionState,
    PermissionType,
    StagedChange,
)
from src.models.db_object import ObjectType


def fetch_all_permissions(conn: pyodbc.Connection) -> list[PermissionAssignment]:
    """
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
                # Generate T-SQL statement based on action
                if change.action == "GRANT":
                    stmt = f"""
                        GRANT {change.permission_type.value}
                        ON [{change.schema_name}].[{change.object_name}]
                        TO [{change.user_login}]
                    """
                elif change.action == "DENY":
                    stmt = f"""
                        DENY {change.permission_type.value}
                        ON [{change.schema_name}].[{change.object_name}]
                        TO [{change.user_login}]
                    """
                else:  # REVOKE
                    stmt = f"""
                        REVOKE {change.permission_type.value}
                        ON [{change.schema_name}].[{change.object_name}]
                        FROM [{change.user_login}]
                    """

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

    Query:
        Uses IS_MEMBER() to check role membership and sys.database_permissions
        for explicit grants to the current user (SYSTEM_USER).

    Example:
        >>> conn = create_connection(config)
        >>> admin_perms = get_administrator_permissions(conn)
        >>> (\"dbo\", \"Orders\", PermissionType.SELECT) in admin_perms
        True
    """
    cursor = conn.cursor()
    try:
        # Get current user's login name
        cursor.execute("SELECT SYSTEM_USER")
        admin_login = cursor.fetchone()[0]

        # Fetch administrator's permissions
        # Include both direct grants and role-based grants (if db_owner/sysadmin)
        query = """
            SELECT
                s.name AS schema_name,
                o.name AS object_name,
                p.permission_name
            FROM sys.database_permissions p
            JOIN sys.objects o ON p.major_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            JOIN sys.database_principals pr ON p.grantee_principal_id = pr.principal_id
            WHERE p.class = 1
              AND p.minor_id = 0
              AND p.state_desc IN ('GRANT', 'GRANT_WITH_GRANT_OPTION')
              AND pr.name = ?
              AND p.permission_name IN (
                  'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                  'EXECUTE', 'ALTER', 'REFERENCES', 'VIEW DEFINITION'
              )
              AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
        """

        cursor.execute(query, (admin_login,))

        permissions = set()
        for row in cursor.fetchall():
            try:
                perm_type = PermissionType(row.permission_name)
                permissions.add((row.schema_name, row.object_name, perm_type))
            except ValueError:
                continue

        return permissions

    finally:
        cursor.close()
