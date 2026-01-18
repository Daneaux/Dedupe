"""Image file model with metadata."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple
import os


@dataclass
class ImageFile:
    """Represents an image file with its metadata."""

    path: Path
    file_size: int = 0
    width: int = 0
    height: int = 0
    hash_value: Optional[str] = None
    cnn_encoding: Optional[object] = None

    def __post_init__(self):
        """Convert path to Path object if string."""
        if isinstance(self.path, str):
            self.path = Path(self.path)

        # Get file size if not provided
        if self.file_size == 0 and self.path.exists():
            self.file_size = self.path.stat().st_size

    @property
    def filename(self) -> str:
        """Get the filename."""
        return self.path.name

    @property
    def directory(self) -> Path:
        """Get the parent directory."""
        return self.path.parent

    @property
    def extension(self) -> str:
        """Get the file extension (lowercase, without dot)."""
        return self.path.suffix.lower().lstrip(".")

    @property
    def resolution(self) -> int:
        """Get total pixel count (width * height)."""
        return self.width * self.height

    @property
    def dimensions(self) -> Tuple[int, int]:
        """Get dimensions as (width, height) tuple."""
        return (self.width, self.height)

    @property
    def path_depth(self) -> int:
        """Get the path depth (number of path components)."""
        return len(self.path.parts)

    @property
    def file_size_str(self) -> str:
        """Get human-readable file size."""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def dimensions_str(self) -> str:
        """Get dimensions as string."""
        if self.width and self.height:
            return f"{self.width} x {self.height}"
        return "Unknown"

    def load_metadata(self) -> bool:
        """
        Load image metadata (dimensions) from file.
        Returns True if successful, False otherwise.
        """
        try:
            from PIL import Image

            # Try to open with PIL first
            try:
                with Image.open(self.path) as img:
                    self.width, self.height = img.size
                    return True
            except Exception:
                pass

            # Try rawpy for RAW files
            if self.extension in ("raw", "cr2", "crw", "cr3", "raf", "nef", "arw"):
                try:
                    import rawpy
                    with rawpy.imread(str(self.path)) as raw:
                        sizes = raw.sizes
                        self.width = sizes.width
                        self.height = sizes.height
                        return True
                except Exception:
                    pass

            return False

        except ImportError:
            return False

    def __hash__(self):
        """Hash based on file path."""
        return hash(self.path)

    def __eq__(self, other):
        """Equality based on file path."""
        if isinstance(other, ImageFile):
            return self.path == other.path
        return False

    def __repr__(self):
        return f"ImageFile({self.path.name}, {self.file_size_str}, {self.dimensions_str})"
