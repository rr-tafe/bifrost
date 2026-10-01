"""
Main application window for Bifrost.

This module provides the BifrostApp class which manages the root Tk window,
tab navigation, view lifecycle, and application startup/shutdown.

Architecture:
    BifrostApp (Tk root)
    ├── HeaderBar (server info, status)
    ├── TabStrip (Matrix | Audit)
    └── ViewContainer (switches active view)
        ├── MatrixView (permission grid)
        └── AuditView (audit log)

    Auxiliary dialogs:
        - TagManagerDialog (TagsView)
        - SettingsDialog (SettingsView)

Usage:
    from src.ui.app import BifrostApp

    app = BifrostApp()
    app.mainloop()
"""

import sys
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.models.config import Configuration
from src.services.config import load_config
from src.services.matrix import PermissionMatrix
from src.services.tags import TagStore
from src.ui.views.audit import AuditView
from src.ui.views.matrix import MatrixView
from src.ui.views.settings import SettingsView
from src.ui.views.tags import TagsView


class ViewType:
    """View type constants."""

    MATRIX = "matrix"
    AUDIT = "audit"


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
        3. If config missing/invalid: Open Settings dialog
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
        self.matrix: PermissionMatrix | None = None
        self.current_view: str | None = None  # None until first view is shown
        self._has_unsaved_changes = False
        self._connection_monitor_job: str | None = None
        self._connection_lost_notified = False
        self._settings_window: tk.Toplevel | None = None
        self._settings_view: SettingsView | None = None
        # (tested_config, success, message) from the last test or connect attempt
        self._last_connection_test: tuple[Configuration, bool, str] | None = None
        self._tags_window: tk.Toplevel | None = None
        self._tags_view: TagsView | None = None

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

        controls = ttk.Frame(self._header_frame)
        controls.grid(row=0, column=3, padx=10, pady=5, sticky="e")

        ttk.Button(controls, text="🔄 Refresh", command=self._refresh).pack(side="left", padx=3)
        ttk.Button(controls, text="🏷 Tags", command=self._open_tags_dialog).pack(side="left", padx=3)
        ttk.Button(controls, text="⚙ Settings", command=self._open_settings_dialog).pack(side="left", padx=3)

    def _create_tabs(self) -> None:
        """Create the tab strip for navigation."""
        self._tab_buttons: dict[str, ttk.Button] = {}

        tabs = [
            (ViewType.MATRIX, "📊 Matrix", "View/edit permission matrix"),
            (ViewType.AUDIT, "📋 Audit", "View change history"),
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
            command=self._open_settings_dialog,
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
            accelerator="Ctrl+S / Ctrl+Enter",
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
            label="Audit View",
            command=lambda: self.switch_view(ViewType.AUDIT),
            accelerator="Ctrl+4",
        )
        view_menu.add_command(
            label="Tag Manager...",
            command=self._open_tags_dialog,
            accelerator="Ctrl+2",
        )
        view_menu.add_command(
            label="Settings...",
            command=self._open_settings_dialog,
            accelerator="Ctrl+,",
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
        self.bind("<Control-o>", lambda e: self._open_settings_dialog())
        self.bind("<Control-e>", lambda e: self._export_permissions())
        self.bind("<Control-z>", lambda e: self._undo())
        self.bind("<Control-y>", lambda e: self._redo())
        self.bind("<Control-s>", lambda e: self._commit_changes())
        self.bind("<Control-Return>", lambda e: self._commit_changes())
        self.bind("<Escape>", lambda e: self._cancel_changes())
        self.bind("<F5>", lambda e: self._refresh())
        self.bind("<Control-Key-1>", lambda e: self.switch_view(ViewType.MATRIX))
        self.bind("<Control-Key-2>", lambda e: self._open_tags_dialog())
        self.bind("<Control-Key-4>", lambda e: self.switch_view(ViewType.AUDIT))
        self.bind("<Control-comma>", lambda e: self._open_settings_dialog())

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
        # Load tags
        self.tag_store = TagStore.load()

        # Always render the shell with matrix as default tab.
        self.switch_view(ViewType.MATRIX)

        # Load configuration
        config, error = load_config()
        if error:
            self.set_status(f"Config: {error}")
            self._open_settings_dialog()
        else:
            self.config = config
            self._try_connect()

    def _try_connect(self) -> None:
        """Attempt to connect with current configuration."""
        if not self.config or not self.config.is_valid():
            self.switch_view(ViewType.MATRIX)
            self._open_settings_dialog()
            return

        self.set_status("Connecting...")

        try:
            from src.db.audit import ensure_audit_log_table
            from src.db.connection import create_connection, get_current_user

            # Create connection
            self.connection = create_connection(self.config)

            # Ensure audit log table exists
            ensure_audit_log_table(self.connection, self.config.schema)

            # Get current user
            current_user = get_current_user(self.connection)

            # Build permission matrix (loads users, objects, permissions internally)
            self.matrix = PermissionMatrix(self.connection, self.config.schema, self.tag_store)
            self.matrix.load()

            # Update UI
            self._update_connection_status(connected=True)
            self._connection_lost_notified = False
            self._update_header_info(
                server=self.config.server,
                database=self.config.database,
                user=current_user,
            )
            self._start_connection_monitor()

            # Switch to matrix view first (creates the view if needed)
            self.switch_view(ViewType.MATRIX)

            # Then update views with data (now that they exist)
            self._update_views_with_data(self.matrix.users, self.matrix.objects)

            self.set_status(f"Connected as {current_user}")
            self._last_connection_test = (
                self.config,
                True,
                f"Connected to {self.config.server}/{self.config.database}",
            )

        except ImportError as e:
            self.set_status(f"Module error: {e}")
            self._update_connection_status(connected=False)
            self._stop_connection_monitor()
            self.switch_view(ViewType.MATRIX)  # Show empty matrix

        except Exception as e:
            self.set_status(f"Connection failed: {e}")
            self._update_connection_status(connected=False)
            self._stop_connection_monitor()
            self.switch_view(ViewType.MATRIX)
            self._open_settings_dialog()

    def _update_views_with_data(self, users: list, objects: list) -> None:
        """Update views with loaded data."""
        # Update matrix view
        if ViewType.MATRIX in self._views:
            matrix_view = self._views[ViewType.MATRIX]
            if hasattr(matrix_view, "set_matrix"):
                matrix_view.set_matrix(self.matrix)
                matrix_view.refresh()

        # Update tags dialog view if open
        if self._tags_view is not None:
            self._tags_view.set_data(self.tag_store, users, objects)

        # Update audit view with fetch callback
        if ViewType.AUDIT in self._views:
            audit_view = self._views[ViewType.AUDIT]
            if hasattr(audit_view, "set_callbacks"):
                audit_view.set_callbacks(
                    on_fetch=self._fetch_audit_entries,
                    on_export=None,  # Use default export
                )

    def switch_view(self, view_type: str) -> None:
        """
        Switch to a different view.

        Args:
            view_type: ViewType constant (MATRIX, AUDIT)
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

        if view_type == ViewType.AUDIT and isinstance(view, AuditView):
            self._configure_audit_view(view)
            if self.connection:
                view.refresh()

        self.current_view = view_type
        self.set_status(f"Viewing: {view_type.title()}")

    def _configure_audit_view(self, view: AuditView) -> None:
        """Ensure audit callbacks are always wired to current connection state."""
        if self.connection:
            view.set_callbacks(on_fetch=self._fetch_audit_entries, on_export=None)
        else:
            view.set_callbacks(on_fetch=None, on_export=None)

    def _get_or_create_view(self, view_type: str) -> tk.Frame:
        """Get existing view or create a new one."""
        if view_type not in self._views:
            self._views[view_type] = self._create_view(view_type)
        return self._views[view_type]

    def _create_view(self, view_type: str) -> tk.Frame:
        """Create a view instance."""
        if view_type == ViewType.MATRIX:
            view = MatrixView(
                self._view_container,
                matrix=self.matrix,  # Pass current matrix (may be None if not connected)
                on_commit=self._commit_changes,
                on_cancel=self._cancel_changes,
            )
            if self.matrix:
                view.refresh()
            return view

        if view_type == ViewType.AUDIT:
            view = AuditView(
                self._view_container,
                on_fetch=self._fetch_audit_entries if self.connection else None,
                on_export=None,
            )
            self._configure_audit_view(view)
            return view

        # Placeholder for any future views
        frame = ttk.Frame(self._view_container)
        return frame

    def _open_settings_dialog(self) -> None:
        """Open settings as a modal dialog instead of a shell tab."""
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.deiconify()
            self._settings_window.lift()
            self._settings_window.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Settings")
        win.geometry("1000x720")
        win.transient(self)
        win.grab_set()

        def on_close_settings() -> None:
            self._settings_view = None
            if self._settings_window is not None:
                self._settings_window.destroy()
            self._settings_window = None

        view = SettingsView(
            win,
            config=self.config,
            on_save=self._on_settings_saved,
            on_test=self._test_connection,
            on_cancel=on_close_settings,
            last_test=self._last_connection_test,
        )
        view.pack(fill="both", expand=True)

        self._settings_window = win
        self._settings_view = view

        win.protocol("WM_DELETE_WINDOW", on_close_settings)

    def _open_tags_dialog(self) -> None:
        """Open tag manager as a non-shell dialog."""
        if self._tags_window is not None and self._tags_window.winfo_exists():
            self._tags_window.deiconify()
            self._tags_window.lift()
            self._tags_window.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Tag Manager")
        win.geometry("1100x760")
        win.transient(self)

        users = self.matrix.users if self.matrix else []
        objects = self.matrix.objects if self.matrix else []

        view = TagsView(
            win,
            tag_store=self.tag_store,
            users=users,
            objects=objects,
        )
        view.pack(fill="both", expand=True)
        view.refresh()

        self._tags_window = win
        self._tags_view = view

        def on_close_tags() -> None:
            self._tags_view = None
            if self.matrix:
                self.matrix.set_tag_store(self.tag_store)
            if self._tags_window is not None:
                self._tags_window.destroy()
            self._tags_window = None

        win.protocol("WM_DELETE_WINDOW", on_close_tags)

    def _on_settings_saved(self, config: Configuration) -> None:
        """Handle settings saved callback."""
        self.config = config
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.destroy()
        self._settings_window = None
        self._settings_view = None
        self._try_connect()

    def _test_connection(self, config: Configuration) -> tuple[bool, str]:
        """Test database connection and remember the result for the Settings dialog."""
        try:
            from src.db.connection import test_connection

            success, message = test_connection(config)
        except ImportError:
            success, message = False, "Database module not available"
        except Exception as e:
            success, message = False, f"Connection failed: {str(e)}"

        self._last_connection_test = (config, success, message)
        return success, message

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

    def _update_header_info(self, server: str, database: str, user: str) -> None:
        """Update header with connection details."""
        self._server_label.configure(text=f"{server}/{database} ({user})")

    def _start_connection_monitor(self) -> None:
        """Start background connection health monitoring."""
        self._stop_connection_monitor()
        self._connection_monitor_job = self.after(30000, self._check_connection_health)

    def _stop_connection_monitor(self) -> None:
        """Stop background connection health monitoring."""
        if self._connection_monitor_job is not None:
            try:
                self.after_cancel(self._connection_monitor_job)
            except Exception:
                pass
            self._connection_monitor_job = None

    def _check_connection_health(self) -> None:
        """Heartbeat check for active database connection."""
        if not self.connection:
            self._connection_monitor_job = None
            return

        try:
            cursor = self.connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()

            self._connection_monitor_job = self.after(30000, self._check_connection_health)
        except Exception as e:
            self._connection_monitor_job = None
            self._handle_connection_loss(str(e))

    def _handle_connection_loss(self, error: str) -> None:
        """Handle detected connection loss and offer reconnect."""
        if self._connection_lost_notified:
            return

        self._connection_lost_notified = True
        self._update_connection_status(connected=False)
        staged_count = len(self.matrix.get_staged_changes()) if self.matrix else 0
        if staged_count > 0:
            self.set_status(f"Connection lost - {staged_count} staged change(s) preserved")
        else:
            self.set_status("Connection lost - no staged changes")

        action = self._show_connection_loss_dialog(error=error, staged_count=staged_count)
        if action == "reconnect":
            self._reconnect_preserving_staged_changes()
        elif action == "settings":
            self._open_settings_dialog()
            self.set_status("Connection lost - update settings to reconnect")
        else:
            self.set_status("Offline mode - staged changes preserved")

    def _show_connection_loss_dialog(self, error: str, staged_count: int) -> str:
        """Show a connection-loss dialog with recovery options.

        Returns:
            str: "reconnect", "settings", or "offline"
        """
        result = tk.StringVar(value="offline")

        dialog = tk.Toplevel(self)
        dialog.title("Connection Lost")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        body = ttk.Frame(dialog, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="⚠ Connection to SQL Server was lost",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        staged_text = (
            f"Staged changes preserved: {staged_count}"
            if staged_count
            else "No staged changes are currently pending."
        )
        ttk.Label(body, text=staged_text, justify="left", wraplength=520).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(body, text=f"Error: {error}", justify="left", wraplength=520).pack(
            anchor="w", pady=(0, 10)
        )

        ttk.Label(
            body,
            text="Choose how you want to continue:",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        button_row = ttk.Frame(body)
        button_row.pack(fill="x", pady=(4, 0))

        def choose(value: str) -> None:
            result.set(value)
            dialog.destroy()

        reconnect_btn = ttk.Button(
            button_row,
            text="Reconnect Now",
            command=lambda: choose("reconnect"),
        )
        reconnect_btn.pack(side="left", padx=(0, 6))
        ttk.Button(
            button_row,
            text="Open Settings",
            command=lambda: choose("settings"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            button_row,
            text="Stay Offline",
            command=lambda: choose("offline"),
        ).pack(side="left")

        dialog.bind("<Return>", lambda e: choose("reconnect"))
        dialog.bind("<Escape>", lambda e: choose("offline"))
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("offline"))

        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx()+120}+{self.winfo_rooty()+120}")
        reconnect_btn.focus_set()

        self.wait_window(dialog)
        return result.get()

    def _reconnect_preserving_staged_changes(self) -> None:
        """Reconnect and preserve currently staged changes."""
        if not self.config:
            self._open_settings_dialog()
            return

        staged = self.matrix.get_staged_changes() if self.matrix else []

        try:
            from src.db.audit import ensure_audit_log_table
            from src.db.connection import create_connection, get_current_user

            if self.connection:
                try:
                    self.connection.close()
                except Exception:
                    pass

            self.connection = create_connection(self.config)
            ensure_audit_log_table(self.connection, self.config.schema)

            current_user = get_current_user(self.connection)

            new_matrix = PermissionMatrix(self.connection, self.config.schema, self.tag_store)
            new_matrix.load()

            for change in staged:
                new_matrix.stage_change(
                    user_login=change.user_login,
                    schema_name=change.schema_name,
                    object_name=change.object_name,
                    permission_type=change.permission_type,
                    new_state=change.new_state,
                    add_to_undo=False,
                )

            self.matrix = new_matrix
            self._connection_lost_notified = False
            self._update_connection_status(connected=True)
            self._update_header_info(self.config.server, self.config.database, current_user)
            self._start_connection_monitor()

            self._update_views_with_data(self.matrix.users, self.matrix.objects)
            if self.current_view in self._views and hasattr(self._views[self.current_view], "refresh"):
                self._views[self.current_view].refresh()

            self.set_status("Reconnected - staged changes restored")
        except Exception as e:
            self._update_connection_status(connected=False)
            self.set_status(f"Reconnect failed: {e}")
            follow_up = messagebox.askyesnocancel(
                "Reconnect Failed",
                "Could not reconnect to the database.\n\n"
                "Yes = Retry reconnect now\n"
                "No = Open settings\n"
                "Cancel = Stay offline",
            )
            if follow_up is True:
                self._reconnect_preserving_staged_changes()
            elif follow_up is False:
                self._open_settings_dialog()

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
        self._open_settings_dialog()

    def _disconnect(self) -> None:
        """Disconnect from database."""
        self._stop_connection_monitor()
        if self.connection:
            self.connection.close()
            self.connection = None
        self._update_connection_status(connected=False)
        self.set_status("Disconnected")

    def _export_permissions(self) -> None:
        """Export permission matrix to CSV."""
        if not self.matrix:
            messagebox.showinfo("Export", "No matrix data to export.")
            return

        try:
            from src.services.export import export_permissions_from_index, get_suggested_filename

            database = self.config.database if self.config else "database"
            suggested_name = get_suggested_filename("permissions", database)

            file_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile=suggested_name,
            )

            if not file_path:
                return

            error = export_permissions_from_index(
                file_path=file_path,
                index=self.matrix.index,
                include_none=True,
            )

            if error:
                messagebox.showerror("Export Failed", error)
                return

            messagebox.showinfo("Export Complete", f"Permissions exported to:\n{file_path}")
            self.set_status("Permissions CSV exported")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _export_audit(self) -> None:
        """Export audit log to CSV."""
        if not self.connection:
            messagebox.showinfo("Export", "Connect to a database to export audit log.")
            return

        try:
            from src.services.export import export_audit_csv, get_suggested_filename

            database = self.config.database if self.config else "database"
            suggested_name = get_suggested_filename("audit", database)

            file_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile=suggested_name,
            )

            if not file_path:
                return

            entries = self._fetch_audit_entries({})
            error = export_audit_csv(file_path=file_path, entries=entries)

            if error:
                messagebox.showerror("Export Failed", error)
                return

            messagebox.showinfo("Export Complete", f"Audit log exported to:\n{file_path}")
            self.set_status("Audit log CSV exported")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def _undo(self) -> None:
        """Undo last change."""
        if not self.matrix:
            self.set_status("No active matrix")
            return

        if self.matrix.undo():
            self._has_unsaved_changes = self.matrix.has_staged_changes()
            if ViewType.MATRIX in self._views:
                self._views[ViewType.MATRIX].refresh()
            self.set_status("Undo applied")
        else:
            self.set_status("Nothing to undo")

    def _redo(self) -> None:
        """Redo last undone change."""
        if not self.matrix:
            self.set_status("No active matrix")
            return

        if self.matrix.redo():
            self._has_unsaved_changes = self.matrix.has_staged_changes()
            if ViewType.MATRIX in self._views:
                self._views[ViewType.MATRIX].refresh()
            self.set_status("Redo applied")
        else:
            self.set_status("Nothing to redo")

    def _show_commit_preview(self, staged_changes: list) -> str:
        """Show a commit preview dialog for larger staged batches.

        Returns:
            str: "commit", "review", or "cancel"
        """
        if len(staged_changes) < 5:
            return "commit"

        result = tk.StringVar(value="cancel")
        show_all = tk.BooleanVar(value=False)

        dialog = tk.Toplevel(self)
        dialog.title(f"Review {len(staged_changes)} Permission Changes")
        dialog.transient(self)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text=f"Review {len(staged_changes)} Permission Changes",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            container,
            text="You're about to commit the following staged changes:",
        ).pack(anchor="w", pady=(0, 8))

        preview_text = tk.Text(container, width=96, height=12, wrap="word", state="normal")
        preview_text.pack(fill="both", expand=True)

        def render_preview() -> None:
            preview_text.configure(state="normal")
            preview_text.delete("1.0", tk.END)

            to_show = staged_changes if show_all.get() else staged_changes[:3]
            for change in to_show:
                preview_text.insert(
                    tk.END,
                    f"✓ {change.action} {change.permission_type.value} to {change.user_login} "
                    f"on {change.schema_name}.{change.object_name}\n"
                    f"  Previous: {change.previous_state.value}\n\n",
                )

            remaining = len(staged_changes) - len(to_show)
            if remaining > 0:
                preview_text.insert(tk.END, f"... and {remaining} more change(s)\n")

            preview_text.configure(state="disabled")

        def toggle_show_all() -> None:
            show_all.set(not show_all.get())
            toggle_btn.configure(
                text=(
                    "Show first 3 changes"
                    if show_all.get()
                    else f"Show all {len(staged_changes)} changes"
                )
            )
            render_preview()

        toggle_btn = ttk.Button(
            container,
            text=f"Show all {len(staged_changes)} changes",
            command=toggle_show_all,
        )
        toggle_btn.pack(anchor="w", pady=(8, 10))

        action_row = ttk.Frame(container)
        action_row.pack(fill="x")

        def choose(action: str) -> None:
            result.set(action)
            dialog.destroy()

        ttk.Button(
            action_row,
            text="Review in Matrix",
            command=lambda: choose("review"),
        ).pack(side="left")

        commit_btn = ttk.Button(
            action_row,
            text="Commit All",
            command=lambda: choose("commit"),
        )
        commit_btn.pack(side="right", padx=(6, 0))

        ttk.Button(
            action_row,
            text="Cancel",
            command=lambda: choose("cancel"),
        ).pack(side="right")

        dialog.bind("<Escape>", lambda e: choose("cancel"))
        dialog.bind("<Return>", lambda e: choose("commit"))
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))

        render_preview()
        commit_btn.focus_set()
        self.wait_window(dialog)
        return result.get()

    def _show_partial_commit_dialog(
        self,
        successes: int,
        failures: list[tuple],
    ) -> str:
        """Show partial commit details and return the next action."""
        result = tk.StringVar(value="retry")

        dialog = tk.Toplevel(self)
        dialog.title("Commit Partially Failed")
        dialog.transient(self)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="⚠ Commit Partially Failed",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            container,
            text=f"{successes} change(s) succeeded, {len(failures)} failed.",
        ).pack(anchor="w", pady=(0, 8))

        text = tk.Text(container, width=100, height=12, wrap="word", state="normal")
        text.pack(fill="both", expand=True)
        text.insert(tk.END, "Failed changes remain staged. Fix issues and retry.\n\n")
        for change, err in failures:
            text.insert(
                tk.END,
                f"✗ FAILED: {change.action} {change.permission_type.value} "
                f"for {change.user_login} on {change.schema_name}.{change.object_name}\n"
                f"  Reason: {err}\n\n",
            )
        text.configure(state="disabled")

        row = ttk.Frame(container)
        row.pack(fill="x", pady=(10, 0))

        def choose(action: str) -> None:
            result.set(action)
            dialog.destroy()

        ttk.Button(
            row,
            text="View Audit Log",
            command=lambda: choose("view_audit"),
        ).pack(side="left")

        if successes > 0:
            ttk.Button(
                row,
                text="Retry Failed",
                command=lambda: choose("retry"),
            ).pack(side="right", padx=(6, 0))

        ttk.Button(
            row,
            text="Discard Failed",
            command=lambda: choose("discard"),
        ).pack(side="right")

        dialog.bind("<Escape>", lambda e: choose("discard"))
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("discard"))

        self.wait_window(dialog)
        return result.get()

    def _commit_changes(self) -> None:
        """Commit all pending changes to the database."""
        if not self.connection:
            self.set_status("Not connected to database")
            return

        if not hasattr(self, "matrix") or not self.matrix:
            self.set_status("No changes to commit")
            return

        staged_changes = self.matrix.get_staged_changes()
        if not staged_changes:
            self.set_status("No changes to commit")
            return

        preview_action = self._show_commit_preview(staged_changes)
        if preview_action == "cancel":
            self.set_status("Commit cancelled")
            return
        if preview_action == "review":
            self.switch_view(ViewType.MATRIX)
            self.set_status("Review staged changes in matrix")
            return

        self.set_status("Committing changes...")

        try:
            results = self.matrix.commit()

            failures = [(change, err) for change, err in results if err]
            successes = len(results) - len(failures)

            self._has_unsaved_changes = self.matrix.has_staged_changes()

            # Refresh matrix view
            if ViewType.MATRIX in self._views:
                self._views[ViewType.MATRIX].refresh()

            if failures:
                action = self._show_partial_commit_dialog(successes, failures)

                if action == "view_audit":
                    self.switch_view(ViewType.AUDIT)
                    self.set_status(
                        f"Commit partial: {successes} succeeded, {len(failures)} failed"
                    )
                elif action == "discard":
                    self.matrix.cancel()
                    if ViewType.MATRIX in self._views:
                        self._views[ViewType.MATRIX].refresh()
                    self.set_status("Discarded failed staged changes")
                else:
                    self.switch_view(ViewType.MATRIX)
                    self.set_status(
                        f"{len(failures)} failed change(s) remain staged for retry"
                    )
            else:
                self.set_status(f"Committed {successes} change(s)")
                if successes >= 5:
                    show_audit = messagebox.askyesno(
                        "Commit Complete",
                        f"{successes} permission changes were applied successfully.\n\n"
                        "Open Audit Log now?",
                    )
                    if show_audit:
                        self.switch_view(ViewType.AUDIT)

        except Exception as e:
            self.connection.rollback()
            messagebox.showerror("Commit Failed", str(e))
            self.set_status("Commit failed")
            self._handle_connection_loss(str(e))

    def _cancel_changes(self) -> None:
        """Cancel all pending changes."""
        if not hasattr(self, "matrix") or not self.matrix:
            self.set_status("No changes to cancel")
            return

        staged_count = len(self.matrix.get_staged_changes())
        if staged_count == 0:
            self.set_status("No changes to cancel")
            return

        should_cancel = True
        if staged_count >= 5:
            should_cancel = messagebox.askyesno(
                "Cancel Changes",
                f"Discard {staged_count} staged change(s)? This cannot be undone.",
            )

        if should_cancel:
            self.matrix.cancel()
            self._has_unsaved_changes = False

            # Refresh matrix view
            if ViewType.MATRIX in self._views:
                self._views[ViewType.MATRIX].refresh()

            self.set_status(f"Discarded {staged_count} change(s)")

    def _refresh(self) -> None:
        """Refresh current view with fresh data from database."""
        if not self.connection:
            self.set_status("Not connected to database")
            return

        self.set_status("Refreshing...")

        try:
            # Matrix.refresh() reloads from DB and preserves staged changes
            if hasattr(self, "matrix") and self.matrix:
                self.matrix.refresh()

            # Update views with fresh data
            if self.matrix:
                self._update_views_with_data(self.matrix.users, self.matrix.objects)

            # Refresh current view
            if self.current_view in self._views:
                view = self._views[self.current_view]
                if hasattr(view, "refresh"):
                    view.refresh()

            self.set_status("Refreshed")

        except Exception as e:
            self.set_status(f"Refresh failed: {e}")
            self._handle_connection_loss(str(e))

    def _fetch_audit_entries(self, filters: dict) -> list:
        """Fetch audit entries from database with filters."""
        if not self.connection:
            return []

        try:
            from src.db.audit import fetch_audit_entries

            start_date = filters.get("from_date")
            end_date = filters.get("to_date")
            if end_date and isinstance(end_date, datetime):
                # End-of-day is already normalized by the view.
                end_date = end_date

            return fetch_audit_entries(
                self.connection,
                self.config.schema,
                start_date=start_date,
                end_date=end_date,
                affected_user_contains=filters.get("user"),
                object_search=filters.get("object"),
                action=filters.get("action"),
                limit=filters.get("limit"),
            )
        except Exception as e:
            raise RuntimeError(str(e)) from e

    def _show_shortcuts(self) -> None:
        """Show keyboard shortcuts dialog."""
        shortcuts = """
Keyboard Shortcuts
==================

Navigation:
  Ctrl+1    Matrix View
    Ctrl+4    Audit View
    Ctrl+2    Tag Manager
    Ctrl+,    Settings

Actions:
  Ctrl+S    Commit Changes
    Ctrl+Enter Commit Changes
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
        self._stop_connection_monitor()
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
