"""Analyzer for determining which images to keep or delete."""

from typing import List, Dict, Tuple, Optional
from pathlib import Path

from ..models.image_file import ImageFile
from ..models.duplicate_group import DuplicateGroup


class ImageAnalyzer:
    """Analyzes duplicate groups and provides recommendations."""

    def __init__(
        self,
        prefer_resolution: bool = True,
        prefer_size: bool = True,
        prefer_shorter_path: bool = True
    ):
        """
        Initialize the analyzer with preference settings.

        Args:
            prefer_resolution: Prefer higher resolution images.
            prefer_size: Prefer larger file sizes.
            prefer_shorter_path: Prefer files with shorter paths.
        """
        self.prefer_resolution = prefer_resolution
        self.prefer_size = prefer_size
        self.prefer_shorter_path = prefer_shorter_path

    def analyze_groups(self, groups: List[DuplicateGroup]) -> Dict[str, any]:
        """
        Analyze all duplicate groups and return summary statistics.

        Args:
            groups: List of DuplicateGroup objects.

        Returns:
            Dictionary with analysis results.
        """
        total_files = sum(len(g) for g in groups)
        total_duplicate_files = sum(len(g.suggested_delete) for g in groups)
        total_size = sum(g.total_size for g in groups)
        potential_savings = sum(g.potential_savings for g in groups)

        intra_directory_groups = [g for g in groups if g.is_intra_directory]
        cross_directory_groups = [g for g in groups if not g.is_intra_directory]

        return {
            "total_groups": len(groups),
            "total_files": total_files,
            "total_duplicate_files": total_duplicate_files,
            "total_size": total_size,
            "potential_savings": potential_savings,
            "potential_savings_str": self._format_size(potential_savings),
            "intra_directory_groups": len(intra_directory_groups),
            "cross_directory_groups": len(cross_directory_groups),
            "groups": groups
        }

    def rank_images(self, group: DuplicateGroup) -> List[Tuple[ImageFile, float]]:
        """
        Rank images in a group by quality/preference score.

        Higher score = better candidate to keep.

        Args:
            group: DuplicateGroup to rank.

        Returns:
            List of (ImageFile, score) tuples, sorted by score descending.
        """
        if not group.images:
            return []

        # Normalize values for scoring
        max_resolution = max((img.resolution for img in group.images), default=1)
        max_size = max((img.file_size for img in group.images), default=1)
        max_path_depth = max((img.path_depth for img in group.images), default=1)

        scored: List[Tuple[ImageFile, float]] = []

        for img in group.images:
            score = 0.0

            # Resolution score (0-40 points)
            if self.prefer_resolution and max_resolution > 0:
                score += (img.resolution / max_resolution) * 40

            # File size score (0-35 points)
            if self.prefer_size and max_size > 0:
                score += (img.file_size / max_size) * 35

            # Path depth score (0-15 points, shorter is better)
            if self.prefer_shorter_path and max_path_depth > 0:
                depth_ratio = img.path_depth / max_path_depth
                score += (1 - depth_ratio) * 15

            # Filename length as tiebreaker (0-10 points, shorter is better)
            max_name_len = max((len(i.filename) for i in group.images), default=1)
            if max_name_len > 0:
                name_ratio = len(img.filename) / max_name_len
                score += (1 - name_ratio) * 10

            scored.append((img, score))

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])
        return scored

    def get_recommendation(
        self,
        group: DuplicateGroup
    ) -> Dict[str, any]:
        """
        Get detailed recommendation for a duplicate group.

        Args:
            group: DuplicateGroup to analyze.

        Returns:
            Dictionary with recommendation details.
        """
        ranked = self.rank_images(group)

        if not ranked:
            return {"keep": None, "delete": [], "reasons": []}

        keep_image, keep_score = ranked[0]
        delete_images = [(img, score) for img, score in ranked[1:]]

        # Generate reasons for the recommendation
        reasons = []

        if len(ranked) > 1:
            runner_up, runner_up_score = ranked[1]

            if keep_image.resolution > runner_up.resolution:
                reasons.append(
                    f"Higher resolution: {keep_image.dimensions_str} vs {runner_up.dimensions_str}"
                )

            if keep_image.file_size > runner_up.file_size:
                reasons.append(
                    f"Larger file: {keep_image.file_size_str} vs {runner_up.file_size_str}"
                )

            if keep_image.path_depth < runner_up.path_depth:
                reasons.append(
                    f"Shorter path: depth {keep_image.path_depth} vs {runner_up.path_depth}"
                )

        return {
            "keep": keep_image,
            "keep_score": keep_score,
            "delete": delete_images,
            "reasons": reasons,
            "savings": sum(img.file_size for img, _ in delete_images),
            "savings_str": self._format_size(
                sum(img.file_size for img, _ in delete_images)
            )
        }

    def compare_images(
        self,
        img1: ImageFile,
        img2: ImageFile
    ) -> Dict[str, any]:
        """
        Compare two images and return detailed comparison.

        Args:
            img1: First image.
            img2: Second image.

        Returns:
            Dictionary with comparison details.
        """
        comparison = {
            "img1": {
                "path": str(img1.path),
                "filename": img1.filename,
                "size": img1.file_size,
                "size_str": img1.file_size_str,
                "resolution": img1.resolution,
                "dimensions": img1.dimensions_str,
                "path_depth": img1.path_depth
            },
            "img2": {
                "path": str(img2.path),
                "filename": img2.filename,
                "size": img2.file_size,
                "size_str": img2.file_size_str,
                "resolution": img2.resolution,
                "dimensions": img2.dimensions_str,
                "path_depth": img2.path_depth
            },
            "differences": []
        }

        # Resolution comparison
        if img1.resolution != img2.resolution:
            if img1.resolution > img2.resolution:
                comparison["differences"].append(
                    f"Image 1 has higher resolution ({img1.dimensions_str} vs {img2.dimensions_str})"
                )
            else:
                comparison["differences"].append(
                    f"Image 2 has higher resolution ({img2.dimensions_str} vs {img1.dimensions_str})"
                )

        # Size comparison
        if img1.file_size != img2.file_size:
            if img1.file_size > img2.file_size:
                comparison["differences"].append(
                    f"Image 1 is larger ({img1.file_size_str} vs {img2.file_size_str})"
                )
            else:
                comparison["differences"].append(
                    f"Image 2 is larger ({img2.file_size_str} vs {img1.file_size_str})"
                )

        # Path depth comparison
        if img1.path_depth != img2.path_depth:
            if img1.path_depth < img2.path_depth:
                comparison["differences"].append(
                    f"Image 1 has shorter path (depth {img1.path_depth} vs {img2.path_depth})"
                )
            else:
                comparison["differences"].append(
                    f"Image 2 has shorter path (depth {img2.path_depth} vs {img1.path_depth})"
                )

        return comparison

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
