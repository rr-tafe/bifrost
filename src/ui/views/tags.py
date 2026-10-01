"""
Tags view for Bifrost.

This module provides the TagsView class which allows users to manage
custom tags on users and database objects for filtering.

Features:
    - View all tags with usage counts
    - Add/remove tags from users
    - Add/remove tags from objects
    - Rename tags globally
    - Delete unused tags

Usage:
    from src.ui.views.tags import TagsView

    view = TagsView(parent, tag_store, users, objects)
    view.pack(fill="both", expand=True)
"""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from src.services.tags import TagStore
from src.validation import validate_tag


class TagsView(ttk.Frame):
    """
    Tag management view.

    Provides interface for managing tags on users and database objects.

    Attributes:
        tag_store: TagStore service instance
        users: List of DatabaseUser objects
        objects: List of DatabaseObject objects

    Example:
        >>> view = TagsView(
        ...     parent=container,
        ...     tag_store=tag_store,
        ...     users=users,
        ...     objects=objects,
        ... )
    """

    def __init__(
        self,
        parent: tk.Widget,
        tag_store: TagStore | None = None,
        users: list | None = None,
        objects: list | None = None,
    ):
        """
        Initialize the tags view.

        Args:
            parent: Parent widget
            tag_store: TagStore service instance
            users: List of database users
            objects: List of database objects
        """
        super().__init__(parent)

        self.tag_store = tag_store or TagStore()
        self.users = users or []
        self.objects = objects or []

        self._selected_tag: str | None = None

        self._create_layout()
        self._bind_wheel_routing()

    def _create_layout(self) -> None:
        """Create the view layout."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # Left panel: Tag list
        self._create_tag_list_panel()

        # Right panel: Tag details
        self._create_details_panel()

    def _create_tag_list_panel(self) -> None:
        """Create the tag list panel."""
        left_frame = ttk.LabelFrame(self, text="Tags", padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        left_frame.grid_columnconfigure(0, weight=1)
        left_frame.grid_rowconfigure(1, weight=1)

        # Toolbar
        toolbar = ttk.Frame(left_frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ttk.Button(toolbar, text="➕ New Tag", command=self._add_tag).pack(side="left", padx=2)
        ttk.Button(toolbar, text="✏️ Rename", command=self._rename_tag).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🗑️ Delete", command=self._delete_tag).pack(side="left", padx=2)

        # Tag listbox
        list_frame = ttk.Frame(left_frame)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self._tag_listbox = tk.Listbox(list_frame, selectmode="single", font=("Segoe UI", 10))
        self._tag_listbox.grid(row=0, column=0, sticky="nsew")
        self._tag_listbox.bind("<<ListboxSelect>>", self._on_tag_selected)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tag_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tag_listbox.configure(yscrollcommand=scrollbar.set)

        # Tag count
        self._tag_count_label = ttk.Label(left_frame, text="0 tags", foreground="gray")
        self._tag_count_label.grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _create_details_panel(self) -> None:
        """Create the tag details panel."""
        right_frame = ttk.Frame(self, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_rowconfigure(3, weight=1)

        # Tag info
        self._tag_info_label = ttk.Label(
            right_frame,
            text="Select a tag to view details",
            font=("Segoe UI", 12),
        )
        self._tag_info_label.grid(row=0, column=0, sticky="w", pady=(0, 10))

        # Users with tag
        users_frame = ttk.LabelFrame(right_frame, text="Users with this tag", padding=10)
        users_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        users_frame.grid_columnconfigure(0, weight=1)
        users_frame.grid_rowconfigure(0, weight=1)

        self._users_listbox = tk.Listbox(users_frame, selectmode="multiple", font=("Segoe UI", 10))
        self._users_listbox.grid(row=0, column=0, sticky="nsew")

        users_scroll = ttk.Scrollbar(users_frame, orient="vertical", command=self._users_listbox.yview)
        users_scroll.grid(row=0, column=1, sticky="ns")
        self._users_listbox.configure(yscrollcommand=users_scroll.set)

        # User buttons
        users_btn_frame = ttk.Frame(users_frame)
        users_btn_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        ttk.Button(
            users_btn_frame,
            text="Add Users...",
            command=self._add_users_to_tag,
        ).pack(side="left", padx=2)

        ttk.Button(
            users_btn_frame,
            text="Remove Selected",
            command=self._remove_users_from_tag,
        ).pack(side="left", padx=2)

        # Objects with tag
        objects_frame = ttk.LabelFrame(right_frame, text="Objects with this tag", padding=10)
        objects_frame.grid(row=3, column=0, sticky="nsew", pady=5)
        objects_frame.grid_columnconfigure(0, weight=1)
        objects_frame.grid_rowconfigure(0, weight=1)

        self._objects_listbox = tk.Listbox(objects_frame, selectmode="multiple", font=("Segoe UI", 10))
        self._objects_listbox.grid(row=0, column=0, sticky="nsew")

        objects_scroll = ttk.Scrollbar(objects_frame, orient="vertical", command=self._objects_listbox.yview)
        objects_scroll.grid(row=0, column=1, sticky="ns")
        self._objects_listbox.configure(yscrollcommand=objects_scroll.set)

        # Object buttons
        objects_btn_frame = ttk.Frame(objects_frame)
        objects_btn_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0))

        ttk.Button(
            objects_btn_frame,
            text="Add Objects...",
            command=self._add_objects_to_tag,
        ).pack(side="left", padx=2)

        ttk.Button(
            objects_btn_frame,
            text="Remove Selected",
            command=self._remove_objects_from_tag,
        ).pack(side="left", padx=2)

    def _bind_wheel_routing(self) -> None:
        """Route wheel events to listboxes when pointer is over them."""
        self._wheel_widgets = (
            self._tag_listbox,
            self._users_listbox,
            self._objects_listbox,
        )
        toplevel = self.winfo_toplevel()
        toplevel.bind("<MouseWheel>", self._on_global_mouse_wheel, add="+")

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
        """Handle wheel over any listbox in the tags view."""
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            hovered = self.winfo_containing(pointer_x, pointer_y)
        except tk.TclError:
            return None

        if hovered is None:
            return None

        target = None
        for widget in self._wheel_widgets:
            if self._is_descendant_widget(hovered, widget):
                target = widget
                break

        if target is None:
            return None

        if event.delta == 0:
            return "break"

        delta_units = int(-1 * (event.delta / 120))
        if delta_units == 0:
            delta_units = -1 if event.delta > 0 else 1

        if bool(event.state & 0x0001):
            try:
                target.xview_scroll(delta_units, "units")
            except tk.TclError:
                pass
        else:
            target.yview_scroll(delta_units, "units")
        return "break"

    def refresh(self) -> None:
        """Refresh the tag list."""
        self._tag_listbox.delete(0, tk.END)

        all_tags = sorted(self.tag_store.get_all_tags())

        for tag in all_tags:
            user_count = len(self.tag_store.get_users_with_tag(tag))
            obj_count = len(self.tag_store.get_objects_with_tag(tag))
            self._tag_listbox.insert(tk.END, f"{tag} ({user_count}u, {obj_count}o)")

        self._tag_count_label.configure(text=f"{len(all_tags)} tag(s)")

        # Clear details
        self._selected_tag = None
        self._tag_info_label.configure(text="Select a tag to view details")
        self._users_listbox.delete(0, tk.END)
        self._objects_listbox.delete(0, tk.END)

    def _on_tag_selected(self, event) -> None:
        """Handle tag selection."""
        selection = self._tag_listbox.curselection()
        if not selection:
            return

        # Get tag name (strip counts)
        item_text = self._tag_listbox.get(selection[0])
        tag = item_text.split(" (")[0]
        self._selected_tag = tag

        self._tag_info_label.configure(text=f"Tag: {tag}")

        # Show users with this tag
        self._users_listbox.delete(0, tk.END)
        for user in self.tag_store.get_users_with_tag(tag):
            self._users_listbox.insert(tk.END, user)

        # Show objects with this tag
        self._objects_listbox.delete(0, tk.END)
        for obj in self.tag_store.get_objects_with_tag(tag):
            self._objects_listbox.insert(tk.END, obj)

    def _add_tag(self) -> None:
        """Add a new tag."""
        tag = simpledialog.askstring(
            "New Tag",
            "Enter tag name (alphanumeric only):",
            parent=self,
        )

        if not tag:
            return

        errors = validate_tag(tag)
        if errors:
            messagebox.showerror("Invalid Tag", "\n".join(errors))
            return

        # Tag doesn't need to be assigned to anything initially
        messagebox.showinfo("Tag Created", f"Tag '{tag}' created.\n\nAssign it to users or objects using the Add buttons.")
        self.refresh()
        self._select_tag(tag)

    def _rename_tag(self) -> None:
        """Rename the selected tag."""
        if not self._selected_tag:
            messagebox.showwarning("No Selection", "Please select a tag to rename.")
            return

        new_name = simpledialog.askstring(
            "Rename Tag",
            f"Enter new name for '{self._selected_tag}':",
            parent=self,
            initialvalue=self._selected_tag,
        )

        if not new_name or new_name == self._selected_tag:
            return

        errors = validate_tag(new_name)
        if errors:
            messagebox.showerror("Invalid Tag", "\n".join(errors))
            return

        try:
            self.tag_store.rename_tag(self._selected_tag, new_name)
            self._save_tags()
            self.refresh()
            self._select_tag(new_name)
        except ValueError as e:
            messagebox.showerror("Rename Failed", str(e))

    def _delete_tag(self) -> None:
        """Delete the selected tag."""
        if not self._selected_tag:
            messagebox.showwarning("No Selection", "Please select a tag to delete.")
            return

        user_count = len(self.tag_store.get_users_with_tag(self._selected_tag))
        obj_count = len(self.tag_store.get_objects_with_tag(self._selected_tag))

        if user_count > 0 or obj_count > 0:
            confirm = messagebox.askyesno(
                "Confirm Delete",
                f"Tag '{self._selected_tag}' is assigned to {user_count} user(s) and {obj_count} object(s).\n\n"
                "Are you sure you want to delete it?",
            )
            if not confirm:
                return

        # Remove tag from all users and objects
        for user in self.tag_store.get_users_with_tag(self._selected_tag):
            self.tag_store.remove_user_tag(user, self._selected_tag)

        for obj in self.tag_store.get_objects_with_tag(self._selected_tag):
            self.tag_store.remove_object_tag(obj, self._selected_tag)

        self._save_tags()
        self.refresh()

    def _add_users_to_tag(self) -> None:
        """Add users to the selected tag."""
        if not self._selected_tag:
            messagebox.showwarning("No Selection", "Please select a tag first.")
            return

        # Show user selection dialog
        dialog = UserSelectionDialog(self, self.users, self._selected_tag)
        self.wait_window(dialog)

        if dialog.selected_users:
            for user in dialog.selected_users:
                self.tag_store.add_user_tag(user, self._selected_tag)
            self._save_tags()
            self._on_tag_selected(None)

    def _remove_users_from_tag(self) -> None:
        """Remove selected users from the tag."""
        if not self._selected_tag:
            return

        selection = self._users_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select users to remove.")
            return

        for idx in reversed(selection):
            user = self._users_listbox.get(idx)
            self.tag_store.remove_user_tag(user, self._selected_tag)

        self._save_tags()
        self._on_tag_selected(None)
        self.refresh()

    def _add_objects_to_tag(self) -> None:
        """Add objects to the selected tag."""
        if not self._selected_tag:
            messagebox.showwarning("No Selection", "Please select a tag first.")
            return

        # Show object selection dialog
        dialog = ObjectSelectionDialog(self, self.objects, self._selected_tag)
        self.wait_window(dialog)

        if dialog.selected_objects:
            for obj in dialog.selected_objects:
                self.tag_store.add_object_tag(obj, self._selected_tag)
            self._save_tags()
            self._on_tag_selected(None)

    def _remove_objects_from_tag(self) -> None:
        """Remove selected objects from the tag."""
        if not self._selected_tag:
            return

        selection = self._objects_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select objects to remove.")
            return

        for idx in reversed(selection):
            obj = self._objects_listbox.get(idx)
            self.tag_store.remove_object_tag(obj, self._selected_tag)

        self._save_tags()
        self._on_tag_selected(None)
        self.refresh()

    def _select_tag(self, tag: str) -> None:
        """Select a tag in the listbox."""
        for i in range(self._tag_listbox.size()):
            item_text = self._tag_listbox.get(i)
            if item_text.startswith(tag + " ("):
                self._tag_listbox.selection_clear(0, tk.END)
                self._tag_listbox.selection_set(i)
                self._on_tag_selected(None)
                break

    def _save_tags(self) -> None:
        """Save tags to disk."""
        error = self.tag_store.save()
        if error:
            messagebox.showerror("Save Failed", f"Failed to save tags: {error}")

    def set_data(
        self,
        tag_store: TagStore,
        users: list,
        objects: list,
    ) -> None:
        """Update the view with new data."""
        self.tag_store = tag_store
        self.users = users
        self.objects = objects
        self.refresh()


class UserSelectionDialog(tk.Toplevel):
    """Dialog for selecting users to add to a tag."""

    def __init__(self, parent, users, tag):
        super().__init__(parent)

        self.title(f"Add Users to Tag: {tag}")
        self.geometry("400x500")
        self.transient(parent)
        self.grab_set()

        self.users = users
        self.selected_users: list[str] = []

        self._create_layout()
        self._bind_wheel_routing()

    def _create_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Search
        search_frame = ttk.Frame(self, padding=10)
        search_frame.grid(row=0, column=0, sticky="ew")

        ttk.Label(search_frame, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ttk.Entry(search_frame, textvariable=self._search_var).pack(side="left", fill="x", expand=True, padx=5)

        # Listbox
        list_frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self._listbox = tk.Listbox(list_frame, selectmode="multiple")
        self._listbox.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=scrollbar.set)

        self._populate_list()

        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.grid(row=2, column=0, sticky="ew")

        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Add Selected", command=self._add_selected).pack(side="right", padx=5)

    def _populate_list(self, filter_text: str = "") -> None:
        self._listbox.delete(0, tk.END)
        filter_lower = filter_text.lower()

        for user in self.users:
            name = user.login_name if hasattr(user, "login_name") else str(user)
            if filter_lower and filter_lower not in name.lower():
                continue
            self._listbox.insert(tk.END, name)

    def _on_search(self, *args) -> None:
        self._populate_list(self._search_var.get())

    def _add_selected(self) -> None:
        selection = self._listbox.curselection()
        self.selected_users = [self._listbox.get(i) for i in selection]
        self.destroy()

    def _bind_wheel_routing(self) -> None:
        """Route wheel events to the dialog listbox."""
        self.bind("<MouseWheel>", self._on_dialog_mouse_wheel, add="+")

    def _on_dialog_mouse_wheel(self, event) -> str | None:
        """Handle wheel scroll for the user selection list."""
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            hovered = self.winfo_containing(pointer_x, pointer_y)
        except tk.TclError:
            return None

        if hovered is None:
            return None

        current = hovered
        in_listbox = False
        while current is not None:
            if current == self._listbox:
                in_listbox = True
                break
            try:
                parent_path = current.winfo_parent()
            except tk.TclError:
                break
            if not parent_path:
                break
            try:
                current = current.nametowidget(parent_path)
            except (tk.TclError, KeyError):
                break

        if not in_listbox:
            return None

        if event.delta == 0:
            return "break"
        delta_units = int(-1 * (event.delta / 120))
        if delta_units == 0:
            delta_units = -1 if event.delta > 0 else 1

        if bool(event.state & 0x0001):
            try:
                self._listbox.xview_scroll(delta_units, "units")
            except tk.TclError:
                pass
        else:
            self._listbox.yview_scroll(delta_units, "units")
        return "break"


class ObjectSelectionDialog(tk.Toplevel):
    """Dialog for selecting objects to add to a tag."""

    def __init__(self, parent, objects, tag):
        super().__init__(parent)

        self.title(f"Add Objects to Tag: {tag}")
        self.geometry("400x500")
        self.transient(parent)
        self.grab_set()

        self.objects = objects
        self.selected_objects: list[str] = []

        self._create_layout()
        self._bind_wheel_routing()

    def _create_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Search
        search_frame = ttk.Frame(self, padding=10)
        search_frame.grid(row=0, column=0, sticky="ew")

        ttk.Label(search_frame, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        ttk.Entry(search_frame, textvariable=self._search_var).pack(side="left", fill="x", expand=True, padx=5)

        # Listbox
        list_frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self._listbox = tk.Listbox(list_frame, selectmode="multiple")
        self._listbox.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=scrollbar.set)

        self._populate_list()

        # Buttons
        btn_frame = ttk.Frame(self, padding=10)
        btn_frame.grid(row=2, column=0, sticky="ew")

        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=5)
        ttk.Button(btn_frame, text="Add Selected", command=self._add_selected).pack(side="right", padx=5)

    def _populate_list(self, filter_text: str = "") -> None:
        self._listbox.delete(0, tk.END)
        filter_lower = filter_text.lower()

        for obj in self.objects:
            name = obj.full_name if hasattr(obj, "full_name") else str(obj)
            if filter_lower and filter_lower not in name.lower():
                continue
            self._listbox.insert(tk.END, name)

    def _on_search(self, *args) -> None:
        self._populate_list(self._search_var.get())

    def _add_selected(self) -> None:
        selection = self._listbox.curselection()
        self.selected_objects = [self._listbox.get(i) for i in selection]
        self.destroy()

    def _bind_wheel_routing(self) -> None:
        """Route wheel events to the dialog listbox."""
        self.bind("<MouseWheel>", self._on_dialog_mouse_wheel, add="+")

    def _on_dialog_mouse_wheel(self, event) -> str | None:
        """Handle wheel scroll for the object selection list."""
        try:
            pointer_x, pointer_y = self.winfo_pointerxy()
            hovered = self.winfo_containing(pointer_x, pointer_y)
        except tk.TclError:
            return None

        if hovered is None:
            return None

        current = hovered
        in_listbox = False
        while current is not None:
            if current == self._listbox:
                in_listbox = True
                break
            try:
                parent_path = current.winfo_parent()
            except tk.TclError:
                break
            if not parent_path:
                break
            try:
                current = current.nametowidget(parent_path)
            except (tk.TclError, KeyError):
                break

        if not in_listbox:
            return None

        if event.delta == 0:
            return "break"
        delta_units = int(-1 * (event.delta / 120))
        if delta_units == 0:
            delta_units = -1 if event.delta > 0 else 1

        if bool(event.state & 0x0001):
            try:
                self._listbox.xview_scroll(delta_units, "units")
            except tk.TclError:
                pass
        else:
            self._listbox.yview_scroll(delta_units, "units")
        return "break"
