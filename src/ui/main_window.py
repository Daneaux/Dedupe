"""Main application window."""

from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSplitter, QMessageBox, QFileDialog,
    QMenuBar, QMenu, QLabel, QFrame, QStatusBar, QComboBox,
    QSlider, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction

from .directory_selector import DirectorySelector
from .progress_panel import ProgressPanel
from .results_view import ResultsView
from .image_preview import ImagePreviewPanel
from .session_picker import SessionPickerDialog

from ..core.scanner import ImageScanner
from ..core.deduplicator import Deduplicator
from ..core.file_operations import FileOperations
from ..utils.export import ResultsExporter
from ..utils.session import SessionManager
from ..models.duplicate_group import DuplicateGroup
from ..models.image_file import ImageFile


class ScanMode:
    """Scan mode enumeration."""
    INTRA_DIRECTORY = "intra_directory"  # Duplicates within same folder
    DATE_FOLDER_MERGE = "date_folder_merge"  # Duplicates across date-prefixed folders


class DetectionMode:
    """Detection algorithm enumeration."""
    EXACT = "exact"  # MD5 hash of pixel data - exact visual match
    PERCEPTUAL = "perceptual"  # Perceptual hash - finds compressed/resized duplicates


class HashAlgorithm:
    """Perceptual hash algorithm options."""
    PHASH = "phash"  # DCT-based perceptual hash (best general purpose)
    DHASH = "dhash"  # Difference hash (fast, gradient-based)
    AHASH = "ahash"  # Average hash (simple, less robust)
    WHASH = "whash"  # Wavelet hash (good balance)


