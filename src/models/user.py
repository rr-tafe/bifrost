"""
Database user domain model for Bifrost.

This module defines the DatabaseUser dataclass representing a SQL Server
database principal that can hold object permissions.

Users are loaded from sys.database_principals and can have local tags assigned
via the tags.json file.

Usage:
    user = DatabaseUser(
        login_name="alice",
        display_name="alice",
        principal_type="S",
        is_disabled=False,
        tags=["finance", "readonly"]
    )
"""

from dataclasses import dataclass, field


@dataclass
class DatabaseUser:
    """
    Represents a SQL Server database principal that can hold object permissions.

    Attributes:
        login_name: Unique identifier; sys.database_principals.name
        display_name: Name shown in UI (same as login_name in v1)
        principal_type: SQL Server type ('S'=SQL, 'U'=Windows, 'G'=group)
        is_disabled: Whether principal is disabled (visual indicator only)
        tags: Local tags assigned via tags.json (alphanumeric, no spaces)

    Validation:
        - login_name must be non-empty
        - Each tag must match ^[A-Za-z0-9]+$

    Note:
        Tags are stored locally in %APPDATA%/Bifrost/tags.json keyed by login_name.
        Disabled users are shown visually but permission management is still allowed.
    """

    login_name: str
    display_name: str
    principal_type: str  # 'S' (SQL), 'U' (Windows), 'G' (group)
    is_disabled: bool = False
    tags: list[str] = field(default_factory=list)
    principal_id: int = 0  # sys.database_principals.principal_id (0 = unknown)

    def __post_init__(self):
        """Validate required fields after initialization."""
        if not self.login_name:
            raise ValueError("login_name must be non-empty")
        if not self.display_name:
            self.display_name = self.login_name

    def add_tag(self, tag: str) -> None:
        """
        Add a tag if not already present (case-insensitive duplicate check).

        Args:
            tag: Tag to add (must match ^[A-Za-z0-9]+$)

        Raises:
            ValueError: If tag format is invalid

        Note:
            Tags are case-preserved but duplicate detection is case-insensitive.
        """
        import re
        if not re.match(r"^[A-Za-z0-9]+$", tag):
            raise ValueError(f"Tag must match ^[A-Za-z0-9]+$, got: {tag}")

        # Case-insensitive duplicate check
        if not any(t.lower() == tag.lower() for t in self.tags):
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """
        Remove a tag (case-insensitive match).

        Args:
            tag: Tag to remove
        """
        self.tags = [t for t in self.tags if t.lower() != tag.lower()]

    def has_tag(self, tag: str) -> bool:
        """
        Check if user has a specific tag (case-insensitive).

        Args:
            tag: Tag to check

        Returns:
            bool: True if tag exists (case-insensitive match)
        """
        return any(t.lower() == tag.lower() for t in self.tags)
