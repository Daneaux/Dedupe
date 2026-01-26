"""File operations for moving and deleting duplicate images."""

from pathlib import Path
from typing import List, Optional, Tuple, Callable
import shutil
import os

from ..models.image_file import ImageFile
from ..models.duplicate_group import DuplicateGroup


class FileOperations:
    """Handles file move and delete operations for duplicates."""

    def __init__(self, duplicate_folder_name: str = "_duplicates"):
        """
        Initialize file operations.

        Args:
            duplicate_folder_name: Name for the parallel duplicate directory.
        """
        self.duplicate_folder_name = duplicate_folder_name

    def move_to_parallel_structure(
        self,
        images: List[ImageFile],
        root_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Tuple[ImageFile, Path, bool, Optional[str]]]:
        """
        Move images to a parallel directory structure.

        Creates a mirror of the original directory structure under a
        '_duplicates' folder at the root level.

        Args:
            images: List of ImageFile objects to move.
            root_dir: Root directory for the parallel structure.
            progress_callback: Optional callback(filename, current, total).

        Returns:
            List of tuples: (image, new_path, success, error_message)
        """
        results: List[Tuple[ImageFile, Path, bool, Optional[str]]] = []
        root_path = Path(root_dir)
        duplicates_root = root_path / self.duplicate_folder_name

        total = len(images)

        for i, image in enumerate(images):
            if progress_callback:
                progress_callback(image.filename, i + 1, total)

            try:
                # Calculate relative path from root
                try:
                    rel_path = image.path.relative_to(root_path)
                except ValueError:
                    # Image is not under root_dir, use just the filename
                    rel_path = Path(image.filename)

                # Create destination path
                dest_path = duplicates_root / rel_path

                # Create destination directory
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # Handle name conflicts
                final_dest = self._get_unique_path(dest_path)

                # Move the file
                shutil.move(str(image.path), str(final_dest))

                results.append((image, final_dest, True, None))

            except Exception as e:
                results.append((image, image.path, False, str(e)))

        return results

    def delete_files(
        self,
        images: List[ImageFile],
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Tuple[ImageFile, bool, Optional[str]]]:
        """
        Delete the specified image files.

        Args:
            images: List of ImageFile objects to delete.
            progress_callback: Optional callback(filename, current, total).

        Returns:
            List of tuples: (image, success, error_message)
        """
        results: List[Tuple[ImageFile, bool, Optional[str]]] = []
        total = len(images)

        for i, image in enumerate(images):
            if progress_callback:
                progress_callback(image.filename, i + 1, total)

            try:
                if image.path.exists():
                    image.path.unlink()
                    results.append((image, True, None))
                else:
                    results.append((image, False, "File not found"))

            except Exception as e:
                results.append((image, False, str(e)))

        return results

    def move_to_trash(
        self,
        images: List[ImageFile],
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Tuple[ImageFile, bool, Optional[str]]]:
        """
        Move files to system trash (macOS).

        Args:
            images: List of ImageFile objects to trash.
            progress_callback: Optional callback(filename, current, total).

        Returns:
            List of tuples: (image, success, error_message)
        """
        results: List[Tuple[ImageFile, bool, Optional[str]]] = []
        total = len(images)

        for i, image in enumerate(images):
            if progress_callback:
                progress_callback(image.filename, i + 1, total)

            try:
                if image.path.exists():
                    # Use macOS trash via osascript
                    import subprocess
                    result = subprocess.run(
                        [
                            "osascript", "-e",
                            f'tell application "Finder" to delete POSIX file "{image.path}"'
                        ],
                        capture_output=True,
                        text=True
                    )

                    if result.returncode == 0:
                        results.append((image, True, None))
                    else:
                        # Fall back to delete
                        image.path.unlink()
                        results.append((image, True, "Moved to trash (fallback)"))
                else:
                    results.append((image, False, "File not found"))

            except Exception as e:
                results.append((image, False, str(e)))

        return results

    def _move_single_file_to_trash(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Move a single file to system trash (macOS).

        Args:
            file_path: Path to the file to trash.

        Returns:
            Tuple of (success, error_message)
        """
        import subprocess
        try:
            result = subprocess.run(
                [
                    "osascript", "-e",
                    f'tell application "Finder" to delete POSIX file "{file_path}"'
                ],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                return (True, None)
            else:
                return (False, f"Trash failed: {result.stderr}")
        except Exception as e:
            return (False, str(e))

    def _get_unique_path(self, path: Path) -> Path:
        """
        Get a unique path by adding a number suffix if file exists.

        Args:
            path: Original path.

        Returns:
            Unique path that doesn't exist.
        """
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1

        while True:
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

    def preview_move(
        self,
        images: List[ImageFile],
        root_dir: Path
    ) -> List[Tuple[Path, Path]]:
        """
        Preview what files would be moved and where.

        Args:
            images: List of images to move.
            root_dir: Root directory for parallel structure.

        Returns:
            List of (source, destination) path tuples.
        """
        preview: List[Tuple[Path, Path]] = []
        root_path = Path(root_dir)
        duplicates_root = root_path / self.duplicate_folder_name

        for image in images:
            try:
                rel_path = image.path.relative_to(root_path)
            except ValueError:
                rel_path = Path(image.filename)

            dest_path = duplicates_root / rel_path
            preview.append((image.path, dest_path))

        return preview

    def validate_paths(
        self,
        images: List[ImageFile]
    ) -> Tuple[List[ImageFile], List[Tuple[ImageFile, str]]]:
        """
        Validate that all image paths exist.

        Args:
            images: List of images to validate.

        Returns:
            Tuple of (valid_images, invalid_images_with_errors)
        """
        valid: List[ImageFile] = []
        invalid: List[Tuple[ImageFile, str]] = []

        for image in images:
            if image.path.exists():
                valid.append(image)
            else:
                invalid.append((image, "File not found"))

        return valid, invalid

    def move_to_target_directories(
        self,
        groups: List[DuplicateGroup],
        delete_duplicates: bool = True,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Tuple[List[Tuple[ImageFile, Path, bool, Optional[str]]], List[Path]]:
        """
        Move/merge files to their target directories (for date folder merge mode).

        For each group:
        - Keeps the suggested_keep file
        - Either deletes duplicates or moves non-keepers to target directory
        - Returns list of empty directories that can be removed

        Args:
            groups: List of DuplicateGroup objects with target_directory set.
            delete_duplicates: If True, delete duplicates. If False, move to target.
            progress_callback: Optional callback(filename, current, total).

        Returns:
            Tuple of (results, empty_directories)
            - results: List of (image, new_path, success, error_message)
            - empty_directories: List of directories that are now empty
        """
        results: List[Tuple[ImageFile, Path, bool, Optional[str]]] = []
        directories_to_check: set = set()

        # Count total operations
        total = sum(
            len([img for img in g.images if img != g.suggested_keep])
            for g in groups
        )
        current = 0

        for group in groups:
            if not group.target_directory:
                continue

            target_dir = group.target_directory

            for image in group.images:
                # Skip the keeper
                if image == group.suggested_keep:
                    continue

                current += 1
                if progress_callback:
                    progress_callback(image.filename, current, total)

                # Track the source directory for later cleanup check
                directories_to_check.add(image.directory)

                try:
                    if delete_duplicates:
                        # Move duplicate to trash (instead of permanent deletion)
                        if image.path.exists():
                            success, error = self._move_single_file_to_trash(image.path)
                            if success:
                                results.append((image, image.path, True, None))
                            else:
                                results.append((image, image.path, False, error))
                        else:
                            results.append((image, image.path, False, "File not found"))
                    else:
                        # Move to target directory
                        dest_path = target_dir / image.filename
                        final_dest = self._get_unique_path(dest_path)

                        if image.path.exists():
                            shutil.move(str(image.path), str(final_dest))
                            results.append((image, final_dest, True, None))
                        else:
                            results.append((image, image.path, False, "File not found"))

                except Exception as e:
                    results.append((image, image.path, False, str(e)))

        # Check for empty directories
        empty_dirs: List[Path] = []
        for dir_path in directories_to_check:
            if dir_path.exists() and dir_path.is_dir():
                # Check if directory is empty (no files, may have subdirs)
                has_files = any(dir_path.iterdir())
                if not has_files:
                    empty_dirs.append(dir_path)

        return results, empty_dirs

    def remove_empty_directories(
        self,
        directories: List[Path],
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Tuple[Path, bool, Optional[str]]]:
        """
        Remove empty directories.

        Args:
            directories: List of directory paths to remove.
            progress_callback: Optional callback(dirname, current, total).

        Returns:
            List of (path, success, error_message)
        """
        results: List[Tuple[Path, bool, Optional[str]]] = []
        total = len(directories)

        for i, dir_path in enumerate(directories):
            if progress_callback:
                progress_callback(dir_path.name, i + 1, total)

            try:
                if dir_path.exists() and dir_path.is_dir():
                    # Only remove if truly empty
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        results.append((dir_path, True, None))
                    else:
                        results.append((dir_path, False, "Directory not empty"))
                else:
                    results.append((dir_path, False, "Directory not found"))

            except Exception as e:
                results.append((dir_path, False, str(e)))

        return results
