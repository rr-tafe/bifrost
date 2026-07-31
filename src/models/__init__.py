"""
Domain models for Bifrost.

This package contains dataclasses representing the core domain entities:
    - user.py: DatabaseUser (SQL Server database principals)
    - db_object.py: DatabaseObject (tables, views, procedures, functions)
    - permission.py: PermissionAssignment, PermissionState, PermissionType
    - audit_entry.py: AuditEntry (immutable audit log records)
    - config.py: Configuration (connection settings)

Models are pure data structures with no business logic.
Validation is handled at the boundary (ui/ and validation.py).
"""
