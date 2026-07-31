"""
Unit tests for Bifrost services.

Tests cover:
    - TagStore operations (add, remove, rename, persist)
    - ConfigService operations (save, load, exists)

Note: Matrix service tests are in test_services_matrix.py (require mocks)

Run with: pytest tests/unit/test_services.py -v
"""

import pytest
import json
import tempfile
from pathlib import Path
from src.services.tags import TagStore
from src.services.config import save_config, load_config, config_exists
from src.models.config import Configuration


class TestTagStore:
    """Tests for TagStore class."""

    def test_empty_store(self):
        """Test newly created store returns empty tags for any user."""
        store = TagStore()
        assert store.get_user_tags("alice") == []
        assert store.get_object_tags("dbo.Orders") == []

    def test_add_user_tag(self):
        """Test adding tag to user."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        tags = store.get_user_tags("alice")
        assert "finance" in tags

    def test_add_multiple_user_tags(self):
        """Test adding multiple tags to same user."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_user_tag("alice", "audit")
        tags = store.get_user_tags("alice")
        assert len(tags) == 2

    def test_add_duplicate_user_tag(self):
        """Test duplicate tags are not added twice (case-insensitive)."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_user_tag("alice", "Finance")  # Case-insensitive duplicate
        tags = store.get_user_tags("alice")
        assert len(tags) == 1

    def test_add_object_tag(self):
        """Test adding tag to object."""
        store = TagStore()
        store.add_object_tag("dbo.Orders", "sensitive")
        tags = store.get_object_tags("dbo.Orders")
        assert "sensitive" in tags

    def test_remove_user_tag(self):
        """Test removing tag from user."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.remove_user_tag("alice", "finance")
        tags = store.get_user_tags("alice")
        assert tags == []

    def test_remove_nonexistent_tag(self):
        """Test removing tag that doesn't exist (no error)."""
        store = TagStore()
        store.remove_user_tag("alice", "nosuchtag")  # Should not raise

    def test_rename_tag(self):
        """Test renaming tag updates all users and objects."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_object_tag("dbo.Orders", "finance")
        store.rename_tag("finance", "accounting")
        assert "accounting" in store.get_user_tags("alice")
        assert "accounting" in store.get_object_tags("dbo.Orders")
        assert "finance" not in store.get_user_tags("alice")

    def test_rename_tag_multiple_users(self):
        """Test renaming tag updates all users."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_user_tag("bob", "finance")
        store.rename_tag("finance", "accounting")
        assert "accounting" in store.get_user_tags("alice")
        assert "accounting" in store.get_user_tags("bob")

    def test_save_and_load(self):
        """Test save and load round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tags.json"

            # Create and save
            store = TagStore()
            store.add_user_tag("alice", "finance")
            store.add_object_tag("dbo.Orders", "sensitive")
            store.save(path)

            # Load in new instance
            store2 = TagStore.load(path)

            assert "finance" in store2.get_user_tags("alice")
            assert "sensitive" in store2.get_object_tags("dbo.Orders")

    def test_load_nonexistent_file(self):
        """Test loading nonexistent file returns empty store."""
        store = TagStore.load(Path("/nonexistent/tags.json"))
        assert store.get_user_tags("alice") == []

    def test_get_all_tags(self):
        """Test getting unique set of all tags."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_user_tag("bob", "finance")
        store.add_user_tag("alice", "audit")
        all_tags = store.get_all_tags()
        assert all_tags == {"finance", "audit"}

    def test_get_users_with_tag(self):
        """Test getting users that have a specific tag."""
        store = TagStore()
        store.add_user_tag("alice", "finance")
        store.add_user_tag("bob", "finance")
        store.add_user_tag("charlie", "audit")
        users = store.get_users_with_tag("finance")
        assert set(users) == {"alice", "bob"}


class TestConfigService:
    """Tests for config service functions."""

    def test_save_and_load_config(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            config = Configuration(
                server="SQLSERVER01",
                port=1433,
                database="TestDB",
                schema="dbo",
                auth_type="windows",
            )
            error = save_config(config, path)
            assert error is None

            loaded, load_error = load_config(path)
            assert load_error is None
            assert loaded is not None
            assert loaded.server == "SQLSERVER01"
            assert loaded.database == "TestDB"

    def test_load_nonexistent_config(self):
        """Test loading nonexistent config returns default with message."""
        loaded, error = load_config(Path("/nonexistent/config.json"))
        # Should return default config with error message
        assert loaded is not None
        assert error is not None
        assert "not found" in error.lower()

    def test_config_exists_true(self):
        """Test config_exists returns True when file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            config = Configuration(server="localhost", database="TestDB")
            save_config(config, path)
            assert config_exists(path)

    def test_config_exists_false(self):
        """Test config_exists returns False when file doesn't exist."""
        assert not config_exists(Path("/nonexistent/config.json"))

    def test_load_corrupted_config(self):
        """Test loading corrupted config returns default with error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("not valid json {", encoding="utf-8")

            loaded, error = load_config(path)
            assert loaded is not None  # Default config
            assert error is not None
            assert "corrupt" in error.lower() or "invalid" in error.lower()

    def test_config_excludes_credentials(self):
        """Test saved config does not contain credentials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            config = Configuration(
                server="localhost",
                database="TestDB",
                username="secret_user",
                password="secret_pass",
            )
            save_config(config, path)

            # Read raw JSON
            raw = json.loads(path.read_text(encoding="utf-8"))
            assert "username" not in raw
            assert "password" not in raw
            assert "secret" not in path.read_text(encoding="utf-8")
