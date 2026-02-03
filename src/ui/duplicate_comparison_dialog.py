"""Dialog for comparing source and destination images when duplicates are detected."""

from pathlib import Path
from typing import Optional
from enum import Enum, auto
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy
)

from PIL import Image

from ..utils.exif_extractor import ExifExtractor


class DuplicateResolution(Enum):
    """Result options for duplicate resolution."""
    SKIP = auto()           # Don't move, keep source where it is
    TRASH_SOURCE = auto()   # Move source to trash
    REPLACE = auto()        # Replace destination with source
    KEEP_BOTH = auto()      # Rename source and move anyway


class ImageComparisonWidget(QFrame):
    """Widget displaying a single image with metadata for comparison."""

    THUMBNAIL_SIZE = 300

    def __init__(self, file_path: Path, title: str, parent=None):
        super().__init__(parent)
        self.file_path = Path(file_path)
        self.title = title
        self._exif = ExifExtractor()

        self._setup_ui()
        self._load_image()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(2)
        self.setStyleSheet("""
            ImageComparisonWidget {
                border: 2px solid #ccc;
                border-radius: 8px;
                background-color: #fafafa;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title_label = QLabel(self.title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        layout.addWidget(title_label)

        # Thumbnail
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #e0e0e0; border-radius: 4px;")
        layout.addWidget(self.thumbnail_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Filename
        filename = self.file_path.name
        if len(filename) > 35:
            filename = filename[:32] + "..."
        self.name_label = QLabel(filename)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.name_label.setToolTip(self.file_path.name)
        layout.addWidget(self.name_label)

        # File info container
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # File size
        if self.file_path.exists():
            size = os.path.getsize(self.file_path)
            size_str = self._format_size(size)
        else:
            size_str = "File not found"
        self.size_label = QLabel(f"Size: {size_str}")
        self.size_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.size_label)

        # Dimensions (filled after image load)
        self.dims_label = QLabel("Dimensions: Loading...")
        self.dims_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.dims_label)

        # EXIF date
        self.date_label = QLabel("Date: Loading...")
        self.date_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.date_label)

        layout.addLayout(info_layout)

        # Full path (truncated)
        path_str = str(self.file_path.parent)
        if len(path_str) > 45:
            path_str = "..." + path_str[-42:]
        self.path_label = QLabel(path_str)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_label.setStyleSheet("color: #999; font-size: 10px;")
        self.path_label.setToolTip(str(self.file_path))
        layout.addWidget(self.path_label)

    def _load_image(self):
        """Load and display the image with metadata."""
        try:
            if not self.file_path.exists():
                self.thumbnail_label.setText("File not found")
                self.dims_label.setText("Dimensions: N/A")
                self.date_label.setText("Date: N/A")
                return

            # Load image
            with Image.open(self.file_path) as img:
                # Get dimensions before resizing
                orig_width, orig_height = img.size
                self.dims_label.setText(f"Dimensions: {orig_width} x {orig_height}")

                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # Create thumbnail
                img.thumbnail((self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE), Image.Resampling.LANCZOS)

                # Convert to QPixmap
                data = img.tobytes("raw", "RGB")
                qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qimage)

                self.thumbnail_label.setPixmap(pixmap)

            # Get EXIF date
            date_original, date_digitized, fallback = self._exif.get_dates(self.file_path)
            if date_original:
                date_str = date_original.strftime("%Y-%m-%d %H:%M:%S")
                self.date_label.setText(f"Date (EXIF): {date_str}")
            elif date_digitized:
                date_str = date_digitized.strftime("%Y-%m-%d %H:%M:%S")
                self.date_label.setText(f"Date (EXIF digitized): {date_str}")
            else:
                date_str = fallback.strftime("%Y-%m-%d %H:%M:%S")
                self.date_label.setText(f"Date (file modified): {date_str}")

        except Exception as e:
            self.thumbnail_label.setText(f"Error loading\n{type(e).__name__}")
            self.dims_label.setText("Dimensions: Error")
            self.date_label.setText("Date: Error")

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable form."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


class DuplicateComparisonDialog(QDialog):
    """Dialog showing source and destination images side-by-side for duplicate resolution."""

    def __init__(self, source_path: Path, dest_path: Path, parent=None):
        """
        Initialize the comparison dialog.

        Args:
            source_path: Path to the source file (being moved)
            dest_path: Path to the existing file in destination
            parent: Parent widget
        """
        super().__init__(parent)
        self.source_path = Path(source_path)
        self.dest_path = Path(dest_path)
        self._result = DuplicateResolution.SKIP

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Duplicate Detected")
        self.setMinimumSize(750, 550)
        self.resize(850, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("Duplicate file detected in destination folder")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #d32f2f;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Description
        desc = QLabel(
            "The file you're moving appears to be a duplicate of an existing file "
            "in the destination. Choose how to handle this:"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #555; font-size: 12px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        # Image comparison - side by side
        comparison_layout = QHBoxLayout()
        comparison_layout.setSpacing(20)

        # Source image (left)
        self.source_widget = ImageComparisonWidget(self.source_path, "SOURCE (Being Moved)")
        self.source_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        comparison_layout.addWidget(self.source_widget)

        # Arrow in the middle
        arrow_label = QLabel("->")
        arrow_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #666;")
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        comparison_layout.addWidget(arrow_label)

        # Destination image (right)
        self.dest_widget = ImageComparisonWidget(self.dest_path, "DESTINATION (Existing)")
        self.dest_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        comparison_layout.addWidget(self.dest_widget)

        layout.addLayout(comparison_layout, stretch=1)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        # Skip button
        skip_btn = QPushButton("Skip")
        skip_btn.setToolTip("Don't move this file, keep it in the source location")
        skip_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                font-size: 12px;
                border: 1px solid #ccc;
                border-radius: 4px;
                background-color: #f5f5f5;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        skip_btn.clicked.connect(self._on_skip)
        button_layout.addWidget(skip_btn)

        # Trash source button
        trash_btn = QPushButton("Move Source to Trash")
        trash_btn.setToolTip("Delete the source file (move to trash)")
        trash_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                font-size: 12px;
                border: 1px solid #f44336;
                border-radius: 4px;
                background-color: #ffebee;
                color: #c62828;
            }
            QPushButton:hover {
                background-color: #ffcdd2;
            }
        """)
        trash_btn.clicked.connect(self._on_trash_source)
        button_layout.addWidget(trash_btn)

        # Replace button
        replace_btn = QPushButton("Replace Destination")
        replace_btn.setToolTip("Replace the existing file with the source file")
        replace_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                font-size: 12px;
                border: 1px solid #ff9800;
                border-radius: 4px;
                background-color: #fff3e0;
                color: #e65100;
            }
            QPushButton:hover {
                background-color: #ffe0b2;
            }
        """)
        replace_btn.clicked.connect(self._on_replace)
        button_layout.addWidget(replace_btn)

        # Keep both button
        keep_both_btn = QPushButton("Keep Both")
        keep_both_btn.setToolTip("Move source with a new name (e.g., filename_1.jpg)")
        keep_both_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                font-size: 12px;
                border: 1px solid #4caf50;
                border-radius: 4px;
                background-color: #e8f5e9;
                color: #2e7d32;
            }
            QPushButton:hover {
                background-color: #c8e6c9;
            }
        """)
        keep_both_btn.clicked.connect(self._on_keep_both)
        button_layout.addWidget(keep_both_btn)

        layout.addLayout(button_layout)

    def _on_skip(self):
        """Handle Skip button click."""
        self._result = DuplicateResolution.SKIP
        self.accept()

    def _on_trash_source(self):
        """Handle Trash Source button click."""
        self._result = DuplicateResolution.TRASH_SOURCE
        self.accept()

    def _on_replace(self):
        """Handle Replace button click."""
        self._result = DuplicateResolution.REPLACE
        self.accept()

    def _on_keep_both(self):
        """Handle Keep Both button click."""
        self._result = DuplicateResolution.KEEP_BOTH
        self.accept()

    def get_result(self) -> DuplicateResolution:
        """Get the user's choice for handling the duplicate."""
        return self._result

    @staticmethod
    def get_resolution(source_path: Path, dest_path: Path, parent=None) -> Optional[DuplicateResolution]:
        """
        Show the dialog and return the user's resolution choice.

        Args:
            source_path: Path to source file
            dest_path: Path to destination file
            parent: Parent widget

        Returns:
            DuplicateResolution if dialog accepted, None if cancelled
        """
        dialog = DuplicateComparisonDialog(source_path, dest_path, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_result()
        return None
