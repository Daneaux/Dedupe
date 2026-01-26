"""Session picker dialog for resuming previous scans."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QWidget, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ..utils.session import SessionManager, SessionInfo


class SessionItemWidget(QWidget):
    """Custom widget for displaying session info in the list."""

    def __init__(self, info: SessionInfo, parent=None):
        super().__init__(parent)
        self.info = info
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Top row: folder name and date
        top_row = QHBoxLayout()

        folder_label = QLabel(self.info.root_directory_name)
        font = QFont()
        font.setBold(True)
        font.setPointSize(13)
        folder_label.setFont(font)
        top_row.addWidget(folder_label)

        top_row.addStretch()

        # Format date nicely
        updated = self.info.updated_datetime
        if updated.date() == datetime.now().date():
            date_str = f"Today at {updated.strftime('%I:%M %p')}"
        else:
            date_str = updated.strftime("%b %d, %Y at %I:%M %p")

        date_label = QLabel(date_str)
        date_label.setStyleSheet("color: #666;")
        top_row.addWidget(date_label)

        layout.addLayout(top_row)

        # Path row
        path_label = QLabel(self.info.root_directory)
        path_label.setStyleSheet("color: #888; font-size: 11px;")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        # Stats row
        stats_row = QHBoxLayout()

        groups_label = QLabel(f"{self.info.total_groups} groups")
        groups_label.setStyleSheet("color: #666;")
        stats_row.addWidget(groups_label)

        stats_row.addWidget(QLabel(" | "))

        dupes_label = QLabel(f"{self.info.total_duplicates} duplicates")
        dupes_label.setStyleSheet("color: #666;")
        stats_row.addWidget(dupes_label)

        stats_row.addWidget(QLabel(" | "))

        savings_label = QLabel(f"Potential savings: {self.info.potential_savings_str}")
        savings_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        stats_row.addWidget(savings_label)

        stats_row.addStretch()

        # Detection mode
        mode_str = f"{self.info.detection_mode.title()}"
        if self.info.detection_mode == "perceptual":
            mode_str += f" ({self.info.hash_algorithm}, threshold={self.info.perceptual_threshold})"
        mode_label = QLabel(mode_str)
        mode_label.setStyleSheet("color: #888; font-size: 10px;")
        stats_row.addWidget(mode_label)

        layout.addLayout(stats_row)


class SessionPickerDialog(QDialog):
    """Dialog for picking a session to resume or starting a new scan."""

    session_selected = pyqtSignal(str)  # Emits session_id
    new_scan_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session_manager = SessionManager()
        self.selected_session_id: Optional[str] = None
        self._setup_ui()
        self._load_sessions()

    def _setup_ui(self):
        self.setWindowTitle("Duplicate Image Finder")
        self.setMinimumSize(650, 450)
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel("Welcome to Duplicate Image Finder")
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Subtitle
        subtitle = QLabel("Resume a previous session or start a new scan")
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # Previous sessions section
        sessions_header = QLabel("Previous Sessions")
        sessions_font = QFont()
        sessions_font.setPointSize(14)
        sessions_font.setBold(True)
        sessions_header.setFont(sessions_font)
        layout.addWidget(sessions_header)

        # Session list
        self.session_list = QListWidget()
        self.session_list.setSpacing(2)
        self.session_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.session_list.itemDoubleClicked.connect(self._on_double_click)
        self.session_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ccc;
                border-radius: 6px;
                background: white;
            }
            QListWidget::item {
                border-bottom: 1px solid #eee;
                padding: 4px;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
            QListWidget::item:hover {
                background-color: #f5f5f5;
            }
        """)
        layout.addWidget(self.session_list, stretch=1)

        # No sessions message (hidden by default)
        self.no_sessions_label = QLabel(
            "No previous sessions found.\nStart a new scan to detect duplicates."
        )
        self.no_sessions_label.setStyleSheet("color: #888; font-size: 13px;")
        self.no_sessions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_sessions_label.setVisible(False)
        layout.addWidget(self.no_sessions_label)

        # Buttons row
        button_layout = QHBoxLayout()

        self.delete_button = QPushButton("Delete Session")
        self.delete_button.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; padding: 8px 16px; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self.delete_button.clicked.connect(self._delete_session)
        self.delete_button.setEnabled(False)
        button_layout.addWidget(self.delete_button)

        button_layout.addStretch()

        self.new_scan_button = QPushButton("Start New Scan")
        self.new_scan_button.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "font-weight: bold; padding: 10px 24px; font-size: 13px; }"
        )
        self.new_scan_button.clicked.connect(self._start_new_scan)
        button_layout.addWidget(self.new_scan_button)

        self.resume_button = QPushButton("Resume Selected")
        self.resume_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 10px 24px; font-size: 13px; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self.resume_button.clicked.connect(self._resume_session)
        self.resume_button.setEnabled(False)
        button_layout.addWidget(self.resume_button)

        layout.addLayout(button_layout)

    def _load_sessions(self):
        """Load and display available sessions."""
        self.session_list.clear()
        sessions = self.session_manager.list_sessions()

        if not sessions:
            self.session_list.setVisible(False)
            self.no_sessions_label.setVisible(True)
            return

        self.session_list.setVisible(True)
        self.no_sessions_label.setVisible(False)

        for info in sessions:
            # Check if directory still exists
            if not Path(info.root_directory).exists():
                continue

            item = QListWidgetItem()
            widget = SessionItemWidget(info)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, info.session_id)

            self.session_list.addItem(item)
            self.session_list.setItemWidget(item, widget)

        if self.session_list.count() == 0:
            self.session_list.setVisible(False)
            self.no_sessions_label.setVisible(True)

    def _on_selection_changed(self):
        """Handle selection change in the list."""
        selected = self.session_list.selectedItems()
        has_selection = len(selected) > 0

        self.resume_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

        if has_selection:
            self.selected_session_id = selected[0].data(Qt.ItemDataRole.UserRole)
        else:
            self.selected_session_id = None

    def _on_double_click(self, item: QListWidgetItem):
        """Handle double-click on a session."""
        self._resume_session()

    def _resume_session(self):
        """Resume the selected session."""
        if self.selected_session_id:
            self.session_selected.emit(self.selected_session_id)
            self.accept()

    def _start_new_scan(self):
        """Start a new scan."""
        self.new_scan_requested.emit()
        self.accept()

    def _delete_session(self):
        """Delete the selected session."""
        if not self.selected_session_id:
            return

        reply = QMessageBox.question(
            self,
            "Delete Session",
            "Are you sure you want to delete this session?\n\n"
            "This will only delete the saved session data, not your actual files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.session_manager.delete_session(self.selected_session_id)
            self._load_sessions()

    def has_sessions(self) -> bool:
        """Check if there are any sessions to display."""
        sessions = self.session_manager.list_sessions()
        # Filter out sessions where directory no longer exists
        return any(Path(s.root_directory).exists() for s in sessions)
