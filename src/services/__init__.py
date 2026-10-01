"""
Business logic services for Bifrost.

This package provides the core application services:
    - matrix.py: In-memory permission matrix; staging engine; commit/cancel
    - tags.py: Tag CRUD operations; read/write tags.json
    - config.py: Configuration persistence to %APPDATA%/Bifrost/config.json
    - export.py: CSV export for permission matrix and audit log

Services coordinate between the database layer (db/) and the UI layer (ui/).
The matrix service is stateful (holds staged changes in memory).
Other services are primarily stateless utilities.
"""
