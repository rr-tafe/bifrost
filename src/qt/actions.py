"""
Every command in the Qt UI.

ActionRegistry creates each QAction once. Menus, the toolbar, the status bar and
the keyboard shortcuts dialog all use these, so a command has one shortcut, one
enabled state and one accessible name everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence


@dataclass(frozen=True)
class ActionSpec:
    """Definition of one command."""

    key: str
    text: str
    menu: str
    shortcuts: tuple[str, ...] = ()
    tip: str = ""
    standard: QKeySequence.StandardKey | None = None


# Menu order and contents. "-" entries are separators.
MENUS: dict[str, list[str]] = {
    "File": ["settings", "disconnect", "-", "export_permissions", "export_audit", "-", "exit"],
    # Discard has no menu item or shortcut on purpose: only the status bar Discard button
    # can throw away staged changes, so a stray keypress never can.
    "Edit": ["undo", "redo", "-", "commit", "-", "toggle_pending"],
    "View": ["view_matrix", "view_audit", "-", "mode_principal", "mode_object", "-", "refresh", "jump", "-", "tags"],
    "Help": ["shortcuts", "db_summary", "about"],
}

SPECS: list[ActionSpec] = [
    ActionSpec("settings", "Connection &settings…", "File", ("Ctrl+,", "Ctrl+O"), "Change the server and database"),
    ActionSpec("disconnect", "&Disconnect", "File", (), "Close the database connection; staged changes are kept"),
    ActionSpec("export_permissions", "Export &permissions…", "File", ("Ctrl+E",), "Save the permission matrix as CSV"),
    ActionSpec("export_audit", "Export &audit log…", "File", ("Ctrl+Shift+E",), "Save the audit log as CSV"),
    ActionSpec("exit", "E&xit", "File", (), "Close Bifrost", QKeySequence.StandardKey.Quit),
    ActionSpec("undo", "&Undo", "Edit", ("Ctrl+Z",), "Undo the last change"),
    ActionSpec("redo", "&Redo", "Edit", ("Ctrl+Y", "Ctrl+Shift+Z"), "Redo the last undone change"),
    ActionSpec("commit", "&Commit changes…", "Edit", ("Ctrl+S", "Ctrl+Return"), "Apply staged changes to the database"),
    ActionSpec("toggle_pending", "Show &pending changes", "Edit", ("Ctrl+Shift+P",), "Show or hide the pending changes list"),
    ActionSpec("view_matrix", "&Matrix", "View", ("Ctrl+1",), "Show the permission matrix"),
    ActionSpec("view_audit", "&Audit log", "View", ("Ctrl+3",), "Show the audit log"),
    ActionSpec("refresh", "&Refresh", "View", ("F5",), "Reload permissions from the database"),
    ActionSpec("mode_principal", "By &principal", "View", ("Ctrl+Shift+1",), "Show one principal's permissions on every object"),
    ActionSpec("mode_object", "By &object", "View", ("Ctrl+Shift+2",), "Show every principal's permissions on one object"),
    ActionSpec("jump", "&Jump to…", "View", ("Ctrl+K",), "Jump to a principal, object or tag"),
    ActionSpec("tags", "&Tags…", "View", ("Ctrl+T",), "Manage tags on principals and objects"),
    ActionSpec("shortcuts", "&Keyboard shortcuts", "Help", ("F1",), "List every keyboard shortcut"),
    ActionSpec("db_summary", "&Database summary", "Help", (), "What was loaded from the database"),
    ActionSpec("about", "&About Bifrost", "Help", (), "Version and diagnostics"),
]

class ActionRegistry(QObject):
    """
    Creates and holds every QAction.

    Attributes:
        actions: key -> QAction
        specs: key -> ActionSpec
        menus: menu name -> action keys in order ("-" = separator)
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}
        self.specs: dict[str, ActionSpec] = {}
        self.menus: dict[str, list[str]] = {menu: list(keys) for menu, keys in MENUS.items()}
        for spec in SPECS:
            action = QAction(spec.text, parent)
            if spec.standard is not None:
                action.setShortcuts(QKeySequence.keyBindings(spec.standard))
            elif spec.shortcuts:
                action.setShortcuts([QKeySequence(s) for s in spec.shortcuts])
            plain = spec.text.replace("&", "").rstrip("…")
            tip = spec.tip or plain
            shortcut_text = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{tip} ({shortcut_text})" if shortcut_text else tip)
            action.setStatusTip(tip)
            action.setObjectName(f"action_{spec.key}")
            self.actions[spec.key] = action
            self.specs[spec.key] = spec

    def __getitem__(self, key: str) -> QAction:
        return self.actions[key]

    def menu_entries(self, menu: str) -> list[QAction | None]:
        """Actions for a menu in order; None marks a separator."""
        return [None if key == "-" else self.actions[key] for key in self.menus[menu]]

    def shortcut_rows(self) -> list[tuple[str, str, str]]:
        """(menu, command, shortcuts) for the keyboard shortcuts dialog."""
        rows = []
        for menu, keys in self.menus.items():
            for key in keys:
                if key == "-":
                    continue
                action = self.actions[key]
                shortcuts = ", ".join(
                    s.toString(QKeySequence.SequenceFormat.NativeText) for s in action.shortcuts()
                )
                rows.append((menu, self.specs[key].text.replace("&", "").rstrip("…"), shortcuts or "—"))
        return rows
