"""
Unit tests for Bifrost validation module.

Tests cover:
    - Tag validation (format)
    - Search term validation
    - Configuration validation
    - Port validation
    - Schema name validation

Note: The validation module returns lists of error strings.
Empty list indicates validation passed.

Run with: pytest tests/unit/test_validation.py -v
"""

import pytest
from src.validation import (
    validate_tag,
    validate_search_term,
    validate_config,
    validate_port,
    validate_schema_name,
)
from src.models.config import Configuration


class TestValidateTag:
    """Tests for tag validation."""

    def test_valid_simple_tag(self):
        """Test valid alphanumeric tag passes."""
        errors = validate_tag("finance")
        assert errors == []

    def test_valid_tag_with_numbers(self):
        """Test tag with numbers passes."""
        errors = validate_tag("team1")
        assert errors == []

    def test_empty_tag_fails(self):
        """Test empty tag returns error."""
        errors = validate_tag("")
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_tag_with_space_fails(self):
        """Test tag with space returns error."""
        errors = validate_tag("my tag")
        assert len(errors) > 0

    def test_tag_with_special_chars_fails(self):
        """Test tag with special characters returns error."""
        errors = validate_tag("finance!")
        assert len(errors) > 0


class TestValidateSearchTerm:
    """Tests for search term validation."""

    def test_valid_search_term(self):
        """Test valid search term passes."""
        errors = validate_search_term("Orders")
        assert errors == []

    def test_empty_search_term(self):
        """Test empty search term is valid (no filter)."""
        errors = validate_search_term("")
        assert errors == []

    def test_search_term_with_special_chars(self):
        """Test special characters are allowed (parameterized queries handle SQL injection)."""
        errors = validate_search_term("O'Brien")
        assert errors == []


class TestValidateConfig:
    """Tests for configuration validation."""

    def test_valid_config(self):
        """Test valid configuration passes."""
        config = Configuration(
            server="SQLSERVER01",
            port=1433,
            database="MyDB",
            schema="dbo",
            auth_type="windows",
        )
        errors = validate_config(config)
        assert len(errors) == 0

    def test_empty_server_fails(self):
        """Test empty server generates error."""
        config = Configuration(server="", database="MyDB")
        errors = validate_config(config)
        assert any("server" in e.lower() for e in errors)

    def test_missing_database_fails(self):
        """Test empty database generates error."""
        config = Configuration(server="localhost", database="")
        errors = validate_config(config)
        assert any("database" in e.lower() for e in errors)


class TestValidatePort:
    """Tests for port validation."""

    def test_valid_port(self):
        """Test valid port passes."""
        errors = validate_port(1433)
        assert errors == []

    def test_valid_port_string(self):
        """Test valid port as string passes."""
        errors = validate_port("1433")
        assert errors == []

    def test_port_at_lower_bound(self):
        """Test port at minimum value passes."""
        errors = validate_port(1)
        assert errors == []

    def test_port_at_upper_bound(self):
        """Test port at maximum value passes."""
        errors = validate_port(65535)
        assert errors == []

    def test_port_zero_fails(self):
        """Test port 0 returns error."""
        errors = validate_port(0)
        assert len(errors) > 0

    def test_negative_port_fails(self):
        """Test negative port returns error."""
        errors = validate_port(-1)
        assert len(errors) > 0

    def test_port_too_high_fails(self):
        """Test port above 65535 returns error."""
        errors = validate_port(65536)
        assert len(errors) > 0

    def test_non_numeric_port_fails(self):
        """Test non-numeric port returns error."""
        errors = validate_port("abc")
        assert len(errors) > 0


class TestValidateSchemaName:
    """Tests for schema name validation."""

    def test_valid_schema(self):
        """Test valid schema name passes."""
        errors = validate_schema_name("dbo")
        assert errors == []

    def test_valid_schema_with_underscore(self):
        """Test schema with underscore passes."""
        errors = validate_schema_name("my_schema")
        assert errors == []

    def test_valid_schema_starting_with_underscore(self):
        """Test schema starting with underscore passes."""
        errors = validate_schema_name("_schema")
        assert errors == []

    def test_empty_schema_fails(self):
        """Test empty schema returns error."""
        errors = validate_schema_name("")
        assert len(errors) > 0
        assert any("empty" in e.lower() for e in errors)

    def test_schema_with_invalid_chars_fails(self):
        """Test schema with special characters returns error."""
        errors = validate_schema_name("bad-schema")
        assert len(errors) > 0

    def test_schema_starting_with_number_fails(self):
        """Test schema starting with number returns error."""
        errors = validate_schema_name("1schema")
        assert len(errors) > 0
