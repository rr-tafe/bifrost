"""
Configuration domain model for Bifrost.

This module defines the Configuration dataclass representing database connection
settings persisted in %APPDATA%/Bifrost/config.json.

The configuration is loaded on startup and saved via the Settings view.
Only Windows Authentication is supported; credentials are never stored.

Usage:
    config = Configuration(
        server="SQLSERVER01",
        port=1433,
        database="MyAppDB",
        schema="dbo",
        auth_type="windows"
    )

    # Validate before use
    errors = config.validate()
    if errors:
        print(f"Invalid config: {errors}")
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Configuration:
    """
    Database connection configuration persisted in config.json.

    Attributes:
        server: SQL Server hostname, IP, or named instance
        port: TCP port (1-65535, default 1433)
        database: Target database name
        schema: Schema for Bifrost tables (default "dbo", must be valid SQL identifier)
        auth_type: Authentication method ("windows" only)
        username: Not used (Windows Auth uses current Windows session)
        password: Not used (credentials are never stored)

    Validation (via validate() method):
        - server: non-empty
        - port: 1-65535
        - database: non-empty
        - schema: non-empty, matches ^[A-Za-z_][A-Za-z0-9_]*$
        - auth_type: must be "windows"

    File location: %APPDATA%/Bifrost/config.json

    Note:
        If config.json is missing or corrupt, the app shows the Settings view
        with an explanatory message (not a crash).
    """

    server: str
    port: int = 1433
    database: str = ""
    schema: str = "dbo"
    auth_type: str = "windows"
    username: str | None = None  # Not used for Windows Auth
    password: str | None = None  # Never stored

    def validate(self) -> list[str]:
        """
        Validate all configuration fields and return a list of errors.

        Returns:
            list[str]: List of validation error messages (empty if valid)

        Validation rules:
            - server: must be non-empty
            - port: must be 1-65535
            - database: must be non-empty
            - schema: must be non-empty and valid SQL identifier
            - auth_type: must be "windows"

        Example:
            >>> config = Configuration(server="", port=99999, database="Test")
            >>> errors = config.validate()
            >>> print(errors)
            ['server must be non-empty', 'port must be between 1 and 65535']
        """
        import re

        errors = []

        if not self.server:
            errors.append("server must be non-empty")

        if not (1 <= self.port <= 65535):
            errors.append("port must be between 1 and 65535")

        if not self.database:
            errors.append("database must be non-empty")

        if not self.schema:
            errors.append("schema must be non-empty")
        elif not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", self.schema):
            errors.append(
                "schema must be a valid SQL identifier (start with letter or underscore, "
                "contain only letters, numbers, underscores)"
            )

        if self.auth_type != "windows":
            errors.append("auth_type must be 'windows' (only Windows Authentication is supported)")

        return errors

    def is_valid(self) -> bool:
        """
        Check if configuration is valid.

        Returns:
            bool: True if no validation errors, False otherwise
        """
        return len(self.validate()) == 0

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize configuration to a dictionary for JSON storage.

        Returns:
            dict: Configuration as a dictionary

        Note:
            username and password are excluded (never stored).
        """
        return {
            "server": self.server,
            "port": self.port,
            "database": self.database,
            "schema": self.schema,
            "auth_type": self.auth_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Configuration":
        """
        Deserialize configuration from a dictionary (loaded from JSON).

        Args:
            data: Dictionary with configuration fields

        Returns:
            Configuration: New configuration instance

        Raises:
            KeyError: If required fields are missing
            TypeError: If field types are incorrect
        """
        return cls(
            server=data["server"],
            port=data.get("port", 1433),
            database=data["database"],
            schema=data.get("schema", "dbo"),
            auth_type=data.get("auth_type", "windows"),
        )

    @classmethod
    def default(cls) -> "Configuration":
        """
        Create a default configuration with placeholder values.

        Returns:
            Configuration: Default configuration (invalid until filled)
        """
        return cls(
            server="",
            port=1433,
            database="",
            schema="dbo",
            auth_type="windows",
        )

    @staticmethod
    def get_config_path() -> Path:
        """
        Get the full path to config.json in %APPDATA%/Bifrost/.

        Returns:
            Path: Full path to config.json

        Note:
            The parent directory is created if it doesn't exist.
        """
        import os

        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA environment variable not set")

        config_dir = Path(appdata) / "Bifrost"
        config_dir.mkdir(parents=True, exist_ok=True)

        return config_dir / "config.json"
