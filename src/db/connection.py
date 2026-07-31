"""
Database connection factory for Bifrost.

This module provides SQL Server connectivity using pyodbc with Windows Authentication.
A single connection is maintained per application session (no connection pooling).

Connection Requirements:
    - Microsoft ODBC Driver 18 for SQL Server installed at OS level
    - Windows 11
    - SQL Server 2019+
    - Windows Authentication only (Trusted_Connection=yes)

Administrator Permissions Required:
    - VIEW DEFINITION on target database
    - SELECT on sys.database_permissions
    - GRANT OPTION on permissions they wish to manage
    - INSERT on <schema>.Bifrost_audit_log
    - ALTER on objects (for extended properties)
    - CREATE SCHEMA (if schema doesn't exist)
    - Typically: db_owner or sysadmin role

Usage:
    from src.db.connection import create_connection, test_connection
    from src.models.config import Configuration
    
    config = Configuration(
        server="SQLSERVER01",
        port=1433,
        database="MyAppDB",
        schema="dbo",
        auth_type="windows"
    )
    
    # Test connection (returns error message or None)
    error = test_connection(config)
    if error:
        print(f"Connection failed: {error}")
    
    # Create connection (raises on failure)
    conn = create_connection(config)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        print(cursor.fetchone()[0])
    finally:
        conn.close()
"""

import pyodbc
from typing import Optional
from src.models.config import Configuration


class DatabaseConnectionError(Exception):
    """Raised when database connection fails."""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        """
        Initialize database connection error.
        
        Args:
            message: User-friendly error message
            original_error: Original exception from pyodbc (if any)
        """
        super().__init__(message)
        self.original_error = original_error


def create_connection(config: Configuration) -> pyodbc.Connection:
    """
    Create a SQL Server connection using the provided configuration.
    
    Args:
        config: Configuration with server, port, database, auth settings
    
    Returns:
        pyodbc.Connection: Active database connection
    
    Raises:
        DatabaseConnectionError: If connection fails
        ValueError: If configuration is invalid
    
    Connection String Format:
        DRIVER={ODBC Driver 18 for SQL Server};
        SERVER=<server>,<port>;
        DATABASE=<database>;
        Trusted_Connection=yes;
        TrustServerCertificate=yes;
        Encrypt=yes;
    
    Note:
        - TrustServerCertificate=yes allows self-signed certificates (common in dev/test)
        - Encrypt=yes enforces encrypted connection
        - Trusted_Connection=yes uses current Windows identity
        - No username/password in connection string
    
    Example:
        >>> config = Configuration(server="localhost", database="MyDB")
        >>> conn = create_connection(config)
        >>> cursor = conn.cursor()
        >>> cursor.execute("SELECT 1")
        >>> cursor.fetchone()
        (1,)
    """
    # Validate configuration before attempting connection
    validation_errors = config.validate()
    if validation_errors:
        raise ValueError(f"Invalid configuration: {', '.join(validation_errors)}")
    
    # Build connection string for Windows Authentication
    connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={config.server},{config.port};"
        f"DATABASE={config.database};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )
    
    try:
        conn = pyodbc.connect(connection_string, timeout=10)
        conn.autocommit = False  # Explicit transaction control for commit/rollback
        return conn
    
    except pyodbc.Error as e:
        # Extract user-friendly error message from pyodbc error
        error_message = str(e)
        
        # Common error patterns and user-friendly messages
        if "Login failed" in error_message or "authentication failed" in error_message.lower():
            friendly_message = (
                f"Authentication failed. Ensure your Windows account has access to "
                f"database '{config.database}' on server '{config.server}'."
            )
        elif "server was not found" in error_message.lower() or "host" in error_message.lower():
            friendly_message = (
                f"Server '{config.server}' not found. Check server name and network connectivity."
            )
        elif "database" in error_message.lower() and "does not exist" in error_message.lower():
            friendly_message = (
                f"Database '{config.database}' does not exist on server '{config.server}'."
            )
        elif "timeout" in error_message.lower():
            friendly_message = (
                f"Connection timeout. Server '{config.server}' may be unreachable or busy."
            )
        else:
            # Generic error with original message
            friendly_message = f"Database connection failed: {error_message}"
        
        raise DatabaseConnectionError(friendly_message, original_error=e)


def test_connection(config: Configuration) -> Optional[str]:
    """
    Test database connection and return error message if it fails.
    
    Args:
        config: Configuration to test
    
    Returns:
        Optional[str]: Error message if connection fails, None if successful
    
    This is a non-raising version of create_connection() for use in the Settings UI
    where we want to show validation feedback without exception handling.
    
    Example:
        >>> config = Configuration(server="invalid", database="test")
        >>> error = test_connection(config)
        >>> if error:
        ...     print(f"Connection failed: {error}")
        Connection failed: Server 'invalid' not found...
    """
    try:
        conn = create_connection(config)
        conn.close()
        return None
    
    except (DatabaseConnectionError, ValueError) as e:
        return str(e)
    
    except Exception as e:
        return f"Unexpected error: {str(e)}"


def get_current_user(conn: pyodbc.Connection) -> str:
    """
    Get the current SQL Server user identity (SYSTEM_USER).
    
    Args:
        conn: Active database connection
    
    Returns:
        str: Current user identity (e.g., "DOMAIN\\username")
    
    This is used for populating the 'administrator' field in audit log entries.
    
    Example:
        >>> conn = create_connection(config)
        >>> user = get_current_user(conn)
        >>> print(user)
        DOMAIN\\alice
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT SYSTEM_USER")
        result = cursor.fetchone()
        return result[0] if result else "UNKNOWN"
    finally:
        cursor.close()


def ensure_schema_exists(conn: pyodbc.Connection, schema_name: str) -> None:
    """
    Ensure the specified schema exists, creating it if necessary.
    
    Args:
        conn: Active database connection
        schema_name: Schema name to check/create
    
    Raises:
        DatabaseConnectionError: If schema creation fails
    
    Note:
        - Skipped if schema is 'dbo' (always exists)
        - Requires CREATE SCHEMA permission
        - Part of the startup sequence (called before audit log table check)
    
    Example:
        >>> conn = create_connection(config)
        >>> ensure_schema_exists(conn, "bifrost")
    """
    if schema_name.lower() == "dbo":
        return  # dbo always exists
    
    cursor = conn.cursor()
    try:
        # Check if schema exists
        cursor.execute(
            "SELECT 1 FROM sys.schemas WHERE name = ?",
            (schema_name,)
        )
        
        if cursor.fetchone():
            return  # Schema already exists
        
        # Create schema
        # Cannot use parameterized query for DDL, so validate schema name first
        import re
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema_name):
            raise ValueError(f"Invalid schema name: {schema_name}")
        
        cursor.execute(f"CREATE SCHEMA [{schema_name}]")
        conn.commit()
    
    except pyodbc.Error as e:
        conn.rollback()
        raise DatabaseConnectionError(
            f"Failed to create schema '{schema_name}': {str(e)}",
            original_error=e
        )
    
    finally:
        cursor.close()


def get_server_version(conn: pyodbc.Connection) -> str:
    """
    Get SQL Server version information.
    
    Args:
        conn: Active database connection
    
    Returns:
        str: SQL Server version string
    
    Example:
        >>> conn = create_connection(config)
        >>> version = get_server_version(conn)
        >>> print(version)
        Microsoft SQL Server 2019...
    """
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT @@VERSION")
        result = cursor.fetchone()
        return result[0] if result else "Unknown"
    finally:
        cursor.close()
