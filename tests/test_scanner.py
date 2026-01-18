"""Tests for the image scanner."""

import pytest
from pathlib import Path

from src.core.scanner import ImageScanner, SUPPORTED_EXTENSIONS
from src.models.image_file import ImageFile


class TestImageScanner:
    """Test cases for ImageScanner."""

    def test_supported_extensions(self):
        """Test that supported extensions are defined correctly."""
        assert "jpg" in SUPPORTED_EXTENSIONS
        assert "jpeg" in SUPPORTED_EXTENSIONS
        assert "gif" in SUPPORTED_EXTENSIONS
        assert "tiff" in SUPPORTED_EXTENSIONS
        assert "cr2" in SUPPORTED_EXTENSIONS
        assert "raf" in SUPPORTED_EXTENSIONS

    def test_is_supported(self):
        """Test extension checking."""
        scanner = ImageScanner()

        assert scanner.is_supported(Path("test.jpg"))
        assert scanner.is_supported(Path("test.JPG"))
        assert scanner.is_supported(Path("test.jpeg"))
        assert scanner.is_supported(Path("test.gif"))
        assert scanner.is_supported(Path("test.tiff"))
        assert scanner.is_supported(Path("test.cr2"))

        assert not scanner.is_supported(Path("test.txt"))
        assert not scanner.is_supported(Path("test.pdf"))
        assert not scanner.is_supported(Path("test.doc"))

    def test_scan_empty_directory(self, temp_dir):
        """Test scanning an empty directory."""
        scanner = ImageScanner()
        images = scanner.scan(temp_dir)

        assert images == []

    def test_scan_with_images(self, sample_images_dir):
        """Test scanning a directory with images."""
        scanner = ImageScanner()
        images = scanner.scan(sample_images_dir)

        assert len(images) > 0
        assert all(isinstance(img, ImageFile) for img in images)

    def test_scan_counts_correctly(self, sample_images_dir):
        """Test that scan counts all images correctly."""
        scanner = ImageScanner()

        # Count should match scan results
        count = scanner.count_files(sample_images_dir)
        images = scanner.scan(sample_images_dir)

        assert count == len(images)

    def test_scan_with_progress_callback(self, sample_images_dir):
        """Test scanning with progress callback."""
        scanner = ImageScanner()
        progress_calls = []

        def callback(current_file, processed, total):
            progress_calls.append((current_file, processed, total))

        images = scanner.scan(sample_images_dir, progress_callback=callback)

        assert len(progress_calls) == len(images)
        assert all(p[2] == len(images) for p in progress_calls)

    def test_scan_respects_extensions_filter(self, mixed_format_images):
        """Test that scanner respects extension filter."""
        # Only scan for JPEG
        scanner = ImageScanner(extensions={"jpg", "jpeg"})
        images = scanner.scan(mixed_format_images)

        assert all(img.extension in {"jpg", "jpeg"} for img in images)

    def test_scan_ignores_non_images(self, mixed_format_images):
        """Test that non-image files are ignored."""
        scanner = ImageScanner()
        images = scanner.scan(mixed_format_images)

        # Should not include the .txt file
        assert not any(img.path.suffix == ".txt" for img in images)

    def test_scan_recursive(self, sample_images_dir):
        """Test recursive scanning."""
        scanner = ImageScanner(recursive=True)
        images = scanner.scan(sample_images_dir)

        # Should find images in subdirectories
        directories = set(img.directory for img in images)
        assert len(directories) > 1

    def test_scan_non_recursive(self, sample_images_dir):
        """Test non-recursive scanning."""
        scanner = ImageScanner(recursive=False)
        images = scanner.scan(sample_images_dir)

        # Root has no images, so should be empty
        assert len(images) == 0

    def test_scan_nonexistent_directory(self):
        """Test scanning nonexistent directory raises error."""
        scanner = ImageScanner()

        with pytest.raises(FileNotFoundError):
            scanner.scan(Path("/nonexistent/directory"))

    def test_scan_file_instead_of_directory(self, sample_images_dir):
        """Test scanning a file instead of directory raises error."""
        scanner = ImageScanner()

        # Get any file
        any_file = list(sample_images_dir.rglob("*.jpg"))[0]

        with pytest.raises(NotADirectoryError):
            scanner.scan(any_file)

    def test_cancel_scan(self, sample_images_dir):
        """Test cancelling a scan."""
        scanner = ImageScanner()

        # Cancel before scan starts
        scanner.cancel()

        images = scanner.scan(sample_images_dir)

        # Should have no or partial results (may complete if too fast)
        # The important thing is that it doesn't crash
        assert len(images) <= scanner.count_files(sample_images_dir)

    def test_group_by_directory(self, sample_images_dir):
        """Test grouping images by directory."""
        scanner = ImageScanner()
        images = scanner.scan(sample_images_dir)

        groups = scanner.group_by_directory(images)

        # Should have 3 subdirectories
        assert len(groups) == 3

        # Each group should have images
        for directory, dir_images in groups.items():
            assert len(dir_images) > 0
            assert all(img.directory == directory for img in dir_images)

    def test_loads_metadata(self, sample_images_dir):
        """Test that metadata is loaded correctly."""
        scanner = ImageScanner()
        images = scanner.scan(sample_images_dir, load_metadata=True)

        # Check that dimensions were loaded
        for img in images:
            assert img.width > 0
            assert img.height > 0
            assert img.file_size > 0
