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

from src.ui.main_window import MainWindow
from src.ui.drive_manager import DriveManagerDialog
from src.core.database import DatabaseManager


def main():
    """Run the Duplicate Finder application."""
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Duplicate Finder")
    app.setOrganizationName("Dedupe")

    # Set application style
    app.setStyle("Fusion")

    # Initialize database
    db = DatabaseManager.get_instance()

    # Create main window (but don't show yet)
    window = MainWindow()

    def show_drive_manager():
        """Show the drive manager dialog."""
        drive_manager = DriveManagerDialog()

        def on_find_duplicates(volume_uuid: str):
            """Handle find duplicates request from drive manager."""
            vol = db.get_volume_by_uuid(volume_uuid)
            if vol:
                window.show()
                window.load_volume_duplicates(volume_uuid)

        def on_cross_drive(volume_uuids: list):
            """Handle cross-drive duplicates request."""
            window.show()
            window.load_cross_drive_duplicates(volume_uuids)

        drive_manager.find_duplicates_requested.connect(on_find_duplicates)
        drive_manager.cross_drive_requested.connect(on_cross_drive)

        result = drive_manager.exec()

        # If dialog was rejected and window not visible, exit
        if result == DriveManagerDialog.DialogCode.Rejected:
            if not window.isVisible():
                app.quit()

    # Connect main window's back button to show drive manager
    window.back_to_drive_manager.connect(show_drive_manager)

    # Show drive manager on startup
    show_drive_manager()

    # If window isn't visible after drive manager closes, exit
    if not window.isVisible():
        sys.exit(0)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
