"""
Matrix view state remembered between launches (QSettings, under "matrix/").

Mode, splitter sizes, the last principal and object, and per-mode filters.
Search text isn't saved (it surprises people on the next launch) and collapsed
groups last only for the session. Filters are stored as JSON so QSettings
backends (registry, plist, ini) all round-trip them the same way.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QSettings

logger = logging.getLogger("bifrost.view_state")

PREFIX = "matrix/"
MODES = ("principal", "object")


@dataclass
class ViewState:
    """
    Attributes:
        mode: "principal" or "object"
        splitter: QSplitter.saveState() bytes
        principal: Last selected login, or ""
        object: Last selected (schema, name), or None
        lists: mode -> left-list state dict
        grids: mode -> grid-header state dict
    """

    mode: str = "principal"
    splitter: QByteArray | None = None
    principal: str = ""
    object: tuple[str, str] | None = None
    lists: dict[str, dict] = field(default_factory=dict)
    grids: dict[str, dict] = field(default_factory=dict)


def _json(settings: QSettings, key: str) -> dict:
    raw = settings.value(PREFIX + key, "")
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except ValueError:
        logger.warning("Ignoring unreadable view state %s", key)
        return {}
    return value if isinstance(value, dict) else {}


def load(settings: QSettings) -> ViewState:
    """Read the saved state; anything missing or unreadable falls back to defaults."""
    mode = str(settings.value(PREFIX + "mode", "principal"))
    splitter = settings.value(PREFIX + "splitter")
    obj = _json(settings, "object")
    schema, name = obj.get("schema"), obj.get("name")
    return ViewState(
        mode=mode if mode in MODES else "principal",
        splitter=splitter if isinstance(splitter, QByteArray) and not splitter.isEmpty() else None,
        principal=str(settings.value(PREFIX + "principal", "") or ""),
        object=(schema, name) if isinstance(schema, str) and isinstance(name, str) else None,
        lists={m: _json(settings, f"list_{m}") for m in MODES},
        grids={m: _json(settings, f"grid_{m}") for m in MODES},
    )


def save(settings: QSettings, state: ViewState) -> None:
    settings.setValue(PREFIX + "mode", state.mode)
    if state.splitter is not None:
        settings.setValue(PREFIX + "splitter", state.splitter)
    settings.setValue(PREFIX + "principal", state.principal)
    obj = {"schema": state.object[0], "name": state.object[1]} if state.object else {}
    settings.setValue(PREFIX + "object", json.dumps(obj))
    for mode in MODES:
        settings.setValue(PREFIX + f"list_{mode}", json.dumps(state.lists.get(mode, {})))
        settings.setValue(PREFIX + f"grid_{mode}", json.dumps(state.grids.get(mode, {})))
