"""File type classification and hash strategy determination.

Determines file types from extensions and which hash algorithm
to use for each file type.
"""

from pathlib import Path
from typing import Optional, Set, Dict, Tuple


# ==================== File Type Categories ====================

# Images that get perceptual hashing (lossy formats benefit from visual matching)
PERCEPTUAL_IMAGE_EXTENSIONS = {
    'jpg', 'jpeg', 'gif',
}

# Images that get exact pixel hashing (lossless or RAW)
EXACT_IMAGE_EXTENSIONS = {
    # Lossless formats
    'png', 'bmp', 'webp', 'tiff', 'tif',
    # High-efficiency formats
    'heic', 'heif', 'avif',
    # RAW formats
    'raw', 'cr2', 'crw', 'cr3',  # Canon
    'nef', 'nrw',                 # Nikon
    'arw', 'srf', 'sr2',          # Sony
    'raf',                        # Fujifilm
    'orf',                        # Olympus
    'rw2',                        # Panasonic
    'pef', 'ptx',                 # Pentax
    'dng',                        # Adobe Digital Negative
    'x3f',                        # Sigma
    '3fr',                        # Hasselblad
    'fff',                        # Imacon/Hasselblad
    'mef',                        # Mamiya
    'mrw',                        # Minolta
    'kdc', 'dcr',                 # Kodak
    'rwl',                        # Leica
    'iiq',                        # Phase One
    'erf',                        # Epson
}

# All image extensions
ALL_IMAGE_EXTENSIONS = PERCEPTUAL_IMAGE_EXTENSIONS | EXACT_IMAGE_EXTENSIONS

# Video extensions
VIDEO_EXTENSIONS = {
    'mp4', 'm4v', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm',
    'mpg', 'mpeg', 'm2v', 'mpe',
    '3gp', '3g2',
    'mts', 'm2ts', 'ts',
    'vob', 'ogv',
    'rm', 'rmvb',
    'asf',
    'divx', 'xvid',
}

# Audio extensions
AUDIO_EXTENSIONS = {
    'mp3', 'wav', 'flac', 'aac', 'm4a', 'wma', 'ogg', 'oga',
    'aiff', 'aif', 'aifc',
    'ape', 'alac',
    'opus', 'webm',  # webm can be audio-only
    'mid', 'midi',
    'mka',
    'ra', 'ram',
    'wv',  # WavPack
}

# Document extensions
DOCUMENT_EXTENSIONS = {
    # PDF
    'pdf',

    # Microsoft Office
    'doc', 'docx', 'docm',
    'xls', 'xlsx', 'xlsm', 'xlsb',
    'ppt', 'pptx', 'pptm',

    # OpenDocument
    'odt', 'ods', 'odp', 'odg',

    # Apple iWork
    'pages', 'numbers', 'keynote',

    # Text formats
    'txt', 'rtf', 'md', 'markdown', 'rst',
    'csv', 'tsv',
    'json', 'xml', 'yaml', 'yml',
    'html', 'htm', 'xhtml',

    # eBooks
    'epub', 'mobi', 'azw', 'azw3',

    # Other documents
    'tex', 'latex',
    'ps', 'eps',
    'xps',
}

# Archive extensions
ARCHIVE_EXTENSIONS = {
    'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'lz', 'lzma',
    'tgz', 'tbz2', 'txz',
    'cab', 'arj', 'lzh',
    'iso', 'dmg', 'img',
}


# ==================== Hash Types ====================

class HashType:
    """Hash type constants."""
    EXACT_MD5 = "exact_md5"              # Full file MD5
    PIXEL_MD5 = "pixel_md5"              # MD5 of pixel data (ignores metadata)
    PERCEPTUAL_PHASH = "perceptual_phash"  # Perceptual hash (pHash)
    PERCEPTUAL_DHASH = "perceptual_dhash"  # Difference hash
    PERCEPTUAL_AHASH = "perceptual_ahash"  # Average hash
    PERCEPTUAL_WHASH = "perceptual_whash"  # Wavelet hash


# ==================== File Type Constants ====================

