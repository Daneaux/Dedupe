"""Dialog for viewing all images in a duplicate group together."""

from pathlib import Path
from typing import List, Optional, Set

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QScrollArea, QWidget, QCheckBox,
    QPushButton, QSizePolicy
)

from PIL import Image

from ..models.duplicate_group import DuplicateGroup
from ..models.image_file import ImageFile


class ImageThumbnailWidget(QFrame):
    """Widget displaying a single image thumbnail with metadata and selection checkbox."""

    selectionChanged = pyqtSignal(object, bool)  # (ImageFile, is_selected_for_deletion)

    THUMBNAIL_SIZE = 200

    def __init__(self, image: ImageFile, is_suggested_keep: bool = False, parent=None):
        super().__init__(parent)
        self.image = image
        self.is_suggested_keep = is_suggested_keep

        self._setup_ui()
        self._load_thumbnail()

    def _setup_ui(self):
        """Set up the widget UI."""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(2)

        # Highlight suggested keep with green border
        if self.is_suggested_keep:
            self.setStyleSheet("""
                ImageThumbnailWidget {
                    border: 3px solid #4CAF50;
                    border-radius: 8px;
                    background-color: #E8F5E9;
                }
            """)
        else:
            self.setStyleSheet("""
                ImageThumbnailWidget {
                    border: 2px solid #ccc;
                    border-radius: 8px;
                    background-color: #fafafa;
                }
            """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Thumbnail image
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("background-color: #f0f0f0; border-radius: 4px;")
        layout.addWidget(self.thumbnail_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Filename (truncated if too long)
        filename = self.image.filename
        if len(filename) > 25:
            filename = filename[:22] + "..."
        self.name_label = QLabel(filename)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.name_label.setToolTip(self.image.filename)
        layout.addWidget(self.name_label)

        # File size
        self.size_label = QLabel(self.image.file_size_str)
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.size_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.size_label)

        # Dimensions
        if self.image.width and self.image.height:
            dims = f"{self.image.width} x {self.image.height}"
        else:
            dims = "Unknown"
        self.dims_label = QLabel(dims)
        self.dims_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dims_label.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(self.dims_label)

        # Volume name (if available)
        volume_name = getattr(self.image, 'volume_name', None)
        if volume_name:
            self.volume_label = QLabel(f"[{volume_name}]")
            self.volume_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.volume_label.setStyleSheet("color: #2196F3; font-size: 10px;")
            layout.addWidget(self.volume_label)

        # Suggested keep badge
        if self.is_suggested_keep:
            keep_label = QLabel("SUGGESTED KEEP")
            keep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            keep_label.setStyleSheet("""
                background-color: #4CAF50;
                color: white;
                font-size: 9px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 3px;
            """)
            layout.addWidget(keep_label)

        # Delete checkbox
        self.delete_checkbox = QCheckBox("Delete this file")
        self.delete_checkbox.setChecked(not self.is_suggested_keep)
        self.delete_checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.delete_checkbox, alignment=Qt.AlignmentFlag.AlignCenter)

        # Path (truncated)
        path_str = str(self.image.path.parent)
        if len(path_str) > 35:
            path_str = "..." + path_str[-32:]
        self.path_label = QLabel(path_str)
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_label.setStyleSheet("color: #999; font-size: 9px;")
        self.path_label.setToolTip(str(self.image.path))
        layout.addWidget(self.path_label)

    def _load_thumbnail(self):
        """Load and display the image thumbnail."""
        try:
            # Check if file exists
            if not self.image.path.exists():
                self.thumbnail_label.setText("File not found")
                return

            # Load image with PIL
            with Image.open(self.image.path) as img:
                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # Calculate scaling to fit thumbnail size while preserving aspect ratio
                img.thumbnail((self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE), Image.Resampling.LANCZOS)

                # Convert to QPixmap
                data = img.tobytes("raw", "RGB")
                qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qimage)

                self.thumbnail_label.setPixmap(pixmap)

        except Exception as e:
            self.thumbnail_label.setText(f"Error loading\n{type(e).__name__}")

    def _on_checkbox_changed(self, state):
        """Handle checkbox state change."""
        is_checked = state == Qt.CheckState.Checked.value
        self.selectionChanged.emit(self.image, is_checked)

    def set_delete_selected(self, selected: bool):
        """Set the delete checkbox state."""
        self.delete_checkbox.blockSignals(True)
        self.delete_checkbox.setChecked(selected)
        self.delete_checkbox.blockSignals(False)

    def is_delete_selected(self) -> bool:
        """Return whether this file is selected for deletion."""
        return self.delete_checkbox.isChecked()


