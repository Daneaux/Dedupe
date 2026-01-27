#!/usr/bin/env python3
"""Main entry point for Duplicate Finder."""

import sys
from pathlib import Path

# Add parent directory to path for imports
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.ui.unified_window import UnifiedWindow
from src.core.database import DatabaseManager


def main():
    """Run the Duplicate Finder application."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Dedupe")
    app.setOrganizationName("Dedupe")

    # Set application style
    app.setStyle("Fusion")

    # Initialize database
    DatabaseManager.get_instance()

    # Create and show the unified window
    window = UnifiedWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
