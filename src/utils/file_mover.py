"""File mover with EXIF-based date organization and duplicate detection."""

from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime
import shutil
import hashlib

from src.utils.exif_extractor import ExifExtractor


class FileMover:
    """Handles moving files to destination with EXIF-based organization.

    Files are organized into YYYY/MM-DD folder structure based on EXIF dates.
    Supports reusing existing directories with descriptions (e.g., "05-03 England wedding").
    Can detect duplicates using hash comparison.
    """

    def __init__(self, db_manager=None, exif_extractor: Optional[ExifExtractor] = None):
        """
        Initialize FileMover.

        Args:
            db_manager: DatabaseManager instance for hash lookups (optional)
            exif_extractor: ExifExtractor instance (creates one if not provided)
        """
        self._db = db_manager
        self._exif = exif_extractor or ExifExtractor()

    def get_destination_path(self, file_path: Path, dest_root: Path) -> Path:
        """
        Determine destination path using EXIF dates and existing directory structure.

        Args:
            file_path: Source file path
            dest_root: Destination root directory

        Returns:
            Full destination path (dest_root/YYYY/MM-DD [description]/filename)
        """
        file_path = Path(file_path)
        dest_root = Path(dest_root)

        # Get date from EXIF (prefer dateTimeOriginal, then digitized, then fallback)
        date_original, date_digitized, fallback_date = self._exif.get_dates(file_path)

        # Use first available date
        file_date = date_original or date_digitized or fallback_date

        # Find or determine destination directory
        dest_dir = self.find_matching_directory(
            dest_root,
            file_date.year,
            file_date.month,
            file_date.day
        )

        return dest_dir / file_path.name

    def find_matching_directory(self, dest_root: Path, year: int, month: int, day: int) -> Path:
        """
        Find existing directory matching the date, even with descriptions.

        Searches for:
        - Exact match: dest_root/2024/05-03/
        - With description: dest_root/2024/05-03 England wedding/
        - Pattern: MM-DD*

        Args:
            dest_root: Root destination directory
            year: Year (e.g., 2024)
            month: Month (1-12)
            day: Day (1-31)

        Returns:
            Path to use for the date (existing directory or new path to create)
        """
        year_dir = dest_root / str(year)
        date_prefix = f"{month:02d}-{day:02d}"

        if year_dir.exists():
            # Look for existing directories starting with MM-DD
            try:
                for subdir in sorted(year_dir.iterdir()):
                    if subdir.is_dir() and subdir.name.startswith(date_prefix):
                        return subdir
            except OSError:
                pass

        # No existing match, return the standard path
        return year_dir / date_prefix

    def check_for_duplicate(
        self,
        source_path: Path,
        dest_dir: Path,
        hash_type: str = "exact_md5"
    ) -> Optional[Path]:
        """
        Check if source file has a duplicate in destination directory.

        Compares using hash data from database if available, otherwise
        computes hashes on the fly.

        Args:
            source_path: Path to source file
            dest_dir: Destination directory to check (flat only, not recursive)
            hash_type: Type of hash to use ("exact_md5" or "pixel_md5")

        Returns:
            Path to duplicate file in dest_dir if found, else None
        """
        source_path = Path(source_path)
        dest_dir = Path(dest_dir)

        if not dest_dir.exists():
            return None

        # Get source hash
        source_hash = self._get_file_hash(source_path, hash_type)
        if not source_hash:
            return None

        # Check each file in destination directory (flat only)
        try:
            for dest_file in dest_dir.iterdir():
                if not dest_file.is_file():
                    continue

                dest_hash = self._get_file_hash(dest_file, hash_type)
                if dest_hash and dest_hash == source_hash:
                    return dest_file
        except OSError:
            pass

        return None

    def _get_file_hash(self, file_path: Path, hash_type: str) -> Optional[str]:
        """
        Get hash for a file, using database if available or computing directly.

        Args:
            file_path: Path to file
            hash_type: Type of hash ("exact_md5" or "pixel_md5")

        Returns:
            Hash string or None if couldn't compute
        """
        # Try database lookup first
        if self._db:
            hash_value = self._lookup_hash_in_db(file_path, hash_type)
            if hash_value:
                return hash_value

        # Compute hash directly
        if hash_type == "exact_md5":
            return self._compute_md5(file_path)
        elif hash_type == "pixel_md5":
            return self._compute_pixel_md5(file_path)

        return None

    def _lookup_hash_in_db(self, file_path: Path, hash_type: str) -> Optional[str]:
        """
        Look up file hash in database.

        Args:
            file_path: Path to file
            hash_type: Type of hash

        Returns:
            Hash value from database or None
        """
        try:
            # Get database connection
            conn = self._db.get_connection()
            cursor = conn.cursor()

            # Look up by file path
            cursor.execute("""
                SELECT h.hash_value
                FROM hashes h
                JOIN files f ON h.file_id = f.id
                JOIN volumes v ON f.volume_id = v.id
                WHERE h.hash_type = ?
                  AND (v.mount_point || '/' || f.relative_path) = ?
            """, (hash_type, str(file_path)))

            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _compute_md5(self, file_path: Path) -> Optional[str]:
        """
        Compute MD5 hash of file contents.

        Args:
            file_path: Path to file

        Returns:
            MD5 hex digest or None if error
        """
        try:
            md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            return md5.hexdigest()
        except Exception:
            return None

    def _compute_pixel_md5(self, file_path: Path) -> Optional[str]:
        """
        Compute MD5 hash of image pixel data.

        Args:
            file_path: Path to image file

        Returns:
            MD5 hex digest of pixel data or None if error
        """
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                # Convert to RGB for consistent hashing
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Hash the raw pixel data
                pixel_data = img.tobytes()
                return hashlib.md5(pixel_data).hexdigest()
        except Exception:
            return None

    def move_file(self, source: Path, destination: Path) -> bool:
        """
        Move file from source to destination.

        Creates destination directory if it doesn't exist.

        Args:
            source: Source file path
            destination: Destination file path

        Returns:
            True if move successful, False otherwise
        """
        source = Path(source)
        destination = Path(destination)

        try:
            # Create destination directory if needed
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Move the file
            shutil.move(str(source), str(destination))
            return True
        except Exception:
            return False

    def move_to_trash(self, file_path: Path) -> bool:
        """
        Move file to system trash.

        Uses send2trash library for cross-platform support.
        Falls back to permanent deletion if send2trash not available.

        Args:
            file_path: Path to file to trash

        Returns:
            True if operation successful, False otherwise
        """
        file_path = Path(file_path)

        try:
            # Try send2trash first (cross-platform trash support)
            try:
                from send2trash import send2trash
                send2trash(str(file_path))
                return True
            except ImportError:
                # send2trash not available, ask before permanent delete
                import os
                os.remove(file_path)
                return True
        except Exception:
            return False

    def get_unique_name(self, dest_path: Path) -> Path:
        """
        Generate unique filename if destination already exists.

        Appends _1, _2, etc. before the extension.

        Args:
            dest_path: Desired destination path

        Returns:
            Unique path that doesn't exist
        """
        dest_path = Path(dest_path)

        if not dest_path.exists():
            return dest_path

        # Generate unique name
        stem = dest_path.stem
        suffix = dest_path.suffix
        parent = dest_path.parent

        counter = 1
        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            if not new_path.exists():
                return new_path
            counter += 1
            if counter > 1000:  # Safety limit
                raise ValueError(f"Could not generate unique name for {dest_path}")

    def get_files_in_directory(self, directory: Path, flat: bool = True) -> List[Path]:
        """
        Get list of files in a directory.

        Args:
            directory: Directory to scan
            flat: If True, only direct children; if False, recursive

        Returns:
            List of file paths
        """
        directory = Path(directory)

        if not directory.exists():
            return []

        try:
            if flat:
                return [f for f in directory.iterdir() if f.is_file()]
            else:
                return list(directory.rglob("*"))
        except OSError:
            return []
