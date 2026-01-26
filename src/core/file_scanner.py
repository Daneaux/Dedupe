"""Enhanced file scanner for all personal file types with database integration.

This scanner supports images, videos, documents, and audio files,
with filtering for system files and integration with the hash database.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Generator, Dict, Tuple, TYPE_CHECKING
import os

from .database import DatabaseManager
from .file_classifier import FileClassifier, FileType
from .volume_manager import VolumeManager, VolumeInfo
from ..utils.file_filters import FileFilter
from ..models.scanned_file import ScannedFile


class ScanStats:
    """Statistics from a scan operation."""

    def __init__(self):
        self.files_scanned = 0
        self.files_added = 0
        self.files_updated = 0
        self.files_unchanged = 0
        self.files_skipped = 0
        self.files_failed = 0

    @property
    def total_processed(self) -> int:
        """Total files processed (excluding skipped)."""
        return self.files_scanned + self.files_unchanged

    def __str__(self) -> str:
        return (
            f"Scanned: {self.files_scanned}, "
            f"Added: {self.files_added}, "
            f"Updated: {self.files_updated}, "
            f"Unchanged: {self.files_unchanged}, "
            f"Skipped: {self.files_skipped}, "
            f"Failed: {self.files_failed}"
        )


class FileScanner:
    """Scans directories for personal files with filtering and database integration."""

    # How often to save checkpoints (every N files)
    CHECKPOINT_INTERVAL = 100

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        file_filter: Optional[FileFilter] = None,
        file_classifier: Optional[FileClassifier] = None,
        volume_manager: Optional[VolumeManager] = None,
    ):
        """Initialize the scanner.

        Args:
            db_manager: Database manager for storing results (optional)
            file_filter: File filter for excluding system files
            file_classifier: File classifier for determining file types
            volume_manager: Volume manager for drive detection
        """
        self.db = db_manager or DatabaseManager.get_instance()
        self.file_filter = file_filter or FileFilter()
        self.classifier = file_classifier or FileClassifier()
        self.volume_manager = volume_manager or VolumeManager()

        self._cancelled = False
        self._paused = False
        self._stats = ScanStats()
        self._current_session_id: Optional[int] = None
        self._current_directory: str = ""
        self._directories_completed: List[str] = []
        self._total_files: int = 0

    def cancel(self):
        """Cancel the current scan operation."""
        self._cancelled = True

    def pause(self):
        """Pause the current scan operation (saves checkpoint)."""
        self._paused = True

    def reset(self):
        """Reset the scanner state."""
        self._cancelled = False
        self._paused = False
        self._stats = ScanStats()
        self._current_session_id = None
        self._current_directory = ""
        self._directories_completed = []
        self._total_files = 0

    @property
    def is_paused(self) -> bool:
        """Check if scanner is paused."""
        return self._paused

    @property
    def session_id(self) -> Optional[int]:
        """Get current session ID."""
        return self._current_session_id

    def scan_volume(
        self,
        volume_info: VolumeInfo,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        scan_path: Optional[Path] = None,
        resume_session_id: Optional[int] = None,
    ) -> Tuple[int, ScanStats]:
        """Scan a volume and store files in the database.

        Args:
            volume_info: Information about the volume to scan
            progress_callback: Optional callback(status, current, total)
            scan_path: Optional specific path within volume (default: scan entire volume)
            resume_session_id: Optional session ID to resume from

        Returns:
            Tuple of (session_id, ScanStats)
        """
        self.reset()

        # Register/update volume in database
        volume_id = self.db.add_volume(
            uuid=volume_info.uuid,
            name=volume_info.name,
            mount_point=str(volume_info.mount_point),
            is_internal=volume_info.is_internal,
            total_size_bytes=volume_info.total_bytes,
            filesystem=volume_info.filesystem,
        )

        # Determine scan root
        root_path = scan_path or volume_info.mount_point

        # Check if resuming from a previous session
        checkpoint = None
        if resume_session_id:
            checkpoint = self.db.get_scan_checkpoint(resume_session_id)
            session_id = resume_session_id
            self._current_session_id = session_id

            # Restore state from checkpoint
            if checkpoint:
                self._directories_completed = checkpoint.get('directories_completed', [])
                self._total_files = checkpoint.get('files_total', 0)
                # Restore stats from session
                session = self.db.get_scan_session(session_id)
                if session:
                    self._stats.files_scanned = session.get('files_scanned', 0)
                    self._stats.files_added = session.get('files_added', 0)
                    self._stats.files_updated = session.get('files_updated', 0)
        else:
            # Start new scan session
            session_id = self.db.start_scan_session(
                volume_id=volume_id,
                scan_path=str(root_path) if scan_path else None
            )
            self._current_session_id = session_id

        try:
            # First pass: count files for progress (unless resuming with known total)
            if not checkpoint or not self._total_files:
                if progress_callback:
                    progress_callback("Counting files...", 0, 0)
                self._total_files = self._count_files(root_path)
                # Reset directories_completed after counting (it gets populated during count)
                self._directories_completed = []

            total_files = self._total_files
            processed = self._stats.files_scanned + self._stats.files_unchanged

            # Second pass: scan and index files
            for file_path, current_dir in self._iterate_files_with_directory(root_path):
                if self._cancelled or self._paused:
                    break

                self._current_directory = current_dir

                # Get relative path
                relative_path = self.volume_manager.get_relative_path(
                    file_path, volume_info.mount_point
                )

                # Determine file type
                file_type = self.classifier.get_file_type(file_path)

                # Skip unsupported files
                if file_type == FileType.OTHER:
                    continue

                # Check file filter (including size check)
                if not self.file_filter.should_include_file(file_path, file_type):
                    self._stats.files_skipped += 1
                    continue

                # Check if file already exists in database
                existing = self.db.get_file_by_path(volume_id, relative_path)

                # Get file stats
                try:
                    stat = file_path.stat()
                    file_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
                except OSError:
                    self._stats.files_failed += 1
                    continue

                # Check if file needs updating
                if existing:
                    # File exists - check if modified
                    if existing.get('file_modified_at') == file_modified:
                        # File unchanged, skip
                        self._stats.files_unchanged += 1
                        processed += 1
                        if progress_callback:
                            progress_callback(file_path.name, processed, total_files)
                        continue
                    else:
                        self._stats.files_updated += 1
                else:
                    self._stats.files_added += 1

                # Load metadata
                scanned_file = self._create_scanned_file(
                    file_path, volume_id, volume_info.mount_point, file_type
                )

                # Store in database
                self.db.add_file(
                    volume_id=volume_id,
                    relative_path=relative_path,
                    filename=scanned_file.filename,
                    extension=scanned_file.extension,
                    file_size_bytes=scanned_file.file_size_bytes,
                    file_type=file_type,
                    width=scanned_file.width,
                    height=scanned_file.height,
                    duration_seconds=scanned_file.duration_seconds,
                    file_created_at=scanned_file.file_created_at.isoformat() if scanned_file.file_created_at else None,
                    file_modified_at=scanned_file.file_modified_at.isoformat() if scanned_file.file_modified_at else None,
                )

                processed += 1
                self._stats.files_scanned += 1

                # Report progress
                if progress_callback:
                    progress_callback(file_path.name, processed, total_files)

                # Save checkpoint periodically
                if processed % self.CHECKPOINT_INTERVAL == 0:
                    self._save_checkpoint(session_id, current_dir, processed, total_files)

            # Update scan session
            self.db.update_scan_session(
                session_id=session_id,
                files_scanned=self._stats.files_scanned,
                files_added=self._stats.files_added,
                files_updated=self._stats.files_updated,
            )

            # Handle paused state
            if self._paused:
                # Save checkpoint and exit
                self._save_checkpoint(
                    session_id, self._current_directory, processed, total_files
                )
                self.db.pause_scan_session(session_id)

                # Update volume status to partial
                file_count = self.db.get_file_count_by_volume(volume_id)
                self.db.update_volume_scan_status(
                    volume_id=volume_id,
                    status='partial',
                    file_count=file_count
                )
                return session_id, self._stats

            # Mark session complete
            status = 'cancelled' if self._cancelled else 'completed'
            self.db.complete_scan_session(session_id, status=status)

            # Delete checkpoint on completion
            self.db.delete_scan_checkpoint(session_id)

            # Update volume status
            file_count = self.db.get_file_count_by_volume(volume_id)
            self.db.update_volume_scan_status(
                volume_id=volume_id,
                status='complete' if not self._cancelled else 'partial',
                file_count=file_count
            )

            return session_id, self._stats

        except Exception as e:
            # Save checkpoint on error so scan can be resumed
            self._save_checkpoint(session_id, self._current_directory, processed, total_files)
            self.db.complete_scan_session(
                session_id,
                status='failed',
                error_message=str(e)
            )
            raise

    def _save_checkpoint(
        self,
        session_id: int,
        current_directory: str,
        files_processed: int,
        files_total: int
    ):
        """Save current scan progress as a checkpoint."""
        self.db.save_scan_checkpoint(
            session_id=session_id,
            current_directory=current_directory,
            files_processed=files_processed,
            files_total=files_total,
            directories_completed=self._directories_completed
        )

    def scan_directory(
        self,
        directory: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Tuple[int, ScanStats]:
        """Scan a specific directory (convenience method).

        Automatically detects the volume and scans the directory.

        Args:
            directory: Directory to scan
            progress_callback: Optional progress callback

        Returns:
            Tuple of (session_id, ScanStats)
        """
        # Get volume info
        volume_info = self.volume_manager.get_volume_for_path(directory)

        if not volume_info:
            # Create a fallback volume info
            uuid = self.volume_manager.get_volume_uuid(directory)
            if not uuid:
                import hashlib
                uuid = f"DIR-{hashlib.md5(str(directory).encode()).hexdigest()[:12]}"

            volume_info = VolumeInfo(
                uuid=uuid,
                name=directory.name,
                mount_point=directory,
                is_internal=True,
                total_bytes=0,
                available_bytes=0,
                filesystem="unknown",
            )

        return self.scan_volume(
            volume_info=volume_info,
            progress_callback=progress_callback,
            scan_path=directory,
        )

    def _count_files(self, root_path: Path) -> int:
        """Count total files to scan."""
        count = 0

        for file_path in self._iterate_files(root_path):
            if self._cancelled:
                break

            file_type = self.classifier.get_file_type(file_path)
            if file_type != FileType.OTHER:
                if self.file_filter.should_include_file(file_path, file_type, check_size=False):
                    count += 1

        return count

    def _iterate_files(self, root_path: Path) -> Generator[Path, None, None]:
        """Iterate through files with directory filtering."""
        for file_path, _ in self._iterate_files_with_directory(root_path):
            yield file_path

    def _iterate_files_with_directory(
        self,
        root_path: Path
    ) -> Generator[Tuple[Path, str], None, None]:
        """Iterate through files, yielding (file_path, current_directory).

        This version tracks directories for checkpoint/resume functionality.
        """
        if not root_path.exists() or not root_path.is_dir():
            return

        # Use os.walk for more control over directory traversal
        for dirpath, dirnames, filenames in os.walk(root_path):
            if self._cancelled or self._paused:
                break

            current_dir = Path(dirpath)
            current_dir_str = str(current_dir)

            # Filter directories in-place to prevent traversal into excluded dirs
            dirnames[:] = [
                d for d in dirnames
                if self.file_filter.should_include_directory(current_dir / d)
            ]

            # Skip files if directory already completed (for resume)
            # But still allow traversal into subdirectories
            if current_dir_str in self._directories_completed:
                continue

            # Yield files
            for filename in filenames:
                if self._cancelled or self._paused:
                    break

                file_path = current_dir / filename
                yield file_path, current_dir_str

            # Mark directory as completed (if not cancelled/paused)
            if not self._cancelled and not self._paused:
                self._directories_completed.append(current_dir_str)

    def _create_scanned_file(
        self,
        file_path: Path,
        volume_id: int,
        volume_mount: Path,
        file_type: str
    ) -> ScannedFile:
        """Create a ScannedFile with loaded metadata."""
        scanned_file = ScannedFile.from_path(
            file_path=file_path,
            volume_id=volume_id,
            volume_mount=volume_mount
        )
        scanned_file.file_type = file_type

        # Load type-specific metadata
        if file_type == FileType.IMAGE:
            self._load_image_metadata(scanned_file, file_path)
        elif file_type == FileType.VIDEO:
            self._load_video_metadata(scanned_file, file_path)
        # Audio and document types don't need special metadata

        return scanned_file

    def _load_image_metadata(self, scanned_file: ScannedFile, file_path: Path):
        """Load image dimensions."""
        try:
            from PIL import Image

            ext = file_path.suffix.lower()

            # Handle RAW files
            if ext in ('.cr2', '.cr3', '.nef', '.arw', '.raf', '.orf', '.dng', '.raw'):
                try:
                    import rawpy
                    with rawpy.imread(str(file_path)) as raw:
                        sizes = raw.sizes
                        scanned_file.width = sizes.width
                        scanned_file.height = sizes.height
                except ImportError:
                    pass
            else:
                # Standard image formats
                with Image.open(file_path) as img:
                    scanned_file.width = img.width
                    scanned_file.height = img.height

        except Exception:
            pass  # Metadata loading is optional

    def _load_video_metadata(self, scanned_file: ScannedFile, file_path: Path):
        """Load video dimensions and duration."""
        # Try to use ffprobe if available
        try:
            import subprocess
            import json

            result = subprocess.run(
                [
                    'ffprobe', '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_streams',
                    str(file_path)
                ],
                capture_output=True,
                timeout=10
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        scanned_file.width = stream.get('width')
                        scanned_file.height = stream.get('height')
                        duration = stream.get('duration')
                        if duration:
                            scanned_file.duration_seconds = float(duration)
                        break

        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass  # ffprobe not available or failed
