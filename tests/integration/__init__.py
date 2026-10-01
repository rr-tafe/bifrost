"""
Integration tests for Bifrost.

This package contains integration tests that require a live SQL Server connection:
    - test_db.py: Database layer integration (connection, reads, writes, audit log)

Tests are marked with @pytest.mark.integration and are excluded from pre-commit hooks.
They require a test SQL Server instance with appropriate permissions.

Run with: pytest tests/integration/ -m integration

Prerequisites:
    - SQL Server 2019+ accessible from the test environment
    - Test database with db_owner or sysadmin privileges
    - Test fixture users and objects (see specs/001-sql-permissions-manager/quickstart.md)
"""