class DuplicateGroupViewerDialog(QDialog):
    """Dialog showing all images in a duplicate group for comparison."""

    def __init__(self, group: DuplicateGroup, parent=None):
        super().__init__(parent)
        self.group = group
        self.thumbnail_widgets: List[ImageThumbnailWidget] = []

        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle(f"Duplicate Group {self.group.group_id}")
        self.setMinimumSize(700, 500)
        self.resize(900, 700)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header_layout = QVBoxLayout()

        title = QLabel(f"Duplicate Group: {self.group.file_count} files")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title)

        # Group info
        info_parts = []
        info_parts.append(f"Total size: {self._format_size(self.group.total_size)}")
        info_parts.append(f"Potential savings: {self._format_size(self.group.potential_savings)}")

        avg_sim = self.group.get_average_similarity()
        if avg_sim > 0:
            info_parts.append(f"Average similarity: {avg_sim:.1%}")

        if self.group.is_cross_volume:
            info_parts.append("Cross-volume duplicates")

        info_label = QLabel(" | ".join(info_parts))
        info_label.setStyleSheet("color: #666; font-size: 12px;")
        header_layout.addWidget(info_label)

        layout.addLayout(header_layout)

        # Instructions
        instructions = QLabel(
            "Review the duplicates below. Check 'Delete this file' for files you want to remove. "
            "The suggested file to keep is highlighted in green."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #555; font-style: italic; margin-bottom: 8px;")
        layout.addWidget(instructions)

        # Scroll area for image grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container for grid
        container = QWidget()
        grid_layout = QGridLayout(container)
        grid_layout.setSpacing(16)
        grid_layout.setContentsMargins(8, 8, 8, 8)

        # Calculate number of columns based on images
        num_images = len(self.group.images)
        if num_images <= 2:
            num_cols = 2
        elif num_images <= 4:
            num_cols = 2
        elif num_images <= 6:
            num_cols = 3
        else:
            num_cols = 3

        # Add image thumbnails
        for i, image in enumerate(self.group.images):
            is_suggested_keep = (image == self.group.suggested_keep)
            thumbnail = ImageThumbnailWidget(image, is_suggested_keep)
            thumbnail.selectionChanged.connect(self._on_selection_changed)
            self.thumbnail_widgets.append(thumbnail)

            row = i // num_cols
            col = i % num_cols
            grid_layout.addWidget(thumbnail, row, col)

        # Add stretch to push items to top-left
        grid_layout.setRowStretch(grid_layout.rowCount(), 1)
        grid_layout.setColumnStretch(num_cols, 1)

        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # Selection summary
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 12px; color: #333;")
        layout.addWidget(self.summary_label)
        self._update_summary()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Select all for deletion (except suggested)
        select_all_btn = QPushButton("Select All Except Keep")
        select_all_btn.clicked.connect(self._select_all_except_keep)
        button_layout.addWidget(select_all_btn)

        # Clear all selections
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all_selections)
        button_layout.addWidget(clear_btn)

        button_layout.addSpacing(20)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px 24px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        apply_btn.clicked.connect(self.accept)
        button_layout.addWidget(apply_btn)

        layout.addLayout(button_layout)

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable form."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    def _on_selection_changed(self, image: ImageFile, is_selected: bool):
        """Handle when a file's deletion selection changes."""
        self._update_summary()

    def _update_summary(self):
        """Update the selection summary label."""
        delete_count = sum(1 for w in self.thumbnail_widgets if w.is_delete_selected())
        keep_count = len(self.thumbnail_widgets) - delete_count

        # Calculate size to be freed
        delete_size = sum(
            w.image.file_size for w in self.thumbnail_widgets if w.is_delete_selected()
        )

        self.summary_label.setText(
            f"Selected: {delete_count} files to delete ({self._format_size(delete_size)}), "
            f"{keep_count} files to keep"
        )

        # Warn if all files selected for deletion
        if keep_count == 0:
            self.summary_label.setStyleSheet("font-size: 12px; color: #f44336; font-weight: bold;")
            self.summary_label.setText(
                "WARNING: All files selected for deletion! At least one file should be kept."
            )
        else:
            self.summary_label.setStyleSheet("font-size: 12px; color: #333;")

    def _select_all_except_keep(self):
        """Select all files for deletion except the suggested keep."""
        for widget in self.thumbnail_widgets:
            widget.set_delete_selected(not widget.is_suggested_keep)
        self._update_summary()

    def _clear_all_selections(self):
        """Clear all deletion selections."""
        for widget in self.thumbnail_widgets:
            widget.set_delete_selected(False)
        self._update_summary()

    def get_files_to_delete(self) -> List[ImageFile]:
        """Return list of files marked for deletion."""
        return [w.image for w in self.thumbnail_widgets if w.is_delete_selected()]

    def get_files_to_keep(self) -> List[ImageFile]:
        """Return list of files marked to keep."""
        return [w.image for w in self.thumbnail_widgets if not w.is_delete_selected()]
