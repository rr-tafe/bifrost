"""
Database object data access for Bifrost.

This module provides functions to read database objects (tables, views, procedures,
functions) from SQL Server system catalog views and manage extended properties
(MS_Description) for object descriptions.

Objects are loaded at matrix initialization and can be filtered/sorted in the UI.
Tags are stored separately in tags.json and merged at the service layer.

Usage:
    from src.db.objects import (
        fetch_all_objects,
        fetch_object_by_name,
        load_object_description,
        save_object_description
    )
    from src.db.connection import create_connection

    conn = create_connection(config)
    try:
        objects = fetch_all_objects(conn)
        for obj in objects:
            print(f"{obj.full_name} ({obj.object_type.value})")

        orders = fetch_object_by_name(conn, "dbo", "Orders")
        description = load_object_description(conn, "dbo", "Orders")
        save_object_description(conn, "dbo", "Orders", "Customer orders table")
    finally:
        conn.close()
"""

import pyodbc
from typing import Optional
from src.models.db_object import DatabaseObject, ObjectType


def fetch_all_objects(conn: pyodbc.Connection) -> list[DatabaseObject]:
    """
    Fetch all database objects that can have object-level permissions.

    Args:
        conn: Active database connection

    Returns:
        list[DatabaseObject]: List of database objects (no tags or descriptions loaded initially)

    Query:
        Reads from sys.objects JOIN sys.schemas where:
            - type IN ('U', 'V', 'P', 'FN', 'IF', 'TF') → tables, views, procedures, functions
            - is_ms_shipped = 0 → excludes system objects
            - schema_id NOT IN (schema_id('sys'), schema_id('INFORMATION_SCHEMA'))

    Columns:
        - schema.name → schema_name
        - object.name → object_name
        - object.type → object_type (mapped via ObjectType.from_sql_type)

    Tags and Descriptions:
        - Tags are loaded separately from tags.json by the TagStore service
        - Descriptions are loaded on-demand or when the Object View is opened

    Example:
        >>> conn = create_connection(config)
        >>> objects = fetch_all_objects(conn)
        >>> len(objects)
        523
        >>> objects[0].full_name
        'dbo.Orders'
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                s.name AS schema_name,
                o.name AS object_name,
                o.type AS object_type
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
            ORDER BY s.name, o.name
        """

        cursor.execute(query)

        objects = []
        for row in cursor.fetchall():
            obj_type = ObjectType.from_sql_type(row.object_type.strip())

            obj = DatabaseObject(
                schema_name=row.schema_name,
                object_name=row.object_name,
                object_type=obj_type,
                tags=[],  # Tags loaded separately by TagStore
                description=None,  # Loaded on-demand
            )
            objects.append(obj)

        return objects

    finally:
        cursor.close()


def fetch_object_by_name(
    conn: pyodbc.Connection,
    schema_name: str,
    object_name: str
) -> Optional[DatabaseObject]:
    """
    Fetch a single database object by schema and name.

    Args:
        conn: Active database connection
        schema_name: Schema name
        object_name: Object name

    Returns:
        Optional[DatabaseObject]: Object if found, None otherwise

    Example:
        >>> conn = create_connection(config)
        >>> orders = fetch_object_by_name(conn, "dbo", "Orders")
        >>> orders.full_name
        'dbo.Orders'
        >>> missing = fetch_object_by_name(conn, "dbo", "NonExistent")
        >>> missing is None
        True
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                s.name AS schema_name,
                o.name AS object_name,
                o.type AS object_type
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE s.name = ?
              AND o.name = ?
              AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
        """

        cursor.execute(query, (schema_name, object_name))
        row = cursor.fetchone()

        if not row:
            return None

        obj_type = ObjectType.from_sql_type(row.object_type.strip())

        return DatabaseObject(
            schema_name=row.schema_name,
            object_name=row.object_name,
            object_type=obj_type,
            tags=[],
            description=None,
        )

    finally:
        cursor.close()


