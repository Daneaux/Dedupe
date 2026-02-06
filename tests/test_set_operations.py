"""Tests for Set Operations with different hash types."""

import pytest
import hashlib
from pathlib import Path
from datetime import datetime

from PIL import Image, ImageDraw
import imagehash

from src.core.database import DatabaseManager


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test_setops.db"
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_path)
    DatabaseManager._instance = db
    yield db
    DatabaseManager.reset_instance()


@pytest.fixture
def two_volumes_with_all_hash_types(test_db, tmp_path):
    """
    Create two volumes with files having all three hash types.

    Setup:
    - Volume A: photo1.jpg (shared), unique_a.jpg (only in A)
    - Volume B: photo1_copy.jpg (exact copy), photo1_compressed.jpg (visually similar),
                unique_b.jpg (only in B)
    """
    vol_a_path = tmp_path / "volume_a"
    vol_b_path = tmp_path / "volume_b"
    vol_a_path.mkdir()
    vol_b_path.mkdir()

    vol_a_id = test_db.add_volume("uuid-vol-a", "Volume A", str(vol_a_path), 1000000000, "apfs")
    vol_b_id = test_db.add_volume("uuid-vol-b", "Volume B", str(vol_b_path), 1000000000, "apfs")

    now = datetime.now().isoformat()

    # Create test image with distinctive features
    img1 = Image.new("RGB", (200, 200), color=(255, 255, 255))
    draw1 = ImageDraw.Draw(img1)
    draw1.rectangle([20, 20, 80, 80], fill=(255, 0, 0))
    draw1.ellipse([100, 20, 180, 100], fill=(0, 255, 0))

    # Create unique images for each volume
    img_unique_a = Image.new("RGB", (200, 200), color=(0, 0, 128))
    ImageDraw.Draw(img_unique_a).polygon([(100, 10), (10, 190), (190, 190)], fill=(255, 255, 0))

    img_unique_b = Image.new("RGB", (200, 200), color=(128, 0, 0))
    ImageDraw.Draw(img_unique_b).ellipse([20, 20, 180, 180], fill=(0, 255, 255))

    # Save images
    img1.save(vol_a_path / "photo1.jpg", "JPEG", quality=95)
    img1.save(vol_b_path / "photo1_copy.jpg", "JPEG", quality=95)  # Exact copy
    img1.save(vol_b_path / "photo1_compressed.jpg", "JPEG", quality=20)  # Compressed
    img_unique_a.save(vol_a_path / "unique_a.jpg", "JPEG", quality=95)
    img_unique_b.save(vol_b_path / "unique_b.jpg", "JPEG", quality=95)

    # Helper functions for hash computation
    def get_exact_md5(file_path):
        return hashlib.md5(file_path.read_bytes()).hexdigest()

    def get_pixel_md5(file_path):
        with Image.open(file_path) as img:
            return hashlib.md5(img.convert('RGB').tobytes()).hexdigest()

    def get_phash(file_path):
        with Image.open(file_path) as img:
            return str(imagehash.phash(img))

    # Add all files with all hash types
    for vol_id, vol_path, files in [
        (vol_a_id, vol_a_path, ["photo1.jpg", "unique_a.jpg"]),
        (vol_b_id, vol_b_path, ["photo1_copy.jpg", "photo1_compressed.jpg", "unique_b.jpg"])
    ]:
        for filename in files:
            file_path = vol_path / filename
            file_id = test_db.add_file(
                volume_id=vol_id, relative_path=filename, filename=filename,
                extension="jpg", file_size_bytes=file_path.stat().st_size,
                file_type="image", file_created_at=now, file_modified_at=now,
                width=200, height=200
            )
            test_db.add_hash(file_id, "exact_md5", get_exact_md5(file_path))
            test_db.add_hash(file_id, "pixel_md5", get_pixel_md5(file_path))
            test_db.add_hash(file_id, "perceptual_phash", get_phash(file_path))

    test_db.update_volume_scan_status(vol_a_id, status='complete', file_count=2)
    test_db.update_volume_scan_status(vol_b_id, status='complete', file_count=3)

    return {'db': test_db, 'vol_a_id': vol_a_id, 'vol_b_id': vol_b_id}


class TestSetOperationsDifference:
    """Test set difference (B - A) with different hash types."""

    def test_difference_exact_md5(self, two_volumes_with_all_hash_types):
        """exact_md5: only byte-identical files are excluded from difference."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        diff = db.get_set_difference(setup['vol_b_id'], setup['vol_a_id'], "exact_md5")
        filenames = [r['filename'] for r in diff]

        # photo1_copy.jpg - same bytes as A's photo1.jpg, excluded
        # photo1_compressed.jpg - different bytes, included
        # unique_b.jpg - no match in A, included
        assert "photo1_copy.jpg" not in filenames
        assert "photo1_compressed.jpg" in filenames
        assert "unique_b.jpg" in filenames
        assert len(diff) == 2

    def test_difference_pixel_md5(self, two_volumes_with_all_hash_types):
        """pixel_md5: files with same decoded pixels are excluded."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        diff = db.get_set_difference(setup['vol_b_id'], setup['vol_a_id'], "pixel_md5")
        filenames = [r['filename'] for r in diff]

        assert "photo1_copy.jpg" not in filenames  # Same pixels
        assert "unique_b.jpg" in filenames  # Different image

    def test_difference_perceptual_phash(self, two_volumes_with_all_hash_types):
        """perceptual_phash: visually similar images are excluded."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        diff = db.get_set_difference(setup['vol_b_id'], setup['vol_a_id'], "perceptual_phash")
        filenames = [r['filename'] for r in diff]

        # Both photo1_copy and photo1_compressed are visually similar to photo1
        assert "photo1_copy.jpg" not in filenames
        assert "photo1_compressed.jpg" not in filenames
        assert "unique_b.jpg" in filenames
        assert len(diff) == 1


class TestSetOperationsIntersection:
    """Test set intersection (A ∩ B) with different hash types."""

    def test_intersection_exact_md5(self, two_volumes_with_all_hash_types):
        """exact_md5: only byte-identical files appear in intersection."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        intersect = db.get_set_intersection(setup['vol_a_id'], setup['vol_b_id'], "exact_md5")

        # Only photo1.jpg <-> photo1_copy.jpg (same bytes)
        assert len(intersect) == 1
        assert intersect[0]['filename_a'] == "photo1.jpg"
        assert intersect[0]['filename_b'] == "photo1_copy.jpg"

    def test_intersection_pixel_md5(self, two_volumes_with_all_hash_types):
        """pixel_md5: files with same decoded pixels appear in intersection."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        intersect = db.get_set_intersection(setup['vol_a_id'], setup['vol_b_id'], "pixel_md5")
        filenames_b = [r['filename_b'] for r in intersect]

        assert "photo1_copy.jpg" in filenames_b
        assert "unique_b.jpg" not in filenames_b

    def test_intersection_perceptual_phash(self, two_volumes_with_all_hash_types):
        """perceptual_phash: visually similar images appear in intersection."""
        setup = two_volumes_with_all_hash_types
        db = setup['db']

        intersect = db.get_set_intersection(setup['vol_a_id'], setup['vol_b_id'], "perceptual_phash")
        filenames_b = [r['filename_b'] for r in intersect]

        # Both copies match photo1.jpg visually
        assert "photo1_copy.jpg" in filenames_b
        assert "photo1_compressed.jpg" in filenames_b
        assert "unique_b.jpg" not in filenames_b
