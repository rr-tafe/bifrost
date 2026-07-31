"""
Audit view for Bifrost.

This module provides the AuditView class which displays the audit log
of permission changes with filtering and export capabilities.

Features:
    - Paginated audit log display
    - Filter by user, object, date range
    - Export to CSV
    - Human-readable change explanations

Usage:
    from src.ui.views.audit import AuditView

    view = AuditView(parent, fetch_callback, export_callback)
    view.pack(fill="both", expand=True)
"""

import contextlib
import tkinter as tk
from collections.abc import Callable
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk

from src.models.audit_entry import AuditEntry


class AuditView(ttk.Frame):
    """
    Audit log view with filtering and pagination.

    Displays a table of permission changes with filters and export functionality.

    Attributes:
        on_fetch: Callback to fetch audit entries
        on_export: Callback to export audit log to CSV

    Example:
        >>> view = AuditView(
        ...     parent=container,
        ...     on_fetch=lambda filters: fetch_audit_entries(conn, filters),
        ...     on_export=lambda path, entries: export_audit_csv(path, entries),
        ... )
    """

    PAGE_SIZE = 100

    def __init__(
        self,
        parent: tk.Widget,
        on_fetch: Callable[[dict], list[AuditEntry]] | None = None,
        on_export: Callable[[str, list], str | None] | None = None,
    ):
        """
        Initialize the audit view.

        Args:
            parent: Parent widget
            on_fetch: Callback(filters) -> list[AuditEntry]
            on_export: Callback(path, entries) -> error or None
        """
        super().__init__(parent)

        self.on_fetch = on_fetch
        self.on_export = on_export

        self._entries: list[AuditEntry] = []
        self._current_page = 0
        self._total_pages = 0

        self._create_layout()

    def _create_layout(self) -> None:
        """Create the view layout."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Filter bar
        self._create_filter_bar()

        # Audit table
        self._create_table()

        # Pagination and export bar
        self._create_footer()

    def _create_filter_bar(self) -> None:
        """Create the filter bar."""
        filter_frame = ttk.LabelFrame(self, text="Filters", padding=10)
        filter_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        # Row 1: User and Object filters
        ttk.Label(filter_frame, text="User:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self._user_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._user_var, width=20).grid(
            row=0, column=1, sticky="w", padx=5, pady=2
        )

        ttk.Label(filter_frame, text="Object:").grid(row=0, column=2, sticky="w", padx=5, pady=2)
        self._object_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._object_var, width=30).grid(
            row=0, column=3, sticky="w", padx=5, pady=2
        )

        ttk.Label(filter_frame, text="Action:").grid(row=0, column=4, sticky="w", padx=5, pady=2)
        self._action_var = tk.StringVar(value="All")
        ttk.Combobox(
            filter_frame,
            textvariable=self._action_var,
            values=["All", "GRANT", "DENY", "REVOKE"],
            state="readonly",
            width=10,
        ).grid(row=0, column=5, sticky="w", padx=5, pady=2)

        # Row 2: Date range
        ttk.Label(filter_frame, text="From:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self._from_date_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._from_date_var, width=12).grid(
            row=1, column=1, sticky="w", padx=5, pady=2
        )
        ttk.Label(filter_frame, text="(YYYY-MM-DD)", foreground="gray").grid(
            row=1, column=2, sticky="w", padx=0, pady=2
        )

        ttk.Label(filter_frame, text="To:").grid(row=1, column=3, sticky="w", padx=5, pady=2)
        self._to_date_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self._to_date_var, width=12).grid(
            row=1, column=4, sticky="w", padx=5, pady=2
        )

        # Quick date buttons
        btn_frame = ttk.Frame(filter_frame)
        btn_frame.grid(row=1, column=5, columnspan=2, sticky="w", padx=5, pady=2)

        ttk.Button(btn_frame, text="Today", command=lambda: self._set_date_range(0)).pack(
            side="left", padx=2
        )
        ttk.Button(btn_frame, text="7 Days", command=lambda: self._set_date_range(7)).pack(
            side="left", padx=2
        )
        ttk.Button(btn_frame, text="30 Days", command=lambda: self._set_date_range(30)).pack(
            side="left", padx=2
        )
        ttk.Button(btn_frame, text="Clear", command=self._clear_date_range).pack(
            side="left", padx=2
        )

        # Apply button
        ttk.Button(filter_frame, text="🔍 Apply Filters", command=self.refresh).grid(
            row=0, column=6, rowspan=2, padx=20, pady=5
        )

    def _create_table(self) -> None:
        """Create the audit table."""
        table_frame = ttk.Frame(self)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        # Treeview
        columns = ("timestamp", "admin", "user", "object", "permission", "action", "explanation")
        self._tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        # Column headings
        self._tree.heading("timestamp", text="Timestamp")
        self._tree.heading("admin", text="Administrator")
        self._tree.heading("user", text="User")
        self._tree.heading("object", text="Object")
        self._tree.heading("permission", text="Permission")
        self._tree.heading("action", text="Action")
        self._tree.heading("explanation", text="Explanation")

        # Column widths
        self._tree.column("timestamp", width=150, minwidth=100)
        self._tree.column("admin", width=120, minwidth=80)
        self._tree.column("user", width=100, minwidth=80)
        self._tree.column("object", width=150, minwidth=100)
        self._tree.column("permission", width=100, minwidth=80)
        self._tree.column("action", width=70, minwidth=50)
        self._tree.column("explanation", width=300, minwidth=150)

        self._tree.grid(row=0, column=0, sticky="nsew")

        # Scrollbars
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=v_scroll.set)

        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self._tree.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        self._tree.configure(xscrollcommand=h_scroll.set)

        # Tag colors for actions
        self._tree.tag_configure("grant", foreground="green")
        self._tree.tag_configure("deny", foreground="red")
        self._tree.tag_configure("revoke", foreground="gray")

    def _create_footer(self) -> None:
        """Create the pagination and export bar."""
        footer_frame = ttk.Frame(self)
        footer_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)

        # Entry count
        self._count_label = ttk.Label(footer_frame, text="0 entries")
        self._count_label.pack(side="left")

        # Export button
        ttk.Button(footer_frame, text="📥 Export to CSV", command=self._export).pack(
            side="right", padx=5
        )

        # Pagination
        self._page_frame = ttk.Frame(footer_frame)
        self._page_frame.pack(side="right", padx=20)

        ttk.Button(self._page_frame, text="◀ Prev", command=self._prev_page).pack(side="left", padx=2)
        self._page_label = ttk.Label(self._page_frame, text="Page 1 of 1")
        self._page_label.pack(side="left", padx=10)
        ttk.Button(self._page_frame, text="Next ▶", command=self._next_page).pack(side="left", padx=2)

    def _set_date_range(self, days: int) -> None:
        """Set date range from today minus days."""
        today = datetime.now().date()
        from_date = today - timedelta(days=days)

        self._from_date_var.set(from_date.isoformat())
        self._to_date_var.set(today.isoformat())

    def _clear_date_range(self) -> None:
        """Clear date range filters."""
        self._from_date_var.set("")
        self._to_date_var.set("")

    def _get_filters(self) -> dict:
        """Build filter dictionary from UI state."""
        filters = {}

        if self._user_var.get():
            filters["user"] = self._user_var.get()

        if self._object_var.get():
            filters["object"] = self._object_var.get()

        if self._action_var.get() != "All":
            filters["action"] = self._action_var.get()

        if self._from_date_var.get():
            with contextlib.suppress(ValueError):
                filters["from_date"] = datetime.fromisoformat(self._from_date_var.get())

        if self._to_date_var.get():
            with contextlib.suppress(ValueError):
                filters["to_date"] = datetime.fromisoformat(self._to_date_var.get())

        return filters

    def refresh(self) -> None:
        """Refresh the audit log from the database."""
        if not self.on_fetch:
            self._show_placeholder()
            return

        filters = self._get_filters()
        self._entries = self.on_fetch(filters)
        self._current_page = 0
        self._total_pages = max(1, (len(self._entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

        self._update_table()
        self._update_pagination()

    def _update_table(self) -> None:
        """Update the table with current page entries."""
        # Clear existing items
        self._tree.delete(*self._tree.get_children())

        # Calculate page range
        start = self._current_page * self.PAGE_SIZE
        end = min(start + self.PAGE_SIZE, len(self._entries))

        # Insert entries
        for entry in self._entries[start:end]:
            timestamp = entry.changed_at.strftime("%Y-%m-%d %H:%M:%S") if entry.changed_at else ""
            full_object = f"{entry.schema_name}.{entry.object_name}"

            tag = entry.action.lower() if entry.action in ("GRANT", "DENY", "REVOKE") else ""

            self._tree.insert(
                "",
                "end",
                values=(
                    timestamp,
                    entry.administrator,
                    entry.affected_user,
                    full_object,
                    entry.permission_type,
                    entry.action,
                    entry.explanation,
                ),
                tags=(tag,),
            )

        self._count_label.configure(text=f"{len(self._entries)} entries")

    def _update_pagination(self) -> None:
        """Update pagination controls."""
        self._page_label.configure(text=f"Page {self._current_page + 1} of {self._total_pages}")

    def _prev_page(self) -> None:
        """Go to previous page."""
        if self._current_page > 0:
            self._current_page -= 1
            self._update_table()
            self._update_pagination()

    def _next_page(self) -> None:
        """Go to next page."""
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._update_table()
            self._update_pagination()

    def _export(self) -> None:
        """Export audit log to CSV."""
        if not self._entries:
            messagebox.showinfo("Export", "No entries to export.")
            return

        # Get save path
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"Bifrost_audit_{datetime.now().strftime('%Y-%m-%d')}.csv",
        )

        if not file_path:
            return

        if self.on_export:
            error = self.on_export(file_path, self._entries)
            if error:
                messagebox.showerror("Export Failed", error)
            else:
                messagebox.showinfo("Export Complete", f"Exported {len(self._entries)} entries to:\n{file_path}")
        else:
            # Fallback to direct export
            try:
                from src.services.export import export_audit_csv

                error = export_audit_csv(file_path, self._entries)
                if error:
                    messagebox.showerror("Export Failed", error)
                else:
                    messagebox.showinfo("Export Complete", f"Exported {len(self._entries)} entries to:\n{file_path}")
            except ImportError:
                messagebox.showerror("Export Failed", "Export module not available.")

    def _show_placeholder(self) -> None:
        """Show placeholder when not connected."""
        self._tree.delete(*self._tree.get_children())
        self._count_label.configure(text="Connect to a database to view audit log")

    def set_callbacks(
        self,
        on_fetch: Callable[[dict], list[AuditEntry]] | None = None,
        on_export: Callable[[str, list], str | None] | None = None,
    ) -> None:
        """Set the fetch and export callbacks."""
        self.on_fetch = on_fetch
        self.on_export = on_export
