"""Shared test setup."""

import os

# Qt tests run headless (Mac, pre-commit, CI). Must be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
