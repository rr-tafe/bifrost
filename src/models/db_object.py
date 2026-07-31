"""
Database object domain model for Bifrost.

This module defines the DatabaseObject dataclass representing a schema-scoped
SQL Server object (table, view, procedure, function) that permissions can be granted on.

Objects are loaded from sys.objects + sys.schemas and can have:
    - Local tags (stored in tags.json)
    - Descriptions (stored in SQL Server sys.extended_properties as MS_Description)

Usage:
    obj = DatabaseObject(
        schema_name="dbo",
        object_name="Orders",
        object_type=ObjectType.TABLE,
        tags=["finance", "critical"],
        description="Customer orders table"
    )
"""

from dataclasses import dataclass, field
from enum import Enum


class ObjectType(Enum):
    """
    SQL Server object types supported in Bifrost v1.

    Attributes:
        TABLE: User table (sys.objects.type = 'U')
        VIEW: View (sys.objects.type = 'V')
        PROCEDURE: Stored procedure (sys.objects.type = 'P')
        FUNCTION: Function (sys.objects.type in 'FN', 'IF', 'TF')

    Mapping from sys.objects.type:
        'U' → TABLE
        'V' → VIEW
        'P' → PROCEDURE
        'FN', 'IF', 'TF' → FUNCTION
    """

    TABLE = "TABLE"
    VIEW = "VIEW"
    PROCEDURE = "PROCEDURE"
    FUNCTION = "FUNCTION"

    @classmethod
    def from_sql_type(cls, sql_type: str) -> "ObjectType":
        """
        Convert sys.objects.type to ObjectType enum.

        Args:
            sql_type: SQL Server type code from sys.objects.type

        Returns:
            ObjectType: Corresponding enum value

        Raises:
            ValueError: If sql_type is not recognized
        """
        mapping = {
            "U": cls.TABLE,
            "V": cls.VIEW,
            "P": cls.PROCEDURE,
            "FN": cls.FUNCTION,
            "IF": cls.FUNCTION,
            "TF": cls.FUNCTION,
        }

        if sql_type not in mapping:
            raise ValueError(f"Unsupported SQL Server object type: {sql_type}")

        return mapping[sql_type]

    def supports_permission(self, permission_type: "PermissionType") -> bool:  # noqa: F821
        """
        Check if this object type supports a given permission.

        Args:
            permission_type: PermissionType to check

        Returns:
            bool: True if permission is applicable to this object type

        Applicable permissions by type:
            TABLE, VIEW: SELECT, INSERT, UPDATE, DELETE, ALTER, REFERENCES, VIEW DEFINITION
            PROCEDURE, FUNCTION: EXECUTE, ALTER, VIEW DEFINITION
        """
        from src.models.permission import PermissionType

        dml = {PermissionType.SELECT, PermissionType.INSERT,
               PermissionType.UPDATE, PermissionType.DELETE}
        ddl = {PermissionType.ALTER, PermissionType.VIEW_DEFINITION}
        ref = {PermissionType.REFERENCES}
        exe = {PermissionType.EXECUTE}

        if self in (ObjectType.TABLE, ObjectType.VIEW):
            return permission_type in (dml | ddl | ref)
        else:  # PROCEDURE, FUNCTION
            return permission_type in (exe | ddl)


@dataclass
class DatabaseObject:
    """
    Represents a schema-scoped SQL Server object that permissions can be granted on.

    Attributes:
        schema_name: Schema name (part of unique identifier)
        object_name: Object name (part of unique identifier)
        object_type: Type of object (TABLE, VIEW, PROCEDURE, FUNCTION)
        tags: Local tags assigned via tags.json (alphanumeric, no spaces)
        description: Free-text description (stored in sys.extended_properties)

    Unique identifier: f"{schema_name}.{object_name}"

    Validation:
        - schema_name and object_name must be non-empty
        - description max 7500 chars (SQL Server extended_properties limit)
        - Each tag must match ^[A-Za-z0-9]+$

    Note:
        Tags are stored locally in %APPDATA%/Bifrost/tags.json.
        Description is stored in SQL Server (shared across admins).
    """

    schema_name: str
    object_name: str
    object_type: ObjectType
    tags: list[str] = field(default_factory=list)
    description: str | None = None

    def __post_init__(self):
        """Validate required fields after initialization."""
        if not self.schema_name:
            raise ValueError("schema_name must be non-empty")
        if not self.object_name:
            raise ValueError("object_name must be non-empty")
        if self.description is not None and len(self.description) > 7500:
            raise ValueError(
                f"description exceeds SQL Server extended_properties limit (7500 chars): "
                f"{len(self.description)} chars"
            )

    @property
    def full_name(self) -> str:
        """
        Return the fully qualified object name.

        Returns:
            str: "schema_name.object_name"
        """
        return f"{self.schema_name}.{self.object_name}"

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
        Check if object has a specific tag (case-insensitive).

        Args:
            tag: Tag to check

        Returns:
            bool: True if tag exists (case-insensitive match)
        """
        return any(t.lower() == tag.lower() for t in self.tags)

    def supports_permission(self, permission_type: "PermissionType") -> bool:  # noqa: F821
        """
        Check if this object supports a given permission type.

        Args:
            permission_type: PermissionType to check

        Returns:
            bool: True if permission is applicable to this object
        """
        return self.object_type.supports_permission(permission_type)
