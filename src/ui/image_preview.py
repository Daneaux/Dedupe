"""Image preview panel for comparing duplicate images."""

from pathlib import Path
from typing import Optional, List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QImage

from ..models.image_file import ImageFile


class ImagePreviewWidget(QWidget):
    """Widget for displaying a single image with metadata."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._current_image: Optional[ImageFile] = None

    def _setup_ui(self):
        """Set up the preview widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Image display area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #2a2a2a;")
        self.image_label.setMinimumSize(200, 200)
        self.scroll_area.setWidget(self.image_label)

        layout.addWidget(self.scroll_area, stretch=1)

        # Metadata frame
        metadata_frame = QFrame()
        metadata_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        metadata_layout = QVBoxLayout(metadata_frame)
        metadata_layout.setContentsMargins(5, 5, 5, 5)
        metadata_layout.setSpacing(2)

        self.filename_label = QLabel()
        self.filename_label.setStyleSheet("font-weight: bold;")
        self.filename_label.setWordWrap(True)
        metadata_layout.addWidget(self.filename_label)

        self.path_label = QLabel()
        self.path_label.setStyleSheet("color: gray; font-size: 10px;")
        self.path_label.setWordWrap(True)
        metadata_layout.addWidget(self.path_label)

        info_layout = QHBoxLayout()
        self.size_label = QLabel()
        info_layout.addWidget(self.size_label)

        self.dimensions_label = QLabel()
        info_layout.addWidget(self.dimensions_label)

        info_layout.addStretch()
        metadata_layout.addLayout(info_layout)

        layout.addWidget(metadata_frame)

    def set_image(self, image: Optional[ImageFile]):
        """
        Set the image to display.

        Args:
            image: ImageFile to display, or None to clear.
        """
        self._current_image = image

        if image is None:
            self.image_label.clear()
            self.image_label.setText("No image selected")
            self.filename_label.setText("")
            self.path_label.setText("")
            self.size_label.setText("")
            self.dimensions_label.setText("")
            return

        # Load and display image
        self._load_image(image.path)

        # Update metadata
        self.filename_label.setText(image.filename)
        self.path_label.setText(str(image.directory))
        self.size_label.setText(f"Size: {image.file_size_str}")
        self.dimensions_label.setText(f"Dimensions: {image.dimensions_str}")

    def _load_image(self, path: Path):
        """Load and display an image from path."""
        try:
            # Try loading with Qt first
            pixmap = QPixmap(str(path))

            if pixmap.isNull():
                # Try loading with PIL for unsupported formats
                try:
                    from PIL import Image
                    import io

                    with Image.open(path) as img:
                        # Convert to RGB if necessary
                        if img.mode != "RGB":
                            img = img.convert("RGB")

                        # Save to bytes
                        buffer = io.BytesIO()
                        img.save(buffer, format="PNG")
                        buffer.seek(0)

                        # Load as QPixmap
                        pixmap = QPixmap()
                        pixmap.loadFromData(buffer.read())

                except Exception:
                    # Try rawpy for RAW files
                    try:
                        import rawpy
                        import numpy as np

                        with rawpy.imread(str(path)) as raw:
                            rgb = raw.postprocess()

                        height, width, channel = rgb.shape
                        bytes_per_line = 3 * width
                        qimg = QImage(
                            rgb.data, width, height, bytes_per_line,
                            QImage.Format.Format_RGB888
                        )
                        pixmap = QPixmap.fromImage(qimg)

                    except Exception:
                        self.image_label.setText("Cannot load image")
                        return

            if not pixmap.isNull():
                # Scale to fit while maintaining aspect ratio
                scaled = pixmap.scaled(
                    self.scroll_area.size() - QSize(20, 20),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)
            else:
                self.image_label.setText("Cannot load image")

        except Exception as e:
            self.image_label.setText(f"Error: {str(e)[:50]}")

    def resizeEvent(self, event):
        """Handle resize to rescale image."""
        super().resizeEvent(event)
        if self._current_image:
            self._load_image(self._current_image.path)


class ImagePreviewPanel(QWidget):
    """Panel for side-by-side image comparison."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the comparison panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("Image Preview")
        title.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(title)

        # Splitter for side-by-side view
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.preview1 = ImagePreviewWidget()
        self.preview2 = ImagePreviewWidget()

        self.splitter.addWidget(self.preview1)
        self.splitter.addWidget(self.preview2)

        # Set equal sizes
        self.splitter.setSizes([1, 1])

        layout.addWidget(self.splitter, stretch=1)

        # Comparison info
        self.comparison_label = QLabel()
        self.comparison_label.setStyleSheet(
            "background-color: #f0f0f0; padding: 5px; border-radius: 3px;"
        )
        self.comparison_label.setWordWrap(True)
        self.comparison_label.hide()
        layout.addWidget(self.comparison_label)

    def set_images(self, images: List[ImageFile]):
        """
        Set images for comparison.

        Args:
            images: List of images to compare (uses first two).
        """
        if len(images) >= 1:
            self.preview1.set_image(images[0])
        else:
            self.preview1.set_image(None)

        if len(images) >= 2:
            self.preview2.set_image(images[1])
            self._show_comparison(images[0], images[1])
        else:
            self.preview2.set_image(None)
            self.comparison_label.hide()

    def _show_comparison(self, img1: ImageFile, img2: ImageFile):
        """Show comparison between two images."""
        differences = []

        # Resolution comparison
        if img1.resolution != img2.resolution:
            if img1.resolution > img2.resolution:
                differences.append(f"Left has higher resolution")
            else:
                differences.append(f"Right has higher resolution")

        # Size comparison
        if img1.file_size != img2.file_size:
            if img1.file_size > img2.file_size:
                diff = img1.file_size - img2.file_size
                differences.append(f"Left is larger by {self._format_size(diff)}")
            else:
                diff = img2.file_size - img1.file_size
                differences.append(f"Right is larger by {self._format_size(diff)}")

        if differences:
            self.comparison_label.setText(" | ".join(differences))
            self.comparison_label.show()
        else:
            self.comparison_label.setText("Images appear identical")
            self.comparison_label.show()

    def clear(self):
        """Clear the preview panel."""
        self.preview1.set_image(None)
        self.preview2.set_image(None)
        self.comparison_label.hide()

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