class ScanWorker(QThread):
    """Worker thread for scanning and detecting duplicates."""

    progress = pyqtSignal(str, int, int)  # status, current, total
    groups_found = pyqtSignal(list)  # emits new groups as they're found
    finished = pyqtSignal()  # signals completion
    error = pyqtSignal(str)

    def __init__(
        self,
        directory: Path,
        scan_mode: str = ScanMode.INTRA_DIRECTORY,
        detection_mode: str = DetectionMode.EXACT,
        perceptual_threshold: int = 10,  # Sensitivity for perceptual mode (0=strict, 20=loose)
        hash_algorithm: str = HashAlgorithm.PHASH,  # Which perceptual hash algorithm to use
        hash_threshold: int = 0,  # 0 = exact duplicates only
        cnn_threshold: float = 0.85,
        use_cnn: bool = False,  # Disabled - too slow for large collections
        focus_intra_directory: bool = True,
        hash_method: str = "dhash"  # DHash is fastest
    ):
        super().__init__()
        self.directory = directory
        self.scan_mode = scan_mode
        self.detection_mode = detection_mode
        self.perceptual_threshold = perceptual_threshold
        self.hash_algorithm = hash_algorithm
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
            hash_method=hash_method,
            detection_mode=detection_mode,
            perceptual_threshold=perceptual_threshold,
            hash_algorithm=hash_algorithm
        )
        self._cancelled = False

    def run(self):
        """Run the scan and duplicate detection."""
        try:
            self._cancelled = False

            if self.scan_mode == ScanMode.DATE_FOLDER_MERGE:
                self._run_date_folder_merge()
            else:
                self._run_intra_directory()

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def _run_intra_directory(self):
        """Standard intra-directory duplicate scan."""
        # Phase 1: Scan for images
        self.progress.emit("Counting files...", 0, 0)

        images = self._scanner.scan(
            self.directory,
            progress_callback=lambda f, c, t: self.progress.emit(
                f"Scanning: {f}", c, t
            )
        )

        if not images:
            return

        # Phase 2: Find duplicates directory by directory
        self.progress.emit("Finding duplicates...", 0, len(images))

        self._find_duplicates_incremental(images)

    def _run_date_folder_merge(self):
        """Date folder merge mode: find duplicates across date-prefixed folders."""
        self.progress.emit("Finding date folder pairs...", 0, 0)

        groups = self._deduplicator.find_duplicates_across_date_folders(
            self.directory,
            progress_callback=lambda s, c, t: self.progress.emit(s, c, t)
        )

        if groups:
            self.groups_found.emit(groups)

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

    # Signal emitted when user wants to go back to drive manager
    back_to_drive_manager = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._groups: List[DuplicateGroup] = []
        self._root_dir: Optional[Path] = None
        self._worker: Optional[ScanWorker] = None
        self._scan_mode: str = ScanMode.INTRA_DIRECTORY
        self._detection_mode: str = DetectionMode.EXACT
        self._perceptual_threshold: int = 10  # Default sensitivity (0=strict, 20=loose)
        self._hash_algorithm: str = HashAlgorithm.PHASH  # Default algorithm
        self._session_manager = SessionManager()
        self._current_session_id: Optional[str] = None
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

        # Top navigation bar
        nav_layout = QHBoxLayout()

        self.back_button = QPushButton("← Back to Drive Manager")
        self.back_button.setStyleSheet(
            "QPushButton { padding: 6px 12px; }"
        )
        self.back_button.clicked.connect(self._go_back_to_drive_manager)
        nav_layout.addWidget(self.back_button)

        nav_layout.addStretch()

        layout.addLayout(nav_layout)

        # Directory selection
        dir_layout = QHBoxLayout()

        dir_label = QLabel("Root Directory:")
        dir_layout.addWidget(dir_label)

        self.dir_selector = DirectorySelector()
        dir_layout.addWidget(self.dir_selector, stretch=1)

        layout.addLayout(dir_layout)

        # Mode selection and scan button
        mode_layout = QHBoxLayout()

        mode_label = QLabel("Scan Mode:")
        mode_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Intra-Directory (duplicates within same folder)", ScanMode.INTRA_DIRECTORY)
        self.mode_combo.addItem("Date Folder Merge (2004/01-18 + 01-18 Vegas)", ScanMode.DATE_FOLDER_MERGE)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.setMinimumWidth(350)
        mode_layout.addWidget(self.mode_combo)

        mode_layout.addSpacing(20)

        detection_label = QLabel("Detection:")
        mode_layout.addWidget(detection_label)

        self.detection_combo = QComboBox()
        self.detection_combo.addItem("Exact (MD5 pixel data)", DetectionMode.EXACT)
        self.detection_combo.addItem("Perceptual (finds compressed/resized)", DetectionMode.PERCEPTUAL)
        self.detection_combo.currentIndexChanged.connect(self._on_detection_mode_changed)
        self.detection_combo.setMinimumWidth(250)
        mode_layout.addWidget(self.detection_combo)

        mode_layout.addSpacing(20)

        # Algorithm selector (only visible in perceptual mode)
        self.algorithm_label = QLabel("Algorithm:")
        self.algorithm_label.setVisible(False)
        mode_layout.addWidget(self.algorithm_label)

        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItem("pHash (DCT, best general)", HashAlgorithm.PHASH)
        self.algorithm_combo.addItem("dHash (gradient, fast)", HashAlgorithm.DHASH)
        self.algorithm_combo.addItem("aHash (average, simple)", HashAlgorithm.AHASH)
        self.algorithm_combo.addItem("wHash (wavelet)", HashAlgorithm.WHASH)
        self.algorithm_combo.currentIndexChanged.connect(self._on_algorithm_changed)
        self.algorithm_combo.setMinimumWidth(160)
        self.algorithm_combo.setVisible(False)
        mode_layout.addWidget(self.algorithm_combo)

        mode_layout.addSpacing(10)

        # Sensitivity control (only visible in perceptual mode)
        self.sensitivity_label = QLabel("Sensitivity:")
        self.sensitivity_label.setVisible(False)
        mode_layout.addWidget(self.sensitivity_label)

        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setMinimum(0)
        self.sensitivity_slider.setMaximum(20)
        self.sensitivity_slider.setValue(10)  # Default threshold
        self.sensitivity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sensitivity_slider.setTickInterval(5)
        self.sensitivity_slider.setMinimumWidth(120)
        self.sensitivity_slider.setVisible(False)
        self.sensitivity_slider.valueChanged.connect(self._on_sensitivity_changed)
        mode_layout.addWidget(self.sensitivity_slider)

        self.sensitivity_value_label = QLabel("10 (medium)")
        self.sensitivity_value_label.setMinimumWidth(80)
        self.sensitivity_value_label.setVisible(False)
        mode_layout.addWidget(self.sensitivity_value_label)

        mode_layout.addStretch()

        self.scan_button = QPushButton("Scan for Duplicates")
        self.scan_button.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-weight: bold; padding: 8px 16px; }"
        )
        self.scan_button.clicked.connect(self._start_scan)
        mode_layout.addWidget(self.scan_button)

        layout.addLayout(mode_layout)

        # Progress panel
        self.progress_panel = ProgressPanel()
        self.progress_panel.cancel_requested.connect(self._cancel_scan)
        layout.addWidget(self.progress_panel)

        # Main content splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Results view
        self.results_view = ResultsView()
        self.results_view.images_for_preview.connect(self._preview_images)
        self.results_view.trash_group_requested.connect(self._trash_group)
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

        self.merge_button = QPushButton("Merge Folders (Move Duplicates to Trash)")
        self.merge_button.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; }"
        )
        self.merge_button.clicked.connect(self._merge_folders)
        self.merge_button.setEnabled(False)
        self.merge_button.setVisible(False)  # Only show in merge mode
        action_layout.addWidget(self.merge_button)

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

        sessions_action = QAction("Manage Sessions...", self)
        sessions_action.triggered.connect(self._show_sessions)
        file_menu.addAction(sessions_action)

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

    def _go_back_to_drive_manager(self):
        """Go back to the drive manager screen."""
        # Check if there's an active scan
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Scan in Progress",
                "A scan is currently in progress. Are you sure you want to go back?\n\n"
                "The scan will be cancelled.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._cancel_scan()

        self.hide()
        self.back_to_drive_manager.emit()

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

    def _on_mode_changed(self, index: int):
        """Handle scan mode change."""
        self._scan_mode = self.mode_combo.currentData()

        # Show/hide appropriate buttons based on mode
        is_merge_mode = self._scan_mode == ScanMode.DATE_FOLDER_MERGE
        self.merge_button.setVisible(is_merge_mode)
        self.move_button.setVisible(not is_merge_mode)

    def _on_detection_mode_changed(self, index: int):
        """Handle detection mode change."""
        self._detection_mode = self.detection_combo.currentData()

        # Show/hide perceptual options based on detection mode
        is_perceptual = self._detection_mode == DetectionMode.PERCEPTUAL
        self.algorithm_label.setVisible(is_perceptual)
        self.algorithm_combo.setVisible(is_perceptual)
        self.sensitivity_label.setVisible(is_perceptual)
        self.sensitivity_slider.setVisible(is_perceptual)
        self.sensitivity_value_label.setVisible(is_perceptual)

    def _on_algorithm_changed(self, index: int):
        """Handle hash algorithm change."""
        self._hash_algorithm = self.algorithm_combo.currentData()

    def _on_sensitivity_changed(self, value: int):
        """Handle sensitivity slider change."""
        self._perceptual_threshold = value

        # Update label with descriptive text
        if value <= 3:
            desc = "strict"
        elif value <= 7:
            desc = "tight"
        elif value <= 12:
            desc = "medium"
        elif value <= 16:
            desc = "loose"
        else:
            desc = "very loose"

        self.sensitivity_value_label.setText(f"{value} ({desc})")

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

        # Show progress based on mode
        if self._scan_mode == ScanMode.DATE_FOLDER_MERGE:
            self.progress_panel.start("Finding date folder pairs to merge...")
        else:
            self.progress_panel.start("Scanning for duplicate images...")

        # Create and start worker with selected modes
        self._worker = ScanWorker(
            directory,
            scan_mode=self._scan_mode,
            detection_mode=self._detection_mode,
            perceptual_threshold=self._perceptual_threshold,
            hash_algorithm=self._hash_algorithm
        )
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
            if self._scan_mode == ScanMode.DATE_FOLDER_MERGE:
                self.merge_button.setEnabled(True)
            else:
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

            # Save session
            self._save_session()
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

    def _merge_folders(self):
        """Merge date folders by deleting duplicates and cleaning up empty folders."""
        if not self._groups:
            QMessageBox.information(
                self,
                "No Results",
                "No duplicate groups to merge. Run a scan first."
            )
            return

        # Count what will happen
        total_to_delete = sum(
            len([img for img in g.images if img != g.suggested_keep])
            for g in self._groups
        )

        # Get folders that might become empty
        source_folders = set()
        for group in self._groups:
            for img in group.images:
                if img != group.suggested_keep and group.target_directory:
                    if img.directory != group.target_directory:
                        source_folders.add(img.directory)

        # Confirm
        msg = f"This will:\n\n"
        msg += f"• Move {total_to_delete} duplicate files to Trash\n"
        msg += f"• Keep files with the shortest names\n"
        if source_folders:
            msg += f"• Potentially empty {len(source_folders)} source folder(s)\n"
        msg += f"\nFiles can be recovered from Trash if needed."

        reply = QMessageBox.question(
            self,
            "Confirm Merge",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Second confirm
        reply = QMessageBox.warning(
            self,
            "Confirm",
            f"Move {total_to_delete} duplicate files to Trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform merge
        ops = FileOperations()
        results, empty_dirs = ops.move_to_target_directories(
            self._groups,
            delete_duplicates=True
        )

        # Report results
        success = sum(1 for _, _, ok, _ in results if ok)
        failed = len(results) - success

        # Ask about removing empty directories
        if empty_dirs:
            reply = QMessageBox.question(
                self,
                "Remove Empty Folders?",
                f"Found {len(empty_dirs)} empty folder(s) after merge:\n\n"
                + "\n".join(f"• {d.name}" for d in empty_dirs[:5])
                + ("\n..." if len(empty_dirs) > 5 else "")
                + "\n\nRemove these empty folders?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                dir_results = ops.remove_empty_directories(empty_dirs)
                dirs_removed = sum(1 for _, ok, _ in dir_results if ok)
                QMessageBox.information(
                    self,
                    "Merge Complete",
                    f"Moved {success} duplicate files to Trash.\n"
                    f"Removed {dirs_removed} empty folders."
                    + (f"\n{failed} files failed." if failed > 0 else "")
                )
            else:
                QMessageBox.information(
                    self,
                    "Merge Complete",
                    f"Moved {success} duplicate files to Trash."
                    + (f"\n{failed} files failed." if failed > 0 else "")
                )
        else:
            if failed > 0:
                QMessageBox.warning(
                    self,
                    "Merge Complete",
                    f"Moved {success} files to Trash.\n{failed} files failed."
                )
            else:
                QMessageBox.information(
                    self,
                    "Merge Complete",
                    f"Successfully moved {success} duplicate files to Trash."
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

    def _trash_group(self, group_id: int):
        """Move marked files from a specific group to Trash."""
        # Get the group
        group = self.results_view.get_group_by_id(group_id)
        if not group:
            return

        # Get marked files for this group
        marked_files = self.results_view.get_marked_for_deletion_in_group(group_id)

        if not marked_files:
            QMessageBox.information(
                self,
                "No Files Marked",
                "No files are marked for deletion in this group.\n"
                "Check the files you want to move to Trash."
            )
            return

        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Trash",
            f"Move {len(marked_files)} file(s) to Trash?\n\n"
            + "\n".join(f"• {Path(f).name}" for f in marked_files[:5])
            + ("\n..." if len(marked_files) > 5 else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Perform move to trash
        ops = FileOperations()
        results = ops.move_to_trash(marked_files)

        # Count results
        success = sum(1 for _, ok, _ in results if ok)
        failed = len(results) - success

        if failed > 0:
            QMessageBox.warning(
                self,
                "Trash Complete",
                f"Moved {success} files to Trash.\n{failed} files failed."
            )
        else:
            QMessageBox.information(
                self,
                "Trash Complete",
                f"Moved {success} file(s) to Trash."
            )

        # Remove the group from display if all marked files were trashed
        if success > 0:
            # Remove group from results view
            self.results_view.remove_group(group_id)

            # Also remove from internal groups list
            self._groups = [g for g in self._groups if g.group_id != group_id]

            # Update status
            remaining = len(self._groups)
            if remaining == 0:
                self.status_bar.showMessage("All duplicate groups processed!")
                # Delete session when all groups are processed
                if self._current_session_id:
                    self._session_manager.delete_session(self._current_session_id)
                    self._current_session_id = None
            else:
                self.status_bar.showMessage(f"{remaining} duplicate group(s) remaining")
                # Save session after changes
                self._save_session()

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

    def _show_sessions(self):
        """Show session management dialog."""
        picker = SessionPickerDialog(self)

        def on_session_selected(session_id: str):
            picker.accept()
            self.load_session(session_id)

        picker.session_selected.connect(on_session_selected)
        picker.new_scan_requested.connect(picker.accept)

        picker.exec()

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

    def _save_session(self):
        """Save the current session state."""
        if not self._root_dir or not self._groups:
            return

        try:
            selected = self.results_view._selected_for_action
            self._current_session_id = self._session_manager.save_session(
                root_directory=self._root_dir,
                groups=self._groups,
                scan_mode=self._scan_mode,
                detection_mode=self._detection_mode,
                hash_algorithm=self._hash_algorithm,
                perceptual_threshold=self._perceptual_threshold,
                selected_for_action=selected
            )
        except Exception as e:
            print(f"Error saving session: {e}")

    def load_session(self, session_id: str) -> bool:
        """Load a previously saved session."""
        session_data = self._session_manager.load_session(session_id)

        if not session_data:
            QMessageBox.warning(
                self,
                "Session Not Found",
                "Could not load the selected session. It may have been deleted."
            )
            return False

        info = session_data["info"]
        groups = session_data["groups"]
        selected = session_data["selected_for_action"]

        # Check if directory still exists
        root_dir = Path(info.root_directory)
        if not root_dir.exists():
            QMessageBox.warning(
                self,
                "Directory Not Found",
                f"The directory no longer exists:\n{info.root_directory}"
            )
            return False

        # Restore state
        self._root_dir = root_dir
        self._groups = groups
        self._scan_mode = info.scan_mode
        self._detection_mode = info.detection_mode
        self._hash_algorithm = info.hash_algorithm
        self._perceptual_threshold = info.perceptual_threshold
        self._current_session_id = session_id

        # Update UI to reflect loaded settings
        self.dir_selector.set_directory(str(root_dir))

        # Update mode combo
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == self._scan_mode:
                self.mode_combo.setCurrentIndex(i)
                break

        # Update detection combo
        for i in range(self.detection_combo.count()):
            if self.detection_combo.itemData(i) == self._detection_mode:
                self.detection_combo.setCurrentIndex(i)
                break

        # Update algorithm combo
        for i in range(self.algorithm_combo.count()):
            if self.algorithm_combo.itemData(i) == self._hash_algorithm:
                self.algorithm_combo.setCurrentIndex(i)
                break

        # Update sensitivity slider
        self.sensitivity_slider.setValue(self._perceptual_threshold)

        # Show/hide perceptual controls
        is_perceptual = self._detection_mode == DetectionMode.PERCEPTUAL
        self.algorithm_label.setVisible(is_perceptual)
        self.algorithm_combo.setVisible(is_perceptual)
        self.sensitivity_label.setVisible(is_perceptual)
        self.sensitivity_slider.setVisible(is_perceptual)
        self.sensitivity_value_label.setVisible(is_perceptual)

        # Display results
        self.results_view.clear()
        self.results_view.set_groups(groups)

        # Restore selection state
        self.results_view._selected_for_action = selected
        self.results_view._update_selected_count()

        # Update checkboxes for restored selection
        for i in range(self.results_view.tree.topLevelItemCount()):
            group_item = self.results_view.tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data[0] == "image":
                    path = data[1]
                    if path in selected:
                        child.setCheckState(0, Qt.CheckState.Checked)

        # Enable buttons
        if self._scan_mode == ScanMode.DATE_FOLDER_MERGE:
            self.merge_button.setEnabled(True)
            self.merge_button.setVisible(True)
            self.move_button.setVisible(False)
        else:
            self.move_button.setEnabled(True)
            self.move_button.setVisible(True)
            self.merge_button.setVisible(False)

        self.delete_button.setEnabled(True)
        self.export_button.setEnabled(True)

        # Update status
        total_files = sum(len(g) for g in groups)
        savings = sum(g.potential_savings for g in groups)
        self.status_bar.showMessage(
            f"Resumed: {len(groups)} groups with {total_files} files. "
            f"Potential savings: {self._format_size(savings)}"
        )

        return True

    def load_volume_duplicates(self, volume_uuid: str):
        """Load and find duplicates for a specific volume.

        This is called from the drive manager when user selects 'Find Duplicates'.
        """
        from ..core.database import DatabaseManager

        db = DatabaseManager.get_instance()
        vol = db.get_volume_by_uuid(volume_uuid)

        if not vol:
            QMessageBox.warning(
                self,
                "Volume Not Found",
                "The selected volume was not found in the database."
            )
            return

        # Set the root directory to the volume mount point
        mount_point = vol.get('mount_point')
        if mount_point:
            self.dir_selector.set_directory(mount_point)
            self._root_dir = Path(mount_point)

        # Update status
        file_count = vol.get('file_count', 0)
        self.status_bar.showMessage(
            f"Volume: {vol.get('name')} - {file_count:,} files indexed. "
            "Click 'Scan for Duplicates' to find duplicates."
        )

    def load_cross_drive_duplicates(self, volume_uuids: list):
        """Load and find duplicates across multiple volumes.

        This is called from the drive manager for cross-drive duplicate detection.
        """
        from ..core.database import DatabaseManager

        db = DatabaseManager.get_instance()

        # Get volume names for display
        vol_names = []
        for uuid in volume_uuids:
            vol = db.get_volume_by_uuid(uuid)
            if vol:
                vol_names.append(vol.get('name', 'Unknown'))

        self.status_bar.showMessage(
            f"Cross-drive mode: {', '.join(vol_names)}. "
            "Finding duplicates across all indexed drives..."
        )

        # TODO: Implement cross-drive duplicate detection
        # This would query the database for files with matching hashes
        # across different volumes

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
