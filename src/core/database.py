"""SQLite database manager for persistent hash storage."""

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


# Database schema version for migrations
SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Volumes/Drives table
CREATE TABLE IF NOT EXISTS volumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    mount_point TEXT,
    is_internal INTEGER DEFAULT 0,
    total_size_bytes INTEGER,
    filesystem TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_scan_at TEXT,
    scan_status TEXT DEFAULT 'never',
    file_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_volumes_uuid ON volumes(uuid);

-- Files table
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    file_size_bytes INTEGER NOT NULL,
    file_type TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    duration_seconds REAL,
    file_created_at TEXT,
    file_modified_at TEXT,
    indexed_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (volume_id) REFERENCES volumes(id) ON DELETE CASCADE,
    UNIQUE(volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_files_volume ON files(volume_id);
CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(file_size_bytes);
CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(is_deleted);

-- Hashes table (multiple hash types per file)
CREATE TABLE IF NOT EXISTS hashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    hash_type TEXT NOT NULL,
    hash_value TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    UNIQUE(file_id, hash_type)
);
CREATE INDEX IF NOT EXISTS idx_hashes_type_value ON hashes(hash_type, hash_value);
CREATE INDEX IF NOT EXISTS idx_hashes_file ON hashes(file_id);

-- Duplicate groups table
CREATE TABLE IF NOT EXISTS duplicate_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    hash_type TEXT NOT NULL,
    threshold INTEGER,
    file_count INTEGER NOT NULL,
    status TEXT DEFAULT 'pending'
);

-- Duplicate group members
CREATE TABLE IF NOT EXISTS duplicate_group_files (
    group_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    is_suggested_keep INTEGER DEFAULT 0,
    similarity_score REAL,
    FOREIGN KEY (group_id) REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, file_id)
);

-- Scan sessions for tracking history
CREATE TABLE IF NOT EXISTS scan_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER,
    scan_path TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    files_scanned INTEGER DEFAULT 0,
    files_added INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    files_removed INTEGER DEFAULT 0,
    files_total INTEGER DEFAULT 0,
    last_processed_path TEXT,
    status TEXT DEFAULT 'running',
    error_message TEXT,
    FOREIGN KEY (volume_id) REFERENCES volumes(id)
);

-- Scan checkpoints for pause/resume functionality
CREATE TABLE IF NOT EXISTS scan_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    checkpoint_at TEXT NOT NULL,
    current_directory TEXT,
    files_processed INTEGER DEFAULT 0,
    files_total INTEGER DEFAULT 0,
    directories_completed TEXT,
    FOREIGN KEY (session_id) REFERENCES scan_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON scan_checkpoints(session_id);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- Custom file type extensions (user preferences)
CREATE TABLE IF NOT EXISTS custom_extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extension TEXT NOT NULL UNIQUE,
    action TEXT NOT NULL,  -- 'include' or 'exclude'
    added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_custom_extensions_action ON custom_extensions(action);

-- Unknown file extensions encountered during scanning
CREATE TABLE IF NOT EXISTS unknown_extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extension TEXT NOT NULL UNIQUE,
    occurrence_count INTEGER DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

