"""Session management for saving and restoring duplicate detection state."""

import json
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..models.image_file import ImageFile
from ..models.duplicate_group import DuplicateGroup


def get_sessions_dir() -> Path:
    """Get the directory for storing sessions."""
    sessions_dir = Path.home() / ".dedupe" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def generate_session_id(root_directory: Path) -> str:
    """Generate a unique session ID based on the root directory path."""
    path_hash = hashlib.md5(str(root_directory).encode()).hexdigest()[:12]
    return path_hash


@dataclass
class SessionInfo:
    """Metadata about a saved session."""
    session_id: str
    root_directory: str
    created_at: str
    updated_at: str
    total_groups: int
    total_duplicates: int
    potential_savings: int
    scan_mode: str
    detection_mode: str
    hash_algorithm: str
    perceptual_threshold: int

    @property
    def root_directory_path(self) -> Path:
        return Path(self.root_directory)

    @property
    def created_datetime(self) -> datetime:
        return datetime.fromisoformat(self.created_at)

    @property
    def updated_datetime(self) -> datetime:
        return datetime.fromisoformat(self.updated_at)

    @property
    def potential_savings_str(self) -> str:
        """Get human-readable potential savings."""
        size = self.potential_savings
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def root_directory_name(self) -> str:
        """Get just the folder name from the root directory."""
        return Path(self.root_directory).name

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionInfo':
        return cls(**data)


