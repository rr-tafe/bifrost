"""
Input validation for Bifrost.

This module provides boundary-level validation for user inputs:
    - Tag format validation (^[A-Za-z0-9]+$)
    - Configuration field validation (delegates to Configuration.validate())
    - Search term validation (boundary cases, special characters)

All validation is performed at the UI boundary before data enters the domain layer.
Domain models themselves validate required fields but rely on this module for
format and content validation.

Usage:
    from src.validation import validate_tag, validate_search_term, validate_config
    
    # Tag validation
    errors = validate_tag("Finance123")  # []
    errors = validate_tag("Bad Tag!")     # ["Tag must match ^[A-Za-z0-9]+$"]
    
    # Search validation
    errors = validate_search_term("alice")  # []
    errors = validate_search_term("")       # [] (empty is valid)
    
    # Config validation
    from src.models.config import Configuration
    config = Configuration(server="", port=99999, database="Test")
    errors = validate_config(config)  # ["server must be non-empty", "port must be..."]
"""

import re
from src.models.config import Configuration


def validate_tag(tag: str) -> list[str]:
    """
    Validate a tag against the required format.
    
    Args:
        tag: Tag string to validate
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Rules:
        - Must match ^[A-Za-z0-9]+$ (alphanumeric only, no spaces or special characters)
        - Cannot be empty
    
    Examples:
        >>> validate_tag("Finance")
        []
        >>> validate_tag("Finance123")
        []
        >>> validate_tag("Bad Tag!")
        ['Tag must match ^[A-Za-z0-9]+$ (alphanumeric only, no spaces)']
        >>> validate_tag("")
        ['Tag cannot be empty']
    """
    errors = []
    
    if not tag:
        errors.append("Tag cannot be empty")
        return errors
    
    if not re.match(r"^[A-Za-z0-9]+$", tag):
        errors.append("Tag must match ^[A-Za-z0-9]+$ (alphanumeric only, no spaces)")
    
    return errors


def validate_search_term(search_term: str) -> list[str]:
    """
    Validate a search term for matrix filtering.
    
    Args:
        search_term: Search string to validate
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Rules:
        - Empty string is valid (no filter applied)
        - Special characters are allowed (SQL injection protection handled by parameterization)
        - No length limit (database will handle truncation if needed)
    
    Note:
        This validation is intentionally permissive. SQL injection protection
        is handled by parameterized queries in the database layer.
    
    Examples:
        >>> validate_search_term("alice")
        []
        >>> validate_search_term("")
        []
        >>> validate_search_term("O'Brien")
        []
    """
    # Empty search term is valid (no filter)
    if not search_term:
        return []
    
    # All non-empty search terms are valid
    # Special characters are allowed; SQL injection protection via parameterization
    return []


def validate_config(config: Configuration) -> list[str]:
    """
    Validate a configuration object.
    
    Args:
        config: Configuration instance to validate
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Delegates to Configuration.validate() for all validation logic.
    
    Example:
        >>> from src.models.config import Configuration
        >>> config = Configuration(server="SQLSERVER01", database="MyDB")
        >>> errors = validate_config(config)
        >>> errors
        []
    """
    return config.validate()


def validate_port(port: str | int) -> list[str]:
    """
    Validate a port number string or integer.
    
    Args:
        port: Port number (string or int)
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Rules:
        - Must be numeric
        - Must be in range 1-65535
    
    Examples:
        >>> validate_port("1433")
        []
        >>> validate_port(1433)
        []
        >>> validate_port("abc")
        ['Port must be a number']
        >>> validate_port("99999")
        ['Port must be between 1 and 65535']
    """
    errors = []
    
    try:
        port_int = int(port)
    except (ValueError, TypeError):
        errors.append("Port must be a number")
        return errors
    
    if not (1 <= port_int <= 65535):
        errors.append("Port must be between 1 and 65535")
    
    return errors


def validate_schema_name(schema: str) -> list[str]:
    """
    Validate a SQL Server schema name.
    
    Args:
        schema: Schema name to validate
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Rules:
        - Must be non-empty
        - Must match ^[A-Za-z_][A-Za-z0-9_]*$ (valid SQL identifier)
        - First character must be letter or underscore
        - Subsequent characters can be letters, numbers, or underscores
    
    Examples:
        >>> validate_schema_name("dbo")
        []
        >>> validate_schema_name("_schema123")
        []
        >>> validate_schema_name("123invalid")
        ['Schema must be a valid SQL identifier...']
        >>> validate_schema_name("bad-schema")
        ['Schema must be a valid SQL identifier...']
    """
    errors = []
    
    if not schema:
        errors.append("Schema cannot be empty")
        return errors
    
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", schema):
        errors.append(
            "Schema must be a valid SQL identifier "
            "(start with letter or underscore, contain only letters, numbers, underscores)"
        )
    
    return errors


def validate_description(description: str | None) -> list[str]:
    """
    Validate an object description.
    
    Args:
        description: Object description text (or None)
    
    Returns:
        list[str]: List of validation errors (empty if valid)
    
    Rules:
        - None is valid (no description)
        - Empty string is valid
        - Max 7500 characters (SQL Server extended_properties limit)
        - No special character restrictions
    
    Examples:
        >>> validate_description(None)
        []
        >>> validate_description("")
        []
        >>> validate_description("This is a valid description")
        []
        >>> validate_description("x" * 7501)
        ['Description exceeds maximum length of 7500 characters']
    """
    errors = []
    
    if description is None or description == "":
        return []
    
    if len(description) > 7500:
        errors.append(
            f"Description exceeds maximum length of 7500 characters "
            f"(current: {len(description)} characters)"
        )
    
    return errors
