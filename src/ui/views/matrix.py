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
from collections.abc import Callable
from tkinter import ttk

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
    CELL_WIDTH = 30
    CELL_HEIGHT = 24
    USER_COL_WIDTH = 200
    OBJECT_HEADER_HEIGHT = 60
    PERMISSION_HEADER_HEIGHT = 24

    # Buffer for virtual scrolling
    BUFFER_ROWS = 5
    BUFFER_COLS = 10

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

        # Viewport state
        self._scroll_x = 0
        self._scroll_y = 0
        self._selected_cell: tuple | None = None

        # Canvas items cache
        self._cell_items: dict[tuple, int] = {}
        self._text_items: dict[tuple, int] = {}

        self._create_layout()
        self._bind_events()

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
        """Create the filter bar."""
        filter_frame = ttk.Frame(self)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        # Search
        ttk.Label(filter_frame, text="Search:").pack(side="left", padx=(0, 5))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_changed)
        self._search_entry = ttk.Entry(filter_frame, textvariable=self._search_var, width=30)
        self._search_entry.pack(side="left", padx=5)

        # Object type filter
        ttk.Label(filter_frame, text="Type:").pack(side="left", padx=(20, 5))
        self._type_var = tk.StringVar(value="All")
        self._type_combo = ttk.Combobox(
            filter_frame,
            textvariable=self._type_var,
            values=["All", "TABLE", "VIEW", "PROCEDURE", "FUNCTION"],
            state="readonly",
            width=12,
        )
        self._type_combo.pack(side="left", padx=5)
        self._type_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)

        # Show staged only checkbox
        self._staged_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_frame,
            text="Show staged changes only",
            variable=self._staged_only_var,
            command=self._on_filter_changed,
        ).pack(side="left", padx=20)

        # Refresh button
        ttk.Button(
            filter_frame,
            text="🔄 Refresh",
            command=self.refresh_data,
        ).pack(side="right", padx=5)

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
            "Go to Settings (Ctrl+4) to configure your connection.",
            font=("Segoe UI", 12),
            fill="gray",
            justify="center",
        )

    def _create_action_bar(self) -> None:
        """Create the action bar."""
        action_frame = ttk.Frame(self)
        action_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        # Changes count
        self._changes_label = ttk.Label(
            action_frame,
            text="No pending changes",
            font=("Segoe UI", 10),
        )
        self._changes_label.pack(side="left")

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
        self._canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        # Keyboard
        self.bind("<Return>", self._on_toggle_cell)
        self.bind("<space>", self._on_toggle_cell)
        self.bind("<Up>", lambda e: self._move_selection(0, -1))
        self.bind("<Down>", lambda e: self._move_selection(0, 1))
        self.bind("<Left>", lambda e: self._move_selection(-1, 0))
        self.bind("<Right>", lambda e: self._move_selection(1, 0))

    def _on_y_scroll(self, *args) -> None:
        """Handle vertical scroll."""
        self._canvas.yview(*args)
        self._redraw_visible()

    def _on_x_scroll(self, *args) -> None:
        """Handle horizontal scroll."""
        self._canvas.xview(*args)
        self._redraw_visible()

    def _on_mouse_wheel(self, event) -> None:
        """Handle mouse wheel scroll."""
        # Scroll vertically
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._redraw_visible()

    def _on_canvas_resize(self, event) -> None:
        """Handle canvas resize."""
        self._redraw_visible()

    def _on_canvas_click(self, event) -> None:
        """Handle canvas click - select cell."""
        cell = self._get_cell_at(event.x, event.y)
        if cell:
            self._select_cell(cell)

    def _on_canvas_double_click(self, event) -> None:
        """Handle canvas double-click - toggle cell."""
        cell = self._get_cell_at(event.x, event.y)
        if cell:
            self._select_cell(cell)
            self._toggle_selected_cell()

    def _on_toggle_cell(self, event=None) -> None:
        """Toggle the selected cell."""
        self._toggle_selected_cell()

    def _on_search_changed(self, *args) -> None:
        """Handle search text change."""
        if self.matrix:
            self.matrix.set_search_term(self._search_var.get())
            self._apply_filters()

    def _on_filter_changed(self, event=None) -> None:
        """Handle filter change."""
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Apply current filters and refresh display."""
        if not self.matrix:
            return

        # Apply object type filter
        type_filter = self._type_var.get()
        if type_filter != "All":
            self.matrix.set_filter("object_type", ObjectType(type_filter))
        else:
            self.matrix.clear_filter("object_type")

        # Get filtered data
        self._filtered_users = self.matrix.get_filtered_users()
        self._filtered_objects = self.matrix.get_filtered_objects()

        # Filter to staged only if checked
        if self._staged_only_var.get() and self.matrix.has_staged_changes():
            staged = self.matrix.get_staged_changes()
            staged_users = {c.user_login for c in staged}
            staged_objects = {(c.schema_name, c.object_name) for c in staged}
            self._filtered_users = [u for u in self._filtered_users if u.login_name in staged_users]
            self._filtered_objects = [
                o
                for o in self._filtered_objects
                if (o.schema_name, o.object_name) in staged_objects
            ]

        self._update_scroll_region()
        self._redraw_all()

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

    def _show_placeholder(self, show: bool) -> None:
        """Show or hide the placeholder text."""
        if show:
            self._canvas.itemconfigure(self._placeholder_text, state="normal")
        else:
            self._canvas.itemconfigure(self._placeholder_text, state="hidden")

    def _update_scroll_region(self) -> None:
        """Update the canvas scroll region."""
        if not self._filtered_users or not self._filtered_objects:
            self._canvas.configure(scrollregion=(0, 0, 800, 600))
            return

        # Calculate total size
        total_width = self.USER_COL_WIDTH + len(self._filtered_objects) * len(
            self._permission_types
        ) * self.CELL_WIDTH
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
            return

        self._draw_headers()
        self._redraw_visible()

    def _draw_headers(self) -> None:
        """Draw the header row and column."""
        # User column header
        self._canvas.create_rectangle(
            0,
            0,
            self.USER_COL_WIDTH,
            self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT,
            fill=self.COLOR_HEADER_BG,
            outline="gray",
            tags="header",
        )
        self._canvas.create_text(
            self.USER_COL_WIDTH // 2,
            (self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT) // 2,
            text="User",
            font=("Segoe UI", 10, "bold"),
            tags="header",
        )

        # Object headers
        x = self.USER_COL_WIDTH
        for obj in self._filtered_objects:
            obj_width = len(self._permission_types) * self.CELL_WIDTH

            # Object name header
            self._canvas.create_rectangle(
                x,
                0,
                x + obj_width,
                self.OBJECT_HEADER_HEIGHT,
                fill=self.COLOR_HEADER_BG,
                outline="gray",
                tags="header",
            )
            self._canvas.create_text(
                x + obj_width // 2,
                self.OBJECT_HEADER_HEIGHT // 2,
                text=obj.full_name,
                font=("Segoe UI", 8),
                width=obj_width - 4,
                tags="header",
            )

            # Permission type headers
            for i, perm in enumerate(self._permission_types):
                if not obj.supports_permission(perm):
                    continue

                px = x + i * self.CELL_WIDTH
                self._canvas.create_rectangle(
                    px,
                    self.OBJECT_HEADER_HEIGHT,
                    px + self.CELL_WIDTH,
                    self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT,
                    fill=self.COLOR_HEADER_BG,
                    outline="gray",
                    tags="header",
                )
                self._canvas.create_text(
                    px + self.CELL_WIDTH // 2,
                    self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT // 2,
                    text=perm.value[0],  # First letter
                    font=("Segoe UI", 7),
                    tags="header",
                )

            x += obj_width

    def _redraw_visible(self) -> None:
        """Redraw only the visible cells."""
        if not self._filtered_users or not self._filtered_objects or not self.matrix:
            return

        # Get viewport bounds
        _ = self._canvas.winfo_width()  # For future horizontal culling
        canvas_height = self._canvas.winfo_height()

        # Calculate visible range
        header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT

        try:
            _ = self._canvas.canvasx(0)  # For future horizontal culling
            y_offset = self._canvas.canvasy(0)
        except tk.TclError:
            return

        # Visible rows
        first_row = max(0, int((y_offset - header_height) / self.CELL_HEIGHT) - self.BUFFER_ROWS)
        last_row = min(
            len(self._filtered_users),
            int((y_offset + canvas_height - header_height) / self.CELL_HEIGHT) + self.BUFFER_ROWS,
        )

        # Draw user names and cells for visible rows
        for row_idx in range(first_row, last_row):
            user = self._filtered_users[row_idx]
            y = header_height + row_idx * self.CELL_HEIGHT

            # User name cell
            user_key = ("user", row_idx)
            if user_key not in self._cell_items:
                rect = self._canvas.create_rectangle(
                    0,
                    y,
                    self.USER_COL_WIDTH,
                    y + self.CELL_HEIGHT,
                    fill=self.COLOR_HEADER_BG,
                    outline="gray",
                    tags="cell",
                )
                text = self._canvas.create_text(
                    5,
                    y + self.CELL_HEIGHT // 2,
                    text=user.login_name,
                    anchor="w",
                    font=("Segoe UI", 9),
                    tags="text",
                )
                self._cell_items[user_key] = rect
                self._text_items[user_key] = text

            # Permission cells
            x = self.USER_COL_WIDTH
            for obj_idx, obj in enumerate(self._filtered_objects):
                for perm_idx, perm in enumerate(self._permission_types):
                    if not obj.supports_permission(perm):
                        continue

                    cell_key = (row_idx, obj_idx, perm_idx)
                    px = x + perm_idx * self.CELL_WIDTH

                    # Skip if already drawn
                    if cell_key in self._cell_items:
                        continue

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

                    # Determine color
                    if state == PermissionState.GRANT:
                        color = self.COLOR_GRANT
                    elif state == PermissionState.DENY:
                        color = self.COLOR_DENY
                    else:
                        color = self.COLOR_NONE

                    outline = self.COLOR_STAGED_BORDER if has_staged else "gray"
                    outline_width = 2 if has_staged else 1

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
                    self._cell_items[cell_key] = rect

                x += len(self._permission_types) * self.CELL_WIDTH

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

        header_height = self.OBJECT_HEADER_HEIGHT + self.PERMISSION_HEADER_HEIGHT

        # Check if in header area
        if cy < header_height or cx < self.USER_COL_WIDTH:
            return None

        # Calculate row
        row = int((cy - header_height) / self.CELL_HEIGHT)
        if row >= len(self._filtered_users):
            return None

        # Calculate column
        cell_x = cx - self.USER_COL_WIDTH
        col = int(cell_x / self.CELL_WIDTH)

        # Find object and permission
        obj_idx = col // len(self._permission_types)
        perm_idx = col % len(self._permission_types)

        if obj_idx >= len(self._filtered_objects):
            return None

        return (row, obj_idx, perm_idx)

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

        row, obj_idx, perm_idx = self._selected_cell

        user = self._filtered_users[row]
        obj = self._filtered_objects[obj_idx]
        perm = self._permission_types[perm_idx]

        if not obj.supports_permission(perm):
            return

        # Toggle the cell
        error = self.matrix.toggle_cell(
            user.login_name,
            obj.schema_name,
            obj.object_name,
            perm,
        )

        if error:
            print(f"Toggle error: {error}")
            return

        # Update display
        self._update_cell_display(self._selected_cell)
        self._update_changes_count()

    def _update_cell_display(self, cell: tuple) -> None:
        """Update a single cell's display."""
        if cell not in self._cell_items or not self.matrix:
            return

        row, obj_idx, perm_idx = cell
        user = self._filtered_users[row]
        obj = self._filtered_objects[obj_idx]
        perm = self._permission_types[perm_idx]

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
        self._canvas.itemconfigure(
            self._cell_items[cell],
            fill=color,
            outline=outline,
            width=2,
        )

    def _move_selection(self, dx: int, dy: int) -> None:
        """Move selection by delta."""
        if not self._selected_cell:
            if self._filtered_users and self._filtered_objects:
                self._select_cell((0, 0, 0))
            return

        row, obj_idx, perm_idx = self._selected_cell

        # Move within permissions first
        new_perm_idx = perm_idx + dx
        new_obj_idx = obj_idx
        new_row = row + dy

        # Wrap permissions
        if new_perm_idx < 0:
            new_perm_idx = len(self._permission_types) - 1
            new_obj_idx -= 1
        elif new_perm_idx >= len(self._permission_types):
            new_perm_idx = 0
            new_obj_idx += 1

        # Bounds check
        if new_obj_idx < 0:
            new_obj_idx = 0
            new_perm_idx = 0
        elif new_obj_idx >= len(self._filtered_objects):
            new_obj_idx = len(self._filtered_objects) - 1
            new_perm_idx = len(self._permission_types) - 1

        if new_row < 0:
            new_row = 0
        elif new_row >= len(self._filtered_users):
            new_row = len(self._filtered_users) - 1

        self._select_cell((new_row, new_obj_idx, new_perm_idx))

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
