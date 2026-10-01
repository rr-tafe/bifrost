"""
Every edit the matrix view makes goes through MatrixEditor.

It enforces, in order: editing allowed (connected, not committing), the
20,000-cell selection limit, FR-030 confirmation for 5 or more changes, and
then hands the items to Session.check_then_stage, which runs the FR-017a grant
check and stages them as one undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from src.qt.dialogs.confirm_bulk import confirm_bulk
from src.qt.views.matrix import bulk

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from PySide6.QtWidgets import QWidget

    from src.models.permission import PermissionState
    from src.qt.session import Session
    from src.qt.views.matrix.bulk import BulkSummary, Item
    from src.services.matrix import CellRef

STATUS_MS = 5_000
LIMIT_MESSAGE = f"Select at most {bulk.SELECTION_LIMIT:,} cells, or use a group action"


class MatrixEditor(QObject):
    """
    Staging front door for the matrix view.

    Attributes:
        suppress_confirm: Set by "Don't ask again"; lasts until Bifrost restarts
        confirm: (sentence, summary) -> (accepted, don't ask again); tests replace it
    """

    def __init__(self, session: Session, widget: QWidget) -> None:
        super().__init__(widget)
        self.session = session
        self.widget = widget
        self.suppress_confirm = False
        self.confirm: Callable[[str, BulkSummary], tuple[bool, bool]] = lambda sentence, summary: confirm_bulk(
            self.widget, sentence, summary
        )

    def _status(self, text: str) -> None:
        self.session.statusMessage.emit(text, STATUS_MS)

    def ensure_editable(self) -> bool:
        """True if editing is allowed; otherwise say why in the status bar."""
        if self.session.can_edit:
            return True
        self._status(self.session.edit_blocked_reason())
        return False

    def set_state(self, cells: Iterable[CellRef], state: PermissionState, label: str | None = None, limited: bool = True) -> bool:
        """Set every cell to state (G / D / R keys, context menu, group actions)."""
        return self.stage(bulk.items_for(cells, state), label, limited)

    def cycle(self, cell: CellRef) -> bool:
        """none -> GRANT -> DENY -> none for one cell (double-click, Space)."""
        if not self.ensure_editable():
            return False
        state = bulk.cycle_state(self.session.matrix.index, cell)
        self.session.check_then_stage([(cell, state)])
        return True

    def revert(self, cells: Iterable[CellRef], limited: bool = True) -> bool:
        """Set cells back to committed (U key)."""
        if not self.ensure_editable():
            return False
        cells = list(cells)
        items = bulk.revert_items(self.session.matrix.index, cells)
        if not self._allowed(items, limited, "Revert to committed"):
            return False
        self.session.revert_cells(cells)
        return True

    def stage(self, items: list[Item], label: str | None = None, limited: bool = True) -> bool:
        """
        Stage items after the limit and confirmation checks.

        Returns:
            bool: True if the items were handed to the session for staging
        """
        if not self.ensure_editable():
            return False
        if not self._allowed(items, limited, label):
            return False
        self.session.check_then_stage(items, label)
        return True

    def _allowed(self, items: list[Item], limited: bool, label: str | None) -> bool:
        if limited and len(items) > bulk.SELECTION_LIMIT:
            self._status(LIMIT_MESSAGE)
            return False
        if not items:
            self._status("Select one or more cells first")
            return False
        index = self.session.matrix.index
        summary = bulk.summarize(index, items)
        if summary.changed == 0:
            self._status("Nothing to change: every selected cell already has that state")
            return False
        if summary.changed >= bulk.CONFIRM_AT and not self.suppress_confirm:
            sentence = label or bulk.describe_action(index, items)
            accepted, dont_ask = self.confirm(sentence, summary)
            if not accepted:
                return False
            if dont_ask:
                self.suppress_confirm = True
        return True
