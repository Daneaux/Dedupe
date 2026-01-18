"""Tests for file operations."""

import pytest
from pathlib import Path
from PIL import Image

from src.core.file_operations import FileOperations
from src.models.image_file import ImageFile


class TestFileOperations:
    """Test cases for FileOperations."""

    @pytest.fixture
    def sample_files(self, temp_dir):
        """Create sample files for testing."""
        # Create some test images
        subdir = temp_dir / "photos"
        subdir.mkdir()

        files = []
        for i in range(3):
            path = subdir / f"image_{i}.jpg"
            img = Image.new("RGB", (100, 100), color=(i * 50, i * 50, i * 50))
            img.save(path)
            files.append(ImageFile(path=path, file_size=path.stat().st_size))

        return temp_dir, files

    def test_move_to_parallel_structure(self, sample_files):
        """Test moving files to parallel directory structure."""
        root_dir, files = sample_files
        ops = FileOperations()

        results = ops.move_to_parallel_structure(files, root_dir)

        # Check all moves succeeded
        assert all(success for _, _, success, _ in results)

        # Check files exist in new location
        duplicates_dir = root_dir / "_duplicates"
        assert duplicates_dir.exists()

        for img, new_path, success, _ in results:
            assert new_path.exists()
            assert not img.path.exists()  # Original removed

    def test_move_creates_parallel_structure(self, sample_files):
        """Test that parallel structure preserves directory layout."""
        root_dir, files = sample_files
        ops = FileOperations()

        results = ops.move_to_parallel_structure(files, root_dir)

        # Check structure is preserved
        duplicates_dir = root_dir / "_duplicates"
        photos_dup = duplicates_dir / "photos"

        assert photos_dup.exists()
        assert len(list(photos_dup.iterdir())) == 3

    def test_move_handles_name_conflicts(self, sample_files):
        """Test moving handles name conflicts."""
        root_dir, files = sample_files
        ops = FileOperations()

        # Move once
        ops.move_to_parallel_structure(files[:1], root_dir)

        # Create a new file with same name
        new_file = files[0].path.parent / files[0].filename
        img = Image.new("RGB", (100, 100), color=(100, 100, 100))
        img.save(new_file)
        new_img = ImageFile(path=new_file, file_size=new_file.stat().st_size)

        # Move again - should create renamed file
        results = ops.move_to_parallel_structure([new_img], root_dir)

        assert all(success for _, _, success, _ in results)

    def test_delete_files(self, sample_files):
        """Test deleting files."""
        root_dir, files = sample_files
        ops = FileOperations()

        results = ops.delete_files(files)

        # Check all deletes succeeded
        assert all(success for _, success, _ in results)

        # Check files are gone
        for img in files:
            assert not img.path.exists()

    def test_delete_nonexistent_file(self, temp_dir):
        """Test deleting a file that doesn't exist."""
        img = ImageFile(path=temp_dir / "nonexistent.jpg")
        ops = FileOperations()

        results = ops.delete_files([img])

        # Should fail gracefully
        assert len(results) == 1
        assert not results[0][1]  # success = False
        assert results[0][2] is not None  # error message

    def test_preview_move(self, sample_files):
        """Test previewing file moves."""
        root_dir, files = sample_files
        ops = FileOperations()

        preview = ops.preview_move(files, root_dir)

        assert len(preview) == len(files)
        for source, dest in preview:
            assert "_duplicates" in str(dest)
            assert source.name == dest.name

    def test_validate_paths(self, sample_files):
        """Test validating file paths."""
        root_dir, files = sample_files
        ops = FileOperations()

        # Add a nonexistent file
        fake = ImageFile(path=root_dir / "fake.jpg")
        all_files = files + [fake]

        valid, invalid = ops.validate_paths(all_files)

        assert len(valid) == 3
        assert len(invalid) == 1
        assert invalid[0][0] == fake

    def test_progress_callback(self, sample_files):
        """Test that progress callback is called."""
        root_dir, files = sample_files
        ops = FileOperations()

        progress_calls = []

        def callback(filename, current, total):
            progress_calls.append((filename, current, total))

        ops.delete_files(files, progress_callback=callback)

        assert len(progress_calls) == len(files)
        assert all(p[2] == len(files) for p in progress_calls)

    def test_custom_duplicate_folder_name(self, sample_files):
        """Test using custom duplicate folder name."""
        root_dir, files = sample_files
        ops = FileOperations(duplicate_folder_name="_backup")

        ops.move_to_parallel_structure(files, root_dir)

        backup_dir = root_dir / "_backup"
        assert backup_dir.exists()
