"""File filtering rules for excluding system files and non-personal files.

Cross-platform support for macOS, Windows, and Linux.
"""

import platform
import re
from pathlib import Path
from typing import Set, List, Optional


# ==================== Excluded Paths ====================

# macOS system directories
EXCLUDED_PATHS_MACOS = {
    '/Applications',
    '/System',
    '/Library',
    '/private',
    '/usr',
    '/bin',
    '/sbin',
    '/opt',
    '/cores',
    '/var',
    '.Trash',
    '.Spotlight-V100',
    '.fseventsd',
    '.DocumentRevisions-V100',
    '.TemporaryItems',
}

# Windows system directories
EXCLUDED_PATHS_WINDOWS = {
    'Windows',
    'Program Files',
    'Program Files (x86)',
    'ProgramData',
    '$Recycle.Bin',
    'System Volume Information',
    'Recovery',
    'MSOCache',
    'Config.Msi',
    '$WINDOWS.~BT',
    '$WINDOWS.~WS',
}

# Linux system directories
EXCLUDED_PATHS_LINUX = {
    '/bin',
    '/boot',
    '/dev',
    '/etc',
    '/lib',
    '/lib64',
    '/proc',
    '/root',
    '/run',
    '/sbin',
    '/srv',
    '/sys',
    '/tmp',
    '/usr',
    '/var',
    'lost+found',
}

# Cross-platform excluded directories (relative names)
EXCLUDED_DIRS_CROSSPLATFORM = {
    # Version control
    '.git',
    '.svn',
    '.hg',
    '.bzr',

    # Package managers / dependencies
    'node_modules',
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    '.nox',
    '.eggs',
    '*.egg-info',
    'bower_components',
    'vendor',

    # Virtual environments
    'venv',
    '.venv',
    'env',
    '.env',
    'virtualenv',

    # Build directories
    'build',
    'dist',
    'target',
    'out',
    'bin',
    'obj',

    # IDE / Editor
    '.idea',
    '.vscode',
    '.vs',
    '*.xcodeproj',
    '*.xcworkspace',

    # Cache directories
    '.cache',
    'cache',
    '.npm',
    '.yarn',
    '.gradle',
    '.m2',

    # Temporary
    'tmp',
    'temp',
}

# User-level excluded paths (relative to home)
EXCLUDED_USER_PATHS = {
    'Library',  # macOS user library
    'AppData',  # Windows user app data
    '.local',   # Linux user local
    '.config',  # Linux/macOS config
}


# ==================== Excluded Extensions ====================

# System and application files
EXCLUDED_EXTENSIONS = {
    # Executables
    'exe', 'msi', 'dll', 'sys', 'drv', 'ocx', 'cpl', 'scr',
    'app', 'pkg', 'dmg', 'framework', 'bundle', 'kext', 'dylib',
    'so', 'a', 'o', 'ko',
    'deb', 'rpm', 'snap', 'flatpak', 'appimage',

    # Compiled / bytecode
    'pyc', 'pyo', 'pyd',
    'class', 'jar', 'war', 'ear',
    'beam',

    # Database files
    'db', 'sqlite', 'sqlite3', 'db-shm', 'db-wal',
    'mdb', 'accdb', 'frm', 'myd', 'myi',

    # Logs
    'log',

    # Lock files
    'lock', 'lck',

    # Windows specific
    'lnk', 'url', 'ini', 'inf', 'reg',

    # Temporary
    'tmp', 'temp', 'bak', 'swp', 'swo',

    # Development
    'map', 'min.js', 'min.css',
}


# ==================== Excluded Filename Patterns ====================

EXCLUDED_FILENAME_PATTERNS = [
    r'^\.',                  # Hidden files (Unix)
    r'^~\$',                 # Office temp files
    r'\.tmp$',               # Temp files
    r'\.temp$',              # Temp files
    r'\.cache$',             # Cache files
    r'\.bak$',               # Backup files
    r'\.swp$',               # Vim swap
    r'\.swo$',               # Vim swap
    r'^Thumbs\.db$',         # Windows thumbnails
    r'^desktop\.ini$',       # Windows desktop config
    r'^\.DS_Store$',         # macOS metadata
    r'^\.localized$',        # macOS localization
    r'^\.Trashes$',          # macOS trash
    r'^\.AppleDouble$',      # macOS resource fork
    r'^\.AppleDB$',          # macOS database
    r'^\.AppleDesktop$',     # macOS desktop
    r'^Icon\r$',             # macOS custom icon
    r'^\._',                 # macOS resource fork
    r'^\.fuse_hidden',       # FUSE hidden files
    r'^\.nfs',               # NFS temp files
    r'^\.Spotlight-V100$',   # Spotlight index
    r'^\.fseventsd$',        # FSEvents
    r'^\.com\.apple\.',      # macOS system
    r'^~.*\.tmp$',           # Office temp
]


# ==================== Minimum File Sizes ====================

