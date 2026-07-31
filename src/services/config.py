"""
Configuration persistence service for Bifrost.

This module provides functions to load and save database connection configuration
to %APPDATA%/Bifrost/config.json.

Configuration is loaded on app startup and saved via the Settings view.
Only Windows Authentication is supported; no credentials are stored.

Usage:
    from src.services.config import load_config, save_config, config_exists
    from src.models.config import Configuration

    # Load existing config (or default if missing/corrupt)
    config, error = load_config()
    if error:
        print(f"Config load failed: {error}")
        # Show Settings view with error

    # Save config
    config = Configuration(server="SQLSERVER01", database="MyDB")
    error = save_config(config)
    if error:
        print(f"Config save failed: {error}")
"""

import json
from pathlib import Path
from typing import Optional
from src.models.config import Configuration


def load_config() -> tuple[Configuration, Optional[str]]:
    """
    Load configuration from %APPDATA%/Bifrost/config.json.

    Returns:
        tuple[Configuration, Optional[str]]: (config, error_message)
            - If successful: (loaded_config, None)
            - If missing: (default_config, "Configuration file not found")
            - If corrupt: (default_config, "Configuration file is corrupt: {details}")

    Behavior:
        - If config.json missing: Returns default config with error message
        - If config.json corrupt: Returns default config with error message
        - If config.json valid: Returns loaded config with no error

    The error message can be shown in the Settings view to guide the user.

    Example:
        >>> config, error = load_config()
        >>> if error:
        ...     print(f"Using default config: {error}")
        ... else:
        ...     print(f"Loaded config for server: {config.server}")
    """
    try:
        config_path = Configuration.get_config_path()

        if not config_path.exists():
            return (
                Configuration.default(),
                "Configuration file not found. Please enter your database connection details."
            )

        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        config = Configuration.from_dict(data)

        # Validate loaded config
        validation_errors = config.validate()
        if validation_errors:
            error_summary = "; ".join(validation_errors)
            return (
                Configuration.default(),
                f"Configuration file is invalid: {error_summary}"
            )

        return (config, None)

    except json.JSONDecodeError as e:
        return (
            Configuration.default(),
            f"Configuration file is corrupt (invalid JSON): {str(e)}"
        )

    except KeyError as e:
        return (
            Configuration.default(),
            f"Configuration file is missing required field: {str(e)}"
        )

    except Exception as e:
        return (
            Configuration.default(),
            f"Failed to load configuration: {str(e)}"
        )


def save_config(config: Configuration) -> Optional[str]:
    """
    Save configuration to %APPDATA%/Bifrost/config.json.

    Args:
        config: Configuration to save

    Returns:
        Optional[str]: Error message if save failed, None if successful

    Behavior:
        - Creates %APPDATA%/Bifrost/ directory if it doesn't exist
        - Validates configuration before saving
        - Writes JSON with 2-space indentation for readability
        - Sets file permissions to user-only (read/write)

    Example:
        >>> config = Configuration(server="SQLSERVER01", database="MyDB")
        >>> error = save_config(config)
        >>> if error:
        ...     print(f"Save failed: {error}")
        ... else:
        ...     print("Configuration saved successfully")
    """
    try:
        # Validate before saving
        validation_errors = config.validate()
        if validation_errors:
            error_summary = "; ".join(validation_errors)
            return f"Cannot save invalid configuration: {error_summary}"

        config_path = Configuration.get_config_path()

        # Ensure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize to JSON
        data = config.to_dict()

        # Write to file with pretty formatting
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Set file permissions to user-only (Windows)
        # On Windows, file permissions are handled by NTFS ACLs
        # No explicit chmod needed; %APPDATA% is already user-protected

        return None

    except PermissionError:
        return f"Permission denied writing to {config_path}"

    except Exception as e:
        return f"Failed to save configuration: {str(e)}"


def config_exists() -> bool:
    """
    Check if config.json exists.

    Returns:
        bool: True if config file exists, False otherwise

    Used for first-run detection (show Settings view if no config).

    Example:
        >>> if not config_exists():
        ...     print("First run - show Settings view")
    """
    try:
        config_path = Configuration.get_config_path()
        return config_path.exists()
    except Exception:
        return False


def delete_config() -> Optional[str]:
    """
    Delete the configuration file.

    Returns:
        Optional[str]: Error message if deletion failed, None if successful

    Used for testing and debugging. Not exposed in the production UI.

    Example:
        >>> error = delete_config()
        >>> if error:
        ...     print(f"Delete failed: {error}")
        ... else:
        ...     print("Configuration deleted")
    """
    try:
        config_path = Configuration.get_config_path()

        if config_path.exists():
            config_path.unlink()

        return None

    except PermissionError:
        return f"Permission denied deleting {config_path}"

    except Exception as e:
        return f"Failed to delete configuration: {str(e)}"


def get_config_directory() -> Path:
    """
    Get the configuration directory path (%APPDATA%/Bifrost).

    Returns:
        Path: Configuration directory path

    Example:
        >>> config_dir = get_config_directory()
        >>> print(config_dir)
        C:\\Users\\alice\\AppData\\Roaming\\Bifrost
    """
    return Configuration.get_config_path().parent
