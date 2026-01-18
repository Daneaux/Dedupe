"""Directory selector widget."""

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QFileDialog
)
from PyQt6.QtCore import pyqtSignal


class DirectorySelector(QWidget):
    """Widget for selecting a directory."""

    directory_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the directory selector UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select a directory to scan...")
        self.path_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.path_edit, stretch=1)

        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse)
        layout.addWidget(self.browse_button)

    def _browse(self):
        """Open directory browser dialog."""
        current = self.path_edit.text()
        if current and Path(current).exists():
            start_dir = current
        else:
            start_dir = str(Path.home())

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Directory to Scan",
            start_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            self.path_edit.setText(directory)

    def _on_text_changed(self, text: str):
        """Handle text change."""
        self.directory_changed.emit(text)

    def get_directory(self) -> Optional[Path]:
        """Get the selected directory as Path, or None if invalid."""
        text = self.path_edit.text().strip()
        if not text:
            return None

        path = Path(text)
        if path.exists() and path.is_dir():
            return path
        return None

    def set_directory(self, path: str):
        """Set the directory path."""
        self.path_edit.setText(path)

    def is_valid(self) -> bool:
        """Check if the current path is valid."""
        return self.get_directory() is not None
