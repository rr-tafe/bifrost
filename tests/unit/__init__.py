"""
Unit tests for Bifrost.

This package contains unit tests that run without external dependencies:
    - test_matrix.py: Staging logic, commit/cancel, state transitions
    - test_tags.py: Tag validation and CRUD operations
    - test_export.py: CSV format validation
    - test_validation.py: Input boundary validation
    - test_audit.py: Audit log data structures
    - test_objects.py: Object description handling
    - test_config.py: Configuration serialization
    - test_models.py: Domain model validation
    - test_services.py: Service-layer logic
    - test_accessibility.py: Accessibility compliance

All tests use unittest.mock for database isolation.
Run with: pytest tests/unit/
"""
