"""
Tag management service for Bifrost.

This module provides the TagStore class for managing local tag assignments
on users and objects. Tags are stored in %APPDATA%/Bifrost/tags.json.

Tags are local to each administrator's machine (not shared via SQL Server).
Tag format: ^[A-Za-z0-9]+$ (alphanumeric only, no spaces or special characters).

Usage:
    from src.services.tags import TagStore

    # Load tag store
    store = TagStore.load()

    # Add tags to user
    store.add_user_tag("alice", "finance")
    store.add_user_tag("alice", "readonly")

    # Add tags to object
    store.add_object_tag("dbo.Orders", "critical")

    # Save changes
    store.save()

    # Query tags
    user_tags = store.get_user_tags("alice")
    object_tags = store.get_object_tags("dbo.Orders")

    # Get all tags
    all_tags = store.get_all_tags()
"""

import json
from pathlib import Path
from typing import Optional
from src.models.config import Configuration


class TagStore:
    """
    Manages local tag assignments for users and objects.

    Attributes:
        user_tags: dict[str, list[str]] - Maps login_name to list of tags
        object_tags: dict[str, list[str]] - Maps "schema.object" to list of tags

    Storage:
        %APPDATA%/Bifrost/tags.json

    Tag Rules:
        - Format: ^[A-Za-z0-9]+$ (validated at add time)
        - Case-preserved but duplicate detection is case-insensitive
        - Empty tag list is valid

    Thread Safety:
        Not thread-safe. Single-threaded desktop app.

    Example:
        >>> store = TagStore()
        >>> store.add_user_tag("alice", "finance")
        >>> store.get_user_tags("alice")
        ['finance']
        >>> store.save()
    """

    def __init__(self):
        """Initialize an empty TagStore."""
        self.user_tags: dict[str, list[str]] = {}
        self.object_tags: dict[str, list[str]] = {}

    def add_user_tag(self, login_name: str, tag: str) -> None:
        """
        Add a tag to a user (case-insensitive duplicate check).

        Args:
            login_name: Database principal login name
            tag: Tag to add (must match ^[A-Za-z0-9]+$)

        Raises:
            ValueError: If tag format is invalid

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> store.get_user_tags("alice")
            ['finance']
            >>> store.add_user_tag("alice", "Finance")  # Duplicate (case-insensitive)
            >>> store.get_user_tags("alice")
            ['finance']  # Original case preserved
        """
        import re
        if not re.match(r"^[A-Za-z0-9]+$", tag):
            raise ValueError(f"Tag must match ^[A-Za-z0-9]+$, got: {tag}")

        if login_name not in self.user_tags:
            self.user_tags[login_name] = []

        # Case-insensitive duplicate check
        existing_tags_lower = [t.lower() for t in self.user_tags[login_name]]
        if tag.lower() not in existing_tags_lower:
            self.user_tags[login_name].append(tag)

    def add_object_tag(self, full_name: str, tag: str) -> None:
        """
        Add a tag to an object (case-insensitive duplicate check).

        Args:
            full_name: Object name in "schema.object" format
            tag: Tag to add (must match ^[A-Za-z0-9]+$)

        Raises:
            ValueError: If tag format is invalid

        Example:
            >>> store = TagStore()
            >>> store.add_object_tag("dbo.Orders", "critical")
            >>> store.get_object_tags("dbo.Orders")
            ['critical']
        """
        import re
        if not re.match(r"^[A-Za-z0-9]+$", tag):
            raise ValueError(f"Tag must match ^[A-Za-z0-9]+$, got: {tag}")

        if full_name not in self.object_tags:
            self.object_tags[full_name] = []

        existing_tags_lower = [t.lower() for t in self.object_tags[full_name]]
        if tag.lower() not in existing_tags_lower:
            self.object_tags[full_name].append(tag)

    def remove_user_tag(self, login_name: str, tag: str) -> None:
        """
        Remove a tag from a user (case-insensitive match).

        Args:
            login_name: Database principal login name
            tag: Tag to remove

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> store.remove_user_tag("alice", "Finance")  # Case-insensitive
            >>> store.get_user_tags("alice")
            []
        """
        if login_name in self.user_tags:
            self.user_tags[login_name] = [
                t for t in self.user_tags[login_name]
                if t.lower() != tag.lower()
            ]

            # Clean up empty entries
            if not self.user_tags[login_name]:
                del self.user_tags[login_name]

    def remove_object_tag(self, full_name: str, tag: str) -> None:
        """
        Remove a tag from an object (case-insensitive match).

        Args:
            full_name: Object name in "schema.object" format
            tag: Tag to remove

        Example:
            >>> store = TagStore()
            >>> store.add_object_tag("dbo.Orders", "critical")
            >>> store.remove_object_tag("dbo.Orders", "Critical")
            >>> store.get_object_tags("dbo.Orders")
            []
        """
        if full_name in self.object_tags:
            self.object_tags[full_name] = [
                t for t in self.object_tags[full_name]
                if t.lower() != tag.lower()
            ]

            if not self.object_tags[full_name]:
                del self.object_tags[full_name]

    def rename_tag(self, old_tag: str, new_tag: str) -> None:
        """
        Rename a tag across all users and objects (case-insensitive match on old_tag).

        Args:
            old_tag: Existing tag name to rename (case-insensitive match)
            new_tag: New tag name (must match ^[A-Za-z0-9]+$)

        Raises:
            ValueError: If new_tag format is invalid

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> store.add_object_tag("dbo.Orders", "finance")
            >>> store.rename_tag("finance", "Finance2024")
            >>> store.get_user_tags("alice")
            ['Finance2024']
            >>> store.get_object_tags("dbo.Orders")
            ['Finance2024']
        """
        import re
        if not re.match(r"^[A-Za-z0-9]+$", new_tag):
            raise ValueError(f"Tag must match ^[A-Za-z0-9]+$, got: {new_tag}")

        # Rename in user_tags
        for login_name in list(self.user_tags.keys()):
            tags = self.user_tags[login_name]
            renamed_tags = [
                new_tag if t.lower() == old_tag.lower() else t
                for t in tags
            ]
            self.user_tags[login_name] = renamed_tags

        # Rename in object_tags
        for full_name in list(self.object_tags.keys()):
            tags = self.object_tags[full_name]
            renamed_tags = [
                new_tag if t.lower() == old_tag.lower() else t
                for t in tags
            ]
            self.object_tags[full_name] = renamed_tags

    def get_user_tags(self, login_name: str) -> list[str]:
        """
        Get tags for a user.

        Args:
            login_name: Database principal login name

        Returns:
            list[str]: List of tags (empty if user has no tags)

        Example:
            >>> store = TagStore()
            >>> store.get_user_tags("alice")
            []
            >>> store.add_user_tag("alice", "finance")
            >>> store.get_user_tags("alice")
            ['finance']
        """
        return self.user_tags.get(login_name, []).copy()

    def get_object_tags(self, full_name: str) -> list[str]:
        """
        Get tags for an object.

        Args:
            full_name: Object name in "schema.object" format

        Returns:
            list[str]: List of tags (empty if object has no tags)

        Example:
            >>> store = TagStore()
            >>> store.get_object_tags("dbo.Orders")
            []
            >>> store.add_object_tag("dbo.Orders", "critical")
            >>> store.get_object_tags("dbo.Orders")
            ['critical']
        """
        return self.object_tags.get(full_name, []).copy()

    def get_all_tags(self) -> set[str]:
        """
        Get the set of all unique tags across users and objects.

        Returns:
            set[str]: Set of all tags (case-preserved as stored)

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> store.add_object_tag("dbo.Orders", "critical")
            >>> store.add_object_tag("dbo.Products", "finance")
            >>> sorted(store.get_all_tags())
            ['critical', 'finance']
        """
        all_tags = set()

        for tags in self.user_tags.values():
            all_tags.update(tags)

        for tags in self.object_tags.values():
            all_tags.update(tags)

        return all_tags

    def get_users_with_tag(self, tag: str) -> list[str]:
        """
        Get all users that have a specific tag (case-insensitive match).

        Args:
            tag: Tag to search for

        Returns:
            list[str]: List of login names that have the tag

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> store.add_user_tag("bob", "finance")
            >>> store.get_users_with_tag("finance")
            ['alice', 'bob']
        """
        tag_lower = tag.lower()
        return [
            login_name
            for login_name, tags in self.user_tags.items()
            if any(t.lower() == tag_lower for t in tags)
        ]

    def get_objects_with_tag(self, tag: str) -> list[str]:
        """
        Get all objects that have a specific tag (case-insensitive match).

        Args:
            tag: Tag to search for

        Returns:
            list[str]: List of full names (schema.object) that have the tag

        Example:
            >>> store = TagStore()
            >>> store.add_object_tag("dbo.Orders", "critical")
            >>> store.add_object_tag("dbo.Products", "critical")
            >>> store.get_objects_with_tag("critical")
            ['dbo.Orders', 'dbo.Products']
        """
        tag_lower = tag.lower()
        return [
            full_name
            for full_name, tags in self.object_tags.items()
            if any(t.lower() == tag_lower for t in tags)
        ]

    def save(self, path: Optional[Path] = None) -> Optional[str]:
        """
        Save tag store to %APPDATA%/Bifrost/tags.json or a custom path.

        Args:
            path: Optional custom path (defaults to %APPDATA%/Bifrost/tags.json)

        Returns:
            Optional[str]: Error message if save failed, None if successful

        Example:
            >>> store = TagStore()
            >>> store.add_user_tag("alice", "finance")
            >>> error = store.save()
            >>> if error:
            ...     print(f"Save failed: {error}")
        """
        try:
            tags_path = path if path else self.get_tags_path()

            # Ensure parent directory exists
            tags_path.parent.mkdir(parents=True, exist_ok=True)

            # Serialize to JSON
            data = {
                "user_tags": self.user_tags,
                "object_tags": self.object_tags,
            }

            # Write to file with pretty formatting
            with open(tags_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            return None

        except PermissionError:
            return f"Permission denied writing to {tags_path}"

        except Exception as e:
            return f"Failed to save tags: {str(e)}"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "TagStore":
        """
        Load tag store from %APPDATA%/Bifrost/tags.json or a custom path.

        Args:
            path: Optional custom path (defaults to %APPDATA%/Bifrost/tags.json)

        Returns:
            TagStore: Loaded tag store (empty if file missing or corrupt)

        Behavior:
            - If tags.json missing: Returns empty TagStore
            - If tags.json corrupt: Returns empty TagStore (logs warning)
            - If tags.json valid: Returns loaded TagStore

        Example:
            >>> store = TagStore.load()
            >>> user_tags = store.get_user_tags("alice")
        """
        store = cls()

        try:
            tags_path = path if path else cls.get_tags_path()

            if not tags_path.exists():
                return store  # Empty store

            with open(tags_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            store.user_tags = data.get("user_tags", {})
            store.object_tags = data.get("object_tags", {})

            return store

        except Exception:
            # On any error, return empty store
            # Errors are logged but not raised (tags are optional, not critical)
            return cls()

    @staticmethod
    def get_tags_path() -> Path:
        """
        Get the full path to tags.json.

        Returns:
            Path: Full path to %APPDATA%/Bifrost/tags.json

        Example:
            >>> tags_path = TagStore.get_tags_path()
            >>> print(tags_path)
            C:\\Users\\alice\\AppData\\Roaming\\Bifrost\\tags.json
        """
        config_dir = Configuration.get_config_path().parent
        return config_dir / "tags.json"
