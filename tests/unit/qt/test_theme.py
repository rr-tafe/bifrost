"""WCAG contrast checks for the colour tokens (FR-024)."""

import pytest

from src.qt.theme import DARK, LIGHT, TEXT_PAIRS, UI_PAIRS, contrast_ratio


@pytest.mark.parametrize("name,theme", [("light", LIGHT), ("dark", DARK)])
def test_text_pairs_meet_aa(name, theme):
    for fg, bg in TEXT_PAIRS:
        ratio = contrast_ratio(getattr(theme, fg), getattr(theme, bg))
        assert ratio >= 4.5, f"{name}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("name,theme", [("light", LIGHT), ("dark", DARK)])
def test_ui_pairs_meet_3_to_1(name, theme):
    for fg, bg in UI_PAIRS:
        ratio = contrast_ratio(getattr(theme, fg), getattr(theme, bg))
        assert ratio >= 3.0, f"{name}: {fg} on {bg} is {ratio:.2f}:1"


def test_contrast_ratio_known_values():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)