def load_object_description(
    conn: pyodbc.Connection,
    schema_name: str,
    object_name: str
) -> Optional[str]:
    """
    Load the MS_Description extended property for a database object.

    Args:
        conn: Active database connection
        schema_name: Schema name
        object_name: Object name

    Returns:
        Optional[str]: Description text if exists, None otherwise

    Query:
        Reads from sys.extended_properties where:
            - name = 'MS_Description'
            - level0_type = 'SCHEMA', level0_name = schema_name
            - level1_type = 'TABLE'/'VIEW'/'PROCEDURE'/'FUNCTION', level1_name = object_name
            - class = 1 (object-level property)

    Note:
        Descriptions are shared across all administrators (stored in SQL Server).

    Example:
        >>> conn = create_connection(config)
        >>> desc = load_object_description(conn, "dbo", "Orders")
        >>> print(desc)
        "Customer orders table"
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT
                CAST(value AS NVARCHAR(MAX)) AS description
            FROM sys.extended_properties ep
            JOIN sys.objects o ON ep.major_id = o.object_id
            JOIN sys.schemas s ON o.schema_id = s.schema_id
            WHERE ep.name = 'MS_Description'
              AND ep.class = 1
              AND s.name = ?
              AND o.name = ?
        """

        cursor.execute(query, (schema_name, object_name))
        row = cursor.fetchone()

        return row.description if row else None

    finally:
        cursor.close()


def save_object_description(
    conn: pyodbc.Connection,
    schema_name: str,
    object_name: str,
    description: Optional[str]
) -> None:
    """
    Save or update the MS_Description extended property for a database object.

    Args:
        conn: Active database connection
        schema_name: Schema name
        object_name: Object name
        description: Description text (None or empty string clears the description)

    Raises:
        pyodbc.Error: If extended property operation fails

    Behavior:
        - If description is None or empty, removes the extended property
        - If property exists, updates it (sp_updateextendedproperty)
        - If property doesn't exist, adds it (sp_addextendedproperty)

    Note:
        Requires ALTER permission on the target object.
        Description is shared across all administrators.

    Example:
        >>> conn = create_connection(config)
        >>> save_object_description(conn, "dbo", "Orders", "Customer orders table")
        >>> conn.commit()

        >>> # Clear description
        >>> save_object_description(conn, "dbo", "Orders", None)
        >>> conn.commit()
    """
    cursor = conn.cursor()
    try:
        # Check if property exists
        existing = load_object_description(conn, schema_name, object_name)

        if description is None or description == "":
            # Remove property if it exists
            if existing is not None:
                cursor.execute(
                    """
                    EXEC sp_dropextendedproperty
                        @name = 'MS_Description',
                        @level0type = 'SCHEMA', @level0name = ?,
                        @level1type = 'TABLE', @level1name = ?
                    """,
                    (schema_name, object_name)
                )
        elif existing is not None:
            # Update existing property
            cursor.execute(
                """
                EXEC sp_updateextendedproperty
                    @name = 'MS_Description',
                    @value = ?,
                    @level0type = 'SCHEMA', @level0name = ?,
                    @level1type = 'TABLE', @level1name = ?
                """,
                (description, schema_name, object_name)
            )
        else:
            # Add new property
            cursor.execute(
                """
                EXEC sp_addextendedproperty
                    @name = 'MS_Description',
                    @value = ?,
                    @level0type = 'SCHEMA', @level0name = ?,
                    @level1type = 'TABLE', @level1name = ?
                """,
                (description, schema_name, object_name)
            )

        # Commit is handled by caller

    finally:
        cursor.close()


def object_exists(
    conn: pyodbc.Connection,
    schema_name: str,
    object_name: str
) -> bool:
    """
    Check if a database object exists.

    Args:
        conn: Active database connection
        schema_name: Schema name
        object_name: Object name

    Returns:
        bool: True if object exists, False otherwise

    Example:
        >>> conn = create_connection(config)
        >>> object_exists(conn, "dbo", "Orders")
        True
        >>> object_exists(conn, "dbo", "NonExistent")
        False
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT 1
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE s.name = ?
              AND o.name = ?
              AND o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
        """

        cursor.execute(query, (schema_name, object_name))
        return cursor.fetchone() is not None

    finally:
        cursor.close()


def get_object_count(conn: pyodbc.Connection) -> int:
    """
    Get the total count of database objects.

    Args:
        conn: Active database connection

    Returns:
        int: Number of database objects

    Used for scale validation and UI feedback (e.g., "Showing 12 of 523 objects").

    Example:
        >>> conn = create_connection(config)
        >>> get_object_count(conn)
        523
    """
    cursor = conn.cursor()
    try:
        query = """
            SELECT COUNT(*)
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE o.type IN ('U', 'V', 'P', 'FN', 'IF', 'TF')
              AND o.is_ms_shipped = 0
              AND s.name NOT IN ('sys', 'INFORMATION_SCHEMA')
        """

        cursor.execute(query)
        row = cursor.fetchone()
        return row[0] if row else 0

    finally:
        cursor.close()