class FileType:
    """File type constants."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    OTHER = "other"


# ==================== Hash Strategy ====================

# Maps file type to (primary_hash, secondary_hash)
# Secondary hash is optional, used for more precise matching
HASH_STRATEGY: Dict[str, Tuple[str, Optional[str]]] = {
    FileType.IMAGE: (HashType.EXACT_MD5, HashType.PIXEL_MD5),  # Default for images (overridden per extension)
    FileType.VIDEO: (HashType.EXACT_MD5, None),
    FileType.AUDIO: (HashType.EXACT_MD5, None),
    FileType.DOCUMENT: (HashType.EXACT_MD5, None),
    FileType.ARCHIVE: (HashType.EXACT_MD5, None),
    FileType.OTHER: (HashType.EXACT_MD5, None),
}

# Override for specific extensions
EXTENSION_HASH_OVERRIDE: Dict[str, str] = {
    # Perceptual hash for lossy image formats
    'jpg': HashType.PERCEPTUAL_PHASH,
    'jpeg': HashType.PERCEPTUAL_PHASH,
    'gif': HashType.PERCEPTUAL_PHASH,

    # Exact pixel hash for lossless/RAW images
    'png': HashType.PIXEL_MD5,
    'bmp': HashType.PIXEL_MD5,
    'tiff': HashType.PIXEL_MD5,
    'tif': HashType.PIXEL_MD5,
    'webp': HashType.PIXEL_MD5,
    'heic': HashType.PIXEL_MD5,
    'heif': HashType.PIXEL_MD5,

    # RAW formats get pixel MD5
    'raw': HashType.PIXEL_MD5,
    'cr2': HashType.PIXEL_MD5,
    'cr3': HashType.PIXEL_MD5,
    'nef': HashType.PIXEL_MD5,
    'arw': HashType.PIXEL_MD5,
    'raf': HashType.PIXEL_MD5,
    'orf': HashType.PIXEL_MD5,
    'dng': HashType.PIXEL_MD5,
}


class FileClassifier:
    """Classifies files by type and determines hash strategy."""

    def __init__(self, use_custom_settings: bool = True):
        """Initialize the file classifier.

        Args:
            use_custom_settings: If True, load custom extension settings from database
        """
        self._base_extension_to_type = self._build_extension_map()
        self._custom_includes: Set[str] = set()
        self._custom_excludes: Set[str] = set()

        if use_custom_settings:
            self._load_custom_settings()

        self._extension_to_type = self._apply_custom_settings()

    def _build_extension_map(self) -> Dict[str, str]:
        """Build extension to file type mapping."""
        mapping = {}

        for ext in ALL_IMAGE_EXTENSIONS:
            mapping[ext] = FileType.IMAGE

        for ext in VIDEO_EXTENSIONS:
            mapping[ext] = FileType.VIDEO

        for ext in AUDIO_EXTENSIONS:
            mapping[ext] = FileType.AUDIO

        for ext in DOCUMENT_EXTENSIONS:
            mapping[ext] = FileType.DOCUMENT

        for ext in ARCHIVE_EXTENSIONS:
            mapping[ext] = FileType.ARCHIVE

        return mapping

    def _load_custom_settings(self):
        """Load custom extension settings from the database."""
        try:
            from .database import DatabaseManager
            db = DatabaseManager.get_instance()
            self._custom_includes = set(db.get_custom_included_extensions())
            self._custom_excludes = set(db.get_custom_excluded_extensions())
        except Exception:
            # Database not available or error, use defaults
            self._custom_includes = set()
            self._custom_excludes = set()

    def _apply_custom_settings(self) -> Dict[str, str]:
        """Apply custom include/exclude settings to the extension map."""
        mapping = dict(self._base_extension_to_type)

        # Remove excluded extensions
        for ext in self._custom_excludes:
            mapping.pop(ext, None)

        # Add custom included extensions (classify as 'other' by default
        # but still include them in scanning)
        for ext in self._custom_includes:
            if ext not in mapping:
                # Determine type based on common patterns or default to document
                mapping[ext] = self._guess_file_type(ext)

        return mapping

    def _guess_file_type(self, ext: str) -> str:
        """Guess file type for a custom included extension."""
        # Check if it looks like an image, video, etc.
        ext = ext.lower()

        # Image-like extensions
        if any(hint in ext for hint in ['img', 'pic', 'photo', 'image']):
            return FileType.IMAGE

        # Video-like extensions
        if any(hint in ext for hint in ['vid', 'movie', 'clip']):
            return FileType.VIDEO

        # Audio-like extensions
        if any(hint in ext for hint in ['aud', 'sound', 'music']):
            return FileType.AUDIO

        # Default to document (generic file type)
        return FileType.DOCUMENT

    def reload_custom_settings(self):
        """Reload custom settings from the database."""
        self._load_custom_settings()
        self._extension_to_type = self._apply_custom_settings()

    def get_file_type(self, file_path: Path) -> str:
        """Get the file type for a given file.

        Args:
            file_path: Path to the file

        Returns:
            File type string (image, video, audio, document, archive, other)
        """
        ext = file_path.suffix.lower().lstrip('.')
        return self._extension_to_type.get(ext, FileType.OTHER)

    def get_file_type_from_extension(self, extension: str) -> str:
        """Get file type from extension string.

        Args:
            extension: File extension (without dot)

        Returns:
            File type string
        """
        ext = extension.lower().lstrip('.')
        return self._extension_to_type.get(ext, FileType.OTHER)

    def get_hash_type(self, file_path: Path) -> str:
        """Get the recommended hash type for a file.

        Args:
            file_path: Path to the file

        Returns:
            Hash type string
        """
        ext = file_path.suffix.lower().lstrip('.')

        # Check for extension-specific override
        if ext in EXTENSION_HASH_OVERRIDE:
            return EXTENSION_HASH_OVERRIDE[ext]

        # Fall back to file type strategy
        file_type = self.get_file_type(file_path)
        primary, _ = HASH_STRATEGY.get(file_type, (HashType.EXACT_MD5, None))
        return primary

    def get_hash_type_from_extension(self, extension: str) -> str:
        """Get hash type from extension string.

        Args:
            extension: File extension (without dot)

        Returns:
            Hash type string
        """
        ext = extension.lower().lstrip('.')

        if ext in EXTENSION_HASH_OVERRIDE:
            return EXTENSION_HASH_OVERRIDE[ext]

        file_type = self.get_file_type_from_extension(ext)
        primary, _ = HASH_STRATEGY.get(file_type, (HashType.EXACT_MD5, None))
        return primary

    def get_hash_strategy(self, file_path: Path) -> Tuple[str, Optional[str]]:
        """Get full hash strategy (primary and secondary) for a file.

        Args:
            file_path: Path to the file

        Returns:
            Tuple of (primary_hash_type, secondary_hash_type or None)
        """
        file_type = self.get_file_type(file_path)
        ext = file_path.suffix.lower().lstrip('.')

        # For images, use extension-specific strategy
        if file_type == FileType.IMAGE:
            if ext in PERCEPTUAL_IMAGE_EXTENSIONS:  # jpg, jpeg, gif (lossy formats)
                return (HashType.PIXEL_MD5, HashType.PERCEPTUAL_PHASH)
            else:  # RAW and lossless formats - no perceptual hash
                return (HashType.EXACT_MD5, HashType.PIXEL_MD5)

        return HASH_STRATEGY.get(file_type, (HashType.EXACT_MD5, None))

    def is_supported(self, file_path: Path) -> bool:
        """Check if a file type is supported.

        Args:
            file_path: Path to the file

        Returns:
            True if file type is supported for scanning
        """
        return self.get_file_type(file_path) != FileType.OTHER

    def is_supported_extension(self, extension: str) -> bool:
        """Check if an extension is supported.

        Args:
            extension: File extension (without dot)

        Returns:
            True if extension is supported
        """
        ext = extension.lower().lstrip('.')
        return ext in self._extension_to_type

    def uses_perceptual_hash(self, file_path: Path) -> bool:
        """Check if a file should use perceptual hashing.

        Args:
            file_path: Path to the file

        Returns:
            True if perceptual hash is primary hash type
        """
        hash_type = self.get_hash_type(file_path)
        return hash_type.startswith('perceptual_')

    def get_all_supported_extensions(self) -> Set[str]:
        """Get all supported file extensions."""
        return set(self._extension_to_type.keys())

    def get_extensions_for_type(self, file_type: str) -> Set[str]:
        """Get all extensions for a specific file type.

        Args:
            file_type: File type (image, video, etc.)

        Returns:
            Set of extensions
        """
        return {ext for ext, ft in self._extension_to_type.items() if ft == file_type}


# Convenience functions
def get_file_type(file_path: Path) -> str:
    """Quick function to get file type."""
    return FileClassifier().get_file_type(file_path)


def get_hash_type(file_path: Path) -> str:
    """Quick function to get hash type."""
    return FileClassifier().get_hash_type(file_path)


def is_supported(file_path: Path) -> bool:
    """Quick function to check if file is supported."""
    return FileClassifier().is_supported(file_path)
