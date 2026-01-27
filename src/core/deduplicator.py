"""Duplicate detection using perceptual hashing for visual duplicates."""

from pathlib import Path
from typing import List, Dict, Optional, Callable, Set, Tuple
from collections import defaultdict
import hashlib
import multiprocessing
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image
import imagehash

from ..models.image_file import ImageFile
from ..models.duplicate_group import DuplicateGroup


def extract_date_prefix(folder_name: str) -> Optional[str]:
    """
    Extract date prefix from folder name (e.g., '01-18' from '01-18 Grace').

    Supports formats like:
    - MM-DD (01-18)
    - MM-DD suffix (01-18 Grace)
    - YYYY-MM-DD
    - YYYY-MM-DD suffix

    Returns the date prefix or None if not found.
    """
    # Match patterns like "01-18", "2024-01-18", etc. at start of string
    match = re.match(r'^(\d{2,4}-\d{2}(?:-\d{2})?)', folder_name)
    if match:
        return match.group(1)
    return None


def get_target_folder(folders: List[Path]) -> Path:
    """
    Determine the target folder for merging (the one with the longest name).

    Args:
        folders: List of folder paths with the same date prefix.

    Returns:
        The folder with the longest name (e.g., '01-18 Grace' over '01-18').
    """
    return max(folders, key=lambda f: len(f.name))


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


def extract_base_filename(filename: str) -> str:
    """
    Extract the base filename by removing common duplicate suffixes.

    The key insight is that original camera files have patterns like:
    - IMG_0001, DSC_1234, DSCN0001 (underscore + 4 digits is original)

    Duplicate suffixes are typically:
    - _2, _3 (single digit after underscore at very end)
    - _2_1, _2_2 (multiple single-digit suffixes)
    - (1), (2) (parenthetical numbers)
    - copy, copy 2 (word "copy")

    Examples:
        IMG_0001.jpg -> IMG_0001
        IMG_0001_2.jpg -> IMG_0001
        IMG_0001_2_1.jpg -> IMG_0001
        photo (1).jpg -> photo
        photo copy.jpg -> photo
        photo copy 2.jpg -> photo

    Returns the base name without extension and without duplicate suffixes.
    """
    # Remove extension first
    name = Path(filename).stem

    # Remove common duplicate suffixes (applied repeatedly until no more matches)
    # These patterns are designed to NOT match original camera numbering like _0001
    patterns = [
        # Parenthetical numbers: (1), (2), etc. - always a copy indicator
        r'\s*\(\d+\)$',
        # "copy" variations: copy, copy 2, Copy 3, etc.
        r'\s+copy(\s+\d+)?$',
        # Single/double digit suffix: _2, _12 but NOT _0001 (4+ digits = original)
        # Match underscore followed by 1-2 digits at end
        r'_\d{1,2}$',
    ]

    # Apply patterns repeatedly until no changes
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            new_name = re.sub(pattern, '', name, flags=re.IGNORECASE)
            if new_name != name:
                name = new_name
                changed = True

    return name.strip()


