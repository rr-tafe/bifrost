"""
T-SQL text helpers for Bifrost.

Identifiers (schema, object and principal names) cannot be passed as query
parameters, so any statement that names them must quote them. quote_ident()
does what SQL Server's QUOTENAME() does: wrap in brackets and double any
closing bracket inside the name.

Usage:
    from src.db.sql import quote_ident

    stmt = f"GRANT SELECT ON {quote_ident(schema)}.{quote_ident(obj)} TO {quote_ident(user)}"
"""

# SQL Server's sysname is NVARCHAR(128)
MAX_IDENTIFIER_LENGTH = 128


def quote_ident(name: str) -> str:
    """
    Return name as a bracket-quoted T-SQL identifier, like QUOTENAME().

    Args:
        name: Identifier to quote (schema, object or principal name)

    Returns:
        str: Quoted identifier, e.g. "a]b" -> "[a]]b]"

    Raises:
        ValueError: If name is empty, longer than 128 characters, or contains NUL
    """
    if not name:
        raise ValueError("Identifier must be non-empty")
    if len(name) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"Identifier is longer than {MAX_IDENTIFIER_LENGTH} characters: {name[:40]}..."
        )
    if "\x00" in name:
        raise ValueError("Identifier must not contain NUL characters")
    return "[" + name.replace("]", "]]") + "]"
