"""File scanner for discovering image files."""

from pathlib import Path
from typing import List, Set, Generator, Callable, Optional
import os

from ..models.image_file import ImageFile


# Supported image extensions (case-insensitive)
SUPPORTED_EXTENSIONS: Set[str] = {
    "gif", "jpeg", "jpg", "raw", "cr2", "crw", "cr3", "raf", "tiff", "tif",
    "png", "bmp", "webp"  # Additional common formats supported by imagededup
}


class ImageScanner:
    """Scans directories for image files with progress reporting."""

    def __init__(
        self,
        extensions: Optional[Set[str]] = None,
        recursive: bool = True
    ):
        """
        Initialize the scanner.

        Args:
            extensions: Set of file extensions to include (without dots, lowercase).
                       Defaults to SUPPORTED_EXTENSIONS.
            recursive: Whether to scan subdirectories.
        """
        self.extensions = extensions or SUPPORTED_EXTENSIONS
        self.recursive = recursive
        self._cancelled = False

    def is_supported(self, path: Path) -> bool:
        """Check if a file has a supported extension."""
        ext = path.suffix.lower().lstrip(".")
        return ext in self.extensions

    def cancel(self):
        """Cancel the current scan operation."""
        self._cancelled = True

    def reset(self):
        """Reset the scanner state."""
        self._cancelled = False

    def count_files(self, root_dir: Path) -> int:
        """
        Count total image files in directory (for progress calculation).

        Args:
            root_dir: Root directory to scan.

        Returns:
            Total count of matching image files.
        """
        count = 0
        root_path = Path(root_dir)

        if not root_path.exists() or not root_path.is_dir():
            return 0

        if self.recursive:
            for item in root_path.rglob("*"):
                if item.is_file() and self.is_supported(item):
                    count += 1
        else:
            for item in root_path.iterdir():
                if item.is_file() and self.is_supported(item):
                    count += 1

        return count

    def scan(
        self,
        root_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        load_metadata: bool = True
    ) -> List[ImageFile]:
        """
        Scan directory for image files.

        Args:
            root_dir: Root directory to scan.
            progress_callback: Optional callback(current_file, processed, total) for progress updates.
            load_metadata: Whether to load image metadata (dimensions).

        Returns:
            List of ImageFile objects.
        """
        self._cancelled = False
        root_path = Path(root_dir)

        if not root_path.exists():
            raise FileNotFoundError(f"Directory not found: {root_dir}")

        if not root_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {root_dir}")

        # First, count total files for progress reporting
        total = self.count_files(root_path) if progress_callback else 0

        images: List[ImageFile] = []
        processed = 0

        # Scan for files
        if self.recursive:
            file_iterator = root_path.rglob("*")
        else:
            file_iterator = root_path.iterdir()

        for item in file_iterator:
            if self._cancelled:
                break

            if not item.is_file():
                continue

            if not self.is_supported(item):
                continue

            # Create ImageFile object
            image = ImageFile(path=item)

            # Load metadata if requested
            if load_metadata:
                image.load_metadata()

            images.append(image)
            processed += 1

            # Report progress
            if progress_callback:
                progress_callback(str(item), processed, total)

        return images

    def scan_generator(
        self,
        root_dir: Path,
        load_metadata: bool = True
    ) -> Generator[ImageFile, None, None]:
        """
        Scan directory yielding ImageFile objects as they're found.

        Args:
            root_dir: Root directory to scan.
            load_metadata: Whether to load image metadata.

        Yields:
            ImageFile objects as they're discovered.
        """
        self._cancelled = False
        root_path = Path(root_dir)

        if not root_path.exists() or not root_path.is_dir():
            return

        if self.recursive:
            file_iterator = root_path.rglob("*")
        else:
            file_iterator = root_path.iterdir()

        for item in file_iterator:
            if self._cancelled:
                break

            if not item.is_file():
                continue

            if not self.is_supported(item):
                continue

            image = ImageFile(path=item)

            if load_metadata:
                image.load_metadata()

            yield image

    def group_by_directory(self, images: List[ImageFile]) -> dict:
        """
        Group images by their parent directory.

        Args:
            images: List of ImageFile objects.

        Returns:
            Dictionary mapping directory paths to lists of images.
        """
        groups = {}
        for image in images:
            directory = image.directory
            if directory not in groups:
                groups[directory] = []
            groups[directory].append(image)
        return groups
