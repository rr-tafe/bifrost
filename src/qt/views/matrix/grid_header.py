"""
Header above the grid: who or what is shown, counts, tags, the object
description (By object mode) and the grid filters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.models.db_object import ObjectType
from src.qt.views.matrix.chips import ChipButton, MultiSelectChip, Segmented
from src.qt.views.matrix.entity_list import PRINCIPAL_CHIPS, tag_options
from src.qt.views.matrix.grid_model import PRINCIPAL_TYPE_NAMES, GridFilters
from src.qt.widgets.search_field import SearchField

if TYPE_CHECKING:
    from src.qt.session import Session

DESCRIPTION_LINES = 3
SEGMENTS = {
    "principal": (("all", "All objects"), ("access", "Only with access"), ("pending", "Only pending")),
    "object": (("all", "All principals"), ("access", "Only with access"), ("pending", "Only pending")),
}


def _link(text: str, parent: QWidget) -> QToolButton:
    button = QToolButton(parent)
    button.setText(text)
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class GridHeader(QWidget):
    """
    Signals:
        filtersChanged: grid filters changed (read them from .filters)
        tagClicked(str): a tag chip was clicked (add it to the left list's filter)
        tagsRequested: "Tags…" clicked
        makeLikeRequested: "Make like…" clicked
        editDescriptionRequested: "Edit description…" clicked
        refreshListRequested: "Refresh list" on the out-of-date notice
    """

    filtersChanged = Signal()
    tagClicked = Signal(str)
    tagsRequested = Signal()
    makeLikeRequested = Signal()
    editDescriptionRequested = Signal()
    refreshListRequested = Signal()

    def __init__(self, session: Session, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.mode = mode
        self.entity: int | None = None
        self.filters = GridFilters()
        self._description_expanded = False
        principal = mode == "principal"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(4)

        # Title row
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel("", self)
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.2)
        self.title.setFont(font)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.kind = QLabel("", self)
        self.kind.setAccessibleName("Type")
        title_row.addWidget(self.title)
        title_row.addWidget(self.kind)
        self.tag_row = QHBoxLayout()
        self.tag_row.setSpacing(2)
        title_row.addLayout(self.tag_row)
        self.tags_link = _link("Tags…", self)
        self.tags_link.setToolTip("Edit tags in the tag manager")
        self.tags_link.clicked.connect(self.tagsRequested)
        title_row.addWidget(self.tags_link)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        self.counts = QLabel("", self)
        self.counts.setAccessibleName("Counts")
        layout.addWidget(self.counts)

        # Description (By object)
        self.description_box = QWidget(self)
        desc_layout = QHBoxLayout(self.description_box)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        self.description = QLabel("", self.description_box)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.description.setAccessibleName("Description")
        self.more_link = _link("More", self.description_box)
        self.more_link.clicked.connect(self._toggle_description)
        self.edit_description = QPushButton("Edit description…", self.description_box)
        self.edit_description.setToolTip("Descriptions save immediately. They aren't staged or audited.")
        self.edit_description.clicked.connect(self.editDescriptionRequested)
        desc_layout.addWidget(self.description, 1)
        desc_layout.addWidget(self.more_link, 0, Qt.AlignmentFlag.AlignTop)
        desc_layout.addWidget(self.edit_description, 0, Qt.AlignmentFlag.AlignTop)
        self.description_box.setVisible(not principal)
        layout.addWidget(self.description_box)
        self._description_text = ""

        # Filters
        filters = QHBoxLayout()
        filters.setSpacing(4)
        noun = "objects" if principal else "principals"
        self.search = SearchField(f"Filter {noun}…", f"Filter {noun} in the grid", self)
        self.search.searchChanged.connect(self._on_change)
        filters.addWidget(self.search, 2)
        self.schema_chip: MultiSelectChip | None = None
        self.type_chip: MultiSelectChip | None = None
        self.principal_chips: dict[str, ChipButton] = {}
        if principal:
            self.schema_chip = MultiSelectChip("Schema", self)
            self.schema_chip.changed.connect(lambda _k: self._on_change())
            self.type_chip = MultiSelectChip("Type", self)
            self.type_chip.set_options((t.value, t.value.title()) for t in ObjectType)
            self.type_chip.changed.connect(lambda _k: self._on_change())
            filters.addWidget(self.schema_chip)
            filters.addWidget(self.type_chip)
        else:
            for key, text, tip in PRINCIPAL_CHIPS:
                chip = ChipButton(text, text, tip, self)
                chip.toggled.connect(lambda _c: self._on_change())
                self.principal_chips[key] = chip
                filters.addWidget(chip)
        self.tags_chip = MultiSelectChip("Tags", self)
        self.tags_chip.changed.connect(lambda _k: self._on_change())
        filters.addWidget(self.tags_chip)
        filters.addStretch(1)
        layout.addLayout(filters)

        segment_row = QHBoxLayout()
        self.segment = Segmented(SEGMENTS[mode], "Show", self)
        self.segment.changed.connect(lambda _key: self._on_change())
        segment_row.addWidget(self.segment)
        self.stale_link = _link("Filter out of date — Refresh list", self)
        self.stale_link.clicked.connect(self.refreshListRequested)
        self.stale_link.hide()
        segment_row.addWidget(self.stale_link)
        segment_row.addStretch(1)
        self.make_like = QPushButton("Make like…", self)
        self.make_like.setToolTip("Give this principal the same permissions as another principal")
        self.make_like.clicked.connect(self.makeLikeRequested)
        self.make_like.setVisible(principal)
        segment_row.addWidget(self.make_like)
        layout.addLayout(segment_row)

    # --- Entity ---------------------------------------------------------------------------

    def set_entity(self, entity: int | None) -> None:
        self.entity = entity
        self._clear_tags()
        if entity is None or self.session.matrix is None:
            self.title.setText("")
            self.kind.setText("")
            self.counts.setText("")
            self.set_description(None, loading=False)
            return
        ix = self.session.matrix.index
        if self.mode == "principal":
            user = ix.principals[entity]
            self.title.setText(user.login_name)
            self.kind.setText(PRINCIPAL_TYPE_NAMES.get(user.principal_type, user.principal_type))
            tags = user.tags
        else:
            obj = ix.objects[entity]
            self.title.setText(obj.full_name)
            self.kind.setText(obj.object_type.value.title())
            tags = obj.tags
            self.set_description(None, loading=True)
        for tag in tags:
            chip = _link(tag, self)
            chip.setToolTip(f"Show only {'principals' if self.mode == 'principal' else 'objects'} tagged {tag}")
            chip.setAccessibleName(f"Tag {tag}")
            chip.clicked.connect(lambda _=False, t=tag: self.tagClicked.emit(t))
            self.tag_row.addWidget(chip)
        self.update_counts()

    def _clear_tags(self) -> None:
        while self.tag_row.count():
            item = self.tag_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def update_counts(self) -> None:
        if self.entity is None or self.session.matrix is None:
            return
        ix = self.session.matrix.index
        if self.mode == "principal":
            c = ix.principal_counts(self.entity)
            text = f"{c.grants:,} grants · {c.denies:,} denies · {c.pending:,} pending"
        else:
            c = ix.object_counts(self.entity)
            granted = len(ix.principals_by_object[self.entity])
            text = (
                f"{granted:,} principals with access · {c.grants:,} grants · "
                f"{c.denies:,} denies · {c.pending:,} pending"
            )
        self.counts.setText(text)

    # --- Description ----------------------------------------------------------------------

    def set_description(self, text: str | None, loading: bool = False, error: str | None = None) -> None:
        if error:
            shown = f"Couldn't load the description: {error}"
        elif loading:
            shown = "Loading description…"
        else:
            shown = text or "No description"
        self._description_text = shown
        self._description_expanded = False
        self._render_description()
        self.edit_description.setEnabled(not loading and self.entity is not None)

    def _render_description(self) -> None:
        text = self._description_text
        lines = text.splitlines() or [""]
        long = len(lines) > DESCRIPTION_LINES or len(text) > 300
        if long and not self._description_expanded:
            text = "\n".join(lines[:DESCRIPTION_LINES])[:300] + "…"
        self.description.setText(text)
        self.more_link.setVisible(long)
        self.more_link.setText("Less" if self._description_expanded else "More")

    def _toggle_description(self) -> None:
        self._description_expanded = not self._description_expanded
        self._render_description()

    # --- Filters --------------------------------------------------------------------------

    def refresh_options(self) -> None:
        """Reload tag and schema options after a load or a tag change."""
        if self.session.matrix is None:
            return
        ix = self.session.matrix.index
        other = "object" if self.mode == "principal" else "principal"
        self.tags_chip.set_options(tag_options(ix, other))
        if self.schema_chip is not None:
            names: dict[str, str] = {}
            for span in ix.schema_spans:
                names.setdefault(span.schema.casefold(), span.schema)
            self.schema_chip.set_options(sorted(names.items()))
        self._read_controls()

    def _read_controls(self) -> None:
        if self.mode == "principal":
            self.filters = GridFilters(
                text=self.search.text(),
                schemas=self.schema_chip.selected,
                object_types=frozenset(ObjectType(t) for t in self.type_chip.selected),
                tags=self.tags_chip.selected,
                segment=self.segment.value,
            )
        else:
            self.filters = GridFilters(
                text=self.search.text(),
                principal_types=frozenset(k for k, c in self.principal_chips.items() if c.isChecked()),
                tags=self.tags_chip.selected,
                segment=self.segment.value,
            )

    def _on_change(self, *_args) -> None:
        self._read_controls()
        self.filtersChanged.emit()

    def set_filters(self, filters: GridFilters) -> None:
        """Set the controls without emitting filtersChanged."""
        widgets = [self.search, self.segment, self.tags_chip]
        for widget in widgets:
            widget.blockSignals(True)
        self.search.setText(filters.text)
        self.segment.set_value(filters.segment)
        self.tags_chip.set_selected(filters.tags)
        if self.schema_chip is not None:
            self.schema_chip.set_selected(filters.schemas)
            self.type_chip.set_selected(t.value for t in filters.object_types)
        for key, chip in self.principal_chips.items():
            chip.set_checked_quietly(key in filters.principal_types)
        for widget in widgets:
            widget.blockSignals(False)
        self._read_controls()

    def set_stale(self, stale: bool) -> None:
        self.stale_link.setVisible(stale)

    def get_state(self) -> dict:
        f = self.filters
        return {
            "segment": f.segment,
            "schemas": sorted(f.schemas),
            "object_types": sorted(t.value for t in f.object_types),
            "principal_types": sorted(f.principal_types),
            "tags": sorted(f.tags),
        }

    def set_state(self, state: dict) -> None:
        segment = state.get("segment", "all")
        valid_types = {t.value for t in ObjectType}
        self.set_filters(
            GridFilters(
                schemas=frozenset(state.get("schemas", ())),
                object_types=frozenset(ObjectType(t) for t in state.get("object_types", ()) if t in valid_types),
                principal_types=frozenset(state.get("principal_types", ())) & {"U", "G", "S"},
                tags=frozenset(state.get("tags", ())),
                segment=segment if segment in ("all", "access", "pending") else "all",
            )
        )
