"""Scanned file model for all file types (images, videos, documents, audio)."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict


@dataclass
class ScannedFile:
    """Represents a scanned file with metadata and hashes.

    This is a generalized model that works for all file types:
    images, videos, documents, and audio files.
    """

    # Core identification
    id: Optional[int] = None  # Database ID
    volume_id: Optional[int] = None  # FK to volumes table
    path: Optional[Path] = None  # Full absolute path (computed from volume mount + relative)
    relative_path: str = ""  # Path relative to volume root

    # File metadata
    filename: str = ""
    extension: str = ""
    file_size_bytes: int = 0
    file_type: str = ""  # 'image', 'video', 'document', 'audio', 'other'

    # Media-specific metadata
    width: Optional[int] = None  # For images/videos
    height: Optional[int] = None  # For images/videos
    duration_seconds: Optional[float] = None  # For videos/audio

    # Timestamps
    file_created_at: Optional[datetime] = None
    file_modified_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None

    # Hashes (populated on demand)
    hashes: Dict[str, str] = field(default_factory=dict)

    # Flags
    is_deleted: bool = False

    @property
    def file_size_str(self) -> str:
        """Get human-readable file size."""
        size = self.file_size_bytes
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def dimensions(self) -> Optional[tuple]:
        """Get dimensions as tuple (width, height)."""
        if self.width and self.height:
            return (self.width, self.height)
        return None

    @property
    def dimensions_str(self) -> str:
        """Get dimensions as string."""
        if self.width and self.height:
            return f"{self.width} x {self.height}"
        return ""

    @property
    def resolution(self) -> int:
        """Get total resolution (width * height)."""
        if self.width and self.height:
            return self.width * self.height
        return 0

    @property
    def duration_str(self) -> str:
        """Get human-readable duration for videos/audio."""
        if self.duration_seconds is None:
            return ""
        total_seconds = int(self.duration_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def directory(self) -> Path:
        """Get parent directory of the file."""
        if self.path:
            return self.path.parent
        return Path(self.relative_path).parent

    @property
    def is_image(self) -> bool:
        """Check if file is an image."""
        return self.file_type == "image"

    @property
    def is_video(self) -> bool:
        """Check if file is a video."""
        return self.file_type == "video"

    @property
    def is_document(self) -> bool:
        """Check if file is a document."""
        return self.file_type == "document"

    @property
    def is_audio(self) -> bool:
        """Check if file is an audio file."""
        return self.file_type == "audio"

    def get_hash(self, hash_type: str) -> Optional[str]:
        """Get a specific hash value."""
        return self.hashes.get(hash_type)

    def set_hash(self, hash_type: str, hash_value: str):
        """Set a hash value."""
        self.hashes[hash_type] = hash_value

    @classmethod
    def from_db_row(cls, row: Dict, volume_mount: Optional[Path] = None) -> 'ScannedFile':
        """Create ScannedFile from database row dictionary."""
        # Parse timestamps
        file_created = None
        if row.get('file_created_at'):
            try:
                file_created = datetime.fromisoformat(row['file_created_at'])
            except (ValueError, TypeError):
                pass

        file_modified = None
        if row.get('file_modified_at'):
            try:
                file_modified = datetime.fromisoformat(row['file_modified_at'])
            except (ValueError, TypeError):
                pass

        indexed = None
        if row.get('indexed_at'):
            try:
                indexed = datetime.fromisoformat(row['indexed_at'])
            except (ValueError, TypeError):
                pass

        # Compute full path if volume mount is provided
        full_path = None
        if volume_mount and row.get('relative_path'):
            full_path = volume_mount / row['relative_path']

        return cls(
            id=row.get('id'),
            volume_id=row.get('volume_id'),
            path=full_path,
            relative_path=row.get('relative_path', ''),
            filename=row.get('filename', ''),
            extension=row.get('extension', ''),
            file_size_bytes=row.get('file_size_bytes', 0),
            file_type=row.get('file_type', ''),
            width=row.get('width'),
            height=row.get('height'),
            duration_seconds=row.get('duration_seconds'),
            file_created_at=file_created,
            file_modified_at=file_modified,
            indexed_at=indexed,
            is_deleted=bool(row.get('is_deleted', 0)),
        )

    @classmethod
    def from_path(
        cls,
        file_path: Path,
        volume_id: Optional[int] = None,
        volume_mount: Optional[Path] = None
    ) -> 'ScannedFile':
        """Create ScannedFile from a file path.

        Note: This only populates basic info. Use file_classifier
        to set file_type and scanner to load full metadata.
        """
        # Calculate relative path
        relative_path = ""
        if volume_mount:
            try:
                relative_path = str(file_path.relative_to(volume_mount))
            except ValueError:
                relative_path = str(file_path)
        else:
            relative_path = str(file_path)

        # Get file stats
        try:
            stat = file_path.stat()
            file_size = stat.st_size
            file_modified = datetime.fromtimestamp(stat.st_mtime)
            file_created = datetime.fromtimestamp(stat.st_ctime)
        except OSError:
            file_size = 0
            file_modified = None
            file_created = None

        return cls(
            volume_id=volume_id,
            path=file_path,
            relative_path=relative_path,
            filename=file_path.name,
            extension=file_path.suffix.lower().lstrip('.'),
            file_size_bytes=file_size,
            file_created_at=file_created,
            file_modified_at=file_modified,
        )

    def to_db_dict(self) -> Dict:
        """Convert to dictionary for database insertion."""
        return {
            'volume_id': self.volume_id,
            'relative_path': self.relative_path,
            'filename': self.filename,
            'extension': self.extension,
            'file_size_bytes': self.file_size_bytes,
            'file_type': self.file_type,
            'width': self.width,
            'height': self.height,
            'duration_seconds': self.duration_seconds,
            'file_created_at': self.file_created_at.isoformat() if self.file_created_at else None,
            'file_modified_at': self.file_modified_at.isoformat() if self.file_modified_at else None,
        }

    def __str__(self) -> str:
        return f"ScannedFile({self.filename}, {self.file_type}, {self.file_size_str})"

    def __repr__(self) -> str:
        return f"ScannedFile(id={self.id}, path={self.relative_path!r}, type={self.file_type!r})"
