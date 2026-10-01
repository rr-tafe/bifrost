"""
Permission Matrix view for Bifrost.

This module provides the MatrixView class which displays the permission matrix
as a scrollable grid with users as rows and object-permission pairs as columns.

Architecture:
    MatrixView
    ├── FilterBar (search, filters)
    ├── MatrixCanvas (virtual scrolling grid)
    │   ├── User column (sticky)
    │   └── Object × Permission cells
    └── ActionBar (commit, cancel, count)

Virtual Scrolling:
    - Only renders visible cells (viewport + buffer)
    - Handles thousands of users/objects efficiently
    - Smooth scrolling with keyboard and mouse wheel

Cell States:
    - NONE: Gray background
    - GRANT: Green background
    - DENY: Red background
    - Staged changes: Yellow border highlight

Usage:
    from src.ui.views.matrix import MatrixView

    view = MatrixView(
        parent=container,
        matrix=permission_matrix,
        on_commit=commit_handler,
        on_cancel=cancel_handler,
    )
    view.pack(fill="both", expand=True)
"""

import tkinter as tk
import re
from collections.abc import Callable
from tkinter import messagebox, ttk

from src.models.db_object import ObjectType
from src.models.permission import PermissionState, PermissionType


class MatrixView(ttk.Frame):
    """
    Permission matrix view with virtual scrolling.

    Displays a grid of users × (objects × permissions) where each cell
    represents a specific permission state (NONE, GRANT, DENY).

    Attributes:
        matrix: PermissionMatrix service instance
        on_commit: Callback when user clicks Commit
        on_cancel: Callback when user clicks Cancel

    Cell Colors:
        - NONE: #e0e0e0 (gray)
        - GRANT: #90EE90 (light green)
        - DENY: #FFB6C1 (light red/pink)
        - Staged: Yellow border

    Keyboard Shortcuts:
        - Enter/Space: Toggle selected cell
        - Arrow keys: Navigate cells
        - Ctrl+S: Commit
        - Escape: Cancel

    Example:
        >>> view = MatrixView(
        ...     parent=container,
        ...     matrix=permission_matrix,
        ...     on_commit=lambda: print("Committed"),
        ... )
    """

    # Colors
    COLOR_NONE = "#e0e0e0"
    COLOR_GRANT = "#90EE90"
    COLOR_DENY = "#FFB6C1"
    COLOR_STAGED_BORDER = "#FFD700"
    COLOR_SELECTED = "#4169E1"
    COLOR_HEADER_BG = "#f5f5f5"

    # Cell dimensions
    CELL_WIDTH = 28
    CELL_HEIGHT = 28
    USER_COL_WIDTH = 200
    OBJECT_HEADER_HEIGHT = 72
    PERMISSION_HEADER_HEIGHT = 120
    OBJECT_GAP = 6

    # Buffer for virtual scrolling
    BUFFER_ROWS = 5
    BUFFER_COLS = 10
    MAX_SELECTED_USERS = 10
    MAX_SELECTED_OBJECTS = 10
    PAGE_SIZE_OPTIONS = (5, 10, 20, 50)

    def __init__(
        self,
        parent: tk.Widget,
        matrix=None,
        on_commit: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ):
        """
        Initialize the matrix view.

        Args:
            parent: Parent widget
            matrix: PermissionMatrix service (can be None for disconnected state)
            on_commit: Callback when user commits changes
            on_cancel: Callback when user cancels changes
        """
        super().__init__(parent)

        self.matrix = matrix
        self.on_commit = on_commit
        self.on_cancel = on_cancel

        # View state
        self._filtered_users: list = []
        self._filtered_objects: list = []
        self._permission_types: list = list(PermissionType)
        self._all_users: list = []
        self._all_objects: list = []
        self._display_users_per_page = 10
        self._display_objects_per_page = 10
        self._user_page_index = 0
        self._object_page_index = 0
        self._pending_user_selection: set[str] = set()
        self._pending_object_selection: set[str] = set()
        self._applied_user_selection: set[str] = set()
        self._applied_object_selection: set[str] = set()
        self._selected_users_ordered: list = []
        self._selected_objects_ordered: list = []
        self._column_spans: list[tuple[int, int, int, any]] = []
        self._column_defs: list[tuple[int, any, int]] = []
        self._active_highlight: dict | None = None
        self._shown_grant_validation_hint = False

        # Viewport state
        self._scroll_x = 0
        self._scroll_y = 0
        self._selected_cell: tuple | None = None

        # Canvas items cache
        self._cell_items: dict[tuple, int] = {}
        self._text_items: dict[tuple, int] = {}

        self._create_layout()
        self._update_selector_button_labels()
        self._bind_events()

        if matrix:
            matrix.set_on_change_callback(self._update_changes_count)

        if matrix:
            self.refresh_data()

    def _create_layout(self) -> None:
        """Create the view layout."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Filter bar
        self._create_filter_bar()

        # Matrix canvas (with scrollbars)
        self._create_canvas()

        # Action bar
        self._create_action_bar()

    def _create_filter_bar(self) -> None:
        """Create simplified top controls for user/object subset selection."""
        filter_frame = ttk.Frame(self)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        selector_row = ttk.Frame(filter_frame)
        selector_row.pack(side="top", fill="x", pady=(0, 5))

        ttk.Label(selector_row, text="Users:").pack(side="left", padx=(0, 6))
        self._users_selector_btn = ttk.Button(
            selector_row,
            text="Select users...",
            command=self._open_user_selector,
        )
        self._users_selector_btn.pack(side="left")

        ttk.Label(selector_row, text="Objects:").pack(side="left", padx=(16, 6))
        self._objects_selector_btn = ttk.Button(
            selector_row,
            text="Select objects...",
            command=self._open_object_selector,
        )
        self._objects_selector_btn.pack(side="left")

        ttk.Button(
            selector_row,
            text="Clear Selection",
            command=self._clear_selection,
        ).pack(side="left", padx=(16, 0))

        ttk.Label(selector_row, text="Users page:").pack(side="left", padx=(16, 4))
        self._users_prev_btn_top = ttk.Button(
            selector_row,
            text="◀",
            width=3,
            command=self._prev_user_page,
        )
        self._users_prev_btn_top.pack(side="left")
        self._users_page_label_top = ttk.Label(selector_row, text="0-0/0")
        self._users_page_label_top.pack(side="left", padx=4)
        self._users_next_btn_top = ttk.Button(
            selector_row,
            text="▶",
            width=3,
            command=self._next_user_page,
        )
        self._users_next_btn_top.pack(side="left")

        ttk.Label(selector_row, text="Objects page:").pack(side="left", padx=(12, 4))
        self._objects_prev_btn_top = ttk.Button(
            selector_row,
            text="◀",
            width=3,
            command=self._prev_object_page,
        )
        self._objects_prev_btn_top.pack(side="left")
        self._objects_page_label_top = ttk.Label(selector_row, text="0-0/0")
        self._objects_page_label_top.pack(side="left", padx=4)
        self._objects_next_btn_top = ttk.Button(
            selector_row,
            text="▶",
            width=3,
            command=self._next_object_page,
        )
        self._objects_next_btn_top.pack(side="left")

        ttk.Button(
            selector_row,
            text="🔄 Refresh",
            command=self.refresh_data,
        ).pack(side="right", padx=5)

        self._selection_error_label = ttk.Label(filter_frame, text="", foreground="#B22222")
        self._selection_error_label.pack(side="top", fill="x", pady=(0, 4))

        self._orientation_label = ttk.Label(
            filter_frame,
            text="Viewing: not connected",
            foreground="#1E3A8A",
        )
        self._orientation_label.pack(side="top", fill="x", pady=(0, 4))

        self._warning_label = ttk.Label(filter_frame, text="", foreground="orange")
        self._warning_label.pack(side="top", fill="x")

    def _create_canvas(self) -> None:
        """Create the matrix canvas with scrollbars."""
        canvas_frame = ttk.Frame(self)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)

        # Main canvas
        self._canvas = tk.Canvas(
            canvas_frame,
            bg="white",
            highlightthickness=0,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbars
        v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self._on_y_scroll)
        v_scroll.grid(row=0, column=1, sticky="ns")

        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self._on_x_scroll)
        h_scroll.grid(row=1, column=0, sticky="ew")

        self._canvas.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Placeholder text for empty state
        self._placeholder_text = self._canvas.create_text(
            300,
            200,
            text="Connect to a database to view permissions.\n\n"
            "Go to Settings (Ctrl+,) to configure your connection.",
            font=("Segoe UI", 12),
            fill="gray",
            justify="center",
        )

    def _create_action_bar(self) -> None:
        """Create the action bar."""
        action_frame = ttk.Frame(self)
        action_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        nav_row = ttk.Frame(action_frame)
        nav_row.pack(side="top", fill="x", pady=(0, 6))

        ttk.Label(nav_row, text="Users page:").pack(side="left", padx=(0, 4))
        self._users_prev_btn_bottom = ttk.Button(
            nav_row,
            text="◀",
            width=3,
            command=self._prev_user_page,
        )
        self._users_prev_btn_bottom.pack(side="left")
        self._users_page_label_bottom = ttk.Label(nav_row, text="0-0/0")
        self._users_page_label_bottom.pack(side="left", padx=4)
        self._users_next_btn_bottom = ttk.Button(
            nav_row,
            text="▶",
            width=3,
            command=self._next_user_page,
        )
        self._users_next_btn_bottom.pack(side="left")

        ttk.Label(nav_row, text="Objects page:").pack(side="left", padx=(12, 4))
        self._objects_prev_btn_bottom = ttk.Button(
            nav_row,
            text="◀",
            width=3,
            command=self._prev_object_page,
        )
        self._objects_prev_btn_bottom.pack(side="left")
        self._objects_page_label_bottom = ttk.Label(nav_row, text="0-0/0")
        self._objects_page_label_bottom.pack(side="left", padx=4)
        self._objects_next_btn_bottom = ttk.Button(
            nav_row,
            text="▶",
            width=3,
            command=self._next_object_page,
        )
        self._objects_next_btn_bottom.pack(side="left")

        # Changes count
        self._changes_label = ttk.Label(
            action_frame,
            text="No pending changes",
            font=("Segoe UI", 10),
        )
        self._changes_label.pack(side="left", anchor="w")

        # Cancel button
        self._cancel_btn = ttk.Button(
            action_frame,
            text="Cancel Changes",
            command=self._handle_cancel,
            state="disabled",
        )
        self._cancel_btn.pack(side="right", padx=5)

        # Commit button
        self._commit_btn = ttk.Button(
            action_frame,
            text="Commit Changes",
            command=self._handle_commit,
            state="disabled",
        )
        self._commit_btn.pack(side="right", padx=5)

    def _bind_events(self) -> None:
        """Bind event handlers."""
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self._canvas.bind("<Enter>", self._activate_wheel_capture)
        self._canvas.bind("<Leave>", self._deactivate_wheel_capture)

        # Capture wheel events at the toplevel and route them to the matrix
        # when the pointer is over this canvas. This avoids "wheel only on
        # scrollbar" behavior caused by focus-dependent wheel delivery.
        toplevel = self.winfo_toplevel()
        toplevel.bind("<MouseWheel>", self._on_global_mouse_wheel, add="+")

        # Keyboard
        self.bind("<Return>", self._on_toggle_cell)
        self.bind("<space>", self._on_toggle_cell)
        self.bind("<Up>", lambda e: self._move_selection(0, -1))
        self.bind("<Down>", lambda e: self._move_selection(0, 1))
        self.bind("<Left>", lambda e: self._move_selection(-1, 0))
        self.bind("<Right>", lambda e: self._move_selection(1, 0))
        self.bind("<Control-u>", self._focus_user_selector)
        self.bind("<Control-o>", self._focus_object_selector)
        self.bind("<Escape>", self._clear_highlight)

    def _activate_wheel_capture(self, _event=None) -> None:
        """Capture mouse wheel while pointer is over matrix canvas."""
        self._canvas.focus_set()

    def _deactivate_wheel_capture(self, _event=None) -> None:
        """Release mouse wheel capture when leaving matrix canvas."""
        return None

    def _is_descendant_widget(self, widget, ancestor) -> bool:
        """Check whether widget is inside ancestor in the Tk widget tree."""
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            try:
                parent_path = current.winfo_parent()
            except tk.TclError:
                return False
            if not parent_path:
                return False
            try:
                current = current.nametowidget(parent_path)
            except (tk.TclError, KeyError):
                return False
        return False

    def _on_global_mouse_wheel(self, event) -> str | None:
        """Route to matrix wheel handler when pointer is over matrix canvas."""
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            hovered = self.winfo_containing(pointer_x, pointer_y)
        except tk.TclError:
            return None

        if hovered is None or not self._is_descendant_widget(hovered, self._canvas):
            return None

        self._on_mouse_wheel(event)
        return "break"

    def _focus_user_selector(self, event=None) -> str:
        """Focus the user selector button."""
        self._users_selector_btn.focus_set()
        return "break"

    def _focus_object_selector(self, event=None) -> str:
        """Focus the object selector button."""
        self._objects_selector_btn.focus_set()
        return "break"

    def _open_user_selector(self) -> None:
        """Open users dropdown checklist."""
        self._open_selector_popup(kind="users")

    def _open_object_selector(self) -> None:
        """Open objects dropdown checklist."""
        self._open_selector_popup(kind="objects")

    def _is_likely_service_account(self, principal_name: str) -> bool:
        """Heuristic classifier for service-account style principal names."""
        name = principal_name.lower()

        # Pattern family 1: SAS-style naming (e.g. "misasuser", "miusersas").
        if re.match(r"^mi[a-z0-9_-]*sas[a-z0-9_-]*$", name):
            return True

        # Pattern family 2: Tableau-related operational/service identities.
        if "tableau" in name:
            return True

        # Pattern family 3: Environment/workload prefix (e.g. "npe9-*", "dev2-*").
        if re.match(r"^[a-z]{2,5}\d+-[a-z0-9_-]+$", name):
            return True

        service_prefixes = (
            "svc",
            "svc_",
            "svc-",
            "sa_",
            "sa-",
            "app_",
            "app-",
            "sqlagent",
            "agent_",
            "batch_",
            "etl_",
        )
        if any(name.startswith(prefix) for prefix in service_prefixes):
            return True
        if "service" in name:
            return True
        if name.endswith("$"):
            return True
        return False

    def _build_selector_sections(self, kind: str, filtered_choices: list[str]) -> list[tuple[str, list[str]]]:
        """Build ordered sections for selector rendering."""
        if kind == "objects":
            object_map = {o.full_name: o for o in self._all_objects}
            grouped: dict[str, list[str]] = {
                "Tables": [],
                "Views": [],
                "Stored Procedures": [],
                "Functions": [],
                "Other": [],
            }
            for name in filtered_choices:
                obj = object_map.get(name)
                if obj is None:
                    grouped["Other"].append(name)
                    continue

                if obj.object_type == ObjectType.TABLE:
                    grouped["Tables"].append(name)
                elif obj.object_type == ObjectType.VIEW:
                    grouped["Views"].append(name)
                elif obj.object_type == ObjectType.PROCEDURE:
                    grouped["Stored Procedures"].append(name)
                elif obj.object_type == ObjectType.FUNCTION:
                    grouped["Functions"].append(name)
                else:
                    grouped["Other"].append(name)

            ordered = ("Tables", "Views", "Stored Procedures", "Functions", "Other")
            return [(section, grouped[section]) for section in ordered if grouped[section]]

        if kind != "users":
            return [("Items", filtered_choices)]

        user_map = {u.login_name: u for u in self._all_users}
        grouped: dict[str, list[str]] = {
            "Users": [],
            "Service Accounts": [],
            "Groups": [],
        }

        for name in filtered_choices:
            user = user_map.get(name)
            principal_type = user.principal_type if user else ""

            if principal_type == "G":
                grouped["Groups"].append(name)
            elif self._is_likely_service_account(name):
                grouped["Service Accounts"].append(name)
            else:
                grouped["Users"].append(name)

        ordered = ("Users", "Service Accounts", "Groups")
        return [(section, grouped[section]) for section in ordered if grouped[section]]

    def _open_selector_popup(self, kind: str) -> None:
        """Open a checklist popup for users or objects."""
        choices = (
            [u.login_name for u in self._all_users]
            if kind == "users"
            else [o.full_name for o in self._all_objects]
        )
        title = "Select Users" if kind == "users" else "Select Objects"
        pending = self._pending_user_selection if kind == "users" else self._pending_object_selection
        opener = self._users_selector_btn if kind == "users" else self._objects_selector_btn

        popup = tk.Toplevel(self)
        popup.title(title)
        popup.transient(self)
        popup.grab_set()
        popup.resizable(True, True)
        popup.minsize(560, 420)

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=f"Select {kind} (any number):").pack(anchor="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="Use section-specific search boxes below.",
            foreground="gray",
        ).pack(anchor="w", pady=(0, 6))

        error_label = ttk.Label(frame, text="", foreground="#B22222")
        error_label.pack(anchor="w", pady=(0, 6))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        pending_search_refresh_id = None

        def on_canvas_yview(first: str, last: str) -> None:
            scrollbar.set(first, last)
            if kind == "objects":
                render_object_rows()

        canvas.configure(yscrollcommand=on_canvas_yview)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        items_frame = ttk.Frame(canvas) if kind == "users" else None
        canvas_window = canvas.create_window((0, 0), window=items_frame, anchor="nw") if items_frame else None

        checkbox_vars: dict[str, tk.BooleanVar] = {}
        checkbox_widgets: list[ttk.Checkbutton] = []
        filtered_choices = list(choices)
        apply_btn = None
        object_header_height = 34
        object_row_height = 24
        object_section_gap = 8
        object_rows: list[dict] = []
        object_section_order = ["Tables", "Views", "Stored Procedures", "Functions"]
        object_section_source: dict[str, list[str]] = {}
        object_section_filters: dict[str, tk.StringVar] = {}
        object_section_filtered: dict[str, list[str]] = {}
        object_section_headers: dict[str, dict] = {}
        object_section_collapsed: dict[str, bool] = {}
        user_section_filters: dict[str, tk.StringVar] = {}
        user_section_filter_traced: set[str] = set()
        user_section_collapsed: dict[str, bool] = {}
        object_active_index: int | None = None

        def update_scrollregion(_event=None) -> None:
            if kind == "users":
                canvas.configure(scrollregion=canvas.bbox("all"))
                if canvas_window is not None:
                    canvas.itemconfigure(canvas_window, width=canvas.winfo_width())
            else:
                width = max(1, canvas.winfo_width())
                total_height = object_rows[-1]["y2"] if object_rows else 1
                canvas.configure(scrollregion=(0, 0, width, total_height))

        if items_frame is not None:
            items_frame.bind("<Configure>", update_scrollregion)

        def _on_canvas_resize(_event=None) -> None:
            update_scrollregion()
            if kind == "objects":
                render_object_rows()

        canvas.bind("<Configure>", _on_canvas_resize)

        def _popup_widget_contains(widget, ancestor) -> bool:
            current = widget
            while current is not None:
                if current == ancestor:
                    return True
                try:
                    parent_path = current.winfo_parent()
                except tk.TclError:
                    return False
                if not parent_path:
                    return False
                try:
                    current = current.nametowidget(parent_path)
                except (tk.TclError, KeyError):
                    return False
            return False

        def _popup_mouse_wheel(event) -> str | None:
            try:
                pointer_x, pointer_y = popup.winfo_pointerxy()
                hovered = popup.winfo_containing(pointer_x, pointer_y)
            except tk.TclError:
                return None

            if hovered is None or not _popup_widget_contains(hovered, canvas):
                return None

            delta = event.delta
            if delta == 0:
                return "break"
            delta_units = int(-1 * (delta / 120))
            if delta_units == 0:
                delta_units = -1 if delta > 0 else 1

            if bool(event.state & 0x0001):
                canvas.xview_scroll(delta_units, "units")
            else:
                canvas.yview_scroll(delta_units, "units")
            if kind == "objects":
                render_object_rows()
            return "break"

        popup.bind("<MouseWheel>", _popup_mouse_wheel, add="+")

        def on_toggle_choice(name: str, selected_now: bool | None = None) -> None:
            if selected_now is None:
                selected_now = checkbox_vars[name].get()
            if selected_now:
                pending.add(name)
                error_label.configure(text="")
            else:
                pending.discard(name)
                error_label.configure(text="")
            update_apply_button_state()
            if kind == "objects":
                render_object_rows()

        def update_apply_button_state() -> None:
            if apply_btn is None:
                return
            apply_btn.configure(state="normal" if pending else "disabled")

        def set_names_selected(names: list[str], is_selected: bool) -> None:
            for name in names:
                if kind == "users":
                    var = checkbox_vars.get(name)
                    if var is None:
                        var = tk.BooleanVar(value=False)
                        checkbox_vars[name] = var
                    var.set(is_selected)
                if is_selected:
                    pending.add(name)
                else:
                    pending.discard(name)
            error_label.configure(text="")
            update_apply_button_state()
            if kind == "users":
                draw_current_user_list()
            else:
                update_object_section_header_labels()
                render_object_rows()

        def rebuild_list_now() -> None:
            nonlocal filtered_choices, pending_search_refresh_id, object_active_index
            pending_search_refresh_id = None
            if kind == "users":
                filtered_choices = list(choices)
            else:
                filtered_choices = list(choices)
            object_active_index = None
            if kind == "users":
                draw_current_user_list()
            else:
                rebuild_object_rows()
                render_object_rows()

        def rebuild_list(*_args) -> None:
            nonlocal pending_search_refresh_id
            if pending_search_refresh_id is not None:
                try:
                    popup.after_cancel(pending_search_refresh_id)
                except tk.TclError:
                    pass

            # Debounce typing to avoid full redraw on each keystroke for large lists.
            pending_search_refresh_id = popup.after(180, rebuild_list_now)

        def draw_current_user_list() -> None:
            if items_frame is None:
                return

            for child in items_frame.winfo_children():
                child.destroy()
            checkbox_widgets.clear()

            if not filtered_choices:
                ttk.Label(items_frame, text="No matches", foreground="gray").pack(anchor="w")
                return

            def focus_neighbor(widget: ttk.Checkbutton, delta: int) -> str:
                try:
                    idx = checkbox_widgets.index(widget)
                except ValueError:
                    return "break"
                target = idx + delta
                if 0 <= target < len(checkbox_widgets):
                    checkbox_widgets[target].focus_set()
                return "break"

            def toggle_user_section(section_name: str) -> None:
                user_section_collapsed[section_name] = not user_section_collapsed.get(section_name, True)
                draw_current_user_list()

            for section_name, section_names in self._build_selector_sections(kind, filtered_choices):
                if section_name not in user_section_filters:
                    user_section_filters[section_name] = tk.StringVar(value="")
                if section_name not in user_section_filter_traced:
                    user_section_filters[section_name].trace_add("write", rebuild_list)
                    user_section_filter_traced.add(section_name)
                if section_name not in user_section_collapsed:
                    user_section_collapsed[section_name] = True

                section_query = user_section_filters[section_name].get().strip().lower()
                visible_section_names = [n for n in section_names if section_query in n.lower()]

                section_frame = ttk.Frame(items_frame)
                section_frame.pack(fill="x", anchor="w", pady=(0, 8))

                header_row = ttk.Frame(section_frame)
                header_row.pack(fill="x", anchor="w", pady=(0, 2))

                ttk.Button(
                    header_row,
                    text="▶" if user_section_collapsed[section_name] else "▼",
                    width=2,
                    command=lambda section=section_name: toggle_user_section(section),
                ).pack(side="left", padx=(0, 4))

                section_label = ttk.Label(
                    header_row,
                    text=f"{section_name} ({len(visible_section_names)})",
                    font=("Segoe UI", 9, "bold"),
                    cursor="hand2",
                )
                section_label.pack(side="left", padx=(2, 8))
                section_label.bind("<Button-1>", lambda _e, section=section_name: toggle_user_section(section))

                ttk.Entry(
                    header_row,
                    textvariable=user_section_filters[section_name],
                    width=24,
                ).pack(side="left", padx=(0, 8))

                ttk.Button(
                    header_row,
                    text="Select",
                    width=8,
                    command=lambda names=list(visible_section_names): set_names_selected(names, True),
                ).pack(side="left", padx=(0, 4))
                ttk.Button(
                    header_row,
                    text="Clear",
                    width=8,
                    command=lambda names=list(visible_section_names): set_names_selected(names, False),
                ).pack(side="left")

                if user_section_collapsed[section_name]:
                    divider = ttk.Separator(section_frame, orient="horizontal")
                    divider.pack(fill="x", pady=(6, 0))
                    continue

                for name in visible_section_names:
                    var = checkbox_vars.get(name)
                    if var is None:
                        var = tk.BooleanVar(value=name in pending)
                        checkbox_vars[name] = var
                    else:
                        var.set(name in pending)

                    chk = ttk.Checkbutton(
                        section_frame,
                        text=name,
                        variable=var,
                        command=lambda n=name: on_toggle_choice(n),
                    )
                    chk.pack(anchor="w", fill="x", padx=(12, 0), pady=1)
                    chk.bind("<Up>", lambda _e, w=chk: focus_neighbor(w, -1))
                    chk.bind("<Down>", lambda _e, w=chk: focus_neighbor(w, 1))
                    checkbox_widgets.append(chk)

                divider = ttk.Separator(section_frame, orient="horizontal")
                divider.pack(fill="x", pady=(6, 0))

        def update_object_section_header_labels() -> None:
            for section_name, header in object_section_headers.items():
                count = len(object_section_filtered.get(section_name, []))
                header["label"].configure(text=f"{section_name} ({count})")
                header["toggle"].configure(text="▶" if object_section_collapsed.get(section_name, True) else "▼")

        def toggle_object_section(section_name: str) -> None:
            object_section_collapsed[section_name] = not object_section_collapsed.get(section_name, True)
            rebuild_object_rows()
            render_object_rows()

        def ensure_object_section_headers() -> None:
            sections = [name for name in object_section_order if name in object_section_source]
            sections.extend(
                [name for name in object_section_source if name not in object_section_order]
            )

            for section_name in sections:
                if section_name in object_section_headers:
                    continue

                if section_name not in object_section_filters:
                    object_section_filters[section_name] = tk.StringVar(value="")
                    object_section_filters[section_name].trace_add("write", rebuild_list)
                if section_name not in object_section_collapsed:
                    object_section_collapsed[section_name] = True

                header_frame = ttk.Frame(canvas)
                toggle_btn = ttk.Button(
                    header_frame,
                    text="▶",
                    width=2,
                    command=lambda section=section_name: toggle_object_section(section),
                )
                toggle_btn.pack(side="left", padx=(6, 4))

                label = ttk.Label(header_frame, text=section_name, font=("Segoe UI", 9, "bold"), cursor="hand2")
                label.pack(side="left", padx=(2, 8))
                label.bind("<Button-1>", lambda _e, section=section_name: toggle_object_section(section))

                entry = ttk.Entry(header_frame, textvariable=object_section_filters[section_name], width=24)
                entry.pack(side="left", padx=(0, 8))

                ttk.Button(
                    header_frame,
                    text="Select",
                    width=8,
                    command=lambda section=section_name: set_names_selected(
                        list(object_section_filtered.get(section, [])),
                        True,
                    ),
                ).pack(side="left", padx=(0, 4))
                ttk.Button(
                    header_frame,
                    text="Clear",
                    width=8,
                    command=lambda section=section_name: set_names_selected(
                        list(object_section_filtered.get(section, [])),
                        False,
                    ),
                ).pack(side="left")

                win_id = canvas.create_window(0, 0, anchor="nw", window=header_frame, tags="virt_header")
                object_section_headers[section_name] = {
                    "frame": header_frame,
                    "label": label,
                    "toggle": toggle_btn,
                    "window": win_id,
                }

        def rebuild_object_rows() -> None:
            object_rows.clear()
            object_section_source.clear()
            object_section_filtered.clear()

            source_sections = self._build_selector_sections("objects", filtered_choices)
            source_map = {section_name: names for section_name, names in source_sections}

            for base in object_section_order:
                object_section_source[base] = list(source_map.get(base, []))

            for section_name, names in source_sections:
                if section_name not in object_section_source:
                    object_section_source[section_name] = list(names)

            ensure_object_section_headers()

            y = 0
            sections = [name for name in object_section_order if name in object_section_source]
            sections.extend([name for name in object_section_source if name not in object_section_order])

            for section_name in sections:
                section_filter = object_section_filters.get(section_name)
                query = section_filter.get().strip().lower() if section_filter is not None else ""
                filtered_names = [n for n in object_section_source.get(section_name, []) if query in n.lower()]
                object_section_filtered[section_name] = filtered_names

                object_rows.append({"type": "section", "section": section_name, "y1": y, "y2": y + object_header_height})
                y += object_header_height
                if not object_section_collapsed.get(section_name, True):
                    for name in filtered_names:
                        object_rows.append(
                            {
                                "type": "item",
                                "section": section_name,
                                "name": name,
                                "y1": y,
                                "y2": y + object_row_height,
                            }
                        )
                        y += object_row_height

                object_rows.append(
                    {
                        "type": "divider",
                        "section": section_name,
                        "y1": y,
                        "y2": y + object_section_gap,
                    }
                )
                y += object_section_gap

            update_object_section_header_labels()
            width = max(1, canvas.winfo_width())
            canvas.configure(scrollregion=(0, 0, width, max(1, y)))

        def find_object_row_index(canvas_y: float) -> int | None:
            for idx, row in enumerate(object_rows):
                if row["y1"] <= canvas_y < row["y2"]:
                    return idx
            return None

        def render_object_rows() -> None:
            canvas.delete("virt_item")

            if not object_rows:
                canvas.create_text(10, 12, anchor="nw", text="No matches", fill="gray", tags="virt_item")
                return

            y_offset = canvas.canvasy(0)
            height = canvas.winfo_height()
            y_limit = y_offset + height
            width = max(1, canvas.winfo_width())

            for row in object_rows:
                if row["type"] == "section":
                    header = object_section_headers.get(row["section"])
                    if header:
                        canvas.coords(header["window"], 0, row["y1"])
                        canvas.itemconfigure(header["window"], width=width)

            for idx, row in enumerate(object_rows):
                if row["y2"] < y_offset - object_row_height:
                    continue
                if row["y1"] > y_limit + object_row_height:
                    break
                if row["type"] == "divider":
                    canvas.create_rectangle(
                        0,
                        row["y1"],
                        width,
                        row["y2"],
                        fill="#F7F7F7",
                        outline="",
                        tags="virt_item",
                    )
                    continue
                if row["type"] != "item":
                    continue

                y1 = row["y1"]
                y2 = row["y2"]
                name = row["name"]
                is_selected = name in pending
                symbol = "☑" if is_selected else "☐"

                canvas.create_rectangle(0, y1, width, y2, fill="white", outline="#EEEEEE", tags="virt_item")
                canvas.create_text(10, y1 + object_row_height // 2, anchor="w", text=symbol, tags="virt_item")
                canvas.create_text(34, y1 + object_row_height // 2, anchor="w", text=name, tags="virt_item")

                if object_active_index == idx:
                    canvas.create_rectangle(
                        1,
                        y1 + 1,
                        width - 1,
                        y2 - 1,
                        outline="#4A90E2",
                        width=1,
                        tags="virt_item",
                    )

        def focus_next_object_item(current_idx: int | None, delta: int) -> None:
            nonlocal object_active_index
            if not object_rows:
                object_active_index = None
                return

            idx = current_idx if current_idx is not None else (-1 if delta > 0 else len(object_rows))
            while True:
                idx += delta
                if idx < 0 or idx >= len(object_rows):
                    break
                if object_rows[idx]["type"] == "item":
                    object_active_index = idx
                    y1 = object_rows[idx]["y1"]
                    y2 = object_rows[idx]["y2"]
                    top = canvas.canvasy(0)
                    bottom = top + canvas.winfo_height()
                    scroll_h = max(1, canvas.bbox("all")[3] if canvas.bbox("all") else 1)
                    if y1 < top:
                        canvas.yview_moveto(y1 / scroll_h)
                    elif y2 > bottom:
                        canvas.yview_moveto(max(0.0, (y2 - canvas.winfo_height()) / scroll_h))
                    render_object_rows()
                    return
            object_active_index = None
            render_object_rows()

        def toggle_active_object_item(_event=None) -> str:
            if object_active_index is None:
                return "break"
            row = object_rows[object_active_index]
            if row["type"] != "item":
                return "break"
            name = row["name"]
            selected_now = name not in pending
            on_toggle_choice(name, selected_now)
            return "break"

        def on_object_canvas_click(event) -> str:
            nonlocal object_active_index
            idx = find_object_row_index(canvas.canvasy(event.y))
            if idx is None:
                return "break"

            row = object_rows[idx]
            if row["type"] == "section":
                toggle_object_section(row["section"])
                return "break"
            if row["type"] != "item":
                object_active_index = idx
                render_object_rows()
                return "break"

            object_active_index = idx
            value = row["name"]
            selected_now = value not in pending
            on_toggle_choice(value, selected_now)
            return "break"

        def focus_first_checkbox(_event=None) -> str:
            if kind == "objects":
                canvas.focus_set()
                focus_next_object_item(None, 1)
                return "break"
            if checkbox_widgets:
                checkbox_widgets[0].focus_set()
            return "break"

        def apply_and_close(_event=None) -> str:
            if not pending:
                error_label.configure(text=f"Select at least one {kind[:-1]}.")
                return "break"
            self._apply_selection()
            popup.destroy()
            return "break"

        def cancel_and_close(_event=None) -> str:
            if kind == "users":
                self._pending_user_selection = set(self._applied_user_selection)
            else:
                self._pending_object_selection = set(self._applied_object_selection)
            self._update_selector_button_labels()
            popup.destroy()
            return "break"

        action_row = ttk.Frame(frame)
        action_row.pack(fill="x", pady=(8, 0))
        ttk.Button(
            action_row,
            text="Select All",
            command=lambda: set_names_selected(list(filtered_choices), True),
        ).pack(side="left")
        ttk.Button(
            action_row,
            text="Deselect All",
            command=lambda: set_names_selected(list(filtered_choices), False),
        ).pack(side="left", padx=(6, 0))

        apply_btn = ttk.Button(action_row, text="Apply", command=apply_and_close)
        apply_btn.pack(side="right")
        ttk.Button(action_row, text="Cancel", command=cancel_and_close).pack(side="right", padx=(0, 6))

        if kind == "objects":
            scrollbar.configure(command=lambda *args: (canvas.yview(*args), render_object_rows()))
            canvas.bind("<Button-1>", on_object_canvas_click)
            canvas.bind("<Up>", lambda _e: (focus_next_object_item(object_active_index, -1), "break")[1])
            canvas.bind("<Down>", lambda _e: (focus_next_object_item(object_active_index, 1), "break")[1])
            canvas.bind("<Return>", toggle_active_object_item)
            canvas.bind("<space>", toggle_active_object_item)
        else:
            scrollbar.configure(command=canvas.yview)

        popup.bind("<Escape>", cancel_and_close)
        popup.bind("<Return>", apply_and_close)
        popup.protocol("WM_DELETE_WINDOW", cancel_and_close)

        if kind == "users":
            draw_current_user_list()
        else:
            rebuild_object_rows()
            render_object_rows()
        update_apply_button_state()
        popup.update_idletasks()
        popup.geometry(f"620x520+{opener.winfo_rootx()}+{opener.winfo_rooty() + opener.winfo_height() + 4}")
        if kind == "objects":
            canvas.focus_set()

    def _apply_selection(self) -> None:
        """Apply pending user/object selections to the matrix projection."""
        self._applied_user_selection = set(self._pending_user_selection)
        self._applied_object_selection = set(self._pending_object_selection)
        self._user_page_index = 0
        self._object_page_index = 0
        self._selection_error_label.configure(text="")
        self._update_selector_button_labels()
        self._apply_filters()

    def _clear_selection(self) -> None:
        """Clear both pending and applied selections."""
        self._pending_user_selection.clear()
        self._pending_object_selection.clear()
        self._applied_user_selection.clear()
        self._applied_object_selection.clear()
        self._user_page_index = 0
        self._object_page_index = 0
        self._selection_error_label.configure(text="")
        self._update_selector_button_labels()
        self._apply_filters()

    def _update_selector_button_labels(self) -> None:
        """Update dropdown button labels to reflect pending selections."""
        users_count = len(self._pending_user_selection)
        objects_count = len(self._pending_object_selection)
        self._users_selector_btn.configure(text=f"Users ({users_count} selected)")
        self._objects_selector_btn.configure(text=f"Objects ({objects_count} selected)")

    def _prev_user_page(self) -> None:
        """Go to previous users page in displayed matrix."""
        if self._user_page_index > 0:
            self._user_page_index -= 1
            self._apply_filters()

    def _next_user_page(self) -> None:
        """Go to next users page in displayed matrix."""
        if not self._selected_users_ordered:
            return
        max_page = max(0, (len(self._selected_users_ordered) - 1) // self._display_users_per_page)
        if self._user_page_index < max_page:
            self._user_page_index += 1
            self._apply_filters()

    def _prev_object_page(self) -> None:
        """Go to previous objects page in displayed matrix."""
        if self._object_page_index > 0:
            self._object_page_index -= 1
            self._apply_filters()

    def _next_object_page(self) -> None:
        """Go to next objects page in displayed matrix."""
        if not self._selected_objects_ordered:
            return
        max_page = max(0, (len(self._selected_objects_ordered) - 1) // self._display_objects_per_page)
        if self._object_page_index < max_page:
            self._object_page_index += 1
            self._apply_filters()

    def _update_display_pagination_labels(self) -> None:
        """Update top and bottom pagination controls for users and objects."""
        users_total = len(self._selected_users_ordered)
        objects_total = len(self._selected_objects_ordered)

        user_max_page = max(0, (users_total - 1) // self._display_users_per_page) if users_total else 0
        object_max_page = (
            max(0, (objects_total - 1) // self._display_objects_per_page) if objects_total else 0
        )

        def user_range() -> str:
            if users_total == 0:
                return "0-0/0"
            start = self._user_page_index * self._display_users_per_page + 1
            end = min(start + self._display_users_per_page - 1, users_total)
            return f"{start}-{end}/{users_total}"

        def object_range() -> str:
            if objects_total == 0:
                return "0-0/0"
            start = self._object_page_index * self._display_objects_per_page + 1
            end = min(start + self._display_objects_per_page - 1, objects_total)
            return f"{start}-{end}/{objects_total}"

        users_text = user_range()
        objects_text = object_range()

        for lbl in (self._users_page_label_top, self._users_page_label_bottom):
            lbl.configure(text=users_text)
        for lbl in (self._objects_page_label_top, self._objects_page_label_bottom):
            lbl.configure(text=objects_text)

        user_prev_state = "normal" if self._user_page_index > 0 else "disabled"
        user_next_state = "normal" if self._user_page_index < user_max_page else "disabled"
        object_prev_state = "normal" if self._object_page_index > 0 else "disabled"
        object_next_state = "normal" if self._object_page_index < object_max_page else "disabled"

        for btn in (self._users_prev_btn_top, self._users_prev_btn_bottom):
            btn.configure(state=user_prev_state)
        for btn in (self._users_next_btn_top, self._users_next_btn_bottom):
            btn.configure(state=user_next_state)
        for btn in (self._objects_prev_btn_top, self._objects_prev_btn_bottom):
            btn.configure(state=object_prev_state)
        for btn in (self._objects_next_btn_top, self._objects_next_btn_bottom):
            btn.configure(state=object_next_state)

    def set_display_page_sizes(self, users_per_page: int, objects_per_page: int) -> None:
        """Set display page sizes (intended to be called from Settings)."""
        if users_per_page in self.PAGE_SIZE_OPTIONS:
            self._display_users_per_page = users_per_page
        if objects_per_page in self.PAGE_SIZE_OPTIONS:
            self._display_objects_per_page = objects_per_page
        self._user_page_index = 0
        self._object_page_index = 0
        self._apply_filters()

    def _on_y_scroll(self, *args) -> None:
        """Handle vertical scroll."""
        self._canvas.yview(*args)
        self._redraw_all()

    def _on_x_scroll(self, *args) -> None:
        """Handle horizontal scroll."""
        self._canvas.xview(*args)
        self._redraw_all()

    def _on_mouse_wheel(self, event) -> None:
        """Handle mouse wheel scroll."""
        shift_pressed = bool(event.state & 0x0001)
        if event.delta == 0:
            return
        delta_units = int(-1 * (event.delta / 120))
        if delta_units == 0:
            delta_units = -1 if event.delta > 0 else 1
        if shift_pressed:
            self._canvas.xview_scroll(delta_units, "units")
        else:
            self._canvas.yview_scroll(delta_units, "units")

        self._redraw_visible()
        self._draw_headers()

    def _on_canvas_resize(self, event) -> None:
        """Handle canvas resize."""
        self._redraw_all()

    def _on_canvas_click(self, event) -> None:
        """Handle canvas click - select cell."""
        header = self._get_header_at(event.x, event.y)
        if header:
            self._on_header_click(header)
            return

        row_header = self._get_user_row_header_at(event.x, event.y)
        if row_header:
            self._on_user_row_header_click(row_header)
            return

        cell = self._get_cell_at(event.x, event.y)
        if cell:
            self._select_cell(cell)

    def _get_header_at(self, x: int, y: int) -> dict | None:
        """Get header metadata at canvas coordinates."""
        if not self._filtered_objects:
            return None

        try:
            cx = self._canvas.canvasx(x)
            cy = self._canvas.canvasy(y)
        except tk.TclError:
            return None

        x_offset = self._canvas.canvasx(0)
        y_offset = self._canvas.canvasy(0)
        total_header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT
        if cy >= y_offset + total_header_height:
            return None

        if cx < x_offset + self.USER_COL_WIDTH:
            return {"type": "user_header"}

        for start_x, end_x, obj_idx, _obj in self._column_spans:
            if start_x <= cx < end_x:
                if cy < y_offset + self.OBJECT_HEADER_HEIGHT:
                    return {"type": "object_header", "obj_idx": obj_idx}
                for col_idx, (mapped_obj_idx, _perm, px) in enumerate(self._column_defs):
                    if mapped_obj_idx != obj_idx:
                        continue
                    if px <= cx < px + self.CELL_WIDTH:
                        return {"type": "perm_header", "obj_idx": obj_idx, "col_idx": col_idx}
        return None

    def _get_user_row_header_at(self, x: int, y: int) -> dict | None:
        """Get row header metadata when clicking the frozen user column."""
        if not self._filtered_users:
            return None

        try:
            cx = self._canvas.canvasx(x)
            cy = self._canvas.canvasy(y)
        except tk.TclError:
            return None

        header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT
        x_offset = self._canvas.canvasx(0)
        y_offset = self._canvas.canvasy(0)
        if cx >= x_offset + self.USER_COL_WIDTH or cy < y_offset + header_height:
            return None

        row = int((cy - (y_offset + header_height)) / self.CELL_HEIGHT)
        if row < 0 or row >= len(self._filtered_users):
            return None

        return {"type": "user_row_header", "row": row}

    def _on_header_click(self, header: dict) -> None:
        """Handle header click for cross-query highlighting."""
        htype = header.get("type")
        if htype == "perm_header":
            perm = self._column_defs[header["col_idx"]][1]
            active = self._active_highlight
            if active and active.get("type") == "permission" and active.get("permission") == perm:
                self._active_highlight = None
            else:
                self._active_highlight = {"type": "permission", "permission": perm}
        elif htype == "object_header":
            obj = self._filtered_objects[header["obj_idx"]]
            active = self._active_highlight
            if active and active.get("type") == "object" and active.get("object") == obj.full_name:
                self._active_highlight = None
            else:
                self._active_highlight = {"type": "object", "object": obj.full_name}
        else:
            return

        self._redraw_all()

    def _on_user_row_header_click(self, header: dict) -> None:
        """Handle row-header click for user-based highlight."""
        user = self._filtered_users[header["row"]]
        active = self._active_highlight
        if active and active.get("type") == "user" and active.get("user") == user.login_name:
            self._active_highlight = None
        else:
            self._active_highlight = {"type": "user", "user": user.login_name}
        self._redraw_all()

    def _clear_highlight(self, event=None) -> str:
        """Clear active cross-query highlight."""
        if self._active_highlight is not None:
            self._active_highlight = None
            self._redraw_all()
            return "break"
        return None

    def _get_state_symbol(self, state: PermissionState, has_staged: bool) -> str:
        """Map permission state to checkbox-like symbol."""
        if state == PermissionState.GRANT:
            symbol = "☑"
        elif state == PermissionState.DENY:
            symbol = "☒"
        else:
            symbol = "☐"
        return symbol

    def _dim_color(self, color: str) -> str:
        """Return a dimmed variant for de-emphasized rows."""
        mapping = {
            self.COLOR_GRANT: "#CDEACD",
            self.COLOR_DENY: "#F4D5DC",
            self.COLOR_NONE: "#F0F0F0",
        }
        return mapping.get(color, color)

    def _cell_matches_highlight(
        self,
        user_login: str,
        object_full_name: str,
        perm: PermissionType,
        committed_state: PermissionState,
    ) -> bool:
        """Check if a cell should be emphasized for the active highlight mode."""
        if not self._active_highlight:
            return True

        if committed_state == PermissionState.NONE:
            return False

        htype = self._active_highlight.get("type")
        if htype == "permission":
            return self._active_highlight.get("permission") == perm
        if htype == "user":
            return self._active_highlight.get("user") == user_login
        if htype == "object":
            return self._active_highlight.get("object") == object_full_name
        return True

    def _row_matches_highlight(self, user_login: str) -> bool:
        """Check if a row has at least one emphasized cell."""
        if not self._active_highlight or not self.matrix:
            return True

        for obj in self._filtered_objects:
            for perm in self._permission_types:
                if not obj.supports_permission(perm):
                    continue
                assignment = self.matrix.get_assignment(
                    user_login,
                    obj.schema_name,
                    obj.object_name,
                    perm,
                )
                if self._cell_matches_highlight(
                    user_login,
                    obj.full_name,
                    perm,
                    assignment.committed_state,
                ):
                    return True
        return False

    def _on_canvas_double_click(self, event) -> None:
        """Handle canvas double-click - toggle cell."""
        cell = self._get_cell_at(event.x, event.y)
        if cell:
            self._select_cell(cell)
            self._toggle_selected_cell()

    def _on_toggle_cell(self, event=None) -> None:
        """Toggle the selected cell."""
        self._toggle_selected_cell()

    def _update_orientation_banner(self) -> None:
        """Update orientation text describing current matrix context."""
        if not self.matrix:
            self._orientation_label.configure(text="Viewing: not connected")
            return
        staged = self.matrix.get_staged_change_count()
        user_count = len(self._filtered_users)
        object_count = len(self._filtered_objects)
        total_users = len(self._selected_users_ordered)
        total_objects = len(self._selected_objects_ordered)

        user_start = self._user_page_index * self._display_users_per_page + 1 if total_users else 0
        user_end = min(user_start + self._display_users_per_page - 1, total_users) if total_users else 0
        object_start = self._object_page_index * self._display_objects_per_page + 1 if total_objects else 0
        object_end = (
            min(object_start + self._display_objects_per_page - 1, total_objects)
            if total_objects
            else 0
        )

        text = (
            f"Viewing: {user_count} selected user(s) × {object_count} selected object(s) | "
            f"{staged} staged change(s) | users {user_start}-{user_end}/{total_users} | "
            f"objects {object_start}-{object_end}/{total_objects}"
        )
        self._orientation_label.configure(text=text)

    def _apply_filters(self) -> None:
        """Project matrix to the applied user/object subset and refresh display."""
        if not self.matrix:
            return

        self._all_users = self.matrix.get_filtered_users()
        self._all_objects = self.matrix.get_filtered_objects()

        available_users = {u.login_name for u in self._all_users}
        available_objects = {o.full_name for o in self._all_objects}
        self._pending_user_selection &= available_users
        self._pending_object_selection &= available_objects
        self._applied_user_selection &= available_users
        self._applied_object_selection &= available_objects
        self._update_selector_button_labels()

        applied_users = self._applied_user_selection
        applied_objects = self._applied_object_selection

        self._selected_users_ordered = sorted([u for u in applied_users if u in available_users], key=str.lower)
        self._selected_objects_ordered = sorted(
            [o for o in applied_objects if o in available_objects],
            key=str.lower,
        )

        if not self._selected_users_ordered or not self._selected_objects_ordered:
            self._filtered_users = []
            self._filtered_objects = []
            self._selection_error_label.configure(text="Select users and objects from the dialogs.")
        else:
            self._selection_error_label.configure(text="")
            max_user_page = max(
                0,
                (len(self._selected_users_ordered) - 1) // self._display_users_per_page,
            )
            max_object_page = max(
                0,
                (len(self._selected_objects_ordered) - 1) // self._display_objects_per_page,
            )
            self._user_page_index = min(self._user_page_index, max_user_page)
            self._object_page_index = min(self._object_page_index, max_object_page)

            user_start = self._user_page_index * self._display_users_per_page
            user_end = user_start + self._display_users_per_page
            object_start = self._object_page_index * self._display_objects_per_page
            object_end = object_start + self._display_objects_per_page

            users_page_set = set(self._selected_users_ordered[user_start:user_end])
            objects_page_set = set(self._selected_objects_ordered[object_start:object_end])

            self._filtered_users = [u for u in self._all_users if u.login_name in users_page_set]
            self._filtered_objects = [o for o in self._all_objects if o.full_name in objects_page_set]

        # Check performance and show warning
        perf_info = self.matrix.get_performance_info()
        if perf_info.is_large and perf_info.warning_message:
            self._warning_label.configure(text=perf_info.warning_message)
        else:
            self._warning_label.configure(text="")

        self._rebuild_column_layout()
        self._update_display_pagination_labels()
        self._update_scroll_region()
        self._redraw_all()
        self._update_orientation_banner()

    def refresh_data(self) -> None:
        """Refresh data from the matrix service."""
        if not self.matrix:
            self._show_placeholder(True)
            return

        self._show_placeholder(False)
        self.matrix.refresh()
        self._apply_filters()
        self._update_changes_count()

    def refresh(self) -> None:
        """Alias for refresh_data() for API consistency."""
        self.refresh_data()

    def _show_placeholder(self, show: bool, text: str | None = None) -> None:
        """Show or hide the placeholder text."""
        if text is not None:
            self._canvas.itemconfigure(self._placeholder_text, text=text)
        if show:
            self._canvas.itemconfigure(self._placeholder_text, state="normal")
        else:
            self._canvas.itemconfigure(self._placeholder_text, state="hidden")

    def _rebuild_column_layout(self) -> None:
        """Build column definitions for visible object-permission cells."""
        self._column_spans = []
        self._column_defs = []
        x = self.USER_COL_WIDTH
        for obj_idx, obj in enumerate(self._filtered_objects):
            supported_perms = [p for p in self._permission_types if obj.supports_permission(p)]
            if not supported_perms:
                continue

            start_x = x
            for perm in supported_perms:
                self._column_defs.append((obj_idx, perm, x))
                x += self.CELL_WIDTH
            end_x = x
            self._column_spans.append((start_x, end_x, obj_idx, obj))
            x += self.OBJECT_GAP

    def _column_key_to_index(self, obj_idx: int, perm: PermissionType) -> int | None:
        """Get display column index for an object-permission pair."""
        for idx, (mapped_obj_idx, mapped_perm, _x) in enumerate(self._column_defs):
            if mapped_obj_idx == obj_idx and mapped_perm == perm:
                return idx
        return None

    def _update_scroll_region(self) -> None:
        """Update the canvas scroll region."""
        if not self._filtered_users or not self._filtered_objects:
            self._canvas.configure(scrollregion=(0, 0, 800, 600))
            return

        if not self._column_defs:
            self._rebuild_column_layout()

        last_col_end = self.USER_COL_WIDTH
        if self._column_defs:
            last_col_end = self._column_defs[-1][2] + self.CELL_WIDTH
        total_width = last_col_end + self.OBJECT_GAP
        total_height = (
            self.OBJECT_HEADER_HEIGHT
            + self.PERMISSION_HEADER_HEIGHT
            + len(self._filtered_users) * self.CELL_HEIGHT
        )

        self._canvas.configure(scrollregion=(0, 0, total_width, total_height))

    def _redraw_all(self) -> None:
        """Redraw the entire matrix."""
        # Clear existing items
        self._canvas.delete("cell")
        self._canvas.delete("header")
        self._canvas.delete("text")
        self._cell_items.clear()
        self._text_items.clear()

        if not self._filtered_users or not self._filtered_objects:
            self._show_placeholder(
                True,
                "Select users and objects to build the matrix.\n\n"
                "Use the selectors above, then apply inside each dialog.",
            )
            return

        self._show_placeholder(False)
        self._draw_headers()
        self._redraw_visible()

    def _draw_headers(self) -> None:
        """Draw the header row and column."""
        if not self._column_defs:
            self._rebuild_column_layout()

        y_offset = self._canvas.canvasy(0)
        x_offset = self._canvas.canvasx(0)

        # User column header
        self._canvas.create_rectangle(
            x_offset,
            y_offset,
            x_offset + self.USER_COL_WIDTH,
            y_offset + self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT,
            fill=self.COLOR_HEADER_BG,
            outline="gray",
            tags="header",
        )
        self._canvas.create_text(
            x_offset + self.USER_COL_WIDTH // 2,
            y_offset + (self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT) // 2,
            text="User",
            font=("Segoe UI", 10, "bold"),
            tags="header",
        )

        # Object headers
        for start_x, end_x, obj_idx, obj in self._column_spans:
            obj_width = end_x - start_x

            # Object name header
            object_highlighted = (
                self._active_highlight
                and self._active_highlight.get("type") == "object"
                and self._active_highlight.get("object") == obj.full_name
            )
            self._canvas.create_rectangle(
                start_x,
                y_offset,
                end_x,
                y_offset + self.OBJECT_HEADER_HEIGHT,
                fill="#DDEEFF" if object_highlighted else self.COLOR_HEADER_BG,
                outline="gray",
                tags="header",
            )
            self._canvas.create_text(
                start_x + obj_width // 2,
                y_offset + self.OBJECT_HEADER_HEIGHT // 2,
                text=obj.full_name,
                font=("Segoe UI", 8),
                width=obj_width - 4,
                tags="header",
            )

            # Permission type headers
            for mapped_obj_idx, perm, px in self._column_defs:
                if mapped_obj_idx != obj_idx:
                    continue
                perm_highlighted = (
                    self._active_highlight
                    and self._active_highlight.get("type") == "permission"
                    and self._active_highlight.get("permission") == perm
                )
                header_bg = "#DDEEFF" if perm_highlighted else self.COLOR_HEADER_BG
                self._canvas.create_rectangle(
                    px,
                    y_offset + self.OBJECT_HEADER_HEIGHT,
                    px + self.CELL_WIDTH,
                    y_offset + self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT,
                    fill=header_bg,
                    outline="gray",
                    tags="header",
                )
                self._canvas.create_text(
                    px + self.CELL_WIDTH // 2,
                    y_offset + self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT // 2,
                    text=perm.value,
                    angle=90,
                    font=("Segoe UI", 8),
                    tags="header",
                )

    def _redraw_visible(self) -> None:
        """Redraw only the visible cells with optimized batching."""
        if not self._filtered_users or not self._filtered_objects or not self.matrix:
            return

        # Get viewport bounds
        canvas_width = self._canvas.winfo_width()
        canvas_height = self._canvas.winfo_height()

        # Calculate visible range
        header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT

        try:
            x_offset = self._canvas.canvasx(0)
            y_offset = self._canvas.canvasy(0)
        except tk.TclError:
            return

        # Visible rows with buffer
        first_row = max(0, int((y_offset - header_height) / self.CELL_HEIGHT) - self.BUFFER_ROWS)
        last_row = min(
            len(self._filtered_users),
            int((y_offset + canvas_height - header_height) / self.CELL_HEIGHT) + self.BUFFER_ROWS,
        )

        # Batch updates to reduce canvas redraws
        rendered_cells = set()

        # Draw user names and cells for visible rows
        for row_idx in range(first_row, last_row):
            user = self._filtered_users[row_idx]
            y = header_height + row_idx * self.CELL_HEIGHT
            row_highlight_match = self._row_matches_highlight(user.login_name)
            x_offset = self._canvas.canvasx(0)

            # User name cell
            user_key = ("user", row_idx)
            if user_key not in self._cell_items:
                rect = self._canvas.create_rectangle(
                    x_offset,
                    y,
                    x_offset + self.USER_COL_WIDTH,
                    y + self.CELL_HEIGHT,
                    fill=self.COLOR_HEADER_BG,
                    outline="gray",
                    tags="cell",
                )
                text = self._canvas.create_text(
                    x_offset + 5,
                    y + self.CELL_HEIGHT // 2,
                    text=user.login_name,
                    anchor="w",
                    font=("Segoe UI", 9),
                    tags="text",
                )
                self._cell_items[user_key] = rect
                self._text_items[user_key] = text
            else:
                # User row already exists, just ensure visibility
                rendered_cells.add(user_key)
                self._canvas.coords(
                    self._cell_items[user_key],
                    x_offset,
                    y,
                    x_offset + self.USER_COL_WIDTH,
                    y + self.CELL_HEIGHT,
                )
                if user_key in self._text_items:
                    self._canvas.coords(self._text_items[user_key], x_offset + 5, y + self.CELL_HEIGHT // 2)

            user_row_bg = self.COLOR_HEADER_BG if row_highlight_match else "#ECECEC"
            self._canvas.itemconfigure(self._cell_items[user_key], fill=user_row_bg)

            # Permission cells
            for col_idx, (obj_idx, perm, px) in enumerate(self._column_defs):
                obj = self._filtered_objects[obj_idx]
                cell_key = (row_idx, col_idx)
                rendered_cells.add(cell_key)

                # Get cell state
                assignment = self.matrix.get_assignment(
                    user.login_name,
                    obj.schema_name,
                    obj.object_name,
                    perm,
                )

                if assignment:
                    state = assignment.effective_state
                    has_staged = assignment.has_pending_change
                else:
                    state = PermissionState.NONE
                    has_staged = False

                committed_state = assignment.committed_state if assignment else PermissionState.NONE
                cell_highlight_match = self._cell_matches_highlight(
                    user.login_name,
                    obj.full_name,
                    perm,
                    committed_state,
                )

                # Determine color
                if state == PermissionState.GRANT:
                    color = self.COLOR_GRANT
                elif state == PermissionState.DENY:
                    color = self.COLOR_DENY
                else:
                    color = self.COLOR_NONE

                if not cell_highlight_match:
                    color = self._dim_color(color)

                outline = self.COLOR_STAGED_BORDER if has_staged else "gray"
                outline_width = 2 if has_staged else 1
                symbol = self._get_state_symbol(state, has_staged)

                # Create or update cell
                if cell_key not in self._cell_items:
                    rect = self._canvas.create_rectangle(
                        px,
                        y,
                        px + self.CELL_WIDTH,
                        y + self.CELL_HEIGHT,
                        fill=color,
                        outline=outline,
                        width=outline_width,
                        tags="cell",
                    )
                    txt = self._canvas.create_text(
                        px + self.CELL_WIDTH // 2,
                        y + self.CELL_HEIGHT // 2,
                        text=symbol,
                        font=("Segoe UI", 9, "bold"),
                        fill="#1f1f1f",
                        tags="text",
                    )
                    self._cell_items[cell_key] = rect
                    self._text_items[cell_key] = txt
                else:
                    # Update existing cell properties
                    self._canvas.itemconfigure(
                        self._cell_items[cell_key],
                        fill=color,
                        outline=outline,
                        width=outline_width,
                    )
                    if cell_key in self._text_items:
                        self._canvas.itemconfigure(self._text_items[cell_key], text=symbol)
                        self._canvas.coords(
                            self._text_items[cell_key],
                            px + self.CELL_WIDTH // 2,
                            y + self.CELL_HEIGHT // 2,
                        )

        # Prune cells outside viewport to free canvas memory
        # (Keep a small buffer of rendered cells to avoid constant creation/deletion)
        cells_to_delete = [k for k in self._cell_items if k not in rendered_cells and k[0] != "user"]
        if len(cells_to_delete) > 100:  # Only prune if many cells exist
            for cell_key in cells_to_delete:
                try:
                    self._canvas.delete(self._cell_items[cell_key])
                    if cell_key in self._text_items:
                        self._canvas.delete(self._text_items[cell_key])
                        del self._text_items[cell_key]
                    del self._cell_items[cell_key]
                except (tk.TclError, KeyError):
                    pass

    def _get_cell_at(self, x: int, y: int) -> tuple | None:
        """Get the cell at canvas coordinates."""
        if not self._filtered_users or not self._filtered_objects:
            return None

        # Convert to canvas coordinates
        try:
            cx = self._canvas.canvasx(x)
            cy = self._canvas.canvasy(y)
        except tk.TclError:
            return None

        x_offset = self._canvas.canvasx(0)
        y_offset = self._canvas.canvasy(0)
        header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT

        # Check if in header area
        if cy < y_offset + header_height or cx < x_offset + self.USER_COL_WIDTH:
            return None

        # Calculate row
        row = int((cy - (y_offset + header_height)) / self.CELL_HEIGHT)
        if row >= len(self._filtered_users):
            return None

        for col_idx, (_obj_idx, _perm, px) in enumerate(self._column_defs):
            if px <= cx < px + self.CELL_WIDTH:
                return (row, col_idx)
        return None

    def _select_cell(self, cell: tuple) -> None:
        """Select a cell."""
        # Deselect previous
        if self._selected_cell and self._selected_cell in self._cell_items:
            # Restore original outline
            self._canvas.itemconfigure(
                self._cell_items[self._selected_cell],
                outline="gray",
                width=1,
            )

        self._selected_cell = cell

        # Highlight new selection
        if cell in self._cell_items:
            self._canvas.itemconfigure(
                self._cell_items[cell],
                outline=self.COLOR_SELECTED,
                width=2,
            )

        self.focus_set()

    def _toggle_selected_cell(self) -> None:
        """Toggle the selected cell's permission state."""
        if not self._selected_cell or not self.matrix:
            return

        row, col_idx = self._selected_cell
        obj_idx, perm, _px = self._column_defs[col_idx]

        user = self._filtered_users[row]
        obj = self._filtered_objects[obj_idx]

        if not obj.supports_permission(perm):
            return

        # Toggle the cell
        assignment = self.matrix.get_assignment(
            user.login_name,
            obj.schema_name,
            obj.object_name,
            perm,
        )

        next_state = assignment.effective_state.next_state()
        if next_state == PermissionState.GRANT:
            privilege_error = self.matrix.validate_grant_privilege(
                obj.schema_name,
                obj.object_name,
                perm,
            )
            if privilege_error:
                # If GRANT is blocked, skip to DENY so toggling still progresses.
                next_state = PermissionState.DENY
                if not self._shown_grant_validation_hint:
                    self._shown_grant_validation_hint = True
                    messagebox.showinfo(
                        "Grant Not Allowed",
                        f"{privilege_error}\n\n"
                        "Bifrost skipped GRANT and applied DENY for this toggle. "
                        "Use a higher-privileged account if GRANT is required.",
                    )

        error = self.matrix.stage_change(
            user.login_name,
            obj.schema_name,
            obj.object_name,
            perm,
            next_state,
        )

        if error:
            print(f"Toggle error: {error}")
            return

        # Update display
        self._update_cell_display(self._selected_cell)
        self._update_changes_count()
        self._update_orientation_banner()

    def _update_cell_display(self, cell: tuple) -> None:
        """Update a single cell's display."""
        if cell not in self._cell_items or not self.matrix:
            return

        row, col_idx = cell
        obj_idx, perm, _px = self._column_defs[col_idx]
        user = self._filtered_users[row]
        obj = self._filtered_objects[obj_idx]

        assignment = self.matrix.get_assignment(
            user.login_name,
            obj.schema_name,
            obj.object_name,
            perm,
        )

        if assignment:
            state = assignment.effective_state
            has_staged = assignment.has_pending_change
        else:
            state = PermissionState.NONE
            has_staged = False

        # Determine color
        if state == PermissionState.GRANT:
            color = self.COLOR_GRANT
        elif state == PermissionState.DENY:
            color = self.COLOR_DENY
        else:
            color = self.COLOR_NONE

        # Update cell
        outline = self.COLOR_STAGED_BORDER if has_staged else self.COLOR_SELECTED
        symbol = self._get_state_symbol(state, has_staged)
        self._canvas.itemconfigure(
            self._cell_items[cell],
            fill=color,
            outline=outline,
            width=2,
        )
        if cell in self._text_items:
            self._canvas.itemconfigure(self._text_items[cell], text=symbol)

    def _move_selection(self, dx: int, dy: int) -> None:
        """Move selection by delta."""
        if not self._selected_cell:
            if self._filtered_users and self._column_defs:
                self._select_cell((0, 0))
            return

        row, col_idx = self._selected_cell
        new_col_idx = col_idx + dx
        new_row = row + dy

        if new_col_idx < 0:
            new_col_idx = 0
        elif new_col_idx >= len(self._column_defs):
            new_col_idx = len(self._column_defs) - 1

        if new_row < 0:
            new_row = 0
        elif new_row >= len(self._filtered_users):
            new_row = len(self._filtered_users) - 1

        self._select_cell((new_row, new_col_idx))

    def _update_changes_count(self) -> None:
        """Update the pending changes count display."""
        if not self.matrix:
            self._changes_label.configure(text="Not connected")
            self._commit_btn.configure(state="disabled")
            self._cancel_btn.configure(state="disabled")
            return

        count = self.matrix.get_staged_change_count()
        if count == 0:
            self._changes_label.configure(text="No pending changes")
            self._commit_btn.configure(state="disabled")
            self._cancel_btn.configure(state="disabled")
        else:
            self._changes_label.configure(text=f"📝 {count} pending change(s)")
            self._commit_btn.configure(state="normal")
            self._cancel_btn.configure(state="normal")
        self._update_orientation_banner()

    def _handle_commit(self) -> None:
        """Handle commit button click."""
        if self.on_commit:
            self.on_commit()

    def _handle_cancel(self) -> None:
        """Handle cancel button click."""
        if self.on_cancel:
            self.on_cancel()

    def set_matrix(self, matrix) -> None:
        """Set the matrix service and refresh display."""
        self.matrix = matrix
        if matrix:
            matrix.set_on_change_callback(self._update_changes_count)
        self.refresh_data()