-- Sample paths for unknown/excluded extensions (to show where they were found)
CREATE TABLE IF NOT EXISTS extension_sample_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    extension TEXT NOT NULL,
    volume_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,  -- Directory path relative to volume mount point
    file_count INTEGER DEFAULT 1,
    FOREIGN KEY (volume_id) REFERENCES volumes(id) ON DELETE CASCADE,
    UNIQUE(extension, volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_extension_sample_paths_ext ON extension_sample_paths(extension);

-- Excluded paths per volume (directories to skip during scanning)
CREATE TABLE IF NOT EXISTS excluded_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,  -- Path relative to volume mount point
    added_at TEXT NOT NULL,
    FOREIGN KEY (volume_id) REFERENCES volumes(id) ON DELETE CASCADE,
    UNIQUE(volume_id, relative_path)
);
CREATE INDEX IF NOT EXISTS idx_excluded_paths_volume ON excluded_paths(volume_id);
"""


def get_db_path() -> Path:
    """Get the database file path."""
    db_dir = Path.home() / ".dedupe"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "dedupe.db"


class DatabaseManager:
    """Thread-safe SQLite database manager for hash storage."""

    _instance: Optional['DatabaseManager'] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database manager.

        Args:
            db_path: Path to database file. Defaults to ~/.dedupe/dedupe.db
        """
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    @classmethod
    def get_instance(cls, db_path: Optional[Path] = None) -> 'DatabaseManager':
        """Get singleton instance of database manager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.conn.execute("PRAGMA foreign_keys = ON")
        return self._local.conn

    @contextmanager
    def connection(self):
        """Context manager for database connections with auto-commit."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def cursor(self):
        """Context manager for database cursor."""
        with self.connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

            # Check/set schema version
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)",
                           (SCHEMA_VERSION,))

    # ==================== Volume Operations ====================

    def add_volume(
        self,
        uuid: str,
        name: str,
        mount_point: str,
        is_internal: bool = False,
        total_size_bytes: int = 0,
        filesystem: str = ""
    ) -> int:
        """Add or update a volume in the database.

        Returns the volume ID.
        """
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            # Try to update existing
            cursor.execute("""
                UPDATE volumes
                SET name = ?, mount_point = ?, is_internal = ?,
                    total_size_bytes = ?, filesystem = ?, last_seen_at = ?
                WHERE uuid = ?
            """, (name, mount_point, int(is_internal), total_size_bytes,
                  filesystem, now, uuid))

            if cursor.rowcount == 0:
                # Insert new
                cursor.execute("""
                    INSERT INTO volumes
                    (uuid, name, mount_point, is_internal, total_size_bytes,
                     filesystem, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (uuid, name, mount_point, int(is_internal), total_size_bytes,
                      filesystem, now, now))
                return cursor.lastrowid
            else:
                cursor.execute("SELECT id FROM volumes WHERE uuid = ?", (uuid,))
                return cursor.fetchone()[0]

    def get_volume_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get a volume by its UUID."""
        with self.cursor() as cursor:
            cursor.execute("SELECT * FROM volumes WHERE uuid = ?", (uuid,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_volume_by_id(self, volume_id: int) -> Optional[Dict[str, Any]]:
        """Get a volume by its ID."""
        with self.cursor() as cursor:
            cursor.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_volumes(self) -> List[Dict[str, Any]]:
        """Get all known volumes."""
        with self.cursor() as cursor:
            cursor.execute("SELECT * FROM volumes ORDER BY last_seen_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def update_volume_scan_status(
        self,
        volume_id: int,
        status: str,
        file_count: Optional[int] = None
    ):
        """Update volume scan status."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            if file_count is not None:
                cursor.execute("""
                    UPDATE volumes
                    SET scan_status = ?, last_scan_at = ?, file_count = ?
                    WHERE id = ?
                """, (status, now, file_count, volume_id))
            else:
                cursor.execute("""
                    UPDATE volumes
                    SET scan_status = ?, last_scan_at = ?
                    WHERE id = ?
                """, (status, now, volume_id))

    def delete_volume(self, volume_id: int):
        """Delete a volume and all its files."""
        with self.cursor() as cursor:
            cursor.execute("DELETE FROM volumes WHERE id = ?", (volume_id,))

    # ==================== File Operations ====================

    def add_file(
        self,
        volume_id: int,
        relative_path: str,
        filename: str,
        extension: str,
        file_size_bytes: int,
        file_type: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration_seconds: Optional[float] = None,
        file_created_at: Optional[str] = None,
        file_modified_at: Optional[str] = None
    ) -> int:
        """Add or update a file in the database.

        Returns the file ID.
        """
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            # Try to update existing
            cursor.execute("""
                UPDATE files
                SET filename = ?, extension = ?, file_size_bytes = ?,
                    file_type = ?, width = ?, height = ?, duration_seconds = ?,
                    file_created_at = ?, file_modified_at = ?, indexed_at = ?,
                    is_deleted = 0
                WHERE volume_id = ? AND relative_path = ?
            """, (filename, extension, file_size_bytes, file_type, width, height,
                  duration_seconds, file_created_at, file_modified_at, now,
                  volume_id, relative_path))

            if cursor.rowcount == 0:
                # Insert new
                cursor.execute("""
                    INSERT INTO files
                    (volume_id, relative_path, filename, extension, file_size_bytes,
                     file_type, width, height, duration_seconds, file_created_at,
                     file_modified_at, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (volume_id, relative_path, filename, extension, file_size_bytes,
                      file_type, width, height, duration_seconds, file_created_at,
                      file_modified_at, now))
                return cursor.lastrowid
            else:
                cursor.execute("""
                    SELECT id FROM files
                    WHERE volume_id = ? AND relative_path = ?
                """, (volume_id, relative_path))
                return cursor.fetchone()[0]

    def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get a file by its ID."""
        with self.cursor() as cursor:
            cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_file_by_path(
        self,
        volume_id: int,
        relative_path: str
    ) -> Optional[Dict[str, Any]]:
        """Get a file by volume and path."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM files
                WHERE volume_id = ? AND relative_path = ? AND is_deleted = 0
            """, (volume_id, relative_path))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_files_by_volume(
        self,
        volume_id: int,
        file_type: Optional[str] = None,
        include_deleted: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all files for a volume."""
        with self.cursor() as cursor:
            query = "SELECT * FROM files WHERE volume_id = ?"
            params = [volume_id]

            if not include_deleted:
                query += " AND is_deleted = 0"

            if file_type:
                query += " AND file_type = ?"
                params.append(file_type)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def mark_file_deleted(self, file_id: int):
        """Mark a file as deleted (soft delete)."""
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE files SET is_deleted = 1 WHERE id = ?",
                (file_id,)
            )

    def mark_files_deleted_by_volume(self, volume_id: int):
        """Mark all files on a volume as deleted."""
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE files SET is_deleted = 1 WHERE volume_id = ?",
                (volume_id,)
            )

    def delete_file(self, file_id: int):
        """Permanently delete a file record."""
        with self.cursor() as cursor:
            cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))

    def get_file_count_by_volume(self, volume_id: int) -> int:
        """Get count of files for a volume."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM files
                WHERE volume_id = ? AND is_deleted = 0
            """, (volume_id,))
            return cursor.fetchone()[0]

    # ==================== Hash Operations ====================

    def add_hash(
        self,
        file_id: int,
        hash_type: str,
        hash_value: str
    ):
        """Add or update a hash for a file."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            cursor.execute("""
                INSERT OR REPLACE INTO hashes (file_id, hash_type, hash_value, computed_at)
                VALUES (?, ?, ?, ?)
            """, (file_id, hash_type, hash_value, now))

    def get_hash(self, file_id: int, hash_type: str) -> Optional[str]:
        """Get a specific hash for a file."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT hash_value FROM hashes
                WHERE file_id = ? AND hash_type = ?
            """, (file_id, hash_type))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_all_hashes_for_file(self, file_id: int) -> Dict[str, str]:
        """Get all hashes for a file."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT hash_type, hash_value FROM hashes WHERE file_id = ?",
                (file_id,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def find_files_by_hash(
        self,
        hash_type: str,
        hash_value: str
    ) -> List[Dict[str, Any]]:
        """Find all files with a specific hash value."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT f.* FROM files f
                JOIN hashes h ON f.id = h.file_id
                WHERE h.hash_type = ? AND h.hash_value = ? AND f.is_deleted = 0
            """, (hash_type, hash_value))
            return [dict(row) for row in cursor.fetchall()]

    def find_duplicate_hashes(
        self,
        hash_type: str,
        volume_ids: Optional[List[int]] = None
    ) -> List[Tuple[str, int]]:
        """Find hash values that appear more than once.

        Returns list of (hash_value, count) tuples.
        """
        with self.cursor() as cursor:
            if volume_ids:
                placeholders = ",".join("?" * len(volume_ids))
                cursor.execute(f"""
                    SELECT h.hash_value, COUNT(*) as cnt
                    FROM hashes h
                    JOIN files f ON h.file_id = f.id
                    WHERE h.hash_type = ?
                      AND f.is_deleted = 0
                      AND f.volume_id IN ({placeholders})
                    GROUP BY h.hash_value
                    HAVING cnt > 1
                    ORDER BY cnt DESC
                """, [hash_type] + volume_ids)
            else:
                cursor.execute("""
                    SELECT h.hash_value, COUNT(*) as cnt
                    FROM hashes h
                    JOIN files f ON h.file_id = f.id
                    WHERE h.hash_type = ? AND f.is_deleted = 0
                    GROUP BY h.hash_value
                    HAVING cnt > 1
                    ORDER BY cnt DESC
                """, (hash_type,))

            return [(row[0], row[1]) for row in cursor.fetchall()]

    # ==================== Scan Session Operations ====================

    def start_scan_session(
        self,
        volume_id: int,
        scan_path: Optional[str] = None
    ) -> int:
        """Start a new scan session. Returns session ID."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            cursor.execute("""
                INSERT INTO scan_sessions (volume_id, scan_path, started_at, status)
                VALUES (?, ?, ?, 'running')
            """, (volume_id, scan_path, now))
            return cursor.lastrowid

    def update_scan_session(
        self,
        session_id: int,
        files_scanned: Optional[int] = None,
        files_added: Optional[int] = None,
        files_updated: Optional[int] = None,
        files_removed: Optional[int] = None
    ):
        """Update scan session progress."""
        updates = []
        params = []

        if files_scanned is not None:
            updates.append("files_scanned = ?")
            params.append(files_scanned)
        if files_added is not None:
            updates.append("files_added = ?")
            params.append(files_added)
        if files_updated is not None:
            updates.append("files_updated = ?")
            params.append(files_updated)
        if files_removed is not None:
            updates.append("files_removed = ?")
            params.append(files_removed)

        if updates:
            params.append(session_id)
            with self.cursor() as cursor:
                cursor.execute(
                    f"UPDATE scan_sessions SET {', '.join(updates)} WHERE id = ?",
                    params
                )

    def complete_scan_session(
        self,
        session_id: int,
        status: str = 'completed',
        error_message: Optional[str] = None
    ):
        """Mark a scan session as complete."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            cursor.execute("""
                UPDATE scan_sessions
                SET completed_at = ?, status = ?, error_message = ?
                WHERE id = ?
            """, (now, status, error_message, session_id))

    def get_scan_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Get a scan session by ID."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM scan_sessions WHERE id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== Duplicate Group Operations ====================

    def create_duplicate_group(
        self,
        hash_type: str,
        file_ids: List[int],
        threshold: Optional[int] = None,
        suggested_keep_id: Optional[int] = None,
        similarity_scores: Optional[Dict[int, float]] = None
    ) -> int:
        """Create a new duplicate group. Returns group ID."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            cursor.execute("""
                INSERT INTO duplicate_groups (created_at, hash_type, threshold, file_count)
                VALUES (?, ?, ?, ?)
            """, (now, hash_type, threshold, len(file_ids)))

            group_id = cursor.lastrowid

            # Add members
            for file_id in file_ids:
                is_keep = 1 if file_id == suggested_keep_id else 0
                score = similarity_scores.get(file_id) if similarity_scores else None
                cursor.execute("""
                    INSERT INTO duplicate_group_files
                    (group_id, file_id, is_suggested_keep, similarity_score)
                    VALUES (?, ?, ?, ?)
                """, (group_id, file_id, is_keep, score))

            return group_id

    def get_duplicate_groups(
        self,
        status: Optional[str] = None,
        hash_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get duplicate groups with optional filtering."""
        with self.cursor() as cursor:
            query = "SELECT * FROM duplicate_groups WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if hash_type:
                query += " AND hash_type = ?"
                params.append(hash_type)

            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_duplicate_group_files(
        self,
        group_id: int
    ) -> List[Dict[str, Any]]:
        """Get all files in a duplicate group."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT f.*, dgf.is_suggested_keep, dgf.similarity_score
                FROM files f
                JOIN duplicate_group_files dgf ON f.id = dgf.file_id
                WHERE dgf.group_id = ?
                ORDER BY dgf.is_suggested_keep DESC, f.file_size_bytes DESC
            """, (group_id,))
            return [dict(row) for row in cursor.fetchall()]

    def update_duplicate_group_status(self, group_id: int, status: str):
        """Update the status of a duplicate group."""
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE duplicate_groups SET status = ? WHERE id = ?",
                (status, group_id)
            )

    def delete_duplicate_group(self, group_id: int):
        """Delete a duplicate group."""
        with self.cursor() as cursor:
            cursor.execute(
                "DELETE FROM duplicate_groups WHERE id = ?",
                (group_id,)
            )

    def clear_duplicate_groups(self):
        """Clear all duplicate groups."""
        with self.cursor() as cursor:
            cursor.execute("DELETE FROM duplicate_groups")

    # ==================== Scan Checkpoint Operations ====================

    def save_scan_checkpoint(
        self,
        session_id: int,
        current_directory: str,
        files_processed: int,
        files_total: int,
        directories_completed: List[str]
    ):
        """Save a checkpoint for resuming a paused scan."""
        import json
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            # Delete old checkpoints for this session
            cursor.execute(
                "DELETE FROM scan_checkpoints WHERE session_id = ?",
                (session_id,)
            )

            # Insert new checkpoint
            cursor.execute("""
                INSERT INTO scan_checkpoints
                (session_id, checkpoint_at, current_directory, files_processed,
                 files_total, directories_completed)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, now, current_directory, files_processed,
                  files_total, json.dumps(directories_completed)))

            # Update session with checkpoint info
            cursor.execute("""
                UPDATE scan_sessions
                SET files_scanned = ?, files_total = ?, last_processed_path = ?
                WHERE id = ?
            """, (files_processed, files_total, current_directory, session_id))

    def get_scan_checkpoint(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Get the latest checkpoint for a scan session."""
        import json

        with self.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM scan_checkpoints
                WHERE session_id = ?
                ORDER BY checkpoint_at DESC
                LIMIT 1
            """, (session_id,))

            row = cursor.fetchone()
            if row:
                result = dict(row)
                # Parse directories_completed JSON
                if result.get('directories_completed'):
                    result['directories_completed'] = json.loads(
                        result['directories_completed']
                    )
                else:
                    result['directories_completed'] = []
                return result
            return None

    def delete_scan_checkpoint(self, session_id: int):
        """Delete checkpoint for a session."""
        with self.cursor() as cursor:
            cursor.execute(
                "DELETE FROM scan_checkpoints WHERE session_id = ?",
                (session_id,)
            )

    def get_paused_scan_sessions(
        self,
        volume_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all paused scan sessions, optionally filtered by volume."""
        with self.cursor() as cursor:
            if volume_id:
                cursor.execute("""
                    SELECT ss.*, sc.current_directory, sc.files_processed,
                           sc.files_total, sc.directories_completed
                    FROM scan_sessions ss
                    LEFT JOIN scan_checkpoints sc ON ss.id = sc.session_id
                    WHERE ss.status = 'paused' AND ss.volume_id = ?
                    ORDER BY ss.started_at DESC
                """, (volume_id,))
            else:
                cursor.execute("""
                    SELECT ss.*, sc.current_directory, sc.files_processed,
                           sc.files_total, sc.directories_completed
                    FROM scan_sessions ss
                    LEFT JOIN scan_checkpoints sc ON ss.id = sc.session_id
                    WHERE ss.status = 'paused'
                    ORDER BY ss.started_at DESC
                """)

            results = []
            for row in cursor.fetchall():
                result = dict(row)
                # Parse directories_completed JSON if present
                if result.get('directories_completed'):
                    import json
                    result['directories_completed'] = json.loads(
                        result['directories_completed']
                    )
                else:
                    result['directories_completed'] = []
                results.append(result)

            return results

    def pause_scan_session(self, session_id: int):
        """Mark a scan session as paused."""
        with self.cursor() as cursor:
            cursor.execute(
                "UPDATE scan_sessions SET status = 'paused' WHERE id = ?",
                (session_id,)
            )

    def get_interrupted_scans(self) -> List[Dict[str, Any]]:
        """Get scans that were interrupted (running status but app closed)."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT ss.*, v.uuid as volume_uuid, v.name as volume_name,
                       v.mount_point
                FROM scan_sessions ss
                JOIN volumes v ON ss.volume_id = v.id
                WHERE ss.status IN ('running', 'paused')
                ORDER BY ss.started_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    # ==================== Custom Extension Operations ====================

    def get_custom_included_extensions(self) -> List[str]:
        """Get list of custom included extensions."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT extension FROM custom_extensions WHERE action = 'include'"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_custom_excluded_extensions(self) -> List[str]:
        """Get list of custom excluded extensions."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT extension FROM custom_extensions WHERE action = 'exclude'"
            )
            return [row[0] for row in cursor.fetchall()]

    def set_custom_included_extensions(self, extensions: List[str]):
        """Set the custom included extensions (replaces existing)."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            # Remove existing includes
            cursor.execute("DELETE FROM custom_extensions WHERE action = 'include'")

            # Insert new includes
            for ext in extensions:
                cursor.execute("""
                    INSERT OR REPLACE INTO custom_extensions (extension, action, added_at)
                    VALUES (?, 'include', ?)
                """, (ext.lower(), now))

    def set_custom_excluded_extensions(self, extensions: List[str]):
        """Set the custom excluded extensions (replaces existing)."""
        now = datetime.now().isoformat()

        with self.cursor() as cursor:
            # Remove existing excludes
            cursor.execute("DELETE FROM custom_extensions WHERE action = 'exclude'")

            # Insert new excludes
            for ext in extensions:
                cursor.execute("""
                    INSERT OR REPLACE INTO custom_extensions (extension, action, added_at)
                    VALUES (?, 'exclude', ?)
                """, (ext.lower(), now))

    def clear_custom_extensions(self):
        """Clear all custom extension settings."""
        with self.cursor() as cursor:
            cursor.execute("DELETE FROM custom_extensions")

    # ==================== Unknown Extension Operations ====================

    def add_unknown_extension(self, extension: str):
        """Add or increment count for an unknown extension."""
        now = datetime.now().isoformat()
        ext = extension.lower()

        with self.cursor() as cursor:
            # Try to update existing
            cursor.execute("""
                UPDATE unknown_extensions
                SET occurrence_count = occurrence_count + 1, last_seen_at = ?
                WHERE extension = ?
            """, (now, ext))

            if cursor.rowcount == 0:
                # Insert new
                cursor.execute("""
                    INSERT INTO unknown_extensions
                    (extension, occurrence_count, first_seen_at, last_seen_at)
                    VALUES (?, 1, ?, ?)
                """, (ext, now, now))

    def get_unknown_extensions(self) -> Dict[str, int]:
        """Get all unknown extensions with their occurrence counts."""
        with self.cursor() as cursor:
            cursor.execute(
                "SELECT extension, occurrence_count FROM unknown_extensions"
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def update_unknown_extensions(self, remaining: set):
        """Update unknown extensions table to only keep specified extensions."""
        with self.cursor() as cursor:
            if not remaining:
                cursor.execute("DELETE FROM unknown_extensions")
            else:
                # Delete extensions not in the remaining set
                placeholders = ",".join("?" * len(remaining))
                cursor.execute(f"""
                    DELETE FROM unknown_extensions
                    WHERE extension NOT IN ({placeholders})
                """, list(remaining))

    def clear_unknown_extensions(self):
        """Clear all unknown extensions."""
        with self.cursor() as cursor:
            cursor.execute("DELETE FROM unknown_extensions")

    def add_extension_sample_path(
        self,
        extension: str,
        volume_id: int,
        relative_path: str
    ):
        """Add or update a sample path for an extension.

        Used to track where unknown/excluded extensions were found during scanning.
        """
        ext = extension.lower().lstrip('.')
        # Normalize path: get directory portion only
        dir_path = str(Path(relative_path).parent) if '/' in relative_path else ''

        with self.cursor() as cursor:
            cursor.execute("""
                INSERT INTO extension_sample_paths (extension, volume_id, relative_path, file_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(extension, volume_id, relative_path)
                DO UPDATE SET file_count = file_count + 1
            """, (ext, volume_id, dir_path))

    def get_extension_sample_paths(self, extension: str) -> List[Dict[str, Any]]:
        """Get sample paths where an extension was found.

        Returns list of dicts with 'directory', 'volume_id', 'volume_name',
        'mount_point', and 'file_count' keys.
        """
        ext = extension.lower().lstrip('.')

        with self.cursor() as cursor:
            cursor.execute("""
                SELECT
                    esp.relative_path as directory,
                    esp.volume_id,
                    v.name as volume_name,
                    v.mount_point,
                    esp.file_count
                FROM extension_sample_paths esp
                JOIN volumes v ON esp.volume_id = v.id
                WHERE esp.extension = ?
                ORDER BY esp.file_count DESC, esp.relative_path ASC
            """, (ext,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'directory': row[0] or '/',
                    'volume_id': row[1],
                    'volume_name': row[2],
                    'mount_point': row[3],
                    'file_count': row[4]
                })
            return results

    def clear_extension_sample_paths(self, volume_id: Optional[int] = None):
        """Clear sample paths, optionally for a specific volume."""
        with self.cursor() as cursor:
            if volume_id:
                cursor.execute(
                    "DELETE FROM extension_sample_paths WHERE volume_id = ?",
                    (volume_id,)
                )
            else:
                cursor.execute("DELETE FROM extension_sample_paths")

    def get_extension_counts(self) -> Dict[str, int]:
        """Get counts of files by extension from the files table."""
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT extension, COUNT(*) as cnt
                FROM files
                WHERE is_deleted = 0 AND extension IS NOT NULL AND extension != ''
                GROUP BY extension
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_directories_by_extension(self, extension: str) -> List[Dict[str, Any]]:
        """Get all directories containing files with a specific extension.

        Returns list of dicts with 'directory', 'volume_id', 'volume_name',
        'mount_point', and 'file_count' keys.
        """
        ext = extension.lower().lstrip('.')

        with self.cursor() as cursor:
            cursor.execute("""
                SELECT
                    CASE
                        WHEN INSTR(f.relative_path, '/') > 0
                        THEN SUBSTR(f.relative_path, 1, LENGTH(f.relative_path) - LENGTH(f.filename) - 1)
                        ELSE ''
                    END as directory,
                    f.volume_id,
                    v.name as volume_name,
                    v.mount_point,
                    COUNT(*) as file_count
                FROM files f
                JOIN volumes v ON f.volume_id = v.id
                WHERE f.extension = ? AND f.is_deleted = 0
                GROUP BY directory, f.volume_id
                ORDER BY file_count DESC, directory ASC
            """, (ext,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'directory': row[0] or '/',
                    'volume_id': row[1],
                    'volume_name': row[2],
                    'mount_point': row[3],
                    'file_count': row[4]
                })
            return results

    # ==================== Excluded Paths Operations ====================

    def add_excluded_path(self, volume_id: int, relative_path: str) -> bool:
        """Add an excluded path for a volume.

        Args:
            volume_id: The volume ID
            relative_path: Path relative to volume mount point (e.g., 'Users/foo/bar')

        Returns:
            True if added, False if already exists
        """
        now = datetime.now().isoformat()
        # Normalize path: remove leading/trailing slashes
        normalized = relative_path.strip('/')

        with self.cursor() as cursor:
            try:
                cursor.execute("""
                    INSERT INTO excluded_paths (volume_id, relative_path, added_at)
                    VALUES (?, ?, ?)
                """, (volume_id, normalized, now))
                return True
            except sqlite3.IntegrityError:
                # Already exists
                return False

    def remove_excluded_path(self, volume_id: int, relative_path: str) -> bool:
        """Remove an excluded path for a volume.

        Returns:
            True if removed, False if not found
        """
        normalized = relative_path.strip('/')

        with self.cursor() as cursor:
            cursor.execute("""
                DELETE FROM excluded_paths
                WHERE volume_id = ? AND relative_path = ?
            """, (volume_id, normalized))
            return cursor.rowcount > 0

    def get_excluded_paths(self, volume_id: int) -> List[str]:
        """Get all excluded paths for a volume.

        Returns:
            List of relative paths (e.g., ['Users/foo/bar', 'Library/Caches'])
        """
        with self.cursor() as cursor:
            cursor.execute("""
                SELECT relative_path FROM excluded_paths
                WHERE volume_id = ?
                ORDER BY relative_path
            """, (volume_id,))
            return [row[0] for row in cursor.fetchall()]

    def clear_excluded_paths(self, volume_id: int):
        """Clear all excluded paths for a volume."""
        with self.cursor() as cursor:
            cursor.execute(
                "DELETE FROM excluded_paths WHERE volume_id = ?",
                (volume_id,)
            )