class SessionManager:
    """Manages saving and loading of duplicate detection sessions."""

    def __init__(self):
        self.sessions_dir = get_sessions_dir()

    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self.sessions_dir / f"{session_id}.json"

    def _get_info_path(self, session_id: str) -> Path:
        """Get the file path for session info."""
        return self.sessions_dir / f"{session_id}_info.json"

    def _serialize_image_file(self, img: ImageFile) -> Dict[str, Any]:
        """Serialize an ImageFile to a dictionary."""
        return {
            "path": str(img.path),
            "file_size": img.file_size,
            "width": img.width,
            "height": img.height,
            "hash_value": img.hash_value
        }

    def _deserialize_image_file(self, data: Dict[str, Any]) -> ImageFile:
        """Deserialize a dictionary to an ImageFile."""
        return ImageFile(
            path=Path(data["path"]),
            file_size=data.get("file_size", 0),
            width=data.get("width", 0),
            height=data.get("height", 0),
            hash_value=data.get("hash_value")
        )

    def _serialize_group(self, group: DuplicateGroup) -> Dict[str, Any]:
        """Serialize a DuplicateGroup to a dictionary."""
        suggested_keep_path = str(group.suggested_keep.path) if group.suggested_keep else None

        # Convert similarity_scores keys from tuples to strings
        similarity_scores = {}
        for key, value in group.similarity_scores.items():
            str_key = f"{key[0]}|{key[1]}"
            similarity_scores[str_key] = value

        return {
            "group_id": group.group_id,
            "images": [self._serialize_image_file(img) for img in group.images],
            "similarity_scores": similarity_scores,
            "suggested_keep_path": suggested_keep_path,
            "is_intra_directory": group.is_intra_directory,
            "keep_strategy": group.keep_strategy,
            "target_directory": str(group.target_directory) if group.target_directory else None
        }

    def _deserialize_group(self, data: Dict[str, Any]) -> DuplicateGroup:
        """Deserialize a dictionary to a DuplicateGroup."""
        images = [self._deserialize_image_file(img_data) for img_data in data["images"]]

        # Find suggested keep by path
        suggested_keep = None
        if data.get("suggested_keep_path"):
            for img in images:
                if str(img.path) == data["suggested_keep_path"]:
                    suggested_keep = img
                    break

        # Convert similarity_scores keys back to tuples
        similarity_scores = {}
        for str_key, value in data.get("similarity_scores", {}).items():
            parts = str_key.split("|")
            if len(parts) == 2:
                similarity_scores[tuple(parts)] = value

        target_dir = Path(data["target_directory"]) if data.get("target_directory") else None

        group = DuplicateGroup(
            group_id=data["group_id"],
            images=images,
            similarity_scores=similarity_scores,
            suggested_keep=suggested_keep,
            is_intra_directory=data.get("is_intra_directory", True),
            keep_strategy=data.get("keep_strategy", "largest_file"),
            target_directory=target_dir
        )

        return group

    def save_session(
        self,
        root_directory: Path,
        groups: List[DuplicateGroup],
        scan_mode: str,
        detection_mode: str,
        hash_algorithm: str,
        perceptual_threshold: int,
        selected_for_action: Optional[set] = None
    ) -> str:
        """
        Save the current session state.

        Returns the session ID.
        """
        session_id = generate_session_id(root_directory)
        now = datetime.now().isoformat()

        # Calculate totals
        total_duplicates = sum(len(g.images) for g in groups)
        potential_savings = sum(g.potential_savings for g in groups)

        # Create session info
        info = SessionInfo(
            session_id=session_id,
            root_directory=str(root_directory),
            created_at=now,
            updated_at=now,
            total_groups=len(groups),
            total_duplicates=total_duplicates,
            potential_savings=potential_savings,
            scan_mode=scan_mode,
            detection_mode=detection_mode,
            hash_algorithm=hash_algorithm,
            perceptual_threshold=perceptual_threshold
        )

        # Check if session exists to preserve created_at
        existing_info = self.get_session_info(session_id)
        if existing_info:
            info.created_at = existing_info.created_at

        # Save session data
        session_data = {
            "groups": [self._serialize_group(g) for g in groups],
            "selected_for_action": list(selected_for_action) if selected_for_action else []
        }

        with open(self._get_session_path(session_id), 'w') as f:
            json.dump(session_data, f, indent=2)

        # Save session info
        with open(self._get_info_path(session_id), 'w') as f:
            json.dump(info.to_dict(), f, indent=2)

        return session_id

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a session by ID.

        Returns a dict with 'groups', 'selected_for_action', and 'info'.
        """
        session_path = self._get_session_path(session_id)
        info_path = self._get_info_path(session_id)

        if not session_path.exists() or not info_path.exists():
            return None

        try:
            with open(session_path, 'r') as f:
                session_data = json.load(f)

            with open(info_path, 'r') as f:
                info_data = json.load(f)

            groups = [self._deserialize_group(g) for g in session_data["groups"]]
            selected = set(session_data.get("selected_for_action", []))
            info = SessionInfo.from_dict(info_data)

            return {
                "groups": groups,
                "selected_for_action": selected,
                "info": info
            }
        except Exception as e:
            print(f"Error loading session {session_id}: {e}")
            return None

    def get_session_info(self, session_id: str) -> Optional[SessionInfo]:
        """Get session info without loading full data."""
        info_path = self._get_info_path(session_id)

        if not info_path.exists():
            return None

        try:
            with open(info_path, 'r') as f:
                info_data = json.load(f)
            return SessionInfo.from_dict(info_data)
        except Exception:
            return None

    def list_sessions(self) -> List[SessionInfo]:
        """List all available sessions, sorted by most recently updated."""
        sessions = []

        for info_file in self.sessions_dir.glob("*_info.json"):
            try:
                with open(info_file, 'r') as f:
                    info_data = json.load(f)
                sessions.append(SessionInfo.from_dict(info_data))
            except Exception:
                continue

        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            session_path = self._get_session_path(session_id)
            info_path = self._get_info_path(session_id)

            if session_path.exists():
                session_path.unlink()
            if info_path.exists():
                info_path.unlink()

            return True
        except Exception:
            return False

    def session_exists_for_directory(self, directory: Path) -> Optional[str]:
        """Check if a session exists for a directory. Returns session_id if exists."""
        session_id = generate_session_id(directory)
        if self._get_session_path(session_id).exists():
            return session_id
        return None
