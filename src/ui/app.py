"""
Main application window for Bifrost.

This module provides the BifrostApp class which manages the root Tk window,
tab navigation, view lifecycle, and application startup/shutdown.

Architecture:
    BifrostApp (Tk root)
    ├── HeaderBar (server info, status)
    ├── TabStrip (Matrix | Tags | Audit | Settings)
    └── ViewContainer (switches active view)
        ├── MatrixView (permission grid)
        ├── TagsView (tag management)
        ├── AuditView (audit log)
        └── SettingsView (connection config)

Usage:
    from src.ui.app import BifrostApp

    app = BifrostApp()
    app.mainloop()
"""

import sys
import tkinter as tk
from tkinter import messagebox, ttk

from src.models.config import Configuration
from src.services.config import load_config
from src.services.tags import TagStore
from src.ui.views.matrix import MatrixView
from src.ui.views.settings import SettingsView
from src.ui.views.tags import TagsView


class ViewType:
    """View type constants."""

    MATRIX = "matrix"
    TAGS = "tags"
    AUDIT = "audit"
    SETTINGS = "settings"


class BifrostApp(tk.Tk):
    """
    Main application window for Bifrost.

    Manages the root Tk window, tab navigation, and view lifecycle.

    Attributes:
        config: Current database configuration
        tag_store: Local tag store
        connection: Active database connection (None if disconnected)
        current_view: Currently active view type

    Lifecycle:
        1. Load configuration from %APPDATA%/Bifrost/config.json
        2. Load tags from %APPDATA%/Bifrost/tags.json
        3. If config missing/invalid: Show Settings view
        4. If config valid: Connect to database and show Matrix view
        5. On close: Confirm if unsaved changes, save tags, disconnect

    Example:
        >>> app = BifrostApp()
        >>> app.mainloop()
    """

    WINDOW_TITLE = "Bifrost - SQL Server Permissions Manager"
    MIN_WIDTH = 1024
    MIN_HEIGHT = 768
    DEFAULT_WIDTH = 1280
    DEFAULT_HEIGHT = 900

    def __init__(self):
        """Initialize the main application window."""
        super().__init__()

        # Window configuration
        self.title(self.WINDOW_TITLE)
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}")

        # Center window on screen
        self._center_window()

        # Application state
        self.config: Configuration | None = None
        self.tag_store = TagStore()
        self.connection = None
        self.current_view: str = ViewType.SETTINGS
        self._has_unsaved_changes = False

        # View instances (lazily initialized)
        self._views: dict[str, tk.Frame] = {}

        # Build UI components
        self._create_styles()
        self._create_layout()
        self._create_menu()

        # Load configuration and tags
        self._load_application_state()

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keyboard shortcuts
        self._bind_shortcuts()

    def _center_window(self) -> None:
        """Center the window on the screen."""
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - self.DEFAULT_WIDTH) // 2
        y = (screen_height - self.DEFAULT_HEIGHT) // 2
        self.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}+{x}+{y}")

    def _create_styles(self) -> None:
        """Configure ttk styles for consistent theming."""
        style = ttk.Style()

        # Use default theme
        available_themes = style.theme_names()
        if "vista" in available_themes:
            style.theme_use("vista")
        elif "clam" in available_themes:
            style.theme_use("clam")

        # Tab style
        style.configure(
            "Tab.TButton",
            padding=(20, 10),
            font=("Segoe UI", 10),
        )

        # Active tab style
        style.configure(
            "ActiveTab.TButton",
            padding=(20, 10),
            font=("Segoe UI", 10, "bold"),
        )

        # Status bar style
        style.configure(
            "Status.TLabel",
            padding=(5, 2),
            font=("Segoe UI", 9),
        )

        # Header style
        style.configure(
            "Header.TFrame",
            background="#f0f0f0",
        )

    def _create_layout(self) -> None:
        """Create the main window layout."""
        # Configure root grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=0)  # Tab strip
        self.grid_rowconfigure(2, weight=1)  # View container
        self.grid_rowconfigure(3, weight=0)  # Status bar

        # Header bar
        self._header_frame = ttk.Frame(self, style="Header.TFrame")
        self._header_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self._create_header()

        # Tab strip
        self._tab_frame = ttk.Frame(self)
        self._tab_frame.grid(row=1, column=0, sticky="ew", padx=5)
        self._create_tabs()

        # View container
        self._view_container = ttk.Frame(self)
        self._view_container.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        self._view_container.grid_columnconfigure(0, weight=1)
        self._view_container.grid_rowconfigure(0, weight=1)

        # Status bar
        self._status_frame = ttk.Frame(self)
        self._status_frame.grid(row=3, column=0, sticky="ew")
        self._create_status_bar()

    def _create_header(self) -> None:
        """Create the header bar with server info."""
        self._header_frame.grid_columnconfigure(1, weight=1)

        # App icon/title
        title_label = ttk.Label(
            self._header_frame,
            text="⚡ Bifrost",
            font=("Segoe UI", 14, "bold"),
        )
        title_label.grid(row=0, column=0, padx=10, pady=5)

        # Server info (updated when connected)
        self._server_label = ttk.Label(
            self._header_frame,
            text="Not connected",
            font=("Segoe UI", 10),
        )
        self._server_label.grid(row=0, column=1, padx=10, pady=5)

        # Connection indicator
        self._connection_indicator = ttk.Label(
            self._header_frame,
            text="●",
            foreground="gray",
            font=("Segoe UI", 12),
        )
        self._connection_indicator.grid(row=0, column=2, padx=10, pady=5)

    def _create_tabs(self) -> None:
        """Create the tab strip for navigation."""
        self._tab_buttons: dict[str, ttk.Button] = {}

        tabs = [
            (ViewType.MATRIX, "📊 Matrix", "View/edit permission matrix"),
            (ViewType.TAGS, "🏷️ Tags", "Manage user and object tags"),
            (ViewType.AUDIT, "📋 Audit", "View change history"),
            (ViewType.SETTINGS, "⚙️ Settings", "Configure connection"),
        ]

        for i, (view_type, text, tooltip) in enumerate(tabs):
            btn = ttk.Button(
                self._tab_frame,
                text=text,
                style="Tab.TButton",
                command=lambda vt=view_type: self.switch_view(vt),
            )
            btn.grid(row=0, column=i, padx=2, pady=5)
            self._tab_buttons[view_type] = btn

            # Tooltip
            self._create_tooltip(btn, tooltip)

    def _create_status_bar(self) -> None:
        """Create the status bar."""
        self._status_frame.grid_columnconfigure(1, weight=1)

        # Status message
        self._status_label = ttk.Label(
            self._status_frame,
            text="Ready",
            style="Status.TLabel",
        )
        self._status_label.grid(row=0, column=0, padx=10, pady=2, sticky="w")

        # Pending changes indicator
        self._changes_label = ttk.Label(
            self._status_frame,
            text="",
            style="Status.TLabel",
        )
        self._changes_label.grid(row=0, column=1, padx=10, pady=2, sticky="e")

        # Progress indicator (hidden by default)
        self._progress = ttk.Progressbar(
            self._status_frame,
            mode="indeterminate",
            length=100,
        )

    def _create_menu(self) -> None:
        """Create the menu bar."""
        menubar = tk.Menu(self)
        self.config_menu = menubar  # Store reference

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Connect",
            command=self._connect,
            accelerator="Ctrl+O",
        )
        file_menu.add_command(
            label="Disconnect",
            command=self._disconnect,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Export Permissions...",
            command=self._export_permissions,
            accelerator="Ctrl+E",
        )
        file_menu.add_command(
            label="Export Audit Log...",
            command=self._export_audit,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Exit",
            command=self._on_close,
            accelerator="Alt+F4",
        )
        menubar.add_cascade(label="File", menu=file_menu)

        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(
            label="Undo",
            command=self._undo,
            accelerator="Ctrl+Z",
        )
        edit_menu.add_command(
            label="Redo",
            command=self._redo,
            accelerator="Ctrl+Y",
        )
        edit_menu.add_separator()
        edit_menu.add_command(
            label="Commit Changes",
            command=self._commit_changes,
            accelerator="Ctrl+S",
        )
        edit_menu.add_command(
            label="Cancel Changes",
            command=self._cancel_changes,
            accelerator="Escape",
        )
        menubar.add_cascade(label="Edit", menu=edit_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Refresh",
            command=self._refresh,
            accelerator="F5",
        )
        view_menu.add_separator()
        view_menu.add_command(
            label="Matrix View",
            command=lambda: self.switch_view(ViewType.MATRIX),
            accelerator="Ctrl+1",
        )
        view_menu.add_command(
            label="Tags View",
            command=lambda: self.switch_view(ViewType.TAGS),
            accelerator="Ctrl+2",
        )
        view_menu.add_command(
            label="Audit View",
            command=lambda: self.switch_view(ViewType.AUDIT),
            accelerator="Ctrl+3",
        )
        view_menu.add_command(
            label="Settings View",
            command=lambda: self.switch_view(ViewType.SETTINGS),
            accelerator="Ctrl+4",
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="Keyboard Shortcuts",
            command=self._show_shortcuts,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label="About Bifrost",
            command=self._show_about,
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.configure(menu=menubar)

    def _bind_shortcuts(self) -> None:
        """Bind keyboard shortcuts."""
        self.bind("<Control-o>", lambda e: self._connect())
        self.bind("<Control-e>", lambda e: self._export_permissions())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<Control-s>", lambda e: self._commit_changes())
        self.bind("<Escape>", lambda e: self._cancel_changes())
        self.bind("<F5>", lambda e: self._refresh())
        self.bind("<Control-Key-1>", lambda e: self.switch_view(ViewType.MATRIX))
        self.bind("<Control-Key-2>", lambda e: self.switch_view(ViewType.TAGS))
        self.bind("<Control-Key-3>", lambda e: self.switch_view(ViewType.AUDIT))
        self.bind("<Control-Key-4>", lambda e: self.switch_view(ViewType.SETTINGS))

    def _create_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Create a tooltip for a widget."""

        def enter(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            label = ttk.Label(
                tooltip,
                text=text,
                background="#ffffe0",
                relief="solid",
                borderwidth=1,
                padding=5,
            )
            label.pack()
            widget._tooltip = tooltip

        def leave(event):
            if hasattr(widget, "_tooltip"):
                widget._tooltip.destroy()
                del widget._tooltip

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _load_application_state(self) -> None:
        """Load configuration and tags on startup."""
        # Load configuration
        config, error = load_config()
        if error:
            self.set_status(f"Config: {error}")
            self.switch_view(ViewType.SETTINGS)
        else:
            self.config = config
            self._try_connect()

        # Load tags
        self.tag_store = TagStore.load()

    def _try_connect(self) -> None:
        """Attempt to connect with current configuration."""
        if not self.config or not self.config.is_valid():
            self.switch_view(ViewType.SETTINGS)
            return

        # Connection will be implemented in a future commit
        # For now, just update UI state
        self._update_connection_status(connected=False)
        self.switch_view(ViewType.MATRIX)

    def switch_view(self, view_type: str) -> None:
        """
        Switch to a different view.

        Args:
            view_type: ViewType constant (MATRIX, TAGS, AUDIT, SETTINGS)
        """
        if view_type == self.current_view:
            return

        # Update tab button styles
        for vt, btn in self._tab_buttons.items():
            if vt == view_type:
                btn.configure(style="ActiveTab.TButton")
            else:
                btn.configure(style="Tab.TButton")

        # Hide current view
        for child in self._view_container.winfo_children():
            child.grid_forget()

        # Show new view (create if needed)
        view = self._get_or_create_view(view_type)
        view.grid(row=0, column=0, sticky="nsew")

        self.current_view = view_type
        self.set_status(f"Viewing: {view_type.title()}")

    def _get_or_create_view(self, view_type: str) -> tk.Frame:
        """Get existing view or create a new one."""
        if view_type not in self._views:
            self._views[view_type] = self._create_view(view_type)
        return self._views[view_type]

    def _create_view(self, view_type: str) -> tk.Frame:
        """Create a view instance."""
        if view_type == ViewType.SETTINGS:
            return SettingsView(
                self._view_container,
                config=self.config,
                on_save=self._on_settings_saved,
                on_test=self._test_connection,
            )

        if view_type == ViewType.MATRIX:
            return MatrixView(
                self._view_container,
                matrix=None,  # Will be set when connected
                on_commit=self._commit_changes,
                on_cancel=self._cancel_changes,
            )

        if view_type == ViewType.TAGS:
            view = TagsView(
                self._view_container,
                tag_store=self.tag_store,
                users=[],  # Will be populated when connected
                objects=[],
            )
            view.refresh()
            return view

        # Placeholder frames for views not yet implemented
        frame = ttk.Frame(self._view_container)

        if view_type == ViewType.AUDIT:
            label = ttk.Label(
                frame,
                text="Audit Log View\n\n(Under Construction)",
                font=("Segoe UI", 16),
                justify="center",
            )
            label.pack(expand=True)

        return frame

    def _on_settings_saved(self, config: Configuration) -> None:
        """Handle settings saved callback."""
        self.config = config
        self._try_connect()

    def _test_connection(self, config: Configuration) -> tuple[bool, str]:
        """Test database connection."""
        try:
            from src.db.connection import test_connection

            return test_connection(config)
        except ImportError:
            return False, "Database module not available"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def _update_connection_status(self, connected: bool) -> None:
        """Update the connection indicator."""
        if connected and self.config:
            self._server_label.configure(
                text=f"Connected to {self.config.server}/{self.config.database}"
            )
            self._connection_indicator.configure(foreground="green")
        else:
            self._server_label.configure(text="Not connected")
            self._connection_indicator.configure(foreground="gray")

    def set_status(self, message: str) -> None:
        """Update the status bar message."""
        self._status_label.configure(text=message)

    def set_changes_count(self, count: int) -> None:
        """Update the pending changes indicator."""
        if count > 0:
            self._changes_label.configure(text=f"📝 {count} pending change(s)")
            self._has_unsaved_changes = True
        else:
            self._changes_label.configure(text="")
            self._has_unsaved_changes = False

    def show_progress(self, show: bool = True) -> None:
        """Show or hide the progress indicator."""
        if show:
            self._progress.grid(row=0, column=2, padx=10, pady=2)
            self._progress.start()
        else:
            self._progress.stop()
            self._progress.grid_forget()

    # Command handlers (placeholders for now)

    def _connect(self) -> None:
        """Connect to database."""
        self.switch_view(ViewType.SETTINGS)

    def _disconnect(self) -> None:
        """Disconnect from database."""
        if self.connection:
            self.connection.close()
            self.connection = None
        self._update_connection_status(connected=False)
        self.set_status("Disconnected")

    def _export_permissions(self) -> None:
        """Export permission matrix to CSV."""
        messagebox.showinfo("Export", "Export permissions feature coming soon.")

    def _export_audit(self) -> None:
        """Export audit log to CSV."""
        messagebox.showinfo("Export", "Export audit log feature coming soon.")

    def _undo(self) -> None:
        """Undo last change."""
        self.set_status("Undo - feature coming soon")

    def _redo(self) -> None:
        """Redo last undone change."""
        self.set_status("Redo - feature coming soon")

    def _commit_changes(self) -> None:
        """Commit all pending changes."""
        self.set_status("Commit - feature coming soon")

    def _cancel_changes(self) -> None:
        """Cancel all pending changes."""
        self.set_status("Cancel - feature coming soon")

    def _refresh(self) -> None:
        """Refresh current view."""
        self.set_status("Refreshing...")
        self.after(500, lambda: self.set_status("Ready"))

    def _show_shortcuts(self) -> None:
        """Show keyboard shortcuts dialog."""
        shortcuts = """
Keyboard Shortcuts
==================

Navigation:
  Ctrl+1    Matrix View
  Ctrl+2    Tags View
  Ctrl+3    Audit View
  Ctrl+4    Settings View

Actions:
  Ctrl+S    Commit Changes
  Ctrl+Z    Undo
  Ctrl+Y    Redo
  Escape    Cancel Changes
  F5        Refresh

File:
  Ctrl+O    Connect
  Ctrl+E    Export Permissions
  Alt+F4    Exit
"""
        messagebox.showinfo("Keyboard Shortcuts", shortcuts)

    def _show_about(self) -> None:
        """Show about dialog."""
        about_text = """
Bifrost - SQL Server Permissions Manager

Version: 1.0.0

A desktop application for managing SQL Server
object-level permissions through an intuitive
permission matrix interface.

© 2024 Bifrost Team
"""
        messagebox.showinfo("About Bifrost", about_text)

    def _on_close(self) -> None:
        """Handle window close."""
        if self._has_unsaved_changes:
            result = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Do you want to commit them before exiting?",
            )
            if result is None:  # Cancel
                return
            if result:  # Yes - commit
                self._commit_changes()

        # Save tags
        error = self.tag_store.save()
        if error:
            messagebox.showwarning("Warning", f"Failed to save tags: {error}")

        # Disconnect
        if self.connection:
            self.connection.close()

        self.destroy()


def main() -> int:
    """Application entry point."""
    try:
        app = BifrostApp()
        app.mainloop()
        return 0
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
