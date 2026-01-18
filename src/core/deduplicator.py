"""Duplicate detection using file hashes for exact duplicates."""

from pathlib import Path
from typing import List, Dict, Optional, Callable, Set, Tuple
from collections import defaultdict
import hashlib
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models.image_file import ImageFile
from ..models.duplicate_group import DuplicateGroup


def normalize_extension(ext: str) -> str:
    """Normalize file extension to a canonical form for grouping."""
    ext = ext.lower().lstrip(".")
    # Group similar RAW formats
    raw_formats = {"cr2", "crw", "cr3", "raw"}
    if ext in raw_formats:
        return "raw"
    # Group JPEG variations
    if ext in {"jpg", "jpeg"}:
        return "jpg"
    if ext in {"tif", "tiff"}:
        return "tiff"
    return ext


def compute_file_hash(file_path: str, chunk_size: int = 65536) -> Optional[str]:
    """
    Compute MD5 hash of a file.

    Args:
        file_path: Path to the file.
        chunk_size: Size of chunks to read (default 64KB).

    Returns:
        Hex string of MD5 hash, or None if file cannot be read.
    """
    try:
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError):
        return None


class Deduplicator:
    """Finds exact duplicate images using file hashes."""

    def __init__(
        self,
        hash_threshold: int = 0,  # Ignored - kept for API compatibility
        cnn_threshold: float = 0.85,  # Ignored - kept for API compatibility
        use_cnn: bool = False,  # Ignored - kept for API compatibility
        focus_intra_directory: bool = True,
        hash_method: str = "md5",  # md5 (fast) or sha256 (more secure)
        num_workers: int = 0  # 0 = auto (use all CPU cores)
    ):
        """
        Initialize the deduplicator.

        Args:
            hash_threshold: Ignored (kept for compatibility).
            cnn_threshold: Ignored (kept for compatibility).
            use_cnn: Ignored (kept for compatibility).
            focus_intra_directory: Process each directory separately.
            hash_method: Hash algorithm - 'md5' (fast) or 'sha256' (secure).
            num_workers: Number of parallel workers (0 = auto-detect CPU cores).
        """
        self.focus_intra_directory = focus_intra_directory
        self.hash_method = hash_method.lower()
        # Auto-detect CPU cores if not specified
        self.num_workers = num_workers if num_workers > 0 else multiprocessing.cpu_count()
        self._cancelled = False

    def cancel(self):
        """Cancel the current operation."""
        self._cancelled = True

    def reset(self):
        """Reset the cancellation state."""
        self._cancelled = False

    def find_duplicates(
        self,
        images: List[ImageFile],
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[DuplicateGroup]:
        """
        Find duplicate images in the given list.

        Processes each directory separately and only compares files with the
        same extension type (JPG vs JPG, not JPG vs RAW).

        Args:
            images: List of ImageFile objects to check.
            progress_callback: Optional callback(status, processed, total) for progress.

        Returns:
            List of DuplicateGroup objects containing duplicate sets.
        """
        self._cancelled = False

        if not images:
            return []

        # Group images by directory
        from .scanner import ImageScanner
        scanner = ImageScanner()
        dir_groups = scanner.group_by_directory(images)

        all_groups: List[DuplicateGroup] = []
        group_id = 0

        total_dirs = len(dir_groups)
        processed_dirs = 0

        for directory, dir_images in dir_groups.items():
            if self._cancelled:
                break

            if len(dir_images) < 2:
                processed_dirs += 1
                continue

            if progress_callback:
                progress_callback(
                    f"Processing: {directory.name}",
                    processed_dirs,
                    total_dirs
                )

            # Further group by extension type within this directory
            ext_groups: Dict[str, List[ImageFile]] = defaultdict(list)
            for img in dir_images:
                norm_ext = normalize_extension(img.extension)
                ext_groups[norm_ext].append(img)

            # Process each extension group separately
            for ext, ext_images in ext_groups.items():
                if self._cancelled:
                    break

                if len(ext_images) < 2:
                    continue

                # Find duplicates within this directory + extension group
                dir_duplicates = self._find_duplicates_in_set(ext_images, group_id)

                for group in dir_duplicates:
                    group.is_intra_directory = True
                    all_groups.append(group)
                    group_id += 1

            processed_dirs += 1

        if progress_callback:
            progress_callback("Complete", total_dirs, total_dirs)

        return all_groups

    def _find_duplicates_in_set(
        self,
        images: List[ImageFile],
        start_group_id: int
    ) -> List[DuplicateGroup]:
        """
        Find exact duplicates within a set of images using file hashes.

        Args:
            images: List of images to check.
            start_group_id: Starting ID for new groups.

        Returns:
            List of DuplicateGroup objects.
        """
        if len(images) < 2:
            return []

        # Build path mapping
        path_to_image: Dict[str, ImageFile] = {}
        for img in images:
            path_to_image[str(img.path)] = img

        if self._cancelled:
            return []

        # Compute file hashes in parallel
        hash_to_paths: Dict[str, List[str]] = defaultdict(list)

        def hash_file(img: ImageFile) -> Tuple[str, Optional[str]]:
            """Hash a single file and return (path, hash)."""
            file_hash = compute_file_hash(str(img.path))
            return (str(img.path), file_hash)

        # Parallel hash computation using threads (I/O bound)
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = {executor.submit(hash_file, img): img for img in images}

            for future in as_completed(futures):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return []

                path, file_hash = future.result()
                if file_hash:
                    hash_to_paths[file_hash].append(path)

        if self._cancelled:
            return []

        # Build duplicate groups from files with matching hashes
        groups: List[DuplicateGroup] = []
        group_id = start_group_id

        for file_hash, paths in hash_to_paths.items():
            if len(paths) < 2:
                continue

            # Create group with images that have identical hashes
            image_list = [path_to_image[p] for p in paths if p in path_to_image]

            if len(image_list) < 2:
                continue

            # All files in group are exact duplicates (similarity = 1.0)
            group_scores = {}
            for i, p1 in enumerate(paths):
                for p2 in paths[i+1:]:
                    key = tuple(sorted([p1, p2]))
                    group_scores[key] = 1.0

            group = DuplicateGroup(
                group_id=group_id,
                images=image_list,
                similarity_scores=group_scores
            )
            groups.append(group)
            group_id += 1

        return groups
