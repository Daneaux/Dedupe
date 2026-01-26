"""Cross-platform volume/drive detection and management.

Supports macOS, Windows, and Linux for detecting mounted drives
and obtaining unique volume identifiers.
"""

import hashlib
import platform
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class VolumeInfo:
    """Information about a mounted volume/drive."""

    uuid: str  # Unique identifier (persists across remounts)
    name: str  # Display name
    mount_point: Path  # Where it's mounted
    is_internal: bool  # Internal vs external drive
    total_bytes: int  # Total capacity
    available_bytes: int  # Free space
    filesystem: str  # Filesystem type (APFS, NTFS, ext4, etc.)

    @property
    def total_size_str(self) -> str:
        """Get human-readable total size."""
        return self._format_size(self.total_bytes)

    @property
    def available_size_str(self) -> str:
        """Get human-readable available size."""
        return self._format_size(self.available_bytes)

    @property
    def used_bytes(self) -> int:
        """Get used space in bytes."""
        return self.total_bytes - self.available_bytes

    @property
    def used_percent(self) -> float:
        """Get percentage of space used."""
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100

    @staticmethod
    def _format_size(size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


class VolumeManager:
    """Cross-platform manager for detecting and tracking volumes."""

    def __init__(self):
        self._system = platform.system()

    def list_volumes(self) -> List[VolumeInfo]:
        """List all mounted user-accessible volumes."""
        if self._system == "Darwin":
            return self._list_volumes_macos()
        elif self._system == "Windows":
            return self._list_volumes_windows()
        elif self._system == "Linux":
            return self._list_volumes_linux()
        else:
            return []

    def get_volume_uuid(self, path: Path) -> Optional[str]:
        """Get the unique identifier for a volume containing the given path."""
        mount_point = self._get_mount_point(path)
        if not mount_point:
            return None

        if self._system == "Darwin":
            return self._get_uuid_macos(mount_point)
        elif self._system == "Windows":
            return self._get_uuid_windows(mount_point)
        elif self._system == "Linux":
            return self._get_uuid_linux(mount_point)
        else:
            # Fallback: hash the mount point
            return self._generate_fallback_uuid(mount_point)

    def get_volume_for_path(self, path: Path) -> Optional[VolumeInfo]:
        """Get VolumeInfo for the volume containing the given path."""
        mount_point = self._get_mount_point(path)
        if not mount_point:
            return None

        volumes = self.list_volumes()
        for vol in volumes:
            if vol.mount_point == mount_point:
                return vol

        return None

    def get_relative_path(self, file_path: Path, volume_mount: Path) -> str:
        """Convert absolute path to relative path within volume."""
        try:
            return str(file_path.relative_to(volume_mount))
        except ValueError:
            return str(file_path)

    def get_absolute_path(self, relative_path: str, volume_mount: Path) -> Path:
        """Convert relative path back to absolute using current mount point."""
        return volume_mount / relative_path

    def _get_mount_point(self, path: Path) -> Optional[Path]:
        """Find the mount point for a given path."""
        path = path.resolve()

        # Walk up the path until we find a mount point
        while path != path.parent:
            if path.is_mount() or str(path) in ('/', 'C:\\'):
                return path
            path = path.parent

        # Return root if nothing else found
        return path if path.exists() else None

    # ==================== macOS Implementation ====================

    def _list_volumes_macos(self) -> List[VolumeInfo]:
        """List volumes on macOS using diskutil."""
        volumes = []

        try:
            # Get list of all disks
            result = subprocess.run(
                ['diskutil', 'list', '-plist'],
                capture_output=True,
                check=True
            )
            disk_list = plistlib.loads(result.stdout)

            # Track mount points we've seen to avoid duplicates
            seen_mounts = set()

            for disk in disk_list.get('AllDisksAndPartitions', []):
                # Process APFS containers
                for volume in disk.get('APFSVolumes', []):
                    mount = volume.get('MountPoint')
                    if mount and mount not in seen_mounts:
                        seen_mounts.add(mount)
                        vol_info = self._get_volume_info_macos(mount)
                        if vol_info:
                            volumes.append(vol_info)

                # Process regular partitions
                for partition in disk.get('Partitions', []):
                    mount = partition.get('MountPoint')
                    if mount and mount not in seen_mounts:
                        seen_mounts.add(mount)
                        vol_info = self._get_volume_info_macos(mount)
                        if vol_info:
                            volumes.append(vol_info)

            # Also check /Volumes for any we might have missed
            volumes_dir = Path('/Volumes')
            if volumes_dir.exists():
                for item in volumes_dir.iterdir():
                    if item.is_mount() and str(item) not in seen_mounts:
                        vol_info = self._get_volume_info_macos(str(item))
                        if vol_info:
                            volumes.append(vol_info)

        except (subprocess.CalledProcessError, plistlib.InvalidFileException):
            pass

        return volumes

    def _get_volume_info_macos(self, mount_point: str) -> Optional[VolumeInfo]:
        """Get detailed info for a macOS volume."""
        # Skip system volumes
        if mount_point.startswith('/System/Volumes') and 'Data' not in mount_point:
            return None

        try:
            result = subprocess.run(
                ['diskutil', 'info', '-plist', mount_point],
                capture_output=True,
                check=True
            )
            info = plistlib.loads(result.stdout)

            # Get or generate UUID
            uuid = info.get('VolumeUUID') or info.get('DiskUUID')
            if not uuid:
                uuid = self._generate_fallback_uuid(Path(mount_point))

            # Determine if internal
            is_internal = info.get('Internal', False)

            # Get space info
            total = info.get('TotalSize', 0)
            # For APFS, use container free space
            available = info.get('APFSContainerFree', info.get('FreeSpace', 0))

            return VolumeInfo(
                uuid=uuid,
                name=info.get('VolumeName', Path(mount_point).name),
                mount_point=Path(mount_point),
                is_internal=is_internal,
                total_bytes=total,
                available_bytes=available,
                filesystem=info.get('FilesystemType', 'Unknown'),
            )

        except (subprocess.CalledProcessError, plistlib.InvalidFileException):
            return None

    def _get_uuid_macos(self, mount_point: Path) -> Optional[str]:
        """Get volume UUID on macOS."""
        try:
            result = subprocess.run(
                ['diskutil', 'info', '-plist', str(mount_point)],
                capture_output=True,
                check=True
            )
            info = plistlib.loads(result.stdout)
            return info.get('VolumeUUID') or info.get('DiskUUID')
        except (subprocess.CalledProcessError, plistlib.InvalidFileException):
            return self._generate_fallback_uuid(mount_point)

    # ==================== Windows Implementation ====================

    def _list_volumes_windows(self) -> List[VolumeInfo]:
        """List volumes on Windows."""
        volumes = []

        try:
            import ctypes
            from ctypes import wintypes

            # Get available drive letters
            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()

            for i in range(26):
                if drives_bitmask & (1 << i):
                    drive_letter = chr(ord('A') + i)
                    drive_path = f"{drive_letter}:\\"

                    # Check drive type
                    drive_type = kernel32.GetDriveTypeW(drive_path)

                    # Skip CD-ROM (5) and unknown (0)
                    if drive_type in (0, 5):
                        continue

                    vol_info = self._get_volume_info_windows(drive_path, drive_type)
                    if vol_info:
                        volumes.append(vol_info)

        except Exception:
            pass

        return volumes

    def _get_volume_info_windows(self, drive_path: str, drive_type: int) -> Optional[VolumeInfo]:
        """Get detailed info for a Windows volume."""
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32

            # Get volume information
            volume_name = ctypes.create_unicode_buffer(1024)
            volume_serial = ctypes.c_ulong()
            max_component = ctypes.c_ulong()
            fs_flags = ctypes.c_ulong()
            fs_name = ctypes.create_unicode_buffer(1024)

            kernel32.GetVolumeInformationW(
                drive_path,
                volume_name,
                1024,
                ctypes.byref(volume_serial),
                ctypes.byref(max_component),
                ctypes.byref(fs_flags),
                fs_name,
                1024
            )

            # Get disk space
            free_bytes = ctypes.c_ulonglong()
            total_bytes = ctypes.c_ulonglong()
            total_free = ctypes.c_ulonglong()

            kernel32.GetDiskFreeSpaceExW(
                drive_path,
                ctypes.byref(free_bytes),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free)
            )

            # Generate UUID from serial number
            uuid = f"WIN-{volume_serial.value:08X}"

            # Determine if internal (fixed drive = 3)
            is_internal = drive_type == 3

            name = volume_name.value or drive_path.rstrip('\\')

            return VolumeInfo(
                uuid=uuid,
                name=name,
                mount_point=Path(drive_path),
                is_internal=is_internal,
                total_bytes=total_bytes.value,
                available_bytes=free_bytes.value,
                filesystem=fs_name.value or 'Unknown',
            )

        except Exception:
            return None

    def _get_uuid_windows(self, mount_point: Path) -> Optional[str]:
        """Get volume serial number on Windows."""
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32

            volume_serial = ctypes.c_ulong()
            drive_path = str(mount_point)
            if not drive_path.endswith('\\'):
                drive_path += '\\'

            kernel32.GetVolumeInformationW(
                drive_path,
                None, 0,
                ctypes.byref(volume_serial),
                None, None, None, 0
            )

            return f"WIN-{volume_serial.value:08X}"

        except Exception:
            return self._generate_fallback_uuid(mount_point)

    # ==================== Linux Implementation ====================

    def _list_volumes_linux(self) -> List[VolumeInfo]:
        """List volumes on Linux."""
        volumes = []

        try:
            # Read /proc/mounts
            with open('/proc/mounts', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 4:
                        continue

                    device, mount_point, fs_type, options = parts[:4]

                    # Skip pseudo filesystems
                    if fs_type in ('proc', 'sysfs', 'devtmpfs', 'tmpfs', 'cgroup',
                                  'cgroup2', 'securityfs', 'debugfs', 'fusectl',
                                  'configfs', 'hugetlbfs', 'mqueue', 'pstore'):
                        continue

                    # Skip system mounts
                    if mount_point in ('/boot', '/boot/efi') or mount_point.startswith('/sys'):
                        continue

                    vol_info = self._get_volume_info_linux(device, mount_point, fs_type)
                    if vol_info:
                        volumes.append(vol_info)

        except Exception:
            pass

        return volumes

    def _get_volume_info_linux(
        self,
        device: str,
        mount_point: str,
        fs_type: str
    ) -> Optional[VolumeInfo]:
        """Get detailed info for a Linux volume."""
        try:
            import os

            # Get UUID using blkid
            uuid = None
            try:
                result = subprocess.run(
                    ['blkid', '-s', 'UUID', '-o', 'value', device],
                    capture_output=True,
                    check=True
                )
                uuid = result.stdout.decode().strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

            if not uuid:
                uuid = self._generate_fallback_uuid(Path(mount_point))

            # Get space info
            stat = os.statvfs(mount_point)
            total = stat.f_blocks * stat.f_frsize
            available = stat.f_bavail * stat.f_frsize

            # Determine name
            name = Path(mount_point).name
            if mount_point == '/':
                name = 'Root'

            # Check if internal (heuristic: starts with /dev/sd or /dev/nvme)
            is_internal = device.startswith('/dev/sd') or device.startswith('/dev/nvme')

            return VolumeInfo(
                uuid=f"LIN-{uuid}",
                name=name,
                mount_point=Path(mount_point),
                is_internal=is_internal,
                total_bytes=total,
                available_bytes=available,
                filesystem=fs_type,
            )

        except Exception:
            return None

    def _get_uuid_linux(self, mount_point: Path) -> Optional[str]:
        """Get volume UUID on Linux."""
        try:
            # Read /proc/mounts to find device
            with open('/proc/mounts', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == str(mount_point):
                        device = parts[0]

                        # Get UUID using blkid
                        result = subprocess.run(
                            ['blkid', '-s', 'UUID', '-o', 'value', device],
                            capture_output=True,
                            check=True
                        )
                        uuid = result.stdout.decode().strip()
                        if uuid:
                            return f"LIN-{uuid}"
                        break

        except Exception:
            pass

        return self._generate_fallback_uuid(mount_point)

    # ==================== Fallback ====================

    def _generate_fallback_uuid(self, mount_point: Path) -> str:
        """Generate a fallback UUID based on mount point path.

        This is less reliable than a real UUID but provides some
        stability for filesystems without UUID support.
        """
        path_str = str(mount_point.resolve())
        hash_val = hashlib.md5(path_str.encode()).hexdigest()[:16]
        return f"FALLBACK-{hash_val.upper()}"
