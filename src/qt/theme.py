"""
Colour tokens for the Qt UI.

Standard widgets use the platform style and palette (so Windows High Contrast
works). Only custom-styled elements (pills, permission states, step 3 cells)
use these tokens. Light and dark values follow the OS setting and update live.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette


@dataclass(frozen=True)
class Tokens:
    """One theme's colours (hex strings)."""

    bg: str
    surface: str
    surface_2: str
    line: str
    line_soft: str
    fg: str
    muted: str
    accent: str
    accent_soft: str
    grant: str
    grant_bg: str
    deny: str
    deny_bg: str
    staged: str
    staged_bg: str
    na: str
    danger: str


LIGHT = Tokens(
    bg="#f4f6f9",
    surface="#ffffff",
    surface_2="#eef1f5",
    line="#d5dbe3",
    line_soft="#e5e9ef",
    fg="#18202b",
    muted="#5a6677",
    accent="#2f5fa7",
    accent_soft="#e3ecf8",
    grant="#1a6e42",
    grant_bg="#d9f0e3",
    deny="#b3261e",
    deny_bg="#f8dcd9",
    staged="#8a5700",
    staged_bg="#fff1cc",
    na="#eceff3",
    danger="#b3261e",
)

DARK = Tokens(
    bg="#11151b",
    surface="#181d25",
    surface_2="#202631",
    line="#313a48",
    line_soft="#262e3a",
    fg="#e4e8ee",
    muted="#97a3b4",
    accent="#7fa8e6",
    accent_soft="#1f2e45",
    grant="#6fd19c",
    grant_bg="#173a29",
    deny="#f08a82",
    deny_bg="#43201e",
    staged="#f2c046",
    staged_bg="#3d3113",
    na="#1c222b",
    danger="#f08a82",
)


def is_dark() -> bool:
    """True if the app should use the dark tokens (OS dark mode, or a dark palette)."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    # Unknown (e.g. a High Contrast theme): judge by the palette's window colour
    return QGuiApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128


def tokens() -> Tokens:
    """Return the tokens for the current theme."""
    return DARK if is_dark() else LIGHT


# --- Contrast (WCAG 2.x) -------------------------------------------------------


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Relative luminance of a #rrggbb colour."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two #rrggbb colours (1.0 to 21.0)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


# Text/background pairs that must meet 4.5:1, and UI pairs that must meet 3:1
TEXT_PAIRS = [
    ("fg", "bg"),
    ("fg", "surface"),
    ("fg", "surface_2"),
    ("muted", "surface"),
    ("muted", "surface_2"),
    ("accent", "surface"),
    ("accent", "accent_soft"),
    ("grant", "grant_bg"),
    ("deny", "deny_bg"),
    ("staged", "staged_bg"),
    ("danger", "surface"),
]
UI_PAIRS = [
    ("accent", "surface"),
    ("staged", "surface"),
    ("grant", "surface"),
    ("deny", "surface"),
]
