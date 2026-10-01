"""
Bifrost - SQL Server Permissions Manager

A Python/Tkinter desktop application for Windows 11 that allows administrators
to view and manage SQL Server 2019+ object-level permissions via a staged-commit
permission matrix.

Package structure:
    - db/: Database access layer (pyodbc-based SQL Server connectivity)
    - models/: Domain model dataclasses (users, objects, permissions, audit, config)
    - services/: Business logic (permission matrix, tags, config, CSV export)
    - ui/: Tkinter-based user interface (app window, views, widgets)
    - validation.py: Input validation for tags, config, and search terms

Architectural principles:
    - Single-project flat layout (no backend/frontend split for desktop app)
    - Direct pyodbc usage in db/ module (no ORM or repository patterns)
    - Dataclasses for domain models (no classes with behavior in models/)
    - Business logic in services/ (stateful matrix, stateless utilities)
    - UI in ui/ (Tkinter Canvas-based virtual scrolling for matrix)

Storage:
    - SQL Server: permissions, audit log, object descriptions
    - %APPDATA%/Bifrost/config.json: connection configuration
    - %APPDATA%/Bifrost/tags.json: local tag assignments
    - In-memory: staged permission changes (lost on crash before commit)
"""

__version__ = "1.0.0"
__author__ = "Bifrost Team"

# Package-level imports will be added as modules are implemented
