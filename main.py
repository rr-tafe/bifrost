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
import tkinter as tk
from pathlib import Path


def main():
    """
    Main entry point for the Bifrost application.
    
    Initializes the Tk root window, loads configuration, establishes database
    connection, and shows the appropriate initial view (Matrix or Settings).
    
    Returns:
        int: Exit code (0 for success, non-zero for errors)
    """
    # Create root Tkinter window
    root = tk.Tk()
    root.title("Bifrost - SQL Server Permissions Manager")
    
    # Set minimum window size
    root.minsize(1024, 768)
    
    # TODO: Import and initialize the main application controller
    # This will be implemented in src/ui/app.py (Task T015)
    # from src.ui.app import App
    # app = App(root)
    
    # Placeholder: Show a simple window until the app is implemented
    label = tk.Label(
        root,
        text="Bifrost - SQL Server Permissions Manager\n\nApplication scaffold created.\n"
             "Core implementation in progress...",
        font=("Segoe UI", 14),
        padx=50,
        pady=50
    )
    label.pack(expand=True)
    
    # Start the Tkinter event loop
    root.mainloop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
