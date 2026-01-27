"""Drive manager dialog for selecting and managing scanned drives."""

from datetime import datetime
from pathlib import Path
from typing import Optional, List

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QWidget, QMessageBox, QFrame,
    QFileDialog, QProgressDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont

from ..core.database import DatabaseManager
from ..core.volume_manager import VolumeManager, VolumeInfo
from ..core.file_scanner import FileScanner, ScanStats
from .file_types_manager import FileTypesManagerDialog


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
                status_text = "✓ Scanned"
                status_style = "color: #2e7d32; font-weight: bold;"
            elif status == 'partial':
                status_text = "◐ Partial"
                status_style = "color: #e65100; font-weight: bold;"
            else:
                status_text = "Not Scanned"
                status_style = "color: #757575;"
        else:
            status_text = "Not Scanned"
            status_style = "color: #757575;"

        # Check for paused scan
        if self.db_info and self.db_info.get('has_paused_scan'):
            status_text = "⏸ Paused"
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

            # Check if paused vs finished
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


class DriveManagerDialog(QDialog):
    """Dialog for selecting and managing drives to scan."""

    drive_scan_requested = pyqtSignal(str, object)  # volume_uuid, optional scan_path
    find_duplicates_requested = pyqtSignal(str)  # volume_uuid
    cross_drive_requested = pyqtSignal(list)  # list of volume_uuids

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = DatabaseManager.get_instance()
        self.volume_manager = VolumeManager()
        self.selected_volume: Optional[VolumeInfo] = None
        self._worker: Optional[ScanWorker] = None
        self._is_pausing = False
        self._setup_ui()
        self.refresh_drives()
        self._check_interrupted_scans()

    def _setup_ui(self):
        self.setWindowTitle("Duplicate Finder - Drive Manager")
        self.setMinimumSize(700, 500)
        self.resize(750, 550)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel("Drive Manager")
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        # Subtitle
        subtitle = QLabel("Select a drive to scan for duplicates or manage indexed drives")
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        # Connected drives section
        drives_header = QLabel("Connected Drives")
        drives_font = QFont()
        drives_font.setPointSize(14)
        drives_font.setBold(True)
        drives_header.setFont(drives_font)
        layout.addWidget(drives_header)

        # Drive list
        self.drive_list = QListWidget()
        self.drive_list.setSpacing(2)
        self.drive_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.drive_list.itemDoubleClicked.connect(self._on_double_click)
        self.drive_list.setAlternatingRowColors(True)
        layout.addWidget(self.drive_list, stretch=1)

        # Action buttons row 1
        action_row1 = QHBoxLayout()

        self.refresh_button = QPushButton("🔄 Refresh")
        self.refresh_button.clicked.connect(self.refresh_drives)
        action_row1.addWidget(self.refresh_button)

        self.file_types_button = QPushButton("⚙ File Types")
        self.file_types_button.setToolTip("Manage which file types to include or exclude")
        self.file_types_button.clicked.connect(self._open_file_types_manager)
        action_row1.addWidget(self.file_types_button)

        action_row1.addStretch()

        self.resume_button = QPushButton("Resume Scan")
        self.resume_button.clicked.connect(self._resume_scan)
        self.resume_button.setEnabled(False)
        action_row1.addWidget(self.resume_button)

        self.scan_drive_button = QPushButton("Scan Entire Drive")
        self.scan_drive_button.clicked.connect(self._scan_drive)
        self.scan_drive_button.setEnabled(False)
        action_row1.addWidget(self.scan_drive_button)

        self.scan_folder_button = QPushButton("Scan Folder...")
        self.scan_folder_button.clicked.connect(self._scan_folder)
        self.scan_folder_button.setEnabled(False)
        action_row1.addWidget(self.scan_folder_button)

        layout.addLayout(action_row1)

        # Action buttons row 2
        action_row2 = QHBoxLayout()

        self.remove_button = QPushButton("Remove from Index")
        self.remove_button.clicked.connect(self._remove_drive)
        self.remove_button.setEnabled(False)
        action_row2.addWidget(self.remove_button)

        action_row2.addStretch()

        self.find_dupes_button = QPushButton("Find Duplicates")
        self.find_dupes_button.clicked.connect(self._find_duplicates)
        self.find_dupes_button.setEnabled(False)
        action_row2.addWidget(self.find_dupes_button)

        self.cross_drive_button = QPushButton("Cross-Drive Duplicates")
        self.cross_drive_button.clicked.connect(self._cross_drive_duplicates)
        action_row2.addWidget(self.cross_drive_button)

        layout.addLayout(action_row2)

    def refresh_drives(self):
        """Refresh the list of available drives."""
        self.drive_list.clear()
        self.selected_volume = None
        self._update_buttons()

        # Get paused scans to mark volumes with paused scans
        paused_scans = self.db.get_paused_scan_sessions()
        paused_volume_ids = {s.get('volume_id') for s in paused_scans}

        # Get mounted volumes
        volumes = self.volume_manager.list_volumes()

        # Get database info for each volume
        for vol in volumes:
            db_info = self.db.get_volume_by_uuid(vol.uuid)

            # Check if this volume has a paused scan
            if db_info:
                db_info = dict(db_info)  # Make a copy to modify
                if db_info.get('id') in paused_volume_ids:
                    db_info['has_paused_scan'] = True

            item = QListWidgetItem()
            widget = DriveItemWidget(vol, db_info)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, vol)

            self.drive_list.addItem(item)
            self.drive_list.setItemWidget(item, widget)

        # Update cross-drive button based on indexed drives
        self._update_cross_drive_button()

    def _on_selection_changed(self):
        """Handle selection change in the list."""
        selected = self.drive_list.selectedItems()

        if selected:
            self.selected_volume = selected[0].data(Qt.ItemDataRole.UserRole)
        else:
            self.selected_volume = None

        self._update_buttons()

    def _update_buttons(self):
        """Update button enabled states based on selection."""
        has_selection = self.selected_volume is not None

        self.scan_drive_button.setEnabled(has_selection)
        self.scan_folder_button.setEnabled(has_selection)

        # Check if selected drive is indexed or has paused scan
        if has_selection:
            db_info = self.db.get_volume_by_uuid(self.selected_volume.uuid)
            file_count = (db_info.get('file_count') or 0) if db_info else 0
            is_indexed = file_count > 0
            self.find_dupes_button.setEnabled(is_indexed)
            self.remove_button.setEnabled(is_indexed)

            # Check for paused scan
            has_paused = self._get_paused_session_for_volume(self.selected_volume.uuid) is not None
            self.resume_button.setEnabled(has_paused)
        else:
            self.find_dupes_button.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.resume_button.setEnabled(False)

    def _get_paused_session_for_volume(self, volume_uuid: str) -> Optional[dict]:
        """Get the paused scan session for a volume, if any."""
        db_info = self.db.get_volume_by_uuid(volume_uuid)
        if not db_info:
            return None

        volume_id = db_info.get('id')
        paused_scans = self.db.get_paused_scan_sessions(volume_id)
        return paused_scans[0] if paused_scans else None

    def _update_cross_drive_button(self):
        """Update cross-drive button based on indexed drives."""
        # Count drives with files indexed
        indexed_count = 0
        for vol in self.db.get_all_volumes():
            if (vol.get('file_count') or 0) > 0:
                indexed_count += 1

        self.cross_drive_button.setEnabled(indexed_count >= 2)

    def _on_double_click(self, item: QListWidgetItem):
        """Handle double-click on a drive."""
        vol = item.data(Qt.ItemDataRole.UserRole)
        db_info = self.db.get_volume_by_uuid(vol.uuid)

        if db_info and (db_info.get('file_count') or 0) > 0:
            # Drive is indexed, find duplicates
            self._find_duplicates()
        else:
            # Drive not indexed, scan it
            self._scan_drive()

    def _scan_drive(self):
        """Scan the entire selected drive."""
        if not self.selected_volume:
            return

        self._start_scan(self.selected_volume, scan_path=None)

    def _scan_folder(self):
        """Scan a specific folder on the selected drive."""
        if not self.selected_volume:
            return

        # Open folder browser starting at drive mount point
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder to Scan",
            str(self.selected_volume.mount_point),
            QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            self._start_scan(self.selected_volume, scan_path=Path(folder))

    def _resume_scan(self):
        """Resume a paused scan on the selected drive."""
        if not self.selected_volume:
            return

        paused_session = self._get_paused_session_for_volume(self.selected_volume.uuid)
        if not paused_session:
            QMessageBox.warning(
                self,
                "No Paused Scan",
                "No paused scan found for this drive."
            )
            return

        # Get scan path from session
        scan_path = None
        if paused_session.get('scan_path'):
            scan_path = Path(paused_session['scan_path'])

        self._start_scan(
            self.selected_volume,
            scan_path=scan_path,
            resume_session_id=paused_session['id']
        )

    def _start_scan(
        self,
        volume_info: VolumeInfo,
        scan_path: Optional[Path],
        resume_session_id: Optional[int] = None
    ):
        """Start or resume scanning a drive or folder."""
        # Create progress dialog with Pause button
        progress = QProgressDialog(
            "Scanning files...",
            "Pause",  # Changed from "Cancel" to "Pause"
            0, 100,
            self
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # Track if we're pausing vs cancelling
        self._is_pausing = False

        # Create and start worker
        self._worker = ScanWorker(
            volume_info,
            scan_path,
            resume_session_id=resume_session_id
        )

        def on_progress(status: str, current: int, total: int):
            if total > 0:
                percent = int((current / total) * 100)
                progress.setValue(percent)
                progress.setLabelText(f"Scanning: {status}\n{current:,} / {total:,} files")
            else:
                progress.setLabelText(f"Counting: {status}")

        def on_finished(stats: ScanStats):
            progress.close()
            self._worker = None
            self.refresh_drives()

            QMessageBox.information(
                self,
                "Scan Complete",
                f"Scan completed successfully!\n\n{stats}"
            )

        def on_paused(session_id: int, stats: ScanStats):
            progress.close()
            self._worker = None
            self.refresh_drives()

            QMessageBox.information(
                self,
                "Scan Paused",
                f"Scan paused. You can resume it later.\n\n"
                f"Progress: {stats.files_scanned + stats.files_unchanged:,} files processed"
            )

        def on_error(error: str):
            progress.close()
            self._worker = None
            self.refresh_drives()

            QMessageBox.critical(
                self,
                "Scan Error",
                f"An error occurred during scanning:\n\n{error}"
            )

        def on_button_clicked():
            # Called when Pause button is clicked
            if self._worker:
                self._is_pausing = True
                progress.setLabelText("Pausing scan...")
                self._worker.pause()

        self._worker.progress.connect(on_progress)
        self._worker.finished.connect(on_finished)
        self._worker.paused.connect(on_paused)
        self._worker.error.connect(on_error)
        progress.canceled.connect(on_button_clicked)

        self._worker.start()

    def _remove_drive(self):
        """Remove selected drive from the index."""
        if not self.selected_volume:
            return

        db_info = self.db.get_volume_by_uuid(self.selected_volume.uuid)
        if not db_info:
            return

        reply = QMessageBox.question(
            self,
            "Remove Drive",
            f"Remove '{self.selected_volume.name}' from the index?\n\n"
            "This will delete all indexed file information for this drive. "
            "Your actual files will not be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_volume(db_info['id'])
            self.refresh_drives()

    def _find_duplicates(self):
        """Find duplicates on the selected drive."""
        if not self.selected_volume:
            return

        self.find_duplicates_requested.emit(self.selected_volume.uuid)
        self.accept()

    def _cross_drive_duplicates(self):
        """Find duplicates across all indexed drives."""
        # Get all indexed volumes
        indexed_uuids = []
        for vol in self.db.get_all_volumes():
            if (vol.get('file_count') or 0) > 0:
                indexed_uuids.append(vol['uuid'])

        if len(indexed_uuids) < 2:
            QMessageBox.information(
                self,
                "Cross-Drive Duplicates",
                "You need at least 2 indexed drives to find cross-drive duplicates.\n\n"
                "Please scan more drives first."
            )
            return

        self.cross_drive_requested.emit(indexed_uuids)
        self.accept()

    def _check_interrupted_scans(self):
        """Check for interrupted scans and offer to resume them."""
        interrupted = self.db.get_interrupted_scans()

        if not interrupted:
            return

        # Filter to only include scans for currently mounted volumes
        mounted_uuids = {v.uuid for v in self.volume_manager.list_volumes()}
        resumable = [
            s for s in interrupted
            if s.get('volume_uuid') in mounted_uuids
        ]

        if not resumable:
            return

        # If there's exactly one interrupted scan, offer to resume it
        if len(resumable) == 1:
            scan = resumable[0]
            volume_name = scan.get('volume_name', 'Unknown')
            files_done = scan.get('files_scanned', 0) or 0

            reply = QMessageBox.question(
                self,
                "Resume Interrupted Scan",
                f"An interrupted scan was found for '{volume_name}'.\n"
                f"Progress: {files_done:,} files scanned.\n\n"
                "Would you like to resume this scan?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                # Find the volume and resume
                for vol in self.volume_manager.list_volumes():
                    if vol.uuid == scan.get('volume_uuid'):
                        scan_path = None
                        if scan.get('scan_path'):
                            scan_path = Path(scan['scan_path'])

                        self._start_scan(
                            vol,
                            scan_path=scan_path,
                            resume_session_id=scan['id']
                        )
                        break
        else:
            # Multiple interrupted scans - just notify
            QMessageBox.information(
                self,
                "Interrupted Scans Found",
                f"Found {len(resumable)} interrupted scans.\n"
                "Select a drive and click 'Resume Scan' to continue."
            )

    def _open_file_types_manager(self):
        """Open the file types manager dialog."""
        dialog = FileTypesManagerDialog(self)
        dialog.settings_changed.connect(self._on_file_types_changed)
        dialog.exec()

    def _on_file_types_changed(self):
        """Handle changes to file type settings."""
        # Currently no action needed here, but you could refresh
        # the UI or notify the user if necessary
        pass
