"""
UI views for Bifrost.

This package contains the view classes for each tab in the application:
    - SettingsView: Database connection configuration
    - MatrixView: Permission matrix grid
    - TagsView: Tag management
    - AuditView: Audit log viewer
"""

from src.ui.views.audit import AuditView
from src.ui.views.matrix import MatrixView
from src.ui.views.settings import SettingsView
from src.ui.views.tags import TagsView

__all__ = ["SettingsView", "MatrixView", "TagsView", "AuditView"]
