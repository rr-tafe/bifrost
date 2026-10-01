"""
Tag manager (non-modal).

Left: tags with principal and object counts; New, Rename, Delete. Right: the
selected tag's principals and objects, with Add… (a searchable picker) and
Remove. Every change is saved to tags.json immediately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSortFilterProxyModel, QStringListModel, Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.qt.theme import tokens
from src.qt.widgets.search_field import SearchField
from src.validation import validate_tag

if TYPE_CHECKING:
    from src.qt.session import Session

PRINCIPAL_TYPE_NAMES = {"U": "Windows user", "G": "Windows group", "S": "SQL user"}


class MemberPickerDialog(QDialog):
    """
    Searchable checklist for adding principals or objects to a tag.

    Attributes:
        chosen: Keys (login names or schema.object) the user checked, after exec()
    """

    def __init__(
        self,
        title: str,
        items: list[tuple[str, str]],
        exclude: set[str],
        parent: QWidget | None = None,
    ) -> None:
        """
        Args:
            title: Dialog title
            items: (key, description) for every candidate
            exclude: Keys already in the tag (not offered)
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 560)
        self.chosen: list[str] = []
        layout = QVBoxLayout(self)

        self.search = SearchField("Search…", "Search candidates", self)
        layout.addWidget(self.search)

        self.model = QStandardItemModel(self)
        for key, description in items:
            if key in exclude:
                continue
            item = QStandardItem(f"{key}    {description}" if description else key)
            item.setData(key, Qt.ItemDataRole.UserRole)
            item.setCheckable(True)
            item.setEditable(False)
            self.model.appendRow(item)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search.searchChanged.connect(self._filter)
        self.list = QListView(self)
        self.list.setModel(self.proxy)
        self.list.setUniformItemSizes(True)
        self.list.setAccessibleName("Candidates")
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        select_shown = QPushButton("Select all shown", self)
        select_shown.clicked.connect(lambda: self._set_shown(Qt.CheckState.Checked))
        clear = QPushButton("Clear", self)
        clear.clicked.connect(lambda: self._set_shown(Qt.CheckState.Unchecked))
        self.count = QLabel("", self)
        row.addWidget(select_shown)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(self.count)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox(self)
        self.add_button = self.buttons.addButton("Add", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.model.itemChanged.connect(lambda _item: self._update_count())
        self._update_count()
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)

    def _set_shown(self, state: Qt.CheckState) -> None:
        self.model.blockSignals(True)
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            self.model.itemFromIndex(source).setCheckState(state)
        self.model.blockSignals(False)
        self.model.layoutChanged.emit()
        self._update_count()

    def checked_keys(self) -> list[str]:
        return [
            self.model.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.model.rowCount())
            if self.model.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _update_count(self) -> None:
        count = len(self.checked_keys())
        self.count.setText(f"{count:,} selected")
        self.add_button.setText(f"Add {count:,}" if count else "Add")
        self.add_button.setEnabled(count > 0)

    def _accept(self) -> None:
        self.chosen = self.checked_keys()
        self.accept()


class _MemberList(QWidget):
    """Filterable list of a tag's members with Add… and Remove selected."""

    def __init__(self, noun: str, parent: QWidget) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.search = SearchField(f"Filter {noun}…", f"Filter {noun}", self)
        self.model = QStringListModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search.searchChanged.connect(self.proxy.setFilterFixedString)
        self.list = QListView(self)
        self.list.setModel(self.proxy)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setUniformItemSizes(True)
        self.list.setAccessibleName(f"Tagged {noun}")
        self.add_button = QPushButton("Add…", self)
        self.add_button.setAccessibleName(f"Add {noun} to this tag")
        self.remove_button = QPushButton("Remove selected", self)
        self.remove_button.setAccessibleName(f"Remove the selected {noun} from this tag")
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_members(self, members: list[str]) -> None:
        self.model.setStringList(sorted(members, key=str.casefold))

    def selected(self) -> list[str]:
        return [self.proxy.data(i) for i in self.list.selectionModel().selectedIndexes()]


