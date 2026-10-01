"""
Database user data access for Bifrost.

This module provides functions to read database principals (users) from SQL Server
sys.database_principals catalog view.

Users are loaded at matrix initialization and can be filtered/sorted in the UI.
Tags are stored separately in tags.json and merged at the service layer.

Usage:
    from src.db.users import fetch_all_users, fetch_user_by_login
    from src.db.connection import create_connection

    conn = create_connection(config)
    try:
        users = fetch_all_users(conn)
        for user in users:
            print(f"{user.login_name} ({user.principal_type})")

        alice = fetch_user_by_login(conn, "alice")
    finally:
        conn.close()
"""

import pyodbc
from typing import Optional
from src.models.user import DatabaseUser


def fetch_all_users(conn: pyodbc.Connection) -> list[DatabaseUser]:
    """
    Fetch all database principals that can hold object permissions.

    Args:
        conn: Active database connection

    Returns:
        list[DatabaseUser]: List of database users (no tags loaded - merged at service layer)

    Query:
        Reads from sys.database_principals where:
            - type IN ('S', 'U', 'G') → SQL user, Windows user, Windows group
            - principal_id > 4 → excludes system principals (public, guest, INFORMATION_SCHEMA, sys)
            - name NOT LIKE '##%' → excludes certificate/asymmetric key principals

    Columns:
        - name → login_name, display_name
        - type → principal_type

    Note:
        is_disabled is not available in sys.database_principals, so defaults to False.
        Tags are loaded separately from tags.json by the TagStore service.

    Example:
        >>> conn = create_connection(config)
        >>> users = fetch_all_users(conn)
        >>> len(users)
        47
        >>> users[0].login_name
        'alice'
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                principal_id,
                name,
                type
            FROM sys.database_principals
            WHERE type IN ('S', 'U', 'G')
              AND principal_id > 4
              AND name NOT LIKE '##%'
            ORDER BY name
        """

        cursor.execute(query)

        users = []
        for row in cursor.fetchall():
            user = DatabaseUser(
                login_name=row.name,
                display_name=row.name,
                principal_type=row.type.strip(),  # Strip whitespace from CHAR(1)
                is_disabled=False,  # Not available in sys.database_principals
                tags=[],  # Tags loaded separately by TagStore
                principal_id=row.principal_id,
            )
            users.append(user)

        return users

    finally:
        cursor.close()


def fetch_user_by_login(conn: pyodbc.Connection, login_name: str) -> Optional[DatabaseUser]:
    """
    Fetch a single database principal by login name.

    Args:
        conn: Active database connection
        login_name: Principal name to fetch

    Returns:
        Optional[DatabaseUser]: User if found, None otherwise

    Example:
        >>> conn = create_connection(config)
        >>> alice = fetch_user_by_login(conn, "alice")
        >>> alice.login_name
        'alice'
        >>> missing = fetch_user_by_login(conn, "nonexistent")
        >>> missing is None
        True
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                principal_id,
                name,
                type
            FROM sys.database_principals
            WHERE type IN ('S', 'U', 'G')
              AND principal_id > 4
              AND name = ?
        """

        cursor.execute(query, (login_name,))
        row = cursor.fetchone()

        if not row:
            return None

        return DatabaseUser(
            login_name=row.name,
            display_name=row.name,
            principal_type=row.type.strip(),
            is_disabled=False,  # Not available in sys.database_principals
            tags=[],
            principal_id=row.principal_id,
        )

    finally:
        cursor.close()


def user_exists(conn: pyodbc.Connection, login_name: str) -> bool:
    """
    Check if a database principal exists.

    Args:
        conn: Active database connection
        login_name: Principal name to check

    Returns:
        bool: True if user exists, False otherwise

    Example:
        >>> conn = create_connection(config)
        >>> user_exists(conn, "alice")
        True
        >>> user_exists(conn, "nonexistent")
        False
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT 1
            FROM sys.database_principals
            WHERE type IN ('S', 'U', 'G')
              AND principal_id > 4
              AND name = ?
        """

        cursor.execute(query, (login_name,))
        return cursor.fetchone() is not None

    finally:
        cursor.close()


def get_user_count(conn: pyodbc.Connection) -> int:
    """
    Get the total count of database principals.

    Args:
        conn: Active database connection

    Returns:
        int: Number of database users

    Used for scale validation and UI feedback (e.g., "Showing 10 of 47 users").

    Example:
        >>> conn = create_connection(config)
        >>> get_user_count(conn)
        47
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT COUNT(*)
            FROM sys.database_principals
            WHERE type IN ('S', 'U', 'G')
              AND principal_id > 4
              AND name NOT LIKE '##%'
        """

        cursor.execute(query)
        row = cursor.fetchone()
        return row[0] if row else 0

    finally:
        cursor.close()
