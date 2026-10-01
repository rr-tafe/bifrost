"""
Database access layer for Bifrost.

This package provides SQL Server connectivity and data access for:
    - connection.py: pyodbc connection factory (Windows Authentication only)
    - users.py: Read sys.database_principals for database users
    - objects.py: Read sys.objects + sys.schemas; manage extended properties
    - permissions.py: Read sys.database_permissions; apply GRANT/DENY/REVOKE
    - audit.py: Write to and read from <schema>.Bifrost_audit_log

All modules use pyodbc directly without ORM or repository patterns.
Connection pooling is not used; a single connection is held per app session.
"""
