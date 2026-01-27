"""File Types Manager dialog for managing included/excluded file extensions."""

from typing import Dict, List, Set, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QGroupBox, QMessageBox,
    QSplitter, QWidget, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ..core.database import DatabaseManager


class ExtensionListWidget(QListWidget):
    """Custom list widget for displaying extensions with counts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)


class FileTypesManagerDialog(QDialog):
    """Dialog for managing file type inclusion/exclusion settings."""

    # Emitted when settings are saved
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager.get_instance()
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("File Types Manager")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Manage which file types are scanned for duplicates")
        header.setStyleSheet("font-size: 14px; color: #666; margin-bottom: 8px;")
        layout.addWidget(header)

        # Main content with three columns
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Include section (left)
        include_widget = self._create_section(
            "Included Types",
            "#2e7d32",
            "These file types will be scanned and indexed"
        )
        self.include_list = include_widget.findChild(ExtensionListWidget)
        splitter.addWidget(include_widget)

        # Center section with arrows and unknown list
        center_widget = self._create_center_section()
        splitter.addWidget(center_widget)

        # Exclude section (right)
        exclude_widget = self._create_section(
            "Excluded Types",
            "#c62828",
            "These file types will be ignored"
        )
        self.exclude_list = exclude_widget.findChild(ExtensionListWidget)
        splitter.addWidget(exclude_widget)

        # Set initial sizes
        splitter.setSizes([300, 300, 300])
        layout.addWidget(splitter, stretch=1)

        # Stats row
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # Button row
        button_layout = QHBoxLayout()

        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self._reset_to_defaults)
        button_layout.addWidget(self.reset_btn)

        button_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; "
            "padding: 8px 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1976d2; }"
        )
        self.save_btn.clicked.connect(self._save_and_close)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)

    def _create_section(self, title: str, color: str, description: str) -> QWidget:
        """Create a section widget with title, description, and list."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(description)
        desc_label.setStyleSheet("font-size: 11px; color: #888; margin-bottom: 4px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # List
        list_widget = ExtensionListWidget()
        layout.addWidget(list_widget, stretch=1)

        # Count label
        count_label = QLabel("0 types")
        count_label.setObjectName("count_label")
        count_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(count_label)

        return widget

    def _create_center_section(self) -> QWidget:
        """Create the center section with unknown types and arrow buttons."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 0, 8, 0)

        # Unknown types header
        title_label = QLabel("Unknown Types")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #e65100;")
        layout.addWidget(title_label)

        desc_label = QLabel("File types encountered during scanning that aren't categorized yet")
        desc_label.setStyleSheet("font-size: 11px; color: #888; margin-bottom: 4px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Unknown list
        self.unknown_list = ExtensionListWidget()
        layout.addWidget(self.unknown_list, stretch=1)

        # Arrow buttons
        arrows_layout = QHBoxLayout()

        # Move to Include
        self.to_include_btn = QPushButton("← Include")
        self.to_include_btn.setToolTip("Move selected types to Include list")
        self.to_include_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #388e3c; }"
        )
        self.to_include_btn.clicked.connect(self._move_to_include)
        arrows_layout.addWidget(self.to_include_btn)

        # Move to Exclude
        self.to_exclude_btn = QPushButton("Exclude →")
        self.to_exclude_btn.setToolTip("Move selected types to Exclude list")
        self.to_exclude_btn.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #d32f2f; }"
        )
        self.to_exclude_btn.clicked.connect(self._move_to_exclude)
        arrows_layout.addWidget(self.to_exclude_btn)

        layout.addLayout(arrows_layout)

        # Additional arrow buttons for moving between include/exclude
        move_layout = QHBoxLayout()

        self.include_to_unknown_btn = QPushButton("Remove from Include →")
        self.include_to_unknown_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        self.include_to_unknown_btn.clicked.connect(self._include_to_unknown)
        move_layout.addWidget(self.include_to_unknown_btn)

        move_layout.addStretch()

        self.exclude_to_unknown_btn = QPushButton("← Remove from Exclude")
        self.exclude_to_unknown_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        self.exclude_to_unknown_btn.clicked.connect(self._exclude_to_unknown)
        move_layout.addWidget(self.exclude_to_unknown_btn)

        layout.addLayout(move_layout)

        # Count label
        self.unknown_count_label = QLabel("0 types")
        self.unknown_count_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.unknown_count_label)

        return widget

    def _load_data(self):
        """Load file type data from database and classifier."""
        from ..core.file_classifier import (
            ALL_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
            DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS
        )
        from ..utils.file_filters import EXCLUDED_EXTENSIONS

        # Get custom settings from database
        custom_include = set(self.db.get_custom_included_extensions())
        custom_exclude = set(self.db.get_custom_excluded_extensions())
        unknown_types = self.db.get_unknown_extensions()

        # Build the default include set
        default_include = (
            ALL_IMAGE_EXTENSIONS |
            VIDEO_EXTENSIONS |
            AUDIO_EXTENSIONS |
            DOCUMENT_EXTENSIONS |
            ARCHIVE_EXTENSIONS
        )

        # Apply custom settings
        # Include = (default_include + custom_include) - custom_exclude
        # Exclude = (EXCLUDED_EXTENSIONS + custom_exclude) - custom_include
        final_include = (default_include | custom_include) - custom_exclude
        final_exclude = (EXCLUDED_EXTENSIONS | custom_exclude) - custom_include

        # Get occurrence counts
        extension_counts = self.db.get_extension_counts()

        # Populate include list
        self.include_list.clear()
        for ext in sorted(final_include):
            count = extension_counts.get(ext, 0)
            item = self._create_extension_item(ext, count)
            self.include_list.addItem(item)

        # Populate exclude list
        self.exclude_list.clear()
        for ext in sorted(final_exclude):
            count = extension_counts.get(ext, 0)
            item = self._create_extension_item(ext, count)
            self.exclude_list.addItem(item)

        # Populate unknown list
        self.unknown_list.clear()
        for ext, count in sorted(unknown_types.items(), key=lambda x: -x[1]):
            item = self._create_extension_item(ext, count)
            self.unknown_list.addItem(item)

        self._update_counts()

    def _create_extension_item(self, ext: str, count: int) -> QListWidgetItem:
        """Create a list item for an extension with count."""
        if count > 0:
            text = f".{ext}  ({count:,})"
        else:
            text = f".{ext}"

        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, ext)
        return item

    def _move_to_include(self):
        """Move selected unknown types to include list."""
        selected = self.unknown_list.selectedItems()
        if not selected:
            return

        for item in selected:
            ext = item.data(Qt.ItemDataRole.UserRole)
            # Remove from unknown
            self.unknown_list.takeItem(self.unknown_list.row(item))
            # Add to include
            count = self._get_extension_count(ext)
            new_item = self._create_extension_item(ext, count)
            self.include_list.addItem(new_item)

        self._update_counts()

    def _move_to_exclude(self):
        """Move selected unknown types to exclude list."""
        selected = self.unknown_list.selectedItems()
        if not selected:
            return

        for item in selected:
            ext = item.data(Qt.ItemDataRole.UserRole)
            # Remove from unknown
            self.unknown_list.takeItem(self.unknown_list.row(item))
            # Add to exclude
            count = self._get_extension_count(ext)
            new_item = self._create_extension_item(ext, count)
            self.exclude_list.addItem(new_item)

        self._update_counts()

    def _include_to_unknown(self):
        """Move selected include types back to unknown."""
        selected = self.include_list.selectedItems()
        if not selected:
            return

        for item in selected:
            ext = item.data(Qt.ItemDataRole.UserRole)
            # Remove from include
            self.include_list.takeItem(self.include_list.row(item))
            # Add to unknown
            count = self._get_extension_count(ext)
            new_item = self._create_extension_item(ext, count)
            self.unknown_list.addItem(new_item)

        self._update_counts()

    def _exclude_to_unknown(self):
        """Move selected exclude types back to unknown."""
        selected = self.exclude_list.selectedItems()
        if not selected:
            return

        for item in selected:
            ext = item.data(Qt.ItemDataRole.UserRole)
            # Remove from exclude
            self.exclude_list.takeItem(self.exclude_list.row(item))
            # Add to unknown
            count = self._get_extension_count(ext)
            new_item = self._create_extension_item(ext, count)
            self.unknown_list.addItem(new_item)

        self._update_counts()

    def _get_extension_count(self, ext: str) -> int:
        """Get the occurrence count for an extension."""
        counts = self.db.get_extension_counts()
        return counts.get(ext, 0)

    def _update_counts(self):
        """Update the count labels."""
        include_count = self.include_list.count()
        exclude_count = self.exclude_list.count()
        unknown_count = self.unknown_list.count()

        # Find count labels in sections
        for widget in [self.include_list.parent(), self.exclude_list.parent()]:
            if widget:
                count_label = widget.findChild(QLabel, "count_label")
                if count_label:
                    if widget == self.include_list.parent():
                        count_label.setText(f"{include_count} types")
                    else:
                        count_label.setText(f"{exclude_count} types")

        self.unknown_count_label.setText(f"{unknown_count} types")

        # Update stats
        total_files = sum(self.db.get_extension_counts().values())
        self.stats_label.setText(
            f"Total indexed files: {total_files:,} | "
            f"Include: {include_count} types | "
            f"Exclude: {exclude_count} types | "
            f"Unknown: {unknown_count} types"
        )

    def _reset_to_defaults(self):
        """Reset all settings to defaults."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "This will remove all custom file type settings.\n\n"
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_custom_extensions()
            self._load_data()

    def _save_and_close(self):
        """Save settings and close dialog."""
        from ..core.file_classifier import (
            ALL_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
            DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS
        )
        from ..utils.file_filters import EXCLUDED_EXTENSIONS

        # Get current list contents
        current_include = set()
        for i in range(self.include_list.count()):
            item = self.include_list.item(i)
            current_include.add(item.data(Qt.ItemDataRole.UserRole))

        current_exclude = set()
        for i in range(self.exclude_list.count()):
            item = self.exclude_list.item(i)
            current_exclude.add(item.data(Qt.ItemDataRole.UserRole))

        # Determine what's different from defaults
        default_include = (
            ALL_IMAGE_EXTENSIONS |
            VIDEO_EXTENSIONS |
            AUDIO_EXTENSIONS |
            DOCUMENT_EXTENSIONS |
            ARCHIVE_EXTENSIONS
        )
        default_exclude = EXCLUDED_EXTENSIONS

        # Custom include = things in current_include that aren't in default_include
        # OR things in default_exclude that are now in current_include
        custom_include = (current_include - default_include) | (default_exclude & current_include)

        # Custom exclude = things in current_exclude that aren't in default_exclude
        # OR things in default_include that are now in current_exclude
        custom_exclude = (current_exclude - default_exclude) | (default_include & current_exclude)

        # Save to database
        self.db.set_custom_included_extensions(list(custom_include))
        self.db.set_custom_excluded_extensions(list(custom_exclude))

        # Clear unknown types that were categorized
        remaining_unknown = set()
        for i in range(self.unknown_list.count()):
            item = self.unknown_list.item(i)
            remaining_unknown.add(item.data(Qt.ItemDataRole.UserRole))
        self.db.update_unknown_extensions(remaining_unknown)

        self.settings_changed.emit()
        self.accept()

    def get_included_extensions(self) -> Set[str]:
        """Get the current set of included extensions."""
        extensions = set()
        for i in range(self.include_list.count()):
            item = self.include_list.item(i)
            extensions.add(item.data(Qt.ItemDataRole.UserRole))
        return extensions

    def get_excluded_extensions(self) -> Set[str]:
        """Get the current set of excluded extensions."""
        extensions = set()
        for i in range(self.exclude_list.count()):
            item = self.exclude_list.item(i)
            extensions.add(item.data(Qt.ItemDataRole.UserRole))
        return extensions