# Minimum sizes by file type (in bytes)
MIN_FILE_SIZES = {
    'image': 1024,       # 1 KB - smaller images are usually thumbnails/icons
    'video': 10240,      # 10 KB - smaller videos are usually previews
    'document': 100,     # 100 bytes - even small docs can be meaningful
    'audio': 1024,       # 1 KB - smaller audio files are usually system sounds
    'other': 100,        # 100 bytes
}


class FileFilter:
    """Filter for determining which files to include in scanning."""

    def __init__(self):
        self._system = platform.system()
        self._excluded_patterns = [re.compile(p, re.IGNORECASE) for p in EXCLUDED_FILENAME_PATTERNS]
        self._excluded_extensions = EXCLUDED_EXTENSIONS
        self._excluded_dirs = self._build_excluded_dirs()

    def _build_excluded_dirs(self) -> Set[str]:
        """Build the complete set of excluded directory names."""
        excluded = set(EXCLUDED_DIRS_CROSSPLATFORM)

        if self._system == "Darwin":
            excluded.update(EXCLUDED_PATHS_MACOS)
        elif self._system == "Windows":
            excluded.update(EXCLUDED_PATHS_WINDOWS)
        elif self._system == "Linux":
            excluded.update(EXCLUDED_PATHS_LINUX)

        excluded.update(EXCLUDED_USER_PATHS)
        return excluded

    def should_include_file(
        self,
        file_path: Path,
        file_type: Optional[str] = None,
        check_size: bool = True
    ) -> bool:
        """Determine if a file should be included in scanning.

        Args:
            file_path: Path to the file
            file_type: Optional file type for size checking
            check_size: Whether to check minimum file size

        Returns:
            True if file should be included, False otherwise
        """
        # Check if inside excluded directory
        if self._is_in_excluded_directory(file_path):
            return False

        # Check filename patterns
        if self._matches_excluded_pattern(file_path.name):
            return False

        # Check extension
        ext = file_path.suffix.lower().lstrip('.')
        if ext in self._excluded_extensions:
            return False

        # Check if inside app bundle (macOS)
        if self._system == "Darwin" and self._is_inside_app_bundle(file_path):
            return False

        # Check minimum file size
        if check_size and file_type:
            try:
                file_size = file_path.stat().st_size
                min_size = MIN_FILE_SIZES.get(file_type, MIN_FILE_SIZES['other'])
                if file_size < min_size:
                    return False
            except OSError:
                pass

        return True

    def should_include_directory(self, dir_path: Path) -> bool:
        """Determine if a directory should be traversed.

        Args:
            dir_path: Path to the directory

        Returns:
            True if directory should be traversed, False otherwise
        """
        dir_name = dir_path.name

        # Check if directory name is excluded
        if dir_name in self._excluded_dirs:
            return False

        # Check if it's a hidden directory
        if dir_name.startswith('.') and dir_name not in ('.', '..'):
            return False

        # Check absolute path exclusions
        path_str = str(dir_path)
        for excluded in self._excluded_dirs:
            if excluded.startswith('/') and path_str.startswith(excluded):
                return False

        # Check if inside app bundle (macOS)
        if self._system == "Darwin" and self._is_inside_app_bundle(dir_path):
            return False

        return True

    def _is_in_excluded_directory(self, file_path: Path) -> bool:
        """Check if file is inside an excluded directory."""
        parts = file_path.parts

        for part in parts:
            # Check exact match
            if part in self._excluded_dirs:
                return True

            # Check hidden directories (except root)
            if part.startswith('.') and part not in ('.', '..'):
                # Allow some hidden directories that might contain user files
                if part not in ('.wine', '.steam'):
                    return True

        return False

    def _matches_excluded_pattern(self, filename: str) -> bool:
        """Check if filename matches any excluded pattern."""
        for pattern in self._excluded_patterns:
            if pattern.search(filename):
                return True
        return False

    def _is_inside_app_bundle(self, path: Path) -> bool:
        """Check if path is inside a .app bundle (macOS)."""
        for parent in path.parents:
            if parent.suffix == '.app':
                return True
        return False

    def _is_hidden_windows(self, path: Path) -> bool:
        """Check if file has hidden attribute on Windows."""
        if self._system != "Windows":
            return False

        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return False
            # FILE_ATTRIBUTE_HIDDEN = 0x2
            return bool(attrs & 0x2)
        except Exception:
            return False

    def get_excluded_extensions(self) -> Set[str]:
        """Get the set of excluded extensions."""
        return self._excluded_extensions.copy()

    def get_excluded_directories(self) -> Set[str]:
        """Get the set of excluded directory names."""
        return self._excluded_dirs.copy()


# Convenience function for quick checks
def should_include_file(file_path: Path, file_type: Optional[str] = None) -> bool:
    """Quick check if a file should be included."""
    return FileFilter().should_include_file(file_path, file_type)


def should_include_directory(dir_path: Path) -> bool:
    """Quick check if a directory should be traversed."""
    return FileFilter().should_include_directory(dir_path)
