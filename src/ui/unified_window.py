"""Unified main window with tabbed interface for Dedupe application."""

from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Set

import platform
import subprocess

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QFrame,
    QFileDialog, QProgressDialog, QMessageBox, QSplitter,
    QGroupBox, QRadioButton, QButtonGroup, QComboBox, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QAbstractItemView, QSizePolicy,
    QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QBrush, QColor, QCursor

from ..core.database import DatabaseManager
from ..core.volume_manager import VolumeManager, VolumeInfo
from ..core.file_scanner import FileScanner, ScanStats
from ..core.deduplicator import Deduplicator
from ..models.duplicate_group import DuplicateGroup


# ============================================================================
# EXCLUDED PATHS DIALOG
# ============================================================================

class ExcludedPathsDialog(QDialog):
    """Dialog for managing excluded paths for a volume."""

    def __init__(self, volume_id: int, volume_name: str, mount_point: str, parent=None):
        super().__init__(parent)
        self.volume_id = volume_id
        self.volume_name = volume_name
        self.mount_point = Path(mount_point)
        self.db = DatabaseManager.get_instance()
        self._setup_ui()
        self._load_paths()

    def _setup_ui(self):
        self.setWindowTitle(f"Excluded Paths - {self.volume_name}")
        self.setMinimumSize(600, 400)
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"Excluded Paths for {self.volume_name}")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        subtitle = QLabel(
            "These directories will be skipped during scanning. "
            "Paths are relative to the volume root."
        )
        subtitle.setStyleSheet("color: #666; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Path list
        self.path_list = QListWidget()
        self.path_list.setAlternatingRowColors(True)
        self.path_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.path_list, stretch=1)

        # Stats label
        self.stats_label = QLabel("0 excluded paths")
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # Button row
        button_row = QHBoxLayout()

        self.add_btn = QPushButton("Add Path...")
        self.add_btn.clicked.connect(self._add_path)
        button_row.addWidget(self.add_btn)

        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.remove_btn.setEnabled(False)
        button_row.addWidget(self.remove_btn)

        button_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

        # Connect selection change
        self.path_list.itemSelectionChanged.connect(self._on_selection_changed)

    def _load_paths(self):
        """Load excluded paths from database."""
        self.path_list.clear()
        paths = self.db.get_excluded_paths(self.volume_id)

        for path in paths:
            item = QListWidgetItem(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            # Show full path in tooltip
            full_path = self.mount_point / path
            item.setToolTip(str(full_path))
            self.path_list.addItem(item)

        self._update_stats()

    def _update_stats(self):
        """Update the stats label."""
        count = self.path_list.count()
        self.stats_label.setText(f"{count} excluded path{'s' if count != 1 else ''}")

    def _on_selection_changed(self):
        """Handle selection change."""
        has_selection = len(self.path_list.selectedItems()) > 0
        self.remove_btn.setEnabled(has_selection)

    def _add_path(self):
        """Add a new excluded path."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Directory to Exclude",
            str(self.mount_point),
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder:
            return

        folder_path = Path(folder)

        # Verify the path is under the volume mount point
        try:
            relative_path = folder_path.relative_to(self.mount_point)
            relative_str = str(relative_path)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Path",
                f"The selected directory is not on this volume.\n\n"
                f"Volume: {self.mount_point}\n"
                f"Selected: {folder}"
            )
            return

        # Add to database
        if self.db.add_excluded_path(self.volume_id, relative_str):
            self._load_paths()
        else:
            QMessageBox.information(
                self,
                "Already Excluded",
                f"This path is already in the excluded list:\n{relative_str}"
            )

    def _remove_selected(self):
        """Remove selected paths from exclusion list."""
        selected = self.path_list.selectedItems()
        if not selected:
            return

        count = len(selected)
        reply = QMessageBox.question(
            self,
            "Remove Excluded Paths",
            f"Remove {count} path{'s' if count != 1 else ''} from the exclusion list?\n\n"
            "These directories will be scanned on the next scan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            for item in selected:
                path = item.data(Qt.ItemDataRole.UserRole)
                self.db.remove_excluded_path(self.volume_id, path)
            self._load_paths()


# ============================================================================
# DRIVES TAB
# ============================================================================

class DriveItemWidget(QWidget):
    """Custom widget for displaying drive info in the list."""

    def __init__(self, volume_info: VolumeInfo, db_info: Optional[dict], parent=None):
        super().__init__(parent)
        self.volume_info = volume_info
        self.db_info = db_info
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Top row: drive name and type
        top_row = QHBoxLayout()

        # Drive icon
        icon = "💾" if self.volume_info.is_internal else "💿"
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 24px;")
        top_row.addWidget(icon_label)

        # Drive name
        name_label = QLabel(self.volume_info.name)
        font = QFont()
        font.setBold(True)
        font.setPointSize(13)
        name_label.setFont(font)
        top_row.addWidget(name_label)

        # Drive type badge
        type_text = "Internal" if self.volume_info.is_internal else "External"
        type_label = QLabel(type_text)
        type_label.setStyleSheet(
            "background-color: #e0e0e0; padding: 2px 8px; "
            "border-radius: 10px; font-size: 11px; color: #666;"
        )
        top_row.addWidget(type_label)

        top_row.addStretch()

        # Scan status badge
        if self.db_info:
            status = self.db_info.get('scan_status', 'never')
            if status == 'complete':
                status_text = "Scanned"
                status_style = "color: #2e7d32; font-weight: bold;"
            elif status == 'partial':
                status_text = "Partial"
                status_style = "color: #e65100; font-weight: bold;"
            else:
                status_text = "Not Scanned"
                status_style = "color: #757575;"
        else:
            status_text = "Not Scanned"
            status_style = "color: #757575;"

        # Check for paused scan
        if self.db_info and self.db_info.get('has_paused_scan'):
            status_text = "Paused"
            status_style = "color: #1565c0; font-weight: bold;"

        status_label = QLabel(status_text)
        status_label.setStyleSheet(f"{status_style} font-size: 11px;")
        top_row.addWidget(status_label)

        layout.addLayout(top_row)

        # Mount point
        mount_label = QLabel(str(self.volume_info.mount_point))
        mount_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(mount_label)

        # Stats row
        stats_row = QHBoxLayout()

        # Capacity
        capacity_text = (
            f"{self.volume_info.total_size_str} total, "
            f"{self.volume_info.available_size_str} free"
        )
        capacity_label = QLabel(capacity_text)
        capacity_label.setStyleSheet("color: #666;")
        stats_row.addWidget(capacity_label)

        stats_row.addStretch()

        # Indexed file count and last scan
        if self.db_info and (self.db_info.get('file_count') or 0) > 0:
            file_count = self.db_info['file_count']
            count_label = QLabel(f"{file_count:,} files indexed")
            count_label.setStyleSheet("color: #1565c0; font-weight: bold;")
            stats_row.addWidget(count_label)

            last_scan = self.db_info.get('last_scan_at')
            if last_scan:
                try:
                    scan_dt = datetime.fromisoformat(last_scan)
                    if scan_dt.date() == datetime.now().date():
                        scan_str = f"Today at {scan_dt.strftime('%I:%M %p')}"
                    else:
                        scan_str = scan_dt.strftime("%b %d, %Y")
                    scan_label = QLabel(f"Last scan: {scan_str}")
                    scan_label.setStyleSheet("color: #888; font-size: 11px;")
                    stats_row.addWidget(scan_label)
                except ValueError:
                    pass

        layout.addLayout(stats_row)


class ScanWorker(QThread):
    """Background worker for scanning drives."""

    progress = pyqtSignal(str, int, int)  # status, current, total
    finished = pyqtSignal(object)  # ScanStats
    paused = pyqtSignal(int, object)  # session_id, ScanStats
    error = pyqtSignal(str)

    def __init__(
        self,
        volume_info: VolumeInfo,
        scan_path: Optional[Path] = None,
        resume_session_id: Optional[int] = None,
        parent=None
    ):
        super().__init__(parent)
        self.volume_info = volume_info
        self.scan_path = scan_path
        self.resume_session_id = resume_session_id
        self._scanner: Optional[FileScanner] = None

    def run(self):
        try:
            self._scanner = FileScanner()

            def progress_callback(status: str, current: int, total: int):
                self.progress.emit(status, current, total)

            session_id, stats = self._scanner.scan_volume(
                volume_info=self.volume_info,
                progress_callback=progress_callback,
                scan_path=self.scan_path,
                resume_session_id=self.resume_session_id,
            )

            if self._scanner.is_paused:
                self.paused.emit(session_id, stats)
            else:
                self.finished.emit(stats)

        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        if self._scanner:
            self._scanner.cancel()

    def pause(self):
        if self._scanner:
            self._scanner.pause()

    @property
    def session_id(self) -> Optional[int]:
        if self._scanner:
            return self._scanner.session_id
        return None


class DrivesTab(QWidget):
    """Tab for managing drives and scanning."""

    scan_completed = pyqtSignal()  # Emitted when a scan completes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager.get_instance()
        self.volume_manager = VolumeManager()
        self.selected_volume: Optional[VolumeInfo] = None
        self._worker: Optional[ScanWorker] = None
        self._setup_ui()
        self.refresh_drives()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel("Connected Drives")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        subtitle = QLabel("Select a drive to scan and index for duplicate detection")
        subtitle.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(subtitle)

        # Drive list
        self.drive_list = QListWidget()
        self.drive_list.setSpacing(2)
        self.drive_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.drive_list.itemDoubleClicked.connect(self._on_double_click)
        self.drive_list.setAlternatingRowColors(True)
        layout.addWidget(self.drive_list, stretch=1)

        # Button row
        button_row = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_drives)
        button_row.addWidget(self.refresh_btn)

        button_row.addStretch()

        self.resume_btn = QPushButton("Resume Scan")
        self.resume_btn.clicked.connect(self._resume_scan)
        self.resume_btn.setEnabled(False)
        button_row.addWidget(self.resume_btn)

        self.scan_drive_btn = QPushButton("Scan Entire Drive")
        self.scan_drive_btn.clicked.connect(self._scan_drive)
        self.scan_drive_btn.setEnabled(False)
        button_row.addWidget(self.scan_drive_btn)

        self.scan_folder_btn = QPushButton("Scan Folder...")
        self.scan_folder_btn.clicked.connect(self._scan_folder)
        self.scan_folder_btn.setEnabled(False)
        button_row.addWidget(self.scan_folder_btn)

        layout.addLayout(button_row)

        # Second button row
        button_row2 = QHBoxLayout()

        self.remove_btn = QPushButton("Remove from Index")
        self.remove_btn.clicked.connect(self._remove_drive)
        self.remove_btn.setEnabled(False)
        button_row2.addWidget(self.remove_btn)

        button_row2.addStretch()

        self.excluded_paths_btn = QPushButton("Excluded Paths...")
        self.excluded_paths_btn.clicked.connect(self._manage_excluded_paths)
        self.excluded_paths_btn.setEnabled(False)
        button_row2.addWidget(self.excluded_paths_btn)

        layout.addLayout(button_row2)

    def refresh_drives(self):
        """Refresh the list of available drives."""
        self.drive_list.clear()
        self.selected_volume = None
        self._update_buttons()

        # Get paused scans
        paused_scans = self.db.get_paused_scan_sessions()
        paused_volume_ids = {s.get('volume_id') for s in paused_scans}

        # Get mounted volumes
        volumes = self.volume_manager.list_volumes()

        for vol in volumes:
            db_info = self.db.get_volume_by_uuid(vol.uuid)

            if db_info:
                db_info = dict(db_info)
                if db_info.get('id') in paused_volume_ids:
                    db_info['has_paused_scan'] = True

            item = QListWidgetItem()
            widget = DriveItemWidget(vol, db_info)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, vol)

            self.drive_list.addItem(item)
            self.drive_list.setItemWidget(item, widget)

    def _on_selection_changed(self):
        """Handle selection change."""
        selected = self.drive_list.selectedItems()
        self.selected_volume = selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
        self._update_buttons()

    def _update_buttons(self):
        """Update button states."""
        has_selection = self.selected_volume is not None
        self.scan_drive_btn.setEnabled(has_selection)
        self.scan_folder_btn.setEnabled(has_selection)
        self.excluded_paths_btn.setEnabled(has_selection)

        if has_selection:
            db_info = self.db.get_volume_by_uuid(self.selected_volume.uuid)
            file_count = (db_info.get('file_count') or 0) if db_info else 0
            self.remove_btn.setEnabled(file_count > 0)

            has_paused = self._get_paused_session(self.selected_volume.uuid) is not None
            self.resume_btn.setEnabled(has_paused)
        else:
            self.remove_btn.setEnabled(False)
            self.resume_btn.setEnabled(False)

    def _get_paused_session(self, volume_uuid: str) -> Optional[dict]:
        """Get paused session for a volume."""
        db_info = self.db.get_volume_by_uuid(volume_uuid)
        if not db_info:
            return None
        volume_id = db_info.get('id')
        paused = self.db.get_paused_scan_sessions(volume_id)
        return paused[0] if paused else None

    def _on_double_click(self, item: QListWidgetItem):
        """Handle double-click."""
        vol = item.data(Qt.ItemDataRole.UserRole)
        db_info = self.db.get_volume_by_uuid(vol.uuid)
        if db_info and (db_info.get('file_count') or 0) > 0:
            # Already scanned - could switch to duplicates tab
            pass
        else:
            self._scan_drive()

    def _scan_drive(self):
        """Scan entire selected drive."""
        if self.selected_volume:
            self._start_scan(self.selected_volume, None)

    def _scan_folder(self):
        """Scan a specific folder."""
        if not self.selected_volume:
            return

        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder to Scan",
            str(self.selected_volume.mount_point),
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self._start_scan(self.selected_volume, Path(folder))

    def _resume_scan(self):
        """Resume a paused scan."""
        if not self.selected_volume:
            return

        paused = self._get_paused_session(self.selected_volume.uuid)
        if not paused:
            return

        scan_path = Path(paused['scan_path']) if paused.get('scan_path') else None
        self._start_scan(self.selected_volume, scan_path, paused['id'])

    def _start_scan(self, volume: VolumeInfo, scan_path: Optional[Path], resume_id: Optional[int] = None):
        """Start or resume a scan."""
        progress = QProgressDialog("Scanning...", "Pause", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        self._worker = ScanWorker(volume, scan_path, resume_id)

        def on_progress(status, current, total):
            if total > 0:
                progress.setValue(int((current / total) * 100))
                progress.setLabelText(f"Scanning: {status}\n{current:,} / {total:,}")
            else:
                progress.setLabelText(f"Counting: {status}")

        def on_finished(stats):
            progress.close()
            self._worker = None
            self.refresh_drives()
            self.scan_completed.emit()
            QMessageBox.information(self, "Scan Complete", f"Scan completed!\n\n{stats}")

        def on_paused(session_id, stats):
            progress.close()
            self._worker = None
            self.refresh_drives()
            QMessageBox.information(self, "Scan Paused", "Scan paused. You can resume later.")

        def on_error(error):
            progress.close()
            self._worker = None
            self.refresh_drives()
            QMessageBox.critical(self, "Error", f"Scan error:\n\n{error}")

        def on_cancel():
            if self._worker:
                self._worker.pause()

        self._worker.progress.connect(on_progress)
        self._worker.finished.connect(on_finished)
        self._worker.paused.connect(on_paused)
        self._worker.error.connect(on_error)
        progress.canceled.connect(on_cancel)

        self._worker.start()

    def _remove_drive(self):
        """Remove drive from index."""
        if not self.selected_volume:
            return

        db_info = self.db.get_volume_by_uuid(self.selected_volume.uuid)
        if not db_info:
            return

        reply = QMessageBox.question(
            self, "Remove Drive",
            f"Remove '{self.selected_volume.name}' from the index?\n\n"
            "This will delete all indexed data. Your files won't be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_volume(db_info['id'])
            self.refresh_drives()

    def _manage_excluded_paths(self):
        """Open dialog to manage excluded paths for the selected volume."""
        if not self.selected_volume:
            return

        # Get or create volume in database
        db_info = self.db.get_volume_by_uuid(self.selected_volume.uuid)
        if not db_info:
            # Volume not yet in database, add it
            volume_id = self.db.add_volume(
                uuid=self.selected_volume.uuid,
                name=self.selected_volume.name,
                mount_point=str(self.selected_volume.mount_point),
                is_internal=self.selected_volume.is_internal,
                total_size_bytes=self.selected_volume.total_bytes,
                filesystem=self.selected_volume.filesystem,
            )
        else:
            volume_id = db_info['id']

        dialog = ExcludedPathsDialog(
            volume_id=volume_id,
            volume_name=self.selected_volume.name,
            mount_point=str(self.selected_volume.mount_point),
            parent=self
        )
        dialog.exec()

    def get_indexed_volumes(self) -> List[dict]:
        """Get list of indexed volumes with file counts."""
        result = []
        for vol in self.db.get_all_volumes():
            if (vol.get('file_count') or 0) > 0:
                result.append(vol)
        return result


# ============================================================================
# FILE TYPES TAB
# ============================================================================

def open_directory_in_file_manager(directory_path: str):
    """Open a directory in the system file manager (Finder/Explorer)."""
    path = Path(directory_path)
    if not path.exists():
        return False

    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            subprocess.run(["explorer", str(path)], check=True)
        else:  # Linux and others
            subprocess.run(["xdg-open", str(path)], check=True)
        return True
    except subprocess.SubprocessError:
        return False


class DirectoryListItem(QListWidgetItem):
    """List item for directories that stores full path info."""

    def __init__(self, directory: str, volume_name: str, mount_point: str, file_count: int):
        # Build display text
        if directory == '/':
            display_dir = "(root)"
        else:
            display_dir = directory

        text = f"{display_dir}  ({file_count:,} files)"
        super().__init__(text)

        self.directory = directory
        self.volume_name = volume_name
        self.mount_point = mount_point
        self.file_count = file_count

        # Calculate full path
        if mount_point:
            if directory == '/':
                self.full_path = mount_point
            else:
                self.full_path = str(Path(mount_point) / directory.lstrip('/'))
        else:
            self.full_path = directory

        # Store data for retrieval
        self.setData(Qt.ItemDataRole.UserRole, self.full_path)
        self.setToolTip(f"Volume: {volume_name}\nPath: {self.full_path}\nFiles: {file_count:,}")


class ExtensionDirectoriesDialog(QDialog):
    """Dialog showing directories containing files with a specific extension."""

    def __init__(self, extension: str, parent=None):
        super().__init__(parent)
        self.extension = extension.lower().lstrip('.')
        self.db = DatabaseManager.get_instance()
        self._setup_ui()
        self._load_directories()

    def _setup_ui(self):
        self.setWindowTitle(f"Directories containing .{self.extension} files")
        self.setMinimumSize(600, 400)
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel(f"Directories containing .{self.extension} files")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        subtitle = QLabel("Double-click a directory to open it in your file manager")
        subtitle.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(subtitle)

        # Directory list
        self.dir_list = QListWidget()
        self.dir_list.setAlternatingRowColors(True)
        self.dir_list.itemDoubleClicked.connect(self._on_double_click)
        self.dir_list.setStyleSheet("""
            QListWidget::item {
                padding: 8px;
            }
            QListWidget::item:hover {
                background-color: #e3f2fd;
            }
        """)
        layout.addWidget(self.dir_list, stretch=1)

        # Stats label
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # Button row
        button_row = QHBoxLayout()

        self.open_btn = QPushButton("Open Selected")
        self.open_btn.clicked.connect(self._open_selected)
        self.open_btn.setEnabled(False)
        button_row.addWidget(self.open_btn)

        button_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

        # Connect selection change
        self.dir_list.itemSelectionChanged.connect(self._on_selection_changed)

    def _load_directories(self):
        """Load directories from database."""
        directories = self.db.get_directories_by_extension(self.extension)

        total_files = 0
        total_dirs = len(directories)

        if not directories:
            # Show empty state message
            empty_item = QListWidgetItem(
                f"No indexed files with .{self.extension} extension found.\n\n"
                "This extension may not have been encountered during scanning,\n"
                "or all files with this extension have been deleted."
            )
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setForeground(QBrush(QColor("#666")))
            self.dir_list.addItem(empty_item)
            self.stats_label.setText(f"No .{self.extension} files found")
            return

        # Group by volume for better display
        current_volume = None

        for dir_info in directories:
            volume_name = dir_info['volume_name']

            # Add volume separator if new volume
            if volume_name != current_volume:
                current_volume = volume_name
                separator = QListWidgetItem(f"── {volume_name} ──")
                separator.setFlags(Qt.ItemFlag.NoItemFlags)  # Not selectable
                separator.setForeground(QBrush(QColor("#1565c0")))
                font = separator.font()
                font.setBold(True)
                separator.setFont(font)
                self.dir_list.addItem(separator)

            # Add directory item
            item = DirectoryListItem(
                directory=dir_info['directory'],
                volume_name=volume_name,
                mount_point=dir_info['mount_point'],
                file_count=dir_info['file_count']
            )
            self.dir_list.addItem(item)
            total_files += dir_info['file_count']

        self.stats_label.setText(
            f"{total_dirs} directories, {total_files:,} total .{self.extension} files"
        )

    def _on_selection_changed(self):
        """Handle selection change."""
        selected = self.dir_list.selectedItems()
        has_valid_selection = (
            selected and
            isinstance(selected[0], DirectoryListItem)
        )
        self.open_btn.setEnabled(has_valid_selection)

    def _on_double_click(self, item: QListWidgetItem):
        """Handle double-click on directory."""
        if isinstance(item, DirectoryListItem):
            self._open_directory(item.full_path)

    def _open_selected(self):
        """Open the selected directory."""
        selected = self.dir_list.selectedItems()
        if selected and isinstance(selected[0], DirectoryListItem):
            self._open_directory(selected[0].full_path)

    def _open_directory(self, path: str):
        """Open directory in file manager."""
        if not open_directory_in_file_manager(path):
            QMessageBox.warning(
                self,
                "Cannot Open Directory",
                f"Could not open directory:\n{path}\n\nThe directory may not exist or is not accessible."
            )


class SortableExtensionItem(QListWidgetItem):
    """List item that can sort by name or count."""

    SORT_BY_NAME = 0
    SORT_BY_COUNT = 1

    # Class-level sort mode (shared across all items)
    _sort_mode = SORT_BY_NAME

    def __init__(self, ext: str, count: int):
        # Always show count, even if 0
        text = f".{ext}  ({count:,})"
        super().__init__(text)
        self.ext = ext
        self.count = count
        self.setData(Qt.ItemDataRole.UserRole, ext)
        self.setData(Qt.ItemDataRole.UserRole + 1, count)

    def __lt__(self, other):
        """Custom comparison for sorting."""
        if not isinstance(other, SortableExtensionItem):
            return super().__lt__(other)

        if SortableExtensionItem._sort_mode == SortableExtensionItem.SORT_BY_COUNT:
            # Sort by count descending (higher counts first)
            if self.count != other.count:
                return self.count > other.count
            # Tie-breaker: alphabetical
            return self.ext < other.ext
        else:
            # Sort by name alphabetically
            return self.ext < other.ext

    @classmethod
    def set_sort_mode(cls, mode: int):
        """Set the sort mode for all items."""
        cls._sort_mode = mode


class FileTypesTab(QWidget):
    """Tab for managing file type inclusion/exclusion."""

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager.get_instance()
        self._extension_counts: Dict[str, int] = {}  # Cache for counts
        self._setup_ui()
        # Set initial sort mode to match combo box default (Count)
        SortableExtensionItem.set_sort_mode(SortableExtensionItem.SORT_BY_COUNT)
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header row with title and sort control
        header_row = QHBoxLayout()

        header = QLabel("File Types Manager")
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header.setFont(header_font)
        header_row.addWidget(header)

        header_row.addStretch()

        # Sort control
        sort_label = QLabel("Sort by:")
        sort_label.setStyleSheet("color: #666;")
        header_row.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "Count"])
        self.sort_combo.setCurrentIndex(1)  # Default to sort by Count
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header_row.addWidget(self.sort_combo)

        layout.addLayout(header_row)

        subtitle = QLabel("Manage which file types are scanned for duplicates. All counts show files encountered during scanning.")
        subtitle.setStyleSheet("color: #666; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Three-column layout
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Include section
        include_widget, self.include_list = self._create_section(
            "Included Types", "#2e7d32", "These file types will be scanned"
        )
        splitter.addWidget(include_widget)

        # Center section with unknown
        center_widget = self._create_center_section()
        splitter.addWidget(center_widget)

        # Exclude section
        exclude_widget, self.exclude_list = self._create_section(
            "Excluded Types", "#c62828", "These file types will be ignored"
        )
        splitter.addWidget(exclude_widget)

        splitter.setSizes([300, 300, 300])
        layout.addWidget(splitter, stretch=1)

        # Stats
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # Buttons
        btn_row = QHBoxLayout()

        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self._reset_to_defaults)
        btn_row.addWidget(self.reset_btn)

        btn_row.addStretch()

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; "
            "padding: 8px 16px; font-weight: bold; }"
        )
        self.save_btn.clicked.connect(self._save_changes)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)

    def _create_section(self, title: str, color: str, desc: str) -> tuple:
        """Create a section with title, description, and list. Returns (widget, list_widget)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setStyleSheet("font-size: 11px; color: #888;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        list_widget.setAlternatingRowColors(True)
        list_widget.setSortingEnabled(True)
        list_widget.itemDoubleClicked.connect(self._on_extension_double_clicked)
        list_widget.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout.addWidget(list_widget, stretch=1)

        count_label = QLabel("0 types")
        count_label.setObjectName("count_label")
        count_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(count_label)

        return widget, list_widget

    def _create_center_section(self) -> QWidget:
        """Create center section with unknown types and arrows."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 0, 8, 0)

        title = QLabel("Unknown Types")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #e65100;")
        layout.addWidget(title)

        desc = QLabel("File types encountered during scanning that aren't categorized")
        desc.setStyleSheet("font-size: 11px; color: #888;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.unknown_list = QListWidget()
        self.unknown_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.unknown_list.setAlternatingRowColors(True)
        self.unknown_list.setSortingEnabled(True)
        self.unknown_list.itemDoubleClicked.connect(self._on_extension_double_clicked)
        self.unknown_list.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout.addWidget(self.unknown_list, stretch=1)

        # Arrow buttons
        arrows = QHBoxLayout()

        self.to_include_btn = QPushButton("<- Include")
        self.to_include_btn.setStyleSheet(
            "QPushButton { background-color: #2e7d32; color: white; padding: 6px; }"
        )
        self.to_include_btn.clicked.connect(self._move_to_include)
        arrows.addWidget(self.to_include_btn)

        self.to_exclude_btn = QPushButton("Exclude ->")
        self.to_exclude_btn.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; padding: 6px; }"
        )
        self.to_exclude_btn.clicked.connect(self._move_to_exclude)
        arrows.addWidget(self.to_exclude_btn)

        layout.addLayout(arrows)

        # Remove buttons
        remove_row = QHBoxLayout()

        self.remove_from_include_btn = QPushButton("Remove from Include ->")
        self.remove_from_include_btn.setStyleSheet("font-size: 11px; padding: 4px;")
        self.remove_from_include_btn.clicked.connect(self._include_to_unknown)
        remove_row.addWidget(self.remove_from_include_btn)

        remove_row.addStretch()

        self.remove_from_exclude_btn = QPushButton("<- Remove from Exclude")
        self.remove_from_exclude_btn.setStyleSheet("font-size: 11px; padding: 4px;")
        self.remove_from_exclude_btn.clicked.connect(self._exclude_to_unknown)
        remove_row.addWidget(self.remove_from_exclude_btn)

        layout.addLayout(remove_row)

        self.unknown_count_label = QLabel("0 types")
        self.unknown_count_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.unknown_count_label)

        return widget

    def _on_sort_changed(self, index: int):
        """Handle sort mode change."""
        SortableExtensionItem.set_sort_mode(index)
        # Re-sort all lists
        self.include_list.sortItems()
        self.exclude_list.sortItems()
        self.unknown_list.sortItems()

    def _on_extension_double_clicked(self, item: QListWidgetItem):
        """Handle double-click on an extension item - show directories dialog."""
        if not isinstance(item, SortableExtensionItem):
            return

        ext = item.ext
        count = item.count

        # Determine which list this item is from
        sender = self.sender()
        is_unknown = sender == self.unknown_list
        is_excluded = sender == self.exclude_list

        if count == 0:
            QMessageBox.information(
                self,
                "No Files Found",
                f"No indexed files with extension .{ext} were found.\n\n"
                "This extension may not have been encountered during scanning yet."
            )
            return

        # For unknown/excluded extensions, files were encountered but not indexed
        if is_unknown or is_excluded:
            list_type = "unknown" if is_unknown else "excluded"
            QMessageBox.information(
                self,
                "Files Not Indexed",
                f"Files with extension .{ext} were encountered {count:,} times during scanning, "
                f"but were not indexed because this extension is in the {list_type} list.\n\n"
                "To see directories containing these files, move this extension to the "
                "Include list, save changes, and re-scan your drives."
            )
            return

        # Show directories dialog for included extensions
        dialog = ExtensionDirectoriesDialog(ext, self)
        dialog.exec()

    def _load_data(self):
        """Load file type data."""
        from ..core.file_classifier import (
            ALL_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
            DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS
        )
        from ..utils.file_filters import EXCLUDED_EXTENSIONS

        custom_include = set(self.db.get_custom_included_extensions())
        custom_exclude = set(self.db.get_custom_excluded_extensions())
        unknown_types = self.db.get_unknown_extensions()

        default_include = (
            ALL_IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS |
            DOCUMENT_EXTENSIONS | ARCHIVE_EXTENSIONS
        )

        final_include = (default_include | custom_include) - custom_exclude
        final_exclude = (EXCLUDED_EXTENSIONS | custom_exclude) - custom_include

        # Get ALL extension counts (from indexed files)
        self._extension_counts = self.db.get_extension_counts()

        # Also include counts from unknown_types table for extensions we've seen
        for ext, count in unknown_types.items():
            if ext not in self._extension_counts:
                self._extension_counts[ext] = count

        # Populate include list
        self.include_list.clear()
        for ext in final_include:
            count = self._extension_counts.get(ext, 0)
            self._add_extension_item(self.include_list, ext, count)
        self.include_list.sortItems()

        # Populate exclude list
        self.exclude_list.clear()
        for ext in final_exclude:
            count = self._extension_counts.get(ext, 0)
            self._add_extension_item(self.exclude_list, ext, count)
        self.exclude_list.sortItems()

        # Populate unknown list
        self.unknown_list.clear()
        for ext, count in unknown_types.items():
            self._add_extension_item(self.unknown_list, ext, count)
        self.unknown_list.sortItems()

        self._update_counts()

    def _add_extension_item(self, list_widget: QListWidget, ext: str, count: int):
        """Add an extension item to a list."""
        item = SortableExtensionItem(ext, count)
        list_widget.addItem(item)

    def _move_to_include(self):
        """Move selected unknown types to include."""
        for item in self.unknown_list.selectedItems():
            ext = item.data(Qt.ItemDataRole.UserRole)
            count = self._extension_counts.get(ext, 0)
            self.unknown_list.takeItem(self.unknown_list.row(item))
            self._add_extension_item(self.include_list, ext, count)
        self.include_list.sortItems()
        self._update_counts()

    def _move_to_exclude(self):
        """Move selected unknown types to exclude."""
        for item in self.unknown_list.selectedItems():
            ext = item.data(Qt.ItemDataRole.UserRole)
            count = self._extension_counts.get(ext, 0)
            self.unknown_list.takeItem(self.unknown_list.row(item))
            self._add_extension_item(self.exclude_list, ext, count)
        self.exclude_list.sortItems()
        self._update_counts()

    def _include_to_unknown(self):
        """Move selected include types to unknown."""
        for item in self.include_list.selectedItems():
            ext = item.data(Qt.ItemDataRole.UserRole)
            count = self._extension_counts.get(ext, 0)
            self.include_list.takeItem(self.include_list.row(item))
            self._add_extension_item(self.unknown_list, ext, count)
        self.unknown_list.sortItems()
        self._update_counts()

    def _exclude_to_unknown(self):
        """Move selected exclude types to unknown."""
        for item in self.exclude_list.selectedItems():
            ext = item.data(Qt.ItemDataRole.UserRole)
            count = self._extension_counts.get(ext, 0)
            self.exclude_list.takeItem(self.exclude_list.row(item))
            self._add_extension_item(self.unknown_list, ext, count)
        self.unknown_list.sortItems()
        self._update_counts()

    def _update_counts(self):
        """Update count labels."""
        inc = self.include_list.count()
        exc = self.exclude_list.count()
        unk = self.unknown_list.count()

        # Calculate total files in each category
        inc_files = sum(
            self.include_list.item(i).data(Qt.ItemDataRole.UserRole + 1) or 0
            for i in range(inc)
        )
        exc_files = sum(
            self.exclude_list.item(i).data(Qt.ItemDataRole.UserRole + 1) or 0
            for i in range(exc)
        )
        unk_files = sum(
            self.unknown_list.item(i).data(Qt.ItemDataRole.UserRole + 1) or 0
            for i in range(unk)
        )

        # Find count labels
        for widget in [self.include_list.parent(), self.exclude_list.parent()]:
            if widget:
                label = widget.findChild(QLabel, "count_label")
                if label:
                    if widget == self.include_list.parent():
                        label.setText(f"{inc} types, {inc_files:,} files")
                    else:
                        label.setText(f"{exc} types, {exc_files:,} files")

        self.unknown_count_label.setText(f"{unk} types, {unk_files:,} files")

        total = sum(self._extension_counts.values())
        self.stats_label.setText(
            f"Total files seen: {total:,} | Include: {inc} types ({inc_files:,} files) | "
            f"Exclude: {exc} types ({exc_files:,} files) | Unknown: {unk} types ({unk_files:,} files)"
        )

    def _reset_to_defaults(self):
        """Reset to default settings."""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Remove all custom file type settings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_custom_extensions()
            self._load_data()

    def _save_changes(self):
        """Save current settings."""
        from ..core.file_classifier import (
            ALL_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS,
            DOCUMENT_EXTENSIONS, ARCHIVE_EXTENSIONS
        )
        from ..utils.file_filters import EXCLUDED_EXTENSIONS

        # Get current lists
        current_include = set()
        for i in range(self.include_list.count()):
            current_include.add(self.include_list.item(i).data(Qt.ItemDataRole.UserRole))

        current_exclude = set()
        for i in range(self.exclude_list.count()):
            current_exclude.add(self.exclude_list.item(i).data(Qt.ItemDataRole.UserRole))

        default_include = (
            ALL_IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS |
            DOCUMENT_EXTENSIONS | ARCHIVE_EXTENSIONS
        )
        default_exclude = EXCLUDED_EXTENSIONS

        # Calculate custom settings
        custom_include = (current_include - default_include) | (default_exclude & current_include)
        custom_exclude = (current_exclude - default_exclude) | (default_include & current_exclude)

        # Save
        self.db.set_custom_included_extensions(list(custom_include))
        self.db.set_custom_excluded_extensions(list(custom_exclude))

        # Update unknown
        remaining = set()
        for i in range(self.unknown_list.count()):
            remaining.add(self.unknown_list.item(i).data(Qt.ItemDataRole.UserRole))
        self.db.update_unknown_extensions(remaining)

        self.settings_changed.emit()
        QMessageBox.information(self, "Saved", "File type settings saved.")


# ============================================================================
# DUPLICATES TAB
# ============================================================================

class DuplicateFindWorker(QThread):
    """Worker for finding duplicates."""

    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(list)  # List of DuplicateGroup
    error = pyqtSignal(str)

    def __init__(self, mode: str, source1_id: Optional[int], source2_id: Optional[int],
                 source1_path: Optional[Path] = None, source2_path: Optional[Path] = None,
                 parent=None):
        super().__init__(parent)
        self.mode = mode  # 'intra' or 'cross'
        self.source1_id = source1_id
        self.source2_id = source2_id
        self.source1_path = source1_path
        self.source2_path = source2_path

    def run(self):
        try:
            deduplicator = Deduplicator()

            def progress_cb(status, current, total):
                self.progress.emit(status, current, total)

            if self.mode == 'intra':
                # Find duplicates within a single source
                volume_ids = [self.source1_id] if self.source1_id else None
                groups = deduplicator.find_duplicates_from_db(
                    volume_ids=volume_ids,
                    progress_callback=progress_cb
                )
            else:
                # Find duplicates across two sources (intersection)
                groups = deduplicator.find_cross_volume_duplicates(
                    volume_ids=[self.source1_id, self.source2_id],
                    progress_callback=progress_cb
                )

            self.finished.emit(groups)

        except Exception as e:
            self.error.emit(str(e))


class DuplicatesTab(QWidget):
    """Tab for finding and managing duplicates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager.get_instance()
        self.volume_manager = VolumeManager()
        self._groups: List[DuplicateGroup] = []
        self._selected_for_delete: Set[str] = set()
        self._worker: Optional[DuplicateFindWorker] = None
        self._setup_ui()
        self.refresh_sources()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Top section: source selection
        source_frame = QFrame()
        source_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        source_layout = QVBoxLayout(source_frame)

        # Mode selection
        mode_row = QHBoxLayout()

        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-weight: bold;")
        mode_row.addWidget(mode_label)

        self.mode_group = QButtonGroup(self)

        self.intra_radio = QRadioButton("Find duplicates within a source")
        self.intra_radio.setChecked(True)
        self.intra_radio.toggled.connect(self._on_mode_changed)
        self.mode_group.addButton(self.intra_radio)
        mode_row.addWidget(self.intra_radio)

        self.cross_radio = QRadioButton("Find duplicates between two sources")
        self.cross_radio.toggled.connect(self._on_mode_changed)
        self.mode_group.addButton(self.cross_radio)
        mode_row.addWidget(self.cross_radio)

        mode_row.addStretch()
        source_layout.addLayout(mode_row)

        # Source selection row
        sources_row = QHBoxLayout()

        # Source 1
        src1_group = QGroupBox("Source 1")
        src1_layout = QVBoxLayout(src1_group)

        self.source1_combo = QComboBox()
        self.source1_combo.setMinimumWidth(200)
        src1_layout.addWidget(self.source1_combo)

        self.browse1_btn = QPushButton("Browse Folder...")
        self.browse1_btn.clicked.connect(lambda: self._browse_folder(1))
        src1_layout.addWidget(self.browse1_btn)

        self.source1_path_label = QLabel("")
        self.source1_path_label.setStyleSheet("color: #666; font-size: 11px;")
        self.source1_path_label.setWordWrap(True)
        src1_layout.addWidget(self.source1_path_label)

        sources_row.addWidget(src1_group)

        # Source 2 (for cross mode)
        self.src2_group = QGroupBox("Source 2")
        src2_layout = QVBoxLayout(self.src2_group)

        self.source2_combo = QComboBox()
        self.source2_combo.setMinimumWidth(200)
        src2_layout.addWidget(self.source2_combo)

        self.browse2_btn = QPushButton("Browse Folder...")
        self.browse2_btn.clicked.connect(lambda: self._browse_folder(2))
        src2_layout.addWidget(self.browse2_btn)

        self.source2_path_label = QLabel("")
        self.source2_path_label.setStyleSheet("color: #666; font-size: 11px;")
        self.source2_path_label.setWordWrap(True)
        src2_layout.addWidget(self.source2_path_label)

        self.src2_group.setEnabled(False)
        sources_row.addWidget(self.src2_group)

        sources_row.addStretch()

        # Find button
        self.find_btn = QPushButton("Find Duplicates")
        self.find_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; "
            "padding: 12px 24px; font-size: 14px; font-weight: bold; }"
        )
        self.find_btn.clicked.connect(self._find_duplicates)
        sources_row.addWidget(self.find_btn)

        source_layout.addLayout(sources_row)
        layout.addWidget(source_frame)

        # Results section
        results_header = QHBoxLayout()

        self.results_label = QLabel("Results")
        results_font = QFont()
        results_font.setPointSize(14)
        results_font.setBold(True)
        self.results_label.setFont(results_font)
        results_header.addWidget(self.results_label)

        results_header.addStretch()

        self.summary_label = QLabel("No duplicates found")
        self.summary_label.setStyleSheet("color: #666;")
        results_header.addWidget(self.summary_label)

        layout.addLayout(results_header)

        # Results tree
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["Name", "Size", "Resolution", "Volume", "Path", "Action"])
        self.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.itemChanged.connect(self._on_item_changed)

        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.results_tree.setColumnWidth(0, 200)

        layout.addWidget(self.results_tree, stretch=1)

        # Action buttons
        action_row = QHBoxLayout()

        self.select_suggested_btn = QPushButton("Select Suggested Deletes")
        self.select_suggested_btn.clicked.connect(self._select_suggested)
        action_row.addWidget(self.select_suggested_btn)

        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        action_row.addWidget(self.clear_selection_btn)

        action_row.addStretch()

        self.selected_label = QLabel("0 files selected")
        action_row.addWidget(self.selected_label)

        self.trash_btn = QPushButton("Move Selected to Trash")
        self.trash_btn.setStyleSheet(
            "QPushButton { background-color: #d32f2f; color: white; "
            "padding: 8px 16px; font-weight: bold; }"
        )
        self.trash_btn.clicked.connect(self._trash_selected)
        self.trash_btn.setEnabled(False)
        action_row.addWidget(self.trash_btn)

        layout.addLayout(action_row)

    def refresh_sources(self):
        """Refresh source dropdowns with indexed volumes."""
        self.source1_combo.clear()
        self.source2_combo.clear()

        self.source1_combo.addItem("-- Select a drive --", None)
        self.source2_combo.addItem("-- Select a drive --", None)

        for vol in self.db.get_all_volumes():
            if (vol.get('file_count') or 0) > 0:
                name = f"{vol['name']} ({vol['file_count']:,} files)"
                self.source1_combo.addItem(name, vol['id'])
                self.source2_combo.addItem(name, vol['id'])

    def _on_mode_changed(self):
        """Handle mode radio button change."""
        is_cross = self.cross_radio.isChecked()
        self.src2_group.setEnabled(is_cross)

    def _browse_folder(self, source_num: int):
        """Browse for a folder."""
        folder = QFileDialog.getExistingDirectory(self, f"Select Source {source_num} Folder")
        if folder:
            if source_num == 1:
                self.source1_path_label.setText(folder)
            else:
                self.source2_path_label.setText(folder)

    def _find_duplicates(self):
        """Start finding duplicates."""
        is_cross = self.cross_radio.isChecked()

        # Get source 1
        source1_id = self.source1_combo.currentData()
        source1_path = self.source1_path_label.text() or None

        if not source1_id and not source1_path:
            QMessageBox.warning(self, "No Source", "Please select a drive or folder for Source 1.")
            return

        # Get source 2 for cross mode
        source2_id = None
        source2_path = None
        if is_cross:
            source2_id = self.source2_combo.currentData()
            source2_path = self.source2_path_label.text() or None

            if not source2_id and not source2_path:
                QMessageBox.warning(self, "No Source", "Please select a drive or folder for Source 2.")
                return

        # Clear previous results
        self._groups = []
        self._selected_for_delete = set()
        self.results_tree.clear()

        # Start worker
        progress = QProgressDialog("Finding duplicates...", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        mode = 'cross' if is_cross else 'intra'
        self._worker = DuplicateFindWorker(
            mode, source1_id, source2_id,
            Path(source1_path) if source1_path else None,
            Path(source2_path) if source2_path else None
        )

        def on_progress(status, current, total):
            if total > 0:
                progress.setValue(int((current / total) * 100))
                progress.setLabelText(f"{status}\n{current:,} / {total:,}")

        def on_finished(groups):
            progress.close()
            self._worker = None
            self._groups = groups
            self._populate_results()

        def on_error(error):
            progress.close()
            self._worker = None
            QMessageBox.critical(self, "Error", f"Error finding duplicates:\n\n{error}")

        self._worker.progress.connect(on_progress)
        self._worker.finished.connect(on_finished)
        self._worker.error.connect(on_error)
        progress.canceled.connect(lambda: self._worker.terminate() if self._worker else None)

        self._worker.start()

    def _populate_results(self):
        """Populate the results tree."""
        self.results_tree.clear()
        self._selected_for_delete = set()

        total_groups = len(self._groups)
        total_files = sum(g.file_count for g in self._groups)
        total_savings = sum(g.potential_savings for g in self._groups)

        # Format savings
        savings_str = self._format_size(total_savings)
        self.summary_label.setText(
            f"{total_groups} duplicate groups, {total_files} files, {savings_str} potential savings"
        )

        self.results_tree.blockSignals(True)

        for group in self._groups:
            # Group item
            group_item = QTreeWidgetItem()
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", group.group_id))

            type_label = "Cross-volume" if group.is_cross_volume else (
                "Intra-dir" if group.is_intra_directory else "Cross-dir"
            )
            group_item.setText(0, f"Group {group.group_id} ({group.file_count} files) - {type_label}")
            group_item.setText(5, f"Savings: {group.potential_savings_str}")
            group_item.setExpanded(True)

            self.results_tree.addTopLevelItem(group_item)

            # File items
            for image in group.images:
                is_keep = image == group.suggested_keep
                file_item = QTreeWidgetItem()
                file_item.setData(0, Qt.ItemDataRole.UserRole, ("file", str(image.path)))
                file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)

                if is_keep:
                    file_item.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    file_item.setCheckState(0, Qt.CheckState.Checked)
                    self._selected_for_delete.add(str(image.path))

                file_item.setText(0, image.filename)
                file_item.setText(1, image.file_size_str)
                file_item.setText(2, image.dimensions_str)

                volume_name = getattr(image, 'volume_name', '-')
                file_item.setText(3, volume_name)
                file_item.setText(4, str(image.directory))
                file_item.setText(5, "KEEP" if is_keep else "DELETE")

                if is_keep:
                    file_item.setForeground(5, QBrush(QColor("green")))
                else:
                    file_item.setForeground(5, QBrush(QColor("red")))

                group_item.addChild(file_item)

        self.results_tree.blockSignals(False)
        self._update_selection_count()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle checkbox change."""
        if column != 0:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "file":
            return

        path = data[1]
        is_checked = item.checkState(0) == Qt.CheckState.Checked

        if is_checked:
            self._selected_for_delete.add(path)
            item.setText(5, "DELETE")
            item.setForeground(5, QBrush(QColor("red")))
        else:
            self._selected_for_delete.discard(path)
            item.setText(5, "KEEP")
            item.setForeground(5, QBrush(QColor("green")))

        self._update_selection_count()

    def _select_suggested(self):
        """Select all suggested deletes."""
        self.results_tree.blockSignals(True)

        for i in range(self.results_tree.topLevelItemCount()):
            group_item = self.results_tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data[0] == "file":
                    path = data[1]
                    is_keeper = False
                    for group in self._groups:
                        if group.suggested_keep and str(group.suggested_keep.path) == path:
                            is_keeper = True
                            break

                    if is_keeper:
                        child.setCheckState(0, Qt.CheckState.Unchecked)
                        self._selected_for_delete.discard(path)
                        child.setText(5, "KEEP")
                        child.setForeground(5, QBrush(QColor("green")))
                    else:
                        child.setCheckState(0, Qt.CheckState.Checked)
                        self._selected_for_delete.add(path)
                        child.setText(5, "DELETE")
                        child.setForeground(5, QBrush(QColor("red")))

        self.results_tree.blockSignals(False)
        self._update_selection_count()

    def _clear_selection(self):
        """Clear all selections."""
        self.results_tree.blockSignals(True)

        for i in range(self.results_tree.topLevelItemCount()):
            group_item = self.results_tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setText(5, "KEEP")
                child.setForeground(5, QBrush(QColor("green")))

        self._selected_for_delete.clear()
        self.results_tree.blockSignals(False)
        self._update_selection_count()

    def _update_selection_count(self):
        """Update selection count label."""
        count = len(self._selected_for_delete)
        self.selected_label.setText(f"{count} files selected")
        self.trash_btn.setEnabled(count > 0)

    def _trash_selected(self):
        """Move selected files to trash."""
        if not self._selected_for_delete:
            return

        count = len(self._selected_for_delete)
        reply = QMessageBox.question(
            self, "Confirm Trash",
            f"Move {count} selected files to trash?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        from ..core.file_operations import move_to_trash

        success = 0
        failed = []

        for path_str in list(self._selected_for_delete):
            path = Path(path_str)
            if move_to_trash(path):
                success += 1
                self._selected_for_delete.discard(path_str)
            else:
                failed.append(path_str)

        # Refresh results
        self._populate_results()

        msg = f"Moved {success} files to trash."
        if failed:
            msg += f"\n\nFailed to move {len(failed)} files."

        QMessageBox.information(self, "Complete", msg)

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human readable."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# ============================================================================
# MAIN UNIFIED WINDOW
# ============================================================================

class UnifiedWindow(QMainWindow):
    """Main application window with tabbed interface."""

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Dedupe - Duplicate File Finder")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        # Central widget with tabs
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        # Create tabs
        self.drives_tab = DrivesTab()
        self.file_types_tab = FileTypesTab()
        self.duplicates_tab = DuplicatesTab()

        # Add tabs
        self.tabs.addTab(self.drives_tab, "Drives")
        self.tabs.addTab(self.file_types_tab, "File Types")
        self.tabs.addTab(self.duplicates_tab, "Duplicates")

        # Connect signals
        self.drives_tab.scan_completed.connect(self._on_scan_completed)
        self.file_types_tab.settings_changed.connect(self._on_file_types_changed)

        layout.addWidget(self.tabs)

        # Check for interrupted scans
        self._check_interrupted_scans()

    def _on_scan_completed(self):
        """Handle scan completion - refresh duplicates tab sources."""
        self.duplicates_tab.refresh_sources()

    def _on_file_types_changed(self):
        """Handle file types settings change."""
        # Could reload classifier settings here if needed
        pass

    def _check_interrupted_scans(self):
        """Check for interrupted scans on startup."""
        db = DatabaseManager.get_instance()
        volume_manager = VolumeManager()

        interrupted = db.get_interrupted_scans()
        if not interrupted:
            return

        mounted_uuids = {v.uuid for v in volume_manager.list_volumes()}
        resumable = [s for s in interrupted if s.get('volume_uuid') in mounted_uuids]

        if resumable:
            QMessageBox.information(
                self,
                "Interrupted Scans Found",
                f"Found {len(resumable)} interrupted scan(s).\n"
                "Go to the Drives tab and click 'Resume Scan' to continue."
            )
