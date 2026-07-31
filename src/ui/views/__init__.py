"""
UI views for Bifrost.

This package contains the view classes for each tab in the application:
    - SettingsView: Database connection configuration
    - MatrixView: Permission matrix grid
    - TagsView: Tag management (coming soon)
    - AuditView: Audit log viewer (coming soon)
"""

from src.ui.views.matrix import MatrixView
from src.ui.views.settings import SettingsView

__all__ = ["SettingsView", "MatrixView"]
