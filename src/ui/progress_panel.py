"""Progress panel for displaying scan/processing status."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal


class ProgressPanel(QWidget):
    """Panel showing scanning/processing progress."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        """Set up the progress panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Status frame
        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        frame_layout = QVBoxLayout(frame)

        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-weight: bold;")
        frame_layout.addWidget(self.status_label)

        # Current file label
        self.current_file_label = QLabel("")
        self.current_file_label.setStyleSheet("color: gray; font-size: 11px;")
        self.current_file_label.setWordWrap(True)
        frame_layout.addWidget(self.current_file_label)

        # Progress bar and count
        progress_layout = QHBoxLayout()

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar, stretch=1)

        self.count_label = QLabel("0 / 0")
        self.count_label.setMinimumWidth(80)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_layout.addWidget(self.count_label)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel)
        progress_layout.addWidget(self.cancel_button)

        frame_layout.addLayout(progress_layout)

        layout.addWidget(frame)

    def _on_cancel(self):
        """Handle cancel button click."""
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling...")
        self.cancel_requested.emit()

    def start(self, status: str = "Scanning..."):
        """Start showing progress."""
        self.status_label.setText(status)
        self.current_file_label.setText("")
        self.progress_bar.setValue(0)
        self.count_label.setText("0 / 0")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.show()

    def update_progress(self, current_file: str, processed: int, total: int):
        """
        Update progress display.

        Args:
            current_file: Current file being processed.
            processed: Number of files processed.
            total: Total number of files.
        """
        # Update current file (show just filename and parent)
        if current_file:
            from pathlib import Path
            path = Path(current_file)
            display = f".../{path.parent.name}/{path.name}" if len(str(path)) > 50 else str(path)
            self.current_file_label.setText(display)

        # Update count
        self.count_label.setText(f"{processed:,} / {total:,}")

        # Update progress bar
        if total > 0:
            percent = int((processed / total) * 100)
            self.progress_bar.setValue(percent)
        else:
            self.progress_bar.setValue(0)

    def set_status(self, status: str):
        """Set the status message."""
        self.status_label.setText(status)

    def finish(self, message: str = "Complete"):
        """Mark progress as complete."""
        self.status_label.setText(message)
        self.progress_bar.setValue(100)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Done")

    def reset(self):
        """Reset the panel."""
        self.status_label.setText("Ready")
        self.current_file_label.setText("")
        self.progress_bar.setValue(0)
        self.count_label.setText("0 / 0")
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.hide()
