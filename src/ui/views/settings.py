"""
Settings view for Bifrost.

This module provides the SettingsView class which allows users to configure
the SQL Server connection parameters and test the connection.

Features:
    - Server name/IP input
    - Port configuration (default 1433)
    - Database name selection
    - Schema name configuration
    - Windows Authentication indicator
    - Connection test button
    - Save/Cancel buttons

Usage:
    from src.ui.views.settings import SettingsView

    view = SettingsView(parent, config, on_save_callback)
    view.pack(fill="both", expand=True)
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from src.models.config import Configuration
from src.services.config import save_config


class SettingsView(ttk.Frame):
    """
    Settings view for configuring database connection.

    Attributes:
        config: Current Configuration object
        on_save: Callback when configuration is saved
        on_test: Callback to test connection

    Example:
        >>> view = SettingsView(
        ...     parent=container,
        ...     config=config,
        ...     on_save=lambda cfg: print(f"Saved: {cfg.server}"),
        ...     on_test=lambda cfg: test_connection(cfg),
        ... )
    """

    def __init__(
        self,
        parent: tk.Widget,
        config: Configuration | None = None,
        on_save: Callable[[Configuration], None] | None = None,
        on_test: Callable[[Configuration], tuple[bool, str]] | None = None,
    ):
        """
        Initialize the settings view.

        Args:
            parent: Parent widget
            config: Current configuration (None for new config)
            on_save: Callback when configuration is saved successfully
            on_test: Callback to test connection (returns (success, message))
        """
        super().__init__(parent)

        self.config = config or Configuration.default()
        self.on_save = on_save
        self.on_test = on_test

        # StringVars for form fields
        self._server_var = tk.StringVar(value=self.config.server)
        self._port_var = tk.StringVar(value=str(self.config.port))
        self._database_var = tk.StringVar(value=self.config.database)
        self._schema_var = tk.StringVar(value=self.config.schema)

        self._create_layout()

    def _create_layout(self) -> None:
        """Create the settings form layout."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main container with padding
        container = ttk.Frame(self, padding=20)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)

        # Title
        title_label = ttk.Label(
            container,
            text="Database Connection Settings",
            font=("Segoe UI", 16, "bold"),
        )
        title_label.grid(row=0, column=0, pady=(0, 20), sticky="w")

        # Form frame
        form_frame = ttk.LabelFrame(container, text="Connection Details", padding=15)
        form_frame.grid(row=1, column=0, sticky="ew", pady=10)
        form_frame.grid_columnconfigure(1, weight=1)

        # Server
        ttk.Label(form_frame, text="Server:").grid(row=0, column=0, sticky="w", pady=5)
        self._server_entry = ttk.Entry(form_frame, textvariable=self._server_var, width=40)
        self._server_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=(10, 0))
        ttk.Label(
            form_frame,
            text="SQL Server hostname or IP address",
            foreground="gray",
        ).grid(row=0, column=2, sticky="w", padx=10)

        # Port
        ttk.Label(form_frame, text="Port:").grid(row=1, column=0, sticky="w", pady=5)
        self._port_entry = ttk.Entry(form_frame, textvariable=self._port_var, width=10)
        self._port_entry.grid(row=1, column=1, sticky="w", pady=5, padx=(10, 0))
        ttk.Label(
            form_frame,
            text="Default: 1433",
            foreground="gray",
        ).grid(row=1, column=2, sticky="w", padx=10)

        # Database
        ttk.Label(form_frame, text="Database:").grid(row=2, column=0, sticky="w", pady=5)
        self._database_entry = ttk.Entry(form_frame, textvariable=self._database_var, width=40)
        self._database_entry.grid(row=2, column=1, sticky="ew", pady=5, padx=(10, 0))
        ttk.Label(
            form_frame,
            text="Target database name",
            foreground="gray",
        ).grid(row=2, column=2, sticky="w", padx=10)

        # Schema
        ttk.Label(form_frame, text="Schema:").grid(row=3, column=0, sticky="w", pady=5)
        self._schema_entry = ttk.Entry(form_frame, textvariable=self._schema_var, width=20)
        self._schema_entry.grid(row=3, column=1, sticky="w", pady=5, padx=(10, 0))
        ttk.Label(
            form_frame,
            text="Schema for Bifrost audit tables (default: dbo)",
            foreground="gray",
        ).grid(row=3, column=2, sticky="w", padx=10)

        # Authentication frame
        auth_frame = ttk.LabelFrame(container, text="Authentication", padding=15)
        auth_frame.grid(row=2, column=0, sticky="ew", pady=10)

        # Windows Auth indicator
        ttk.Label(
            auth_frame,
            text="🔒 Windows Authentication",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            auth_frame,
            text="Bifrost uses your Windows credentials to connect to SQL Server.\n"
            "Ensure your account has db_owner or sysadmin privileges on the target database.",
            foreground="gray",
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        # Connection status frame
        self._status_frame = ttk.LabelFrame(container, text="Connection Status", padding=15)
        self._status_frame.grid(row=3, column=0, sticky="ew", pady=10)

        self._status_label = ttk.Label(
            self._status_frame,
            text="Not tested",
            foreground="gray",
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        self._test_btn = ttk.Button(
            self._status_frame,
            text="Test Connection",
            command=self._test_connection,
        )
        self._test_btn.grid(row=0, column=1, sticky="e", padx=(20, 0))

        self._status_frame.grid_columnconfigure(1, weight=1)

        # Button frame
        button_frame = ttk.Frame(container)
        button_frame.grid(row=4, column=0, sticky="e", pady=20)

        ttk.Button(
            button_frame,
            text="Cancel",
            command=self._cancel,
        ).pack(side="right", padx=5)

        ttk.Button(
            button_frame,
            text="Save & Connect",
            command=self._save,
        ).pack(side="right", padx=5)

        # Validation messages
        self._validation_frame = ttk.Frame(container)
        self._validation_frame.grid(row=5, column=0, sticky="ew")

        self._validation_label = ttk.Label(
            self._validation_frame,
            text="",
            foreground="red",
        )
        self._validation_label.pack(anchor="w")

    def _build_config(self) -> Configuration:
        """Build a Configuration from form values."""
        try:
            port = int(self._port_var.get())
        except ValueError:
            port = 1433

        return Configuration(
            server=self._server_var.get().strip(),
            port=port,
            database=self._database_var.get().strip(),
            schema=self._schema_var.get().strip() or "dbo",
            auth_type="windows",
        )

    def _validate(self) -> tuple[bool, list[str]]:
        """
        Validate form inputs.

        Returns:
            tuple[bool, list[str]]: (is_valid, error_messages)
        """
        config = self._build_config()
        errors = config.validate()
        return len(errors) == 0, errors

    def _show_validation_errors(self, errors: list[str]) -> None:
        """Display validation errors."""
        if errors:
            self._validation_label.configure(text="• " + "\n• ".join(errors))
        else:
            self._validation_label.configure(text="")

    def _test_connection(self) -> None:
        """Test the database connection."""
        is_valid, errors = self._validate()
        if not is_valid:
            self._show_validation_errors(errors)
            self._update_status("Validation failed", success=False)
            return

        self._show_validation_errors([])
        config = self._build_config()

        self._update_status("Testing connection...", success=None)
        self.update_idletasks()

        if self.on_test:
            success, message = self.on_test(config)
            self._update_status(message, success=success)
        else:
            # Default test using connection module
            try:
                from src.db.connection import test_connection

                success, message = test_connection(config)
                self._update_status(message, success=success)
            except ImportError:
                self._update_status(
                    "Connection test not available (db module not loaded)",
                    success=None,
                )
            except Exception as e:
                self._update_status(f"Connection failed: {str(e)}", success=False)

    def _update_status(self, message: str, success: bool | None) -> None:
        """Update the connection status display."""
        if success is True:
            color = "green"
            icon = "✓"
        elif success is False:
            color = "red"
            icon = "✗"
        else:
            color = "gray"
            icon = "○"

        self._status_label.configure(text=f"{icon} {message}", foreground=color)

    def _save(self) -> None:
        """Save the configuration."""
        is_valid, errors = self._validate()
        if not is_valid:
            self._show_validation_errors(errors)
            return

        self._show_validation_errors([])
        config = self._build_config()

        # Save to file
        error = save_config(config)
        if error:
            messagebox.showerror("Save Failed", f"Failed to save configuration:\n{error}")
            return

        # Update internal state
        self.config = config

        # Notify callback
        if self.on_save:
            self.on_save(config)

        messagebox.showinfo("Saved", "Configuration saved successfully.")

    def _cancel(self) -> None:
        """Cancel and restore original values."""
        self._server_var.set(self.config.server)
        self._port_var.set(str(self.config.port))
        self._database_var.set(self.config.database)
        self._schema_var.set(self.config.schema)
        self._show_validation_errors([])
        self._update_status("Not tested", success=None)

    def set_config(self, config: Configuration) -> None:
        """
        Update the view with a new configuration.

        Args:
            config: New configuration to display
        """
        self.config = config
        self._server_var.set(config.server)
        self._port_var.set(str(config.port))
        self._database_var.set(config.database)
        self._schema_var.set(config.schema)
        self._show_validation_errors([])
        self._update_status("Not tested", success=None)
