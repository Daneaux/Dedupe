"""Duplicate group model representing a set of similar images."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from .image_file import ImageFile


@dataclass
class DuplicateGroup:
    """Represents a group of duplicate/similar images."""

    group_id: int
    images: List[ImageFile] = field(default_factory=list)
    similarity_scores: Dict[Tuple[str, str], float] = field(default_factory=dict)
    suggested_keep: Optional[ImageFile] = None
    is_intra_directory: bool = True

    def __post_init__(self):
        """Initialize the group and determine suggested keep."""
        if self.images and not self.suggested_keep:
            self._determine_suggested_keep()
        self._check_intra_directory()

    def add_image(self, image: ImageFile, similarity_to_existing: Optional[Dict[str, float]] = None):
        """Add an image to the group with optional similarity scores."""
        if image not in self.images:
            self.images.append(image)

            if similarity_to_existing:
                for existing_path, score in similarity_to_existing.items():
                    key = tuple(sorted([str(image.path), existing_path]))
                    self.similarity_scores[key] = score

            self._determine_suggested_keep()
            self._check_intra_directory()

    def _determine_suggested_keep(self):
        """
        Determine which image should be kept based on priority:
        1. Larger file size (primary - always keep the larger file)
        2. Higher resolution as tiebreaker
        """
        if not self.images:
            self.suggested_keep = None
            return

        # Sort by file size (largest first), then resolution as tiebreaker
        sorted_images = sorted(
            self.images,
            key=lambda img: (
                -img.file_size,    # Larger file size is better (primary)
                -img.resolution,   # Higher resolution as tiebreaker
            )
        )

        self.suggested_keep = sorted_images[0] if sorted_images else None

    def _check_intra_directory(self):
        """Check if all images are in the same directory."""
        if len(self.images) <= 1:
            self.is_intra_directory = True
            return

        directories = set(img.directory for img in self.images)
        self.is_intra_directory = len(directories) == 1

    @property
    def directory(self) -> Optional[Path]:
        """Get the common directory if intra-directory, else None."""
        if self.is_intra_directory and self.images:
            return self.images[0].directory
        return None

    @property
    def suggested_delete(self) -> List[ImageFile]:
        """Get list of images suggested for deletion."""
        if not self.suggested_keep:
            return []
        return [img for img in self.images if img != self.suggested_keep]

    @property
    def file_count(self) -> int:
        """Get the number of images in the group."""
        return len(self.images)

    @property
    def total_size(self) -> int:
        """Get total size of all images in the group."""
        return sum(img.file_size for img in self.images)

    @property
    def potential_savings(self) -> int:
        """Get potential space savings if duplicates are removed."""
        return sum(img.file_size for img in self.suggested_delete)

    @property
    def potential_savings_str(self) -> str:
        """Get human-readable potential savings."""
        size = self.potential_savings
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def get_similarity(self, img1: ImageFile, img2: ImageFile) -> Optional[float]:
        """Get similarity score between two images."""
        key = tuple(sorted([str(img1.path), str(img2.path)]))
        return self.similarity_scores.get(key)

    def get_average_similarity(self) -> float:
        """Get average similarity score for the group."""
        if not self.similarity_scores:
            return 1.0  # Assume exact match if no scores
        return sum(self.similarity_scores.values()) / len(self.similarity_scores)

    def __len__(self):
        return len(self.images)

    def __iter__(self):
        return iter(self.images)

    def __repr__(self):
        return f"DuplicateGroup(id={self.group_id}, files={self.file_count}, intra={self.is_intra_directory})"