class TagManagerDialog(QDialog):
    """Non-modal tag manager."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("Tags")
        self.setModal(False)
        self.resize(900, 600)
        self._new_tags: list[str] = []  # created here but not yet assigned (tags.json can't store them)

        layout = QVBoxLayout(self)
        splitter = QSplitter(self)
        layout.addWidget(splitter, 1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        self.tag_filter = SearchField("Filter tags…", "Filter tags", left)
        self.tag_filter.searchChanged.connect(lambda _t: self.refresh())
        self.tag_list = QListWidget(left)
        self.tag_list.setAccessibleName("Tags")
        self.tag_list.currentItemChanged.connect(lambda *_: self._show_selected())
        new_row = QHBoxLayout()
        self.new_name = QLineEdit(left)
        self.new_name.setPlaceholderText("New tag name (letters and numbers)")
        self.new_name.setAccessibleName("New tag name")
        self.new_name.returnPressed.connect(self.create_tag)
        new_button = QPushButton("New", left)
        new_button.clicked.connect(self.create_tag)
        new_row.addWidget(self.new_name, 1)
        new_row.addWidget(new_button)
        self.new_error = QLabel("", left)
        self.new_error.setStyleSheet(f"color: {tokens().danger};")
        self.new_error.setWordWrap(True)
        self.new_error.hide()
        edit_row = QHBoxLayout()
        self.rename_button = QPushButton("Rename…", left)
        self.rename_button.clicked.connect(self.rename_tag)
        self.delete_button = QPushButton("Delete…", left)
        self.delete_button.clicked.connect(self.delete_tag)
        edit_row.addWidget(self.rename_button)
        edit_row.addWidget(self.delete_button)
        edit_row.addStretch(1)
        left_layout.addWidget(self.tag_filter)
        left_layout.addWidget(self.tag_list, 1)
        left_layout.addLayout(new_row)
        left_layout.addWidget(self.new_error)
        left_layout.addLayout(edit_row)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        self.tag_heading = QLabel("Select a tag", right)
        heading_font = self.tag_heading.font()
        heading_font.setBold(True)
        heading_font.setPointSizeF(heading_font.pointSizeF() * 1.2)
        self.tag_heading.setFont(heading_font)
        self.tabs = QTabWidget(right)
        self.principals = _MemberList("principals", self.tabs)
        self.objects = _MemberList("objects", self.tabs)
        self.tabs.addTab(self.principals, "Principals")
        self.tabs.addTab(self.objects, "Objects")
        self.principals.add_button.clicked.connect(lambda: self.add_members("principals"))
        self.objects.add_button.clicked.connect(lambda: self.add_members("objects"))
        self.principals.remove_button.clicked.connect(lambda: self.remove_members("principals"))
        self.objects.remove_button.clicked.connect(lambda: self.remove_members("objects"))
        right_layout.addWidget(self.tag_heading)
        right_layout.addWidget(self.tabs, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 600])

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.close)
        layout.addWidget(close)

        session.tagsChanged.connect(self.refresh)
        session.dataLoaded.connect(lambda _s: self._show_selected())
        self.refresh()

    # --- Tag list ---------------------------------------------------------------------

    def all_tags(self) -> list[str]:
        """Saved and newly created tags, case-insensitively unique, sorted."""
        seen: dict[str, str] = {}
        for tag in [*self.session.tag_store.get_all_tags(), *self._new_tags]:
            seen.setdefault(tag.casefold(), tag)
        return sorted(seen.values(), key=str.casefold)

    def current_tag(self) -> str | None:
        item = self.tag_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, select: str | None = None) -> None:
        """Rebuild the tag list, keeping (or setting) the selection."""
        store = self.session.tag_store
        select = select or self.current_tag()
        # A new tag that now has members is a normal tag
        saved = {t.casefold() for t in store.get_all_tags()}
        self._new_tags = [t for t in self._new_tags if t.casefold() not in saved]
        text = self.tag_filter.text().strip().casefold()
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for tag in self.all_tags():
            if text and text not in tag.casefold():
                continue
            users = len(store.get_users_with_tag(tag))
            objects = len(store.get_objects_with_tag(tag))
            item = QListWidgetItem(f"{tag}    {users:,} · {objects:,}")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setToolTip(f"{users:,} principals, {objects:,} objects")
            if tag in self._new_tags:
                font = QFont(item.font())
                font.setItalic(True)
                item.setFont(font)
                item.setToolTip("Not saved until it has members")
            self.tag_list.addItem(item)
            if select and tag.casefold() == select.casefold():
                self.tag_list.setCurrentItem(item)
        self.tag_list.blockSignals(False)
        self._show_selected()

    def _show_selected(self) -> None:
        tag = self.current_tag()
        has_tag = tag is not None
        loaded = self.session.matrix is not None
        for widget in (self.rename_button, self.delete_button):
            widget.setEnabled(has_tag)
        for member_list in (self.principals, self.objects):
            member_list.add_button.setEnabled(has_tag and loaded)
            member_list.add_button.setToolTip("" if loaded else "Load data from the database first")
            member_list.remove_button.setEnabled(has_tag)
        if not has_tag:
            self.tag_heading.setText("Select a tag")
            self.principals.set_members([])
            self.objects.set_members([])
            return
        store = self.session.tag_store
        users = store.get_users_with_tag(tag)
        objects = store.get_objects_with_tag(tag)
        suffix = " (not saved until it has members)" if tag in self._new_tags else ""
        self.tag_heading.setText(f"{tag}{suffix}")
        self.principals.set_members(users)
        self.objects.set_members(objects)
        self.tabs.setTabText(0, f"Principals ({len(users):,})")
        self.tabs.setTabText(1, f"Objects ({len(objects):,})")

    # --- Create, rename, delete -------------------------------------------------------

    def create_tag(self) -> None:
        name = self.new_name.text().strip()
        errors = validate_tag(name)
        if not errors and name.casefold() in {t.casefold() for t in self.all_tags()}:
            errors = [f"A tag called '{name}' already exists."]
        if errors:
            self.new_error.setText(errors[0])
            self.new_error.show()
            self.new_name.setAccessibleDescription(errors[0])
            return
        self.new_error.hide()
        self.new_name.setAccessibleDescription("")
        self.new_name.clear()
        self._new_tags.append(name)
        self.refresh(select=name)

    def rename_tag(self) -> None:
        old = self.current_tag()
        if old is None:
            return
        new, ok = QInputDialog.getText(self, "Rename tag", f"New name for '{old}':", text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        errors = validate_tag(new)
        if errors:
            QMessageBox.warning(self, "Invalid tag name", errors[0])
            return
        existing = next((t for t in self.all_tags() if t.casefold() == new.casefold() and t != old), None)
        if existing and existing.casefold() != old.casefold():
            answer = QMessageBox.question(
                self, "Merge tags", f"'{existing}' already exists. Merge '{old}' into '{existing}'?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            new = existing
        if old in self._new_tags:
            self._new_tags = [new if t == old else t for t in self._new_tags]
            self.refresh(select=new)
            return
        store = self.session.tag_store
        for login in store.get_users_with_tag(old):
            store.remove_user_tag(login, old)
            store.add_user_tag(login, new)
        for full_name in store.get_objects_with_tag(old):
            store.remove_object_tag(full_name, old)
            store.add_object_tag(full_name, new)
        self._save(select=new)

    def delete_tag(self) -> None:
        tag = self.current_tag()
        if tag is None:
            return
        if tag in self._new_tags:
            self._new_tags.remove(tag)
            self.refresh()
            return
        store = self.session.tag_store
        users = store.get_users_with_tag(tag)
        objects = store.get_objects_with_tag(tag)
        answer = QMessageBox.question(
            self,
            "Delete tag",
            f"Delete '{tag}'? It's on {len(users):,} principals and {len(objects):,} objects.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for login in users:
            store.remove_user_tag(login, tag)
        for full_name in objects:
            store.remove_object_tag(full_name, tag)
        self._save()

    # --- Members ------------------------------------------------------------------------

    def add_members(self, kind: str) -> None:
        tag = self.current_tag()
        matrix = self.session.matrix
        if tag is None or matrix is None:
            return
        store = self.session.tag_store
        if kind == "principals":
            items = [(u.login_name, PRINCIPAL_TYPE_NAMES.get(u.principal_type, "")) for u in matrix.users]
            exclude = set(store.get_users_with_tag(tag))
            title = f"Add principals to '{tag}'"
        else:
            items = [(o.full_name, o.object_type.value.title()) for o in matrix.objects]
            exclude = set(store.get_objects_with_tag(tag))
            title = f"Add objects to '{tag}'"
        picker = MemberPickerDialog(title, items, exclude, self)
        if picker.exec() != QDialog.DialogCode.Accepted or not picker.chosen:
            return
        for key in picker.chosen:
            if kind == "principals":
                store.add_user_tag(key, tag)
            else:
                store.add_object_tag(key, tag)
        self._save(select=tag)

    def remove_members(self, kind: str) -> None:
        tag = self.current_tag()
        member_list = self.principals if kind == "principals" else self.objects
        selected = member_list.selected()
        if tag is None or not selected:
            return
        store = self.session.tag_store
        for key in selected:
            if kind == "principals":
                store.remove_user_tag(key, tag)
            else:
                store.remove_object_tag(key, tag)
        self._save(select=tag)

    def _save(self, select: str | None = None) -> None:
        error = self.session.save_tags()  # emits tagsChanged -> refresh
        if select:
            self.refresh(select=select)
        if error:
            QMessageBox.warning(self, "Couldn't save tags", error)
