"""Enhanced file scanner for all personal file types with database integration.

This scanner supports images, videos, documents, and audio files,
with filtering for system files and integration with the hash database.

Supports multi-threaded hash computation for improved performance on multi-core systems.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Generator, Dict, Tuple, TYPE_CHECKING
import os
import threading
import warnings

from .database import DatabaseManager

# Configure PIL to handle large images (panoramas, high-res scans, etc.)
# Default limit is ~89MP, increase to ~500MP (e.g., 22000x22000)
try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 500_000_000  # 500 million pixels
except ImportError:
    pass
from .file_classifier import FileClassifier, FileType, HashType
from .volume_manager import VolumeManager, VolumeInfo
from ..utils.file_filters import FileFilter
from ..models.scanned_file import ScannedFile


@dataclass
class HashJob:
    """A job for computing hashes in a worker thread."""
    file_id: int
    file_path: Path
    file_type: str
    primary_hash_type: str
    secondary_hash_type: Optional[str] = None


@dataclass
class HashResult:
    """Result from a hash computation job."""
    file_id: int
    primary_hash_type: str
    primary_hash_value: Optional[str]
    secondary_hash_type: Optional[str] = None
    secondary_hash_value: Optional[str] = None
    error: Optional[str] = None


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
    """Scans directories for personal files with filtering and database integration.

    Supports multi-threaded hash computation for improved performance on multi-core systems.
    The number of worker threads can be configured (defaults to CPU count).
    """

    # How often to save checkpoints (every N files)
    CHECKPOINT_INTERVAL = 100

    # Default number of hash worker threads (0 = auto-detect based on CPU count)
    DEFAULT_HASH_WORKERS = 0

    # Size of the hash job batch before waiting for results
    HASH_BATCH_SIZE = 50

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        file_filter: Optional[FileFilter] = None,
        file_classifier: Optional[FileClassifier] = None,
        volume_manager: Optional[VolumeManager] = None,
        hash_workers: int = 0,
    ):
        """Initialize the scanner.

        Args:
            db_manager: Database manager for storing results (optional)
            file_filter: File filter for excluding system files
            file_classifier: File classifier for determining file types
            volume_manager: Volume manager for drive detection
            hash_workers: Number of threads for parallel hash computation.
                         0 = auto-detect (uses CPU count), 1 = single-threaded
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
        self._excluded_paths: List[str] = []  # User-defined excluded paths
        self._volume_mount_point: Optional[Path] = None  # For relative path calculations

        # Multi-threading configuration
        if hash_workers == 0:
            # Auto-detect: use CPU count, but cap at reasonable limit
            import multiprocessing
            self._hash_workers = min(multiprocessing.cpu_count(), 16)
        else:
            self._hash_workers = max(1, hash_workers)

        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._pending_hash_futures: List[Future] = []
        self._db_lock = threading.Lock()  # Lock for thread-safe DB writes

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
        self._excluded_paths = []
        self._volume_mount_point = None
        self._pending_hash_futures = []

        # Shutdown existing thread pool if any
        if self._thread_pool:
            self._thread_pool.shutdown(wait=False)
            self._thread_pool = None

    @property
    def is_paused(self) -> bool:
        """Check if scanner is paused."""
        return self._paused

    @property
    def session_id(self) -> Optional[int]:
        """Get current session ID."""
        return self._current_session_id

    def _is_path_excluded(self, dir_path: Path) -> bool:
        """Check if a directory path matches any user-defined excluded path.

        Args:
            dir_path: Absolute path to check

        Returns:
            True if path should be excluded, False otherwise
        """
        if not self._excluded_paths or not self._volume_mount_point:
            return False

        # Get relative path from mount point
        try:
            relative = dir_path.relative_to(self._volume_mount_point)
            relative_str = str(relative)
        except ValueError:
            # Path is not under the mount point
            return False

        # Check if this path matches or is under any excluded path
        for excluded in self._excluded_paths:
            # Check if the path equals or starts with the excluded path
            if relative_str == excluded or relative_str.startswith(excluded + '/'):
                return True

        return False

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

        # Store mount point for relative path calculations
        self._volume_mount_point = volume_info.mount_point

        # Load user-defined excluded paths for this volume
        self._excluded_paths = self.db.get_excluded_paths(volume_id)

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

                # Skip unsupported files but track unknown extensions
                if file_type == FileType.OTHER:
                    ext = file_path.suffix.lower().lstrip('.')
                    if ext:  # Only track if there's an extension
                        self.db.add_unknown_extension(ext)
                        # Also record the path for directory listing
                        self.db.add_extension_sample_path(ext, volume_id, relative_path)
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
                file_id = self.db.add_file(
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

                # Compute and store hash for the file
                self._compute_and_store_hash(file_id, file_path, file_type)

                processed += 1
                self._stats.files_scanned += 1

                # Report progress
                if progress_callback:
                    progress_callback(file_path.name, processed, total_files)

                # Save checkpoint periodically
                if processed % self.CHECKPOINT_INTERVAL == 0:
                    self._save_checkpoint(session_id, current_dir, processed, total_files)

            # Wait for all pending hash jobs to complete before finalizing
            if self._hash_workers > 1:
                self._process_completed_hash_futures(wait_all=True)

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
            # Wait for pending hash jobs before error handling
            if self._hash_workers > 1:
                self._process_completed_hash_futures(wait_all=True)

            # Save checkpoint on error so scan can be resumed
            self._save_checkpoint(session_id, self._current_directory, processed, total_files)
            self.db.complete_scan_session(
                session_id,
                status='failed',
                error_message=str(e)
            )
            raise

        finally:
            # Clean up thread pool
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None

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
                and not self._is_path_excluded(current_dir / d)
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
                # Standard image formats - suppress warnings for large images
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)
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

    def _create_hash_job(
        self,
        file_id: int,
        file_path: Path,
        file_type: str
    ) -> HashJob:
        """Create a hash job for a file.

        Args:
            file_id: Database ID of the file
            file_path: Path to the file
            file_type: File type (image, video, etc.)

        Returns:
            HashJob ready for processing
        """
        primary_hash, secondary_hash = self.classifier.get_hash_strategy(file_path)
        return HashJob(
            file_id=file_id,
            file_path=file_path,
            file_type=file_type,
            primary_hash_type=primary_hash,
            secondary_hash_type=secondary_hash
        )

    def _process_hash_job(self, job: HashJob) -> HashResult:
        """Process a hash job (runs in worker thread).

        Args:
            job: The hash job to process

        Returns:
            HashResult with computed hashes
        """
        try:
            # Compute primary hash
            primary_value = self._compute_hash(
                job.file_path, job.primary_hash_type, job.file_type
            )

            # Compute secondary hash if defined
            secondary_value = None
            if job.secondary_hash_type:
                secondary_value = self._compute_hash(
                    job.file_path, job.secondary_hash_type, job.file_type
                )

            return HashResult(
                file_id=job.file_id,
                primary_hash_type=job.primary_hash_type,
                primary_hash_value=primary_value,
                secondary_hash_type=job.secondary_hash_type,
                secondary_hash_value=secondary_value
            )
        except Exception as e:
            return HashResult(
                file_id=job.file_id,
                primary_hash_type=job.primary_hash_type,
                primary_hash_value=None,
                error=str(e)
            )

    def _store_hash_result(self, result: HashResult):
        """Store hash result in the database (thread-safe).

        Args:
            result: Hash result to store
        """
        if result.error:
            return

        with self._db_lock:
            if result.primary_hash_value:
                self.db.add_hash(
                    result.file_id,
                    result.primary_hash_type,
                    result.primary_hash_value
                )
            if result.secondary_hash_value and result.secondary_hash_type:
                self.db.add_hash(
                    result.file_id,
                    result.secondary_hash_type,
                    result.secondary_hash_value
                )

    def _submit_hash_job(self, job: HashJob):
        """Submit a hash job to the thread pool.

        Args:
            job: Hash job to submit
        """
        if self._thread_pool is None:
            self._thread_pool = ThreadPoolExecutor(
                max_workers=self._hash_workers,
                thread_name_prefix="hash_worker"
            )

        future = self._thread_pool.submit(self._process_hash_job, job)
        self._pending_hash_futures.append(future)

        # Process completed futures if we have a batch ready
        if len(self._pending_hash_futures) >= self.HASH_BATCH_SIZE:
            self._process_completed_hash_futures()

    def _process_completed_hash_futures(self, wait_all: bool = False):
        """Process completed hash futures and store results.

        Args:
            wait_all: If True, wait for all pending futures to complete
        """
        if not self._pending_hash_futures:
            return

        if wait_all:
            # Wait for all futures to complete
            for future in as_completed(self._pending_hash_futures):
                try:
                    result = future.result()
                    self._store_hash_result(result)
                except Exception:
                    pass  # Already handled in _process_hash_job
            self._pending_hash_futures.clear()
        else:
            # Process only completed futures
            still_pending = []
            for future in self._pending_hash_futures:
                if future.done():
                    try:
                        result = future.result()
                        self._store_hash_result(result)
                    except Exception:
                        pass
                else:
                    still_pending.append(future)
            self._pending_hash_futures = still_pending

    def _compute_and_store_hash(
        self,
        file_id: int,
        file_path: Path,
        file_type: str
    ):
        """Compute hash(es) for a file and store in the database.

        Uses multi-threading if hash_workers > 1, otherwise computes synchronously.

        Uses the appropriate hash strategy based on file type:
        - Images (jpg, jpeg, gif): perceptual pHash + pixel MD5
        - Images (png, raw, etc): pixel MD5 + perceptual pHash
        - Videos/Audio/Documents: file MD5

        Args:
            file_id: Database ID of the file
            file_path: Path to the file
            file_type: File type (image, video, etc.)
        """
        if self._hash_workers > 1:
            # Multi-threaded: submit job to thread pool
            job = self._create_hash_job(file_id, file_path, file_type)
            self._submit_hash_job(job)
        else:
            # Single-threaded: compute and store synchronously
            primary_hash, secondary_hash = self.classifier.get_hash_strategy(file_path)

            # Compute primary hash
            hash_value = self._compute_hash(file_path, primary_hash, file_type)
            if hash_value:
                self.db.add_hash(file_id, primary_hash, hash_value)

            # Compute secondary hash if defined (e.g., for images)
            if secondary_hash:
                hash_value = self._compute_hash(file_path, secondary_hash, file_type)
                if hash_value:
                    self.db.add_hash(file_id, secondary_hash, hash_value)

    def _compute_hash(
        self,
        file_path: Path,
        hash_type: str,
        file_type: str
    ) -> Optional[str]:
        """Compute a specific type of hash for a file.

        Args:
            file_path: Path to the file
            hash_type: Type of hash to compute (from HashType)
            file_type: File type for context

        Returns:
            Hash value as string, or None if computation failed
        """
        try:
            if hash_type == HashType.EXACT_MD5:
                return self._compute_file_md5(file_path)

            elif hash_type == HashType.PIXEL_MD5:
                return self._compute_pixel_md5(file_path)

            elif hash_type.startswith('perceptual_'):
                # Extract algorithm name (phash, dhash, etc.)
                algorithm = hash_type.replace('perceptual_', '')
                phash = self._compute_perceptual_hash(file_path, algorithm)
                # Convert ImageHash to string for storage
                return str(phash) if phash else None

            else:
                # Unknown hash type, fall back to file MD5
                return self._compute_file_md5(file_path)

        except Exception:
            return None

    def _compute_file_md5(self, file_path: Path, chunk_size: int = 65536) -> Optional[str]:
        """Compute MD5 hash of entire file.

        Args:
            file_path: Path to the file
            chunk_size: Size of chunks to read

        Returns:
            MD5 hex digest or None if failed
        """
        import hashlib
        try:
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(chunk_size), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError):
            return None

    def _compute_pixel_md5(self, file_path: Path) -> Optional[str]:
        """Compute MD5 hash of image pixel data (ignores EXIF metadata).

        Args:
            file_path: Path to the image file

        Returns:
            MD5 hex digest or None if failed
        """
        import hashlib
        try:
            ext = file_path.suffix.lower()

            # Handle RAW files with rawpy
            if ext in ('.cr2', '.crw', '.cr3', '.raf', '.raw', '.nef', '.arw', '.orf', '.dng'):
                try:
                    import rawpy
                    with rawpy.imread(str(file_path)) as raw:
                        rgb = raw.postprocess()
                        hasher = hashlib.md5()
                        hasher.update(rgb.tobytes())
                        return hasher.hexdigest()
                except Exception:
                    # Fall back to file hash
                    return self._compute_file_md5(file_path)

            # Standard image formats with PIL
            from PIL import Image
            # Suppress decompression bomb warnings for large but legitimate images
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)
                with Image.open(file_path) as img:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    pixel_data = img.tobytes()
                    hasher = hashlib.md5()
                    hasher.update(pixel_data)
                    return hasher.hexdigest()

        except Exception:
            # Fall back to file hash
            return self._compute_file_md5(file_path)

    def _compute_perceptual_hash(
        self,
        file_path: Path,
        algorithm: str = "phash"
    ) -> Optional['imagehash.ImageHash']:
        """Compute perceptual hash of an image.

        Args:
            file_path: Path to the image file
            algorithm: Hash algorithm (phash, dhash, ahash, whash)

        Returns:
            ImageHash object or None if failed
        """
        try:
            import imagehash
            from PIL import Image, ImageOps

            # Select hash function
            hash_functions = {
                'phash': imagehash.phash,
                'dhash': imagehash.dhash,
                'ahash': imagehash.average_hash,
                'whash': imagehash.whash,
            }
            hash_func = hash_functions.get(algorithm, imagehash.phash)

            ext = file_path.suffix.lower()

            # Handle RAW files
            if ext in ('.cr2', '.crw', '.cr3', '.raf', '.raw', '.nef', '.arw', '.orf', '.dng'):
                try:
                    import rawpy
                    with rawpy.imread(str(file_path)) as raw:
                        rgb = raw.postprocess()
                        img = Image.fromarray(rgb)
                        return hash_func(img)
                except Exception:
                    return None

            # Standard images - suppress decompression bomb warnings for large images
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)
                with Image.open(file_path) as img:
                    # Apply EXIF orientation correction
                    img = ImageOps.exif_transpose(img)
                    return hash_func(img)

        except Exception:
            return None

    def collect_extension_directories(
        self,
        volume_info: VolumeInfo,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        scan_path: Optional[Path] = None,
    ) -> Dict[str, int]:
        """Quick scan to collect directory info for unknown/excluded extensions.

        This is a lightweight scan that only records where unknown/excluded
        file types are found, without indexing files or computing hashes.

        Args:
            volume_info: Volume to scan
            progress_callback: Optional callback(status, current, total)
            scan_path: Optional specific path to scan (defaults to volume root)

        Returns:
            Dict mapping extension to count of files found
        """
        self._cancelled = False

        # Register volume
        volume_id = self.db.register_volume(
            uuid=volume_info.uuid,
            name=volume_info.name,
            mount_point=str(volume_info.mount_point),
            total_bytes=volume_info.total_bytes,
            filesystem=volume_info.filesystem,
        )

        root_path = scan_path or volume_info.mount_point
        volume_mount = volume_info.mount_point

        # Clear existing sample paths for this volume
        self.db.clear_extension_sample_paths(volume_id)

        # Count files for progress
        if progress_callback:
            progress_callback("Counting files...", 0, 0)

        total_files = 0
        for _ in root_path.rglob('*'):
            if self._cancelled:
                break
            total_files += 1

        if self._cancelled:
            return {}

        # Scan and collect extension info
        extension_counts: Dict[str, int] = {}
        processed = 0

        for file_path in root_path.rglob('*'):
            if self._cancelled:
                break

            if not file_path.is_file():
                continue

            processed += 1

            if progress_callback and processed % 1000 == 0:
                progress_callback(
                    f"Scanning: {file_path.parent.name}",
                    processed,
                    total_files
                )

            # Skip files in excluded directories
            if self.file_filter and not self.file_filter.should_include_directory(file_path.parent):
                continue

            # Get file extension
            ext = file_path.suffix.lower().lstrip('.')
            if not ext:
                continue

            # Check if this is an unknown/excluded extension
            file_type = self.classifier.get_file_type(file_path)

            if file_type == FileType.OTHER:
                # This is an unknown/excluded extension - record it
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

                # Record the directory path
                try:
                    relative_path = str(file_path.relative_to(volume_mount))
                    self.db.add_extension_sample_path(ext, volume_id, relative_path)
                except ValueError:
                    pass  # File not under volume mount

                # Also update the unknown_extensions count
                self.db.add_unknown_extension(ext)

        if progress_callback:
            progress_callback("Complete", total_files, total_files)

        return extension_counts
