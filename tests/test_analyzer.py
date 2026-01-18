"""Tests for the image analyzer."""

import pytest
from pathlib import Path

from src.core.analyzer import ImageAnalyzer
from src.models.image_file import ImageFile
from src.models.duplicate_group import DuplicateGroup


class TestImageAnalyzer:
    """Test cases for ImageAnalyzer."""

    @pytest.fixture
    def sample_group(self, temp_dir):
        """Create a sample duplicate group for testing."""
        # Create test images with different properties
        img1 = ImageFile(
            path=temp_dir / "high_res.jpg",
            file_size=5000000,  # 5 MB
            width=4000,
            height=3000
        )

        img2 = ImageFile(
            path=temp_dir / "subdir/medium_res.jpg",
            file_size=2000000,  # 2 MB
            width=2000,
            height=1500
        )

        img3 = ImageFile(
            path=temp_dir / "subdir/deep/low_res.jpg",
            file_size=500000,  # 500 KB
            width=800,
            height=600
        )

        group = DuplicateGroup(
            group_id=1,
            images=[img1, img2, img3]
        )

        return group

    def test_analyze_groups(self, sample_group):
        """Test analyzing duplicate groups."""
        analyzer = ImageAnalyzer()
        result = analyzer.analyze_groups([sample_group])

        assert result["total_groups"] == 1
        assert result["total_files"] == 3
        assert result["total_duplicate_files"] == 2
        assert result["potential_savings"] > 0

    def test_rank_images_by_resolution(self, sample_group):
        """Test that images are ranked by resolution."""
        analyzer = ImageAnalyzer(
            prefer_resolution=True,
            prefer_size=False,
            prefer_shorter_path=False
        )

        ranked = analyzer.rank_images(sample_group)

        # Highest resolution should be first
        assert ranked[0][0].resolution > ranked[1][0].resolution
        assert ranked[1][0].resolution > ranked[2][0].resolution

    def test_rank_images_by_size(self, temp_dir):
        """Test that images are ranked by file size."""
        # Create images with same resolution but different sizes
        img1 = ImageFile(
            path=temp_dir / "large.jpg",
            file_size=5000000,
            width=1000,
            height=1000
        )

        img2 = ImageFile(
            path=temp_dir / "small.jpg",
            file_size=1000000,
            width=1000,
            height=1000
        )

        group = DuplicateGroup(group_id=1, images=[img1, img2])

        analyzer = ImageAnalyzer(
            prefer_resolution=False,
            prefer_size=True,
            prefer_shorter_path=False
        )

        ranked = analyzer.rank_images(group)

        # Larger file should be first
        assert ranked[0][0].file_size > ranked[1][0].file_size

    def test_rank_images_by_path_depth(self, temp_dir):
        """Test that images are ranked by path depth."""
        # Create images with same size/resolution but different paths
        img1 = ImageFile(
            path=temp_dir / "a" / "b" / "c" / "deep.jpg",
            file_size=1000000,
            width=1000,
            height=1000
        )

        img2 = ImageFile(
            path=temp_dir / "shallow.jpg",
            file_size=1000000,
            width=1000,
            height=1000
        )

        group = DuplicateGroup(group_id=1, images=[img1, img2])

        analyzer = ImageAnalyzer(
            prefer_resolution=False,
            prefer_size=False,
            prefer_shorter_path=True
        )

        ranked = analyzer.rank_images(group)

        # Shallower path should be first
        assert ranked[0][0].path_depth < ranked[1][0].path_depth

    def test_get_recommendation(self, sample_group):
        """Test getting recommendation for a group."""
        analyzer = ImageAnalyzer()
        rec = analyzer.get_recommendation(sample_group)

        assert rec["keep"] is not None
        assert len(rec["delete"]) == 2
        assert rec["savings"] > 0
        assert len(rec["reasons"]) > 0

    def test_recommended_keep_is_best(self, sample_group):
        """Test that recommended keep is the best image."""
        analyzer = ImageAnalyzer()
        rec = analyzer.get_recommendation(sample_group)

        # The keep image should be the high_res one (best resolution)
        assert rec["keep"].width == 4000
        assert rec["keep"].height == 3000

    def test_compare_images(self, temp_dir):
        """Test comparing two images."""
        img1 = ImageFile(
            path=temp_dir / "img1.jpg",
            file_size=2000000,
            width=2000,
            height=1500
        )

        img2 = ImageFile(
            path=temp_dir / "img2.jpg",
            file_size=1000000,
            width=1000,
            height=750
        )

        analyzer = ImageAnalyzer()
        comparison = analyzer.compare_images(img1, img2)

        assert "img1" in comparison
        assert "img2" in comparison
        assert len(comparison["differences"]) > 0

    def test_empty_group(self):
        """Test analyzing an empty group."""
        group = DuplicateGroup(group_id=1, images=[])

        analyzer = ImageAnalyzer()
        ranked = analyzer.rank_images(group)

        assert ranked == []

    def test_single_image_group(self, temp_dir):
        """Test analyzing a group with only one image."""
        img = ImageFile(
            path=temp_dir / "only.jpg",
            file_size=1000000,
            width=1000,
            height=1000
        )

        group = DuplicateGroup(group_id=1, images=[img])

        analyzer = ImageAnalyzer()
        ranked = analyzer.rank_images(group)

        assert len(ranked) == 1
        assert ranked[0][0] == img
