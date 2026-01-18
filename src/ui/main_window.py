"""Main application window."""

from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSplitter, QMessageBox, QFileDialog,
    QMenuBar, QMenu, QLabel, QFrame, QStatusBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction

from .directory_selector import DirectorySelector
from .progress_panel import ProgressPanel
from .results_view import ResultsView
from .image_preview import ImagePreviewPanel

from ..core.scanner import ImageScanner
from ..core.deduplicator import Deduplicator
from ..core.file_operations import FileOperations
from ..utils.export import ResultsExporter
from ..models.duplicate_group import DuplicateGroup
from ..models.image_file import ImageFile


class ScanWorker(QThread):
    """Worker thread for scanning and detecting duplicates."""

    progress = pyqtSignal(str, int, int)  # status, current, total
    groups_found = pyqtSignal(list)  # emits new groups as they're found
    finished = pyqtSignal()  # signals completion
    error = pyqtSignal(str)

    def __init__(
        self,
        directory: Path,
        hash_threshold: int = 0,  # 0 = exact duplicates only
        cnn_threshold: float = 0.85,
        use_cnn: bool = False,  # Disabled - too slow for large collections
        focus_intra_directory: bool = True,
        hash_method: str = "dhash"  # DHash is fastest
    ):
        super().__init__()
        self.directory = directory
        self.hash_threshold = hash_threshold
        self.cnn_threshold = cnn_threshold
        self.use_cnn = use_cnn
        self.focus_intra_directory = focus_intra_directory
        self._scanner = ImageScanner()
        self._deduplicator = Deduplicator(
            hash_threshold=hash_threshold,
            cnn_threshold=cnn_threshold,
            use_cnn=use_cnn,
            focus_intra_directory=focus_intra_directory,
            hash_method=hash_method
        )
        self._cancelled = False

    def run(self):
        """Run the scan and duplicate detection."""
        try:
            self._cancelled = False

            # Phase 1: Scan for images
            self.progress.emit("Counting files...", 0, 0)

            images = self._scanner.scan(
                self.directory,
                progress_callback=lambda f, c, t: self.progress.emit(
                    f"Scanning: {f}", c, t
                )
            )

            if not images:
                self.finished.emit()
                return

            # Phase 2: Find duplicates directory by directory
            self.progress.emit("Finding duplicates...", 0, len(images))

            self._find_duplicates_incremental(images)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def _find_duplicates_incremental(self, images: List[ImageFile]):
        """Find duplicates and emit results incrementally per directory."""
        from collections import defaultdict
        from ..core.deduplicator import normalize_extension

        # Group images by directory
        dir_groups = self._scanner.group_by_directory(images)

        total_dirs = len(dir_groups)
        processed_dirs = 0
        group_id = 0

        for directory, dir_images in dir_groups.items():
            if self._cancelled:
                break

            if len(dir_images) < 2:
                processed_dirs += 1
                continue

            self.progress.emit(
                f"Processing: {directory.name}",
                processed_dirs,
                total_dirs
            )

            # Group by extension type within this directory
            ext_groups: dict = defaultdict(list)
            for img in dir_images:
                norm_ext = normalize_extension(img.extension)
                ext_groups[norm_ext].append(img)

            # Process each extension group
            dir_duplicate_groups = []
            for ext, ext_images in ext_groups.items():
                if self._cancelled:
                    break

                if len(ext_images) < 2:
                    continue

                # Find duplicates within this directory + extension group
                new_groups = self._deduplicator._find_duplicates_in_set(
                    ext_images, group_id
                )

                for group in new_groups:
                    group.is_intra_directory = True
                    dir_duplicate_groups.append(group)
                    group_id += 1

            # Emit groups found in this directory immediately
            if dir_duplicate_groups:
                self.groups_found.emit(dir_duplicate_groups)

            processed_dirs += 1

        self.progress.emit("Complete", total_dirs, total_dirs)

    def cancel(self):
        """Cancel the operation."""
        self._cancelled = True
        self._scanner.cancel()
        self._deduplicator.cancel()


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self._groups: List[DuplicateGroup] = []
        self._root_dir: Optional[Path] = None
        self._worker: Optional[ScanWorker] = None
        self._setup_ui()
        self._setup_menu()

    def _setup_ui(self):
        """Set up the main window UI."""
        self.setWindowTitle("Duplicate Image Finder")
        self.setMinimumSize(1200, 800)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Directory selection
        dir_layout = QHBoxLayout()

        dir_label = QLabel("Root Directory:")
        dir_layout.addWidget(dir_label)

        self.dir_selector = DirectorySelector()
        dir_layout.addWidget(self.dir_selector, stretch=1)

        self.scan_button = QPushButton("Scan for Duplicates")
        self.scan_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 8px 16px; }"
        )
        self.scan_button.clicked.connect(self._start_scan)
        dir_layout.addWidget(self.scan_button)

        layout.addLayout(dir_layout)

        # Progress panel
        self.progress_panel = ProgressPanel()
        self.progress_panel.cancel_requested.connect(self._cancel_scan)
        layout.addWidget(self.progress_panel)

        # Main content splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Results view
        self.results_view = ResultsView()
        self.results_view.images_for_preview.connect(self._preview_images)
        self.splitter.addWidget(self.results_view)

        # Image preview
        self.preview_panel = ImagePreviewPanel()
        self.splitter.addWidget(self.preview_panel)

        # Set initial sizes (60/40 split)
        self.splitter.setSizes([700, 500])

        layout.addWidget(self.splitter, stretch=1)

        # Action buttons
        action_layout = QHBoxLayout()

        self.move_button = QPushButton("Move Selected to _duplicates")
        self.move_button.clicked.connect(self._move_selected)
        self.move_button.setEnabled(False)
        action_layout.addWidget(self.move_button)

        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; }"
        )
        self.delete_button.clicked.connect(self._delete_selected)
        self.delete_button.setEnabled(False)
        action_layout.addWidget(self.delete_button)

        action_layout.addStretch()

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export_csv)
        self.export_button.setEnabled(False)
        action_layout.addWidget(self.export_button)

        layout.addLayout(action_layout)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready - Select a directory to scan")

    def _setup_menu(self):
        """Set up the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        open_action = QAction("Open Directory...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._browse_directory)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        export_csv_action = QAction("Export as CSV...", self)
        export_csv_action.setShortcut("Ctrl+E")
        export_csv_action.triggered.connect(self._export_csv)
        file_menu.addAction(export_csv_action)

        export_summary_action = QAction("Export Summary...", self)
        export_summary_action.triggered.connect(self._export_summary)
        file_menu.addAction(export_summary_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Edit menu
        edit_menu = menubar.addMenu("Edit")

        select_keepers_action = QAction("Select All Keepers", self)
        select_keepers_action.triggered.connect(
            self.results_view._select_all_keepers
        )
        edit_menu.addAction(select_keepers_action)

        select_deletes_action = QAction("Select Suggested Deletes", self)
        select_deletes_action.triggered.connect(
            self.results_view._select_suggested_deletes
        )
        edit_menu.addAction(select_deletes_action)

        clear_action = QAction("Clear Selection", self)
        clear_action.triggered.connect(self.results_view._clear_selection)
        edit_menu.addAction(clear_action)

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _browse_directory(self):
        """Open directory browser."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Directory to Scan",
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            self.dir_selector.set_directory(directory)

    def _start_scan(self):
        """Start the scan operation."""
        directory = self.dir_selector.get_directory()

        if not directory:
            QMessageBox.warning(
                self,
                "Invalid Directory",
                "Please select a valid directory to scan."
            )
            return

        self._root_dir = directory

        # Clear previous results
        self._groups = []
        self.results_view.clear()
        self.preview_panel.clear()

        # Disable buttons
        self.scan_button.setEnabled(False)
        self.move_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.export_button.setEnabled(False)

        # Show progress
        self.progress_panel.start("Scanning for duplicate images...")

        # Create and start worker
        self._worker = ScanWorker(directory)
        self._worker.progress.connect(self._on_progress)
        self._worker.groups_found.connect(self._on_groups_found)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _cancel_scan(self):
        """Cancel the current scan."""
        if self._worker:
            self._worker.cancel()
            self._worker.wait()
            self._worker = None

        self.progress_panel.reset()
        self.scan_button.setEnabled(True)
        self.status_bar.showMessage("Scan cancelled")

    def _on_progress(self, status: str, current: int, total: int):
        """Handle progress update from worker."""
        self.progress_panel.update_progress(status, current, total)

    def _on_groups_found(self, new_groups: List[DuplicateGroup]):
        """Handle new duplicate groups found (incremental update)."""
        self._groups.extend(new_groups)
        self.results_view.add_groups(new_groups)

        # Enable buttons as soon as we have results
        if self._groups:
            self.move_button.setEnabled(True)
            self.delete_button.setEnabled(True)
            self.export_button.setEnabled(True)

        # Update status bar with running totals
        total_files = sum(len(g) for g in self._groups)
        savings = sum(g.potential_savings for g in self._groups)
        self.status_bar.showMessage(
            f"Found {len(self._groups)} groups with {total_files} files so far. "
            f"Potential savings: {self._format_size(savings)}"
        )

    def _on_scan_finished(self):
        """Handle scan completion."""
        self._worker = None

        # Update UI
        self.progress_panel.finish(f"Found {len(self._groups)} duplicate groups")

        # Enable buttons
        self.scan_button.setEnabled(True)

        if self._groups:
            total_files = sum(len(g) for g in self._groups)
            savings = sum(g.potential_savings for g in self._groups)
            self.status_bar.showMessage(
                f"Complete: {len(self._groups)} groups with {total_files} files. "
                f"Potential savings: {self._format_size(savings)}"
            )
        else:
            self.status_bar.showMessage("No duplicates found")

    def _on_scan_error(self, error: str):
        """Handle scan error."""
        self._worker = None
        self.progress_panel.reset()
        self.scan_button.setEnabled(True)

        QMessageBox.critical(
            self,
            "Scan Error",
            f"An error occurred during scanning:\n\n{error}"
        )
        self.status_bar.showMessage("Scan failed")

    def _preview_images(self, images: List[ImageFile]):
        """Preview selected images."""
        self.preview_panel.set_images(images)

    def _move_selected(self):
        """Move selected files to _duplicates folder."""
        selected = self.results_view.get_selected_for_action()

        if not selected:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select files to move by checking their checkboxes."
            )
            return

        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Move",
            f"Move {len(selected)} files to _duplicates folder?\n\n"
            f"Files will be moved to: {self._root_dir}/_duplicates/",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform move
        ops = FileOperations()
        results = ops.move_to_parallel_structure(selected, self._root_dir)

        # Report results
        success = sum(1 for _, _, ok, _ in results if ok)
        failed = len(results) - success

        if failed > 0:
            QMessageBox.warning(
                self,
                "Move Complete",
                f"Moved {success} files successfully.\n{failed} files failed."
            )
        else:
            QMessageBox.information(
                self,
                "Move Complete",
                f"Successfully moved {success} files to _duplicates folder."
            )

        # Refresh results
        self._start_scan()

    def _delete_selected(self):
        """Delete selected files."""
        selected = self.results_view.get_selected_for_action()

        if not selected:
            QMessageBox.information(
                self,
                "No Selection",
                "Please select files to delete by checking their checkboxes."
            )
            return

        # Confirm with strong warning
        reply = QMessageBox.warning(
            self,
            "Confirm Delete",
            f"Permanently delete {len(selected)} files?\n\n"
            "This action cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Double confirm
        reply = QMessageBox.critical(
            self,
            "Final Confirmation",
            f"Are you absolutely sure you want to delete these {len(selected)} files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform delete
        ops = FileOperations()
        results = ops.delete_files(selected)

        # Report results
        success = sum(1 for _, ok, _ in results if ok)
        failed = len(results) - success

        if failed > 0:
            QMessageBox.warning(
                self,
                "Delete Complete",
                f"Deleted {success} files successfully.\n{failed} files failed."
            )
        else:
            QMessageBox.information(
                self,
                "Delete Complete",
                f"Successfully deleted {success} files."
            )

        # Refresh results
        self._start_scan()

    def _export_csv(self):
        """Export results to CSV."""
        if not self._groups:
            QMessageBox.information(
                self,
                "No Results",
                "No duplicate groups to export. Run a scan first."
            )
            return

        # Get save path
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            str(Path.home() / "duplicates.csv"),
            "CSV Files (*.csv)"
        )

        if not path:
            return

        exporter = ResultsExporter()
        success = exporter.export_to_csv(self._groups, Path(path))

        if success:
            QMessageBox.information(
                self,
                "Export Complete",
                f"Results exported to:\n{path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Export Failed",
                "Failed to export results. Check file permissions."
            )

    def _export_summary(self):
        """Export summary report."""
        if not self._groups:
            QMessageBox.information(
                self,
                "No Results",
                "No duplicate groups to export. Run a scan first."
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Summary",
            str(Path.home() / "duplicates_summary.txt"),
            "Text Files (*.txt)"
        )

        if not path:
            return

        exporter = ResultsExporter()
        success = exporter.export_summary(
            self._groups, Path(path), self._root_dir
        )

        if success:
            QMessageBox.information(
                self,
                "Export Complete",
                f"Summary exported to:\n{path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Export Failed",
                "Failed to export summary. Check file permissions."
            )

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Duplicate Image Finder",
            "Duplicate Image Finder v1.0\n\n"
            "Find and manage duplicate images using\n"
            "perceptual hashing and deep learning.\n\n"
            "Built with PyQt6 and imagededup."
        )

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def closeEvent(self, event):
        """Handle window close."""
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Scan in Progress",
                "A scan is currently running. Cancel and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._worker.cancel()
                self._worker.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
