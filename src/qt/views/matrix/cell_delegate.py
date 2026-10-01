"""
Painting for the permission grid: group rows, the name column and cells.

Every colour, pen and brush is made once per theme in apply_theme(); paint()
only reads the index and draws. States never rely on colour alone: glyphs for
GRANT/DENY/none, an outline plus a corner dot for staged, a hatch for cells
that don't apply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from src.models.permission import STATE_DENY, STATE_GRANT
from src.qt.theme import tokens
from src.qt.views.matrix.grid_model import OBJECT_BADGES
from src.services.matrix_index import cell_code, diff_mask

if TYPE_CHECKING:
    from PySide6.QtCore import QModelIndex
    from PySide6.QtWidgets import QWidget

    from src.qt.theme import Tokens
    from src.qt.views.matrix.grid_model import GridModel

ROW_PADDING = 8
DOT = 6
INDENT = 16  # item names sit under their group header


class CellDelegate(QStyledItemDelegate):
    """Paints grid cells; see the module docstring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.read_only = False
        self.flash: tuple[QModelIndex, bool] | None = None  # (index, on) during a reveal flash
        self._row_height = 22
        self.apply_theme(tokens())

    def apply_theme(self, t: Tokens) -> None:
        """Create the colours, pens and brushes for a theme."""
        c = QColor
        self.t = t
        self.surface = c(t.surface)
        self.surface_2 = c(t.surface_2)
        self.fg = c(t.fg)
        self.muted = c(t.muted)
        self.grant_bg = c(t.grant_bg)
        self.deny_bg = c(t.deny_bg)
        self.grant_pen = QPen(c(t.grant))
        self.deny_pen = QPen(c(t.deny))
        self.muted_pen = QPen(self.muted)
        self.fg_pen = QPen(self.fg)
        self.na_brush = QBrush(c(t.na))
        self.hatch_brush = QBrush(c(t.line), Qt.BrushStyle.BDiagPattern)
        self.staged_pen = QPen(c(t.staged), 2)
        self.staged_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.staged_brush = QBrush(c(t.staged))
        self.selected_pen = QPen(c(t.accent), 2)
        self.selected_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        self.selected_fill = QColor(t.accent)
        self.selected_fill.setAlpha(40)
        self.focus_pen = QPen(self.fg, 1, Qt.PenStyle.DashLine)
        self.line_pen = QPen(c(t.line_soft))
        self.badge_bg = c(t.surface_2)

    def set_font(self, font: QFont, row_height: int) -> None:
        self.glyph_font = QFont(font)
        self.glyph_font.setBold(True)
        self.group_font = QFont(font)
        self.group_font.setBold(True)
        self.badge_font = QFont(font)
        self.badge_font.setPointSizeF(max(font.pointSizeF() * 0.8, 6))
        self.badge_font.setBold(True)
        self._row_height = row_height

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(52, self._row_height)

    # --- Paint -----------------------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        model: GridModel = index.model()
        g, r = model.locate(index.row())
        painter.save()
        try:
            if r < 0:
                self._paint_group(painter, option, g, model)
                return
            p, o = model.pair(g, r)
            if index.column() == 0:
                self._paint_name(painter, option, model, p, o)
                return
            self._paint_cell(painter, option, model, p, o, index.column() - 1, index)
        finally:
            painter.restore()

    def _paint_group(self, painter: QPainter, option, g: int, model: GridModel) -> None:
        rect = option.rect
        painter.fillRect(rect, self.surface_2)
        painter.setFont(self.group_font)
        painter.setPen(self.fg_pen)
        text_rect = rect.adjusted(6, 0, -4, 0)
        arrow = "▸" if model.is_collapsed(g) else "▾"
        label = f"{arrow}  {model.group_text(g)}"
        text = option.fontMetrics.elidedText(label, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(self.focus_pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _paint_name(self, painter: QPainter, option, model: GridModel, p: int, o: int) -> None:
        rect = option.rect
        if self.read_only:
            painter.setOpacity(0.6)
        painter.fillRect(rect, self.surface)
        ix = model.ix
        if model.mode == "principal":
            obj = ix.objects[o]
            badge = OBJECT_BADGES.get(obj.object_type.value, "?")
            name = obj.object_name
            elide = Qt.TextElideMode.ElideRight
        else:
            user = ix.principals[p]
            badge = user.principal_type
            name = user.login_name
            elide = Qt.TextElideMode.ElideMiddle
        size = rect.height() - 8
        badge_rect = QRect(rect.left() + INDENT + 2, rect.top() + 4, size + 4, size)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.badge_bg)
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setFont(self.badge_font)
        painter.setPen(self.muted_pen)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
        painter.setFont(option.font)
        painter.setPen(self.fg_pen)
        text_rect = rect.adjusted(INDENT + badge_rect.width() + 8, 0, -4, 0)
        if ix.pending_mask(p, o):
            dot = QRect(text_rect.right() - DOT, rect.center().y() - DOT // 2, DOT, DOT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.staged_brush)
            painter.drawEllipse(dot)
            painter.setPen(self.fg_pen)
            text_rect.setRight(dot.left() - 4)
        text = option.fontMetrics.elidedText(name, elide, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setOpacity(1.0)
            painter.setPen(self.focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _paint_cell(self, painter: QPainter, option, model: GridModel, p: int, o: int, perm: int, index) -> None:
        rect = option.rect
        ix = model.ix
        if not ix.object_applicable[o] & (1 << perm):
            painter.fillRect(rect, self.na_brush)
            painter.fillRect(rect, self.hatch_brush)
            return
        if self.read_only:
            painter.setOpacity(0.6)
        packed = ix.row_state(p, o)
        code = cell_code(packed, perm)
        staged = ix.staged.get((p, o))
        pending = staged is not None and diff_mask(staged, ix.committed.get((p, o), 0)) & (1 << perm)
        if code == STATE_GRANT:
            painter.fillRect(rect, self.grant_bg)
            painter.setPen(self.grant_pen)
            glyph = "✓"
        elif code == STATE_DENY:
            painter.fillRect(rect, self.deny_bg)
            painter.setPen(self.deny_pen)
            glyph = "✕"
        else:
            painter.fillRect(rect, self.surface)
            painter.setPen(self.muted_pen)
            glyph = "·"
        painter.setFont(self.glyph_font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)
        painter.setPen(self.line_pen)
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if pending:
            painter.setPen(self.staged_pen)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.staged_brush)
            painter.drawRect(QRect(rect.right() - DOT - 1, rect.top() + 1, DOT, DOT))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        flash_on = self.flash is not None and self.flash[1] and self.flash[0] == index
        if option.state & QStyle.StateFlag.State_Selected or flash_on:
            painter.fillRect(rect, self.selected_fill)
            painter.setPen(self.selected_pen)
            painter.drawRect(rect.adjusted(3, 3, -4, -4))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setOpacity(1.0)
            painter.setPen(self.focus_pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