def compute_file_hash(file_path: str, chunk_size: int = 65536) -> Optional[str]:
    """
    Compute MD5 hash of a file (full file bytes).

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


def compute_image_hash(file_path: str) -> Optional[str]:
    """
    Compute MD5 hash of image pixel data only, ignoring EXIF metadata.

    This loads the image and hashes the raw pixel data, so images with
    identical visual content but different metadata will have the same hash.

    Args:
        file_path: Path to the image file.

    Returns:
        Hex string of MD5 hash, or None if image cannot be read.
    """
    try:
        # Handle RAW files with rawpy
        ext = Path(file_path).suffix.lower()
        if ext in {'.cr2', '.crw', '.cr3', '.raf', '.raw'}:
            try:
                import rawpy
                with rawpy.imread(file_path) as raw:
                    # Get RGB image data
                    rgb = raw.postprocess()
                    hasher = hashlib.md5()
                    hasher.update(rgb.tobytes())
                    return hasher.hexdigest()
            except Exception:
                # Fall back to file hash if rawpy fails
                return compute_file_hash(file_path)

        # Standard image formats with PIL
        with Image.open(file_path) as img:
            # Convert to RGB to normalize (handles different modes like RGBA, P, etc.)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # Get raw pixel data
            pixel_data = img.tobytes()
            hasher = hashlib.md5()
            hasher.update(pixel_data)
            return hasher.hexdigest()
    except Exception:
        # Fall back to file hash if image processing fails
        return compute_file_hash(file_path)


def compute_perceptual_hash(file_path: str, algorithm: str = "phash") -> Optional[imagehash.ImageHash]:
    """
    Compute perceptual hash of an image for visual duplicate detection.

    Perceptual hashing creates a fingerprint based on visual content, so images
    that look the same will have similar hashes even if one has been compressed,
    resized, or had metadata changes.

    Args:
        file_path: Path to the image file.
        algorithm: Hash algorithm to use - 'phash', 'dhash', 'ahash', or 'whash'.

    Returns:
        ImageHash object (can be compared with - operator for distance), or None if failed.
    """
    from PIL import ImageOps

    # Select hash function based on algorithm
    hash_functions = {
        'phash': imagehash.phash,
        'dhash': imagehash.dhash,
        'ahash': imagehash.average_hash,
        'whash': imagehash.whash,
    }
    hash_func = hash_functions.get(algorithm, imagehash.phash)

    try:
        # Handle RAW files with rawpy
        ext = Path(file_path).suffix.lower()
        if ext in {'.cr2', '.crw', '.cr3', '.raf', '.raw'}:
            try:
                import rawpy
                import numpy as np
                with rawpy.imread(file_path) as raw:
                    # Get RGB image data and convert to PIL Image
                    rgb = raw.postprocess()
                    img = Image.fromarray(rgb)
                    return hash_func(img)
            except Exception:
                return None

        # Standard image formats with PIL
        with Image.open(file_path) as img:
            # Apply EXIF orientation correction - critical for matching rotated images
            img = ImageOps.exif_transpose(img)
            return hash_func(img)
    except Exception:
        return None


def hashes_match(hash1: imagehash.ImageHash, hash2: imagehash.ImageHash, threshold: int = 10) -> bool:
    """
    Check if two perceptual hashes are similar enough to be duplicates.

    Args:
        hash1: First perceptual hash.
        hash2: Second perceptual hash.
        threshold: Maximum Hamming distance to consider as duplicate (0 = exact, 10 = similar).

    Returns:
        True if the hashes are within the threshold distance.
    """
    distance = hash1 - hash2  # Hamming distance
    return distance <= threshold


class Deduplicator:
    """Finds duplicate images using file hashes or perceptual hashing."""

    def __init__(
        self,
        hash_threshold: int = 0,  # Ignored - kept for API compatibility
        cnn_threshold: float = 0.85,  # Ignored - kept for API compatibility
        use_cnn: bool = False,  # Ignored - kept for API compatibility
        focus_intra_directory: bool = True,
        hash_method: str = "md5",  # md5 (fast) or sha256 (more secure)
        num_workers: int = 0,  # 0 = auto (use all CPU cores)
        detection_mode: str = "exact",  # "exact" (MD5 pixel) or "perceptual" (pHash)
        perceptual_threshold: int = 10,  # Hamming distance threshold (0=strict, 20=loose)
        hash_algorithm: str = "phash"  # phash, dhash, ahash, or whash
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
            detection_mode: "exact" for MD5 of pixel data, "perceptual" for pHash.
            perceptual_threshold: Max Hamming distance for perceptual matching (0=strict, 20=loose).
            hash_algorithm: Perceptual hash algorithm - 'phash', 'dhash', 'ahash', or 'whash'.
        """
        self.focus_intra_directory = focus_intra_directory
        self.hash_method = hash_method.lower()
        self.detection_mode = detection_mode
        self.perceptual_threshold = perceptual_threshold
        self.hash_algorithm = hash_algorithm
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

    def _find_duplicates_with_exact_hashes(
        self,
        images: List[ImageFile],
        precomputed_hashes: Dict[str, str],
        start_group_id: int
    ) -> List[DuplicateGroup]:
        """
        Find exact duplicates using precomputed MD5 hashes of pixel data.

        Args:
            images: List of images to check.
            precomputed_hashes: Dict mapping file path to MD5 hash string.
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

        # Group by hash
        hash_to_paths: Dict[str, List[str]] = defaultdict(list)
        for img in images:
            path = str(img.path)
            file_hash = precomputed_hashes.get(path)
            if file_hash:
                hash_to_paths[file_hash].append(path)

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

    def _find_duplicates_with_perceptual_hashes(
        self,
        images: List[ImageFile],
        precomputed_hashes: Dict[str, imagehash.ImageHash],
        start_group_id: int,
        threshold: int = 10
    ) -> List[DuplicateGroup]:
        """
        Find visually similar duplicates using perceptual hashes.

        Uses Union-Find to group images that are within the threshold distance.

        Args:
            images: List of images to check.
            precomputed_hashes: Dict mapping file path to ImageHash.
            start_group_id: Starting ID for new groups.
            threshold: Max Hamming distance to consider as duplicate (0=exact, 10=similar).

        Returns:
            List of DuplicateGroup objects.
        """
        if len(images) < 2:
            return []

        # Build path mapping
        path_to_image: Dict[str, ImageFile] = {}
        for img in images:
            path_to_image[str(img.path)] = img

        # Get list of paths with valid hashes
        valid_paths = [str(img.path) for img in images if str(img.path) in precomputed_hashes]

        if len(valid_paths) < 2:
            return []

        # Union-Find for grouping similar images
        parent = {p: p for p in valid_paths}

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Compare all pairs and union similar ones
        similarity_scores: Dict[Tuple[str, str], float] = {}

        for i, path1 in enumerate(valid_paths):
            hash1 = precomputed_hashes[path1]
            for path2 in valid_paths[i+1:]:
                hash2 = precomputed_hashes[path2]

                distance = hash1 - hash2  # Hamming distance
                if distance <= threshold:
                    union(path1, path2)
                    # Convert distance to similarity (0 distance = 1.0 similarity)
                    # Max distance for 64-bit hash is 64
                    similarity = 1.0 - (distance / 64.0)
                    key = tuple(sorted([path1, path2]))
                    similarity_scores[key] = similarity

        # Group paths by their root parent
        groups_dict: Dict[str, List[str]] = defaultdict(list)
        for path in valid_paths:
            root = find(path)
            groups_dict[root].append(path)

        # Build duplicate groups
        groups: List[DuplicateGroup] = []
        group_id = start_group_id

        for root, paths in groups_dict.items():
            if len(paths) < 2:
                continue

            image_list = [path_to_image[p] for p in paths if p in path_to_image]

            if len(image_list) < 2:
                continue

            # Get similarity scores for this group
            group_scores = {}
            for i, p1 in enumerate(paths):
                for p2 in paths[i+1:]:
                    key = tuple(sorted([p1, p2]))
                    if key in similarity_scores:
                        group_scores[key] = similarity_scores[key]

            group = DuplicateGroup(
                group_id=group_id,
                images=image_list,
                similarity_scores=group_scores
            )
            groups.append(group)
            group_id += 1

        return groups

    def _find_duplicates_by_filename(
        self,
        images: List[ImageFile],
        start_group_id: int
    ) -> List[DuplicateGroup]:
        """
        Find duplicates by matching base filenames (ignoring suffixes like _2, _2_1).

        This is useful for finding copies of the same photo that may have been
        re-encoded or had metadata changes, making them not byte-identical.

        Args:
            images: List of images to check.
            start_group_id: Starting ID for new groups.

        Returns:
            List of DuplicateGroup objects.
        """
        if len(images) < 2:
            return []

        # Group images by their base filename
        base_to_images: Dict[str, List[ImageFile]] = defaultdict(list)

        for img in images:
            base_name = extract_base_filename(img.filename)
            base_to_images[base_name].append(img)

        # Build duplicate groups from files with matching base names
        groups: List[DuplicateGroup] = []
        group_id = start_group_id

        for base_name, matching_images in base_to_images.items():
            # Need at least 2 files AND they must be from different directories
            if len(matching_images) < 2:
                continue

            # Check if files are from different directories (cross-directory duplicates)
            directories = set(img.directory for img in matching_images)
            if len(directories) < 2:
                # All files are in the same directory - not a cross-directory duplicate
                continue

            # Create similarity scores (use 1.0 for filename matches)
            group_scores = {}
            paths = [str(img.path) for img in matching_images]
            for i, p1 in enumerate(paths):
                for p2 in paths[i+1:]:
                    key = tuple(sorted([p1, p2]))
                    group_scores[key] = 1.0

            group = DuplicateGroup(
                group_id=group_id,
                images=matching_images,
                similarity_scores=group_scores
            )
            groups.append(group)
            group_id += 1

        return groups

    def find_duplicates_across_date_folders(
        self,
        year_directory: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[DuplicateGroup]:
        """
        Find duplicates across folders with the same date prefix.

        For a year folder like 2004/, groups folders like:
        - 01-18 and 01-18 Grace
        - 03-22 and 03-22 Birthday Party

        Finds duplicates across these related folders, keeps the file with
        the shortest name, and marks others for deletion/move to the target folder.

        Args:
            year_directory: Year folder (e.g., /photos/2004/)
            progress_callback: Optional callback(status, processed, total)

        Returns:
            List of DuplicateGroup objects with cross-folder duplicates.
        """
        from .scanner import ImageScanner
        from ..models.duplicate_group import KeepStrategy

        import sys
        self._cancelled = False

        if not year_directory.is_dir():
            print(f"DEBUG: {year_directory} is not a directory", flush=True)
            return []

        # Find all subdirectories and group by date prefix
        date_folder_groups: Dict[str, List[Path]] = defaultdict(list)

        print(f"DEBUG: Scanning year directory: {year_directory}", flush=True)
        for subdir in year_directory.iterdir():
            if not subdir.is_dir():
                continue

            date_prefix = extract_date_prefix(subdir.name)
            print(f"DEBUG: Folder '{subdir.name}' -> prefix={date_prefix!r}", flush=True)
            if date_prefix:
                date_folder_groups[date_prefix].append(subdir)

        print(f"DEBUG: Found {len(date_folder_groups)} unique date prefixes", flush=True)
        for prefix, folders in date_folder_groups.items():
            print(f"DEBUG:   {prefix}: {[f.name for f in folders]}", flush=True)

        # Filter to only date prefixes with multiple folders
        date_folder_groups = {
            prefix: folders
            for prefix, folders in date_folder_groups.items()
            if len(folders) > 1
        }

        print(f"DEBUG: After filtering (>1 folder): {len(date_folder_groups)} prefixes", flush=True)

        if not date_folder_groups:
            if progress_callback:
                progress_callback("No date folder pairs found", 0, 0)
            return []

        all_groups: List[DuplicateGroup] = []
        group_id = 0

        total_prefixes = len(date_folder_groups)
        processed_prefixes = 0

        for date_prefix, folders in date_folder_groups.items():
            if self._cancelled:
                break

            if progress_callback:
                folder_names = ", ".join(f.name for f in folders)
                progress_callback(
                    f"Processing: {folder_names}",
                    processed_prefixes,
                    total_prefixes
                )

            # Determine target folder (longest name)
            target_folder = get_target_folder(folders)

            # Scan all related folders (non-recursive, only direct contents)
            all_images: List[ImageFile] = []
            for folder in folders:
                scanner = ImageScanner(recursive=False)
                folder_images = scanner.scan(folder)
                print(f"DEBUG: Scanned {folder.name}: found {len(folder_images)} images", flush=True)
                for img in folder_images[:3]:  # Show first 3 files
                    print(f"DEBUG:   - {img.filename}", flush=True)
                all_images.extend(folder_images)

            print(f"DEBUG: Total images for prefix {date_prefix}: {len(all_images)}", flush=True)

            if len(all_images) < 2:
                processed_prefixes += 1
                continue

            # Group by extension type
            ext_groups: Dict[str, List[ImageFile]] = defaultdict(list)
            for img in all_images:
                norm_ext = normalize_extension(img.extension)
                ext_groups[norm_ext].append(img)

            print(f"DEBUG: Extension groups: {[(ext, len(imgs)) for ext, imgs in ext_groups.items()]}", flush=True)

            # Find duplicates within each extension group
            for ext, ext_images in ext_groups.items():
                if self._cancelled:
                    break

                if len(ext_images) < 2:
                    print(f"DEBUG: Skipping .{ext} - only {len(ext_images)} file(s)", flush=True)
                    continue

                print(f"DEBUG: Checking {len(ext_images)} .{ext} files for duplicates...", flush=True)
                print(f"DEBUG: Detection mode: {self.detection_mode}", flush=True)

                # Group by folder for clearer output
                folder_files: Dict[str, List[ImageFile]] = defaultdict(list)
                for img in ext_images:
                    folder_files[img.directory.name].append(img)

                if self.detection_mode == "perceptual":
                    # Perceptual hashing - finds compressed/resized duplicates
                    print(f"DEBUG: Files and their perceptual hashes ({self.hash_algorithm}):", flush=True)
                    image_hashes: Dict[str, imagehash.ImageHash] = {}
                    for folder_name, imgs in sorted(folder_files.items()):
                        print(f"DEBUG:   [{folder_name}]", flush=True)
                        for img in sorted(imgs, key=lambda x: x.filename):
                            h = compute_perceptual_hash(str(img.path), algorithm=self.hash_algorithm)
                            if h is not None:
                                image_hashes[str(img.path)] = h
                                print(f"DEBUG:     {img.filename} -> {h}", flush=True)
                            else:
                                print(f"DEBUG:     {img.filename} -> FAILED", flush=True)

                    # Find duplicates using perceptual hash similarity
                    print(f"DEBUG: Using {self.hash_algorithm} with threshold: {self.perceptual_threshold}", flush=True)
                    new_groups = self._find_duplicates_with_perceptual_hashes(ext_images, image_hashes, group_id, threshold=self.perceptual_threshold)
                else:
                    # Exact mode - MD5 of pixel data (ignores EXIF but requires exact pixels)
                    print(f"DEBUG: Files and their MD5 hashes (pixel data):", flush=True)
                    image_hashes_exact: Dict[str, str] = {}
                    for folder_name, imgs in sorted(folder_files.items()):
                        print(f"DEBUG:   [{folder_name}]", flush=True)
                        for img in sorted(imgs, key=lambda x: x.filename):
                            h = compute_image_hash(str(img.path))
                            if h is not None:
                                image_hashes_exact[str(img.path)] = h
                                print(f"DEBUG:     {img.filename} -> {h}", flush=True)
                            else:
                                print(f"DEBUG:     {img.filename} -> FAILED", flush=True)

                    # Find duplicates with exact hash matching
                    new_groups = self._find_duplicates_with_exact_hashes(ext_images, image_hashes_exact, group_id)

                print(f"DEBUG: Found {len(new_groups)} duplicate groups for .{ext}", flush=True)

                if new_groups:
                    for g in new_groups:
                        print(f"DEBUG:   Group has {len(g.images)} files: {[img.filename for img in g.images]}", flush=True)

                # Set strategy and target for each group
                for group in new_groups:
                    group.is_intra_directory = False
                    group.keep_strategy = KeepStrategy.SHORTEST_NAME
                    group.target_directory = target_folder
                    group._determine_suggested_keep()  # Recalculate with new strategy
                    all_groups.append(group)
                    group_id += 1

            processed_prefixes += 1

        if progress_callback:
            progress_callback("Complete", total_prefixes, total_prefixes)

        return all_groups

    def find_duplicates_from_db(
        self,
        volume_ids: Optional[List[int]] = None,
        hash_type: str = "exact_md5",
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[DuplicateGroup]:
        """Find duplicates by querying the database for matching hashes.

        This method queries pre-computed hashes from the database rather than
        re-hashing files, making it much faster for volumes that have been scanned.

        Args:
            volume_ids: Optional list of volume IDs to search (None = all volumes)
            hash_type: Type of hash to use for matching (default: exact_md5)
            progress_callback: Optional callback(status, current, total)

        Returns:
            List of DuplicateGroup objects
        """
        from .database import DatabaseManager

        db = DatabaseManager.get_instance()
        self._cancelled = False

        if progress_callback:
            progress_callback("Finding duplicate hashes...", 0, 0)

        # Find all hash values that appear more than once
        duplicate_hashes = db.find_duplicate_hashes(hash_type, volume_ids)

        if not duplicate_hashes:
            return []

        all_groups: List[DuplicateGroup] = []
        group_id = 0
        total_hashes = len(duplicate_hashes)

        for i, (hash_value, count) in enumerate(duplicate_hashes):
            if self._cancelled:
                break

            if progress_callback:
                progress_callback(
                    f"Processing hash {i+1}/{total_hashes}",
                    i, total_hashes
                )

            # Get all files with this hash
            files = db.find_files_by_hash(hash_type, hash_value)

            if len(files) < 2:
                continue

            # Convert DB records to ImageFile objects for compatibility
            image_list = []
            for f in files:
                # Get the volume info to construct full path
                vol = db.get_volume_by_id(f['volume_id'])
                if not vol:
                    continue

                mount_point = vol.get('mount_point', '')
                full_path = Path(mount_point) / f['relative_path']

                # Create ImageFile for compatibility with existing UI
                img = ImageFile(
                    path=full_path,
                    file_size=f['file_size_bytes'],
                    width=f.get('width') or 0,
                    height=f.get('height') or 0,
                )
                # Store DB info for reference
                img.db_file_id = f['id']
                img.db_volume_id = f['volume_id']
                img.volume_name = vol.get('name', 'Unknown')
                image_list.append(img)

            if len(image_list) < 2:
                continue

            # Create similarity scores (all 1.0 for exact matches)
            group_scores = {}
            paths = [str(img.path) for img in image_list]
            for j, p1 in enumerate(paths):
                for p2 in paths[j+1:]:
                    key = tuple(sorted([p1, p2]))
                    group_scores[key] = 1.0

            group = DuplicateGroup(
                group_id=group_id,
                images=image_list,
                similarity_scores=group_scores
            )
            all_groups.append(group)
            group_id += 1

        if progress_callback:
            progress_callback("Complete", total_hashes, total_hashes)

        return all_groups

    def find_cross_volume_duplicates(
        self,
        volume_ids: List[int],
        hash_type: str = "exact_md5",
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[DuplicateGroup]:
        """Find duplicates that exist across multiple volumes.

        This specifically finds files that have copies on different drives,
        useful for consolidating backups or finding redundant copies.

        Args:
            volume_ids: List of volume IDs to search across
            hash_type: Type of hash to use for matching
            progress_callback: Optional callback(status, current, total)

        Returns:
            List of DuplicateGroup objects where files span multiple volumes
        """
        from .database import DatabaseManager

        db = DatabaseManager.get_instance()
        self._cancelled = False

        if progress_callback:
            progress_callback("Finding cross-drive duplicates...", 0, 0)

        # Find all duplicates across the specified volumes
        duplicate_hashes = db.find_duplicate_hashes(hash_type, volume_ids)

        if not duplicate_hashes:
            return []

        all_groups: List[DuplicateGroup] = []
        group_id = 0
        total_hashes = len(duplicate_hashes)

        for i, (hash_value, count) in enumerate(duplicate_hashes):
            if self._cancelled:
                break

            if progress_callback:
                progress_callback(
                    f"Processing hash {i+1}/{total_hashes}",
                    i, total_hashes
                )

            # Get all files with this hash
            files = db.find_files_by_hash(hash_type, hash_value)

            if len(files) < 2:
                continue

            # Check if files span multiple volumes
            volume_set = set(f['volume_id'] for f in files)
            if len(volume_set) < 2:
                # All files on same volume - not a cross-volume duplicate
                continue

            # Convert DB records to ImageFile objects
            image_list = []
            for f in files:
                vol = db.get_volume_by_id(f['volume_id'])
                if not vol:
                    continue

                mount_point = vol.get('mount_point', '')
                full_path = Path(mount_point) / f['relative_path']

                img = ImageFile(
                    path=full_path,
                    file_size=f['file_size_bytes'],
                    width=f.get('width') or 0,
                    height=f.get('height') or 0,
                )
                img.db_file_id = f['id']
                img.db_volume_id = f['volume_id']
                img.volume_name = vol.get('name', 'Unknown')
                image_list.append(img)

            if len(image_list) < 2:
                continue

            # Create similarity scores
            group_scores = {}
            paths = [str(img.path) for img in image_list]
            for j, p1 in enumerate(paths):
                for p2 in paths[j+1:]:
                    key = tuple(sorted([p1, p2]))
                    group_scores[key] = 1.0

            group = DuplicateGroup(
                group_id=group_id,
                images=image_list,
                similarity_scores=group_scores
            )
            group.is_cross_volume = True
            all_groups.append(group)
            group_id += 1

        if progress_callback:
            progress_callback("Complete", total_hashes, total_hashes)

        return all_groups
