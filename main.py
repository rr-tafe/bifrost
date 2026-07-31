#!/usr/bin/env python3
"""
Bifrost - SQL Server Permissions Manager

Entry point for the desktop application. This module initializes the application,
loads the configuration, establishes the database connection, and launches the
main UI window.

Architecture:
    - Load configuration from %APPDATA%/Bifrost/config.json
    - If config missing or corrupt, show Settings view with explanatory message
    - If config valid, attempt SQL Server connection using Windows Authentication
    - On successful connection, load the permission matrix view
    - On connection failure, fall back to Settings view with error details

Usage:
    python main.py

Requirements:
    - Python 3.11+
    - Windows 11
    - Microsoft ODBC Driver 18 for SQL Server
    - SQL Server 2019+ with db_owner or sysadmin privileges on target database
"""

import sys
from src.ui.app import main


if __name__ == "__main__":
    sys.exit(main())
