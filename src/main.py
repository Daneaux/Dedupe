#!/usr/bin/env python3
"""Main entry point for Duplicate Image Finder."""

import sys
from pathlib import Path

# Add parent directory to path for imports
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from src.ui.main_window import MainWindow


def main():
    """Run the Duplicate Image Finder application."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Duplicate Image Finder")
    app.setOrganizationName("Dedupe")

    # Set application style
    app.setStyle("Fusion")

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
