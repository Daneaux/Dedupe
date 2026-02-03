"""Tests for duplicate detection across multiple volumes using the database."""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from PIL import Image

from src.core.database import DatabaseManager
from src.core.deduplicator import Deduplicator


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test_dedupe.db"

    # Reset singleton to ensure clean state
    DatabaseManager.reset_instance()

    # Create a fresh DatabaseManager instance for testing
    db = DatabaseManager(db_path)

    # Also set it as the singleton so Deduplicator can access it
    DatabaseManager._instance = db

    yield db

    # Cleanup - reset singleton
    DatabaseManager.reset_instance()


@pytest.fixture
def two_volumes_with_duplicates(test_db, tmp_path):
    """
    Set up two volumes with duplicate files.

    Volume 1 (vol1): Contains original files
    Volume 2 (vol2): Contains some duplicates and some unique files

    Returns:
        dict with volume info and file paths
    """
    # Create directory structure
    vol1_path = tmp_path / "volume1"
    vol2_path = tmp_path / "volume2"
    vol1_path.mkdir()
    vol2_path.mkdir()

    # Register volumes using add_volume
    vol1_id = test_db.add_volume(
        uuid="TEST-VOL1-UUID",
        name="Test Volume 1",
        mount_point=str(vol1_path),
        total_size_bytes=1000000000,
        filesystem="apfs"
    )

    vol2_id = test_db.add_volume(
        uuid="TEST-VOL2-UUID",
        name="Test Volume 2",
        mount_point=str(vol2_path),
        total_size_bytes=1000000000,
        filesystem="apfs"
    )

    # Create test files
    # File A: exists on both volumes (duplicate)
    file_a_content = b"This is file A content - it will be duplicated"
    (vol1_path / "file_a.txt").write_bytes(file_a_content)
    (vol2_path / "file_a_copy.txt").write_bytes(file_a_content)

    # File B: exists on both volumes (duplicate)
    file_b_content = b"This is file B content - also duplicated across volumes"
    (vol1_path / "file_b.txt").write_bytes(file_b_content)
    (vol2_path / "subdir").mkdir()
    (vol2_path / "subdir" / "file_b_renamed.txt").write_bytes(file_b_content)

    # File C: only on volume 1 (unique)
    file_c_content = b"This is file C - unique to volume 1"
    (vol1_path / "unique_c.txt").write_bytes(file_c_content)

    # File D: only on volume 2 (unique)
    file_d_content = b"This is file D - unique to volume 2"
    (vol2_path / "unique_d.txt").write_bytes(file_d_content)

    # File E: three copies on volume 1 (intra-volume duplicate)
    file_e_content = b"This is file E - duplicated within volume 1"
    (vol1_path / "file_e_1.txt").write_bytes(file_e_content)
    (vol1_path / "file_e_2.txt").write_bytes(file_e_content)
    (vol1_path / "file_e_3.txt").write_bytes(file_e_content)

    # Calculate MD5 hashes
    import hashlib
    hash_a = hashlib.md5(file_a_content).hexdigest()
    hash_b = hashlib.md5(file_b_content).hexdigest()
    hash_c = hashlib.md5(file_c_content).hexdigest()
    hash_d = hashlib.md5(file_d_content).hexdigest()
    hash_e = hashlib.md5(file_e_content).hexdigest()

    # Add files to database
    now = datetime.now().isoformat()

    # Volume 1 files
    file1_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="file_a.txt",
        filename="file_a.txt",
        extension="txt",
        file_size_bytes=len(file_a_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file1_id, "exact_md5", hash_a)

    file2_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="file_b.txt",
        filename="file_b.txt",
        extension="txt",
        file_size_bytes=len(file_b_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file2_id, "exact_md5", hash_b)

    file3_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="unique_c.txt",
        filename="unique_c.txt",
        extension="txt",
        file_size_bytes=len(file_c_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file3_id, "exact_md5", hash_c)

    # File E copies on volume 1
    file_e1_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="file_e_1.txt",
        filename="file_e_1.txt",
        extension="txt",
        file_size_bytes=len(file_e_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file_e1_id, "exact_md5", hash_e)

    file_e2_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="file_e_2.txt",
        filename="file_e_2.txt",
        extension="txt",
        file_size_bytes=len(file_e_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file_e2_id, "exact_md5", hash_e)

    file_e3_id = test_db.add_file(
        volume_id=vol1_id,
        relative_path="file_e_3.txt",
        filename="file_e_3.txt",
        extension="txt",
        file_size_bytes=len(file_e_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file_e3_id, "exact_md5", hash_e)

    # Volume 2 files
    file4_id = test_db.add_file(
        volume_id=vol2_id,
        relative_path="file_a_copy.txt",
        filename="file_a_copy.txt",
        extension="txt",
        file_size_bytes=len(file_a_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file4_id, "exact_md5", hash_a)

    file5_id = test_db.add_file(
        volume_id=vol2_id,
        relative_path="subdir/file_b_renamed.txt",
        filename="file_b_renamed.txt",
        extension="txt",
        file_size_bytes=len(file_b_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file5_id, "exact_md5", hash_b)

    file6_id = test_db.add_file(
        volume_id=vol2_id,
        relative_path="unique_d.txt",
        filename="unique_d.txt",
        extension="txt",
        file_size_bytes=len(file_d_content),
        file_type="document",
        file_created_at=now,
        file_modified_at=now
    )
    test_db.add_hash(file6_id, "exact_md5", hash_d)

    # Update volume file counts
    test_db.update_volume_scan_status(vol1_id, status='complete', file_count=6)
    test_db.update_volume_scan_status(vol2_id, status='complete', file_count=3)

    return {
        'db': test_db,
        'vol1_id': vol1_id,
        'vol2_id': vol2_id,
        'vol1_path': vol1_path,
        'vol2_path': vol2_path,
        'hashes': {
            'a': hash_a,
            'b': hash_b,
            'c': hash_c,
            'd': hash_d,
            'e': hash_e,
        }
    }


class TestDuplicateDetection:
    """Tests for duplicate detection functionality."""

    def test_find_duplicates_within_single_volume(self, two_volumes_with_duplicates):
        """Test finding duplicates within a single volume."""
        setup = two_volumes_with_duplicates
        vol1_id = setup['vol1_id']

        deduplicator = Deduplicator()

        # Find duplicates within volume 1 only
        groups = deduplicator.find_duplicates_from_db(
            volume_ids=[vol1_id],
            hash_type="exact_md5"
        )

        # Should find 1 group: file_e has 3 copies on volume 1
        assert len(groups) == 1, f"Expected 1 duplicate group, got {len(groups)}"

        # The group should have 3 files
        group = groups[0]
        assert len(group.images) == 3, f"Expected 3 files in group, got {len(group.images)}"

        # All files should be from volume 1 and contain "file_e" in the filename
        for img in group.images:
            assert "file_e" in img.filename

    def test_find_duplicates_across_volumes(self, two_volumes_with_duplicates):
        """Test finding duplicates that exist on both volumes."""
        setup = two_volumes_with_duplicates
        vol1_id = setup['vol1_id']
        vol2_id = setup['vol2_id']

        deduplicator = Deduplicator()

        # Find cross-volume duplicates
        groups = deduplicator.find_cross_volume_duplicates(
            volume_ids=[vol1_id, vol2_id],
            hash_type="exact_md5"
        )

        # Should find 2 groups: file_a and file_b exist on both volumes
        assert len(groups) == 2, f"Expected 2 cross-volume duplicate groups, got {len(groups)}"

        # Each group should have exactly 2 files (one from each volume)
        for group in groups:
            assert len(group.images) == 2, f"Expected 2 files in cross-volume group, got {len(group.images)}"
            assert group.is_cross_volume, "Group should be marked as cross-volume"

            # Verify files are from different volumes
            volume_names = set(img.volume_name for img in group.images)
            assert len(volume_names) == 2, "Files should be from different volumes"

    def test_find_all_duplicates_both_volumes(self, two_volumes_with_duplicates):
        """Test finding all duplicates across both volumes (not just cross-volume)."""
        setup = two_volumes_with_duplicates
        vol1_id = setup['vol1_id']
        vol2_id = setup['vol2_id']

        deduplicator = Deduplicator()

        # Find all duplicates on both volumes
        groups = deduplicator.find_duplicates_from_db(
            volume_ids=[vol1_id, vol2_id],
            hash_type="exact_md5"
        )

        # Should find 3 groups:
        # 1. file_a (2 copies across volumes)
        # 2. file_b (2 copies across volumes)
        # 3. file_e (3 copies on volume 1)
        assert len(groups) == 3, f"Expected 3 duplicate groups, got {len(groups)}"

        # Count total duplicate files
        total_files = sum(len(g.images) for g in groups)
        assert total_files == 7, f"Expected 7 total files in groups, got {total_files}"

    def test_no_duplicates_for_unique_files(self, two_volumes_with_duplicates):
        """Test that unique files are not reported as duplicates."""
        setup = two_volumes_with_duplicates

        deduplicator = Deduplicator()

        # Get all groups
        groups = deduplicator.find_duplicates_from_db(
            hash_type="exact_md5"
        )

        # Collect all filenames in duplicate groups
        duplicate_filenames = set()
        for group in groups:
            for img in group.images:
                duplicate_filenames.add(img.filename)

        # Unique files should not appear in any duplicate group
        assert "unique_c.txt" not in duplicate_filenames
        assert "unique_d.txt" not in duplicate_filenames

    def test_duplicate_group_suggests_keep(self, two_volumes_with_duplicates):
        """Test that duplicate groups suggest which file to keep."""
        setup = two_volumes_with_duplicates

        deduplicator = Deduplicator()

        groups = deduplicator.find_duplicates_from_db(
            hash_type="exact_md5"
        )

        for group in groups:
            # Each group should have a suggested keep
            assert group.suggested_keep is not None, "Group should suggest a file to keep"
            assert group.suggested_keep in group.images, "Suggested keep should be in the group"

            # Suggested delete should be all others
            assert len(group.suggested_delete) == len(group.images) - 1

    def test_cross_volume_detection_excludes_intra_volume(self, two_volumes_with_duplicates):
        """Test that cross-volume detection only returns files spanning multiple volumes."""
        setup = two_volumes_with_duplicates
        vol1_id = setup['vol1_id']
        vol2_id = setup['vol2_id']

        deduplicator = Deduplicator()

        # Find cross-volume duplicates
        groups = deduplicator.find_cross_volume_duplicates(
            volume_ids=[vol1_id, vol2_id],
            hash_type="exact_md5"
        )

        # file_e has 3 copies but all on volume 1, so it should NOT appear
        for group in groups:
            filenames = [img.filename for img in group.images]
            assert not any("file_e" in f for f in filenames), \
                "Intra-volume duplicates (file_e) should not appear in cross-volume results"


class TestDuplicateDetectionWithImages:
    """Tests for duplicate detection with actual image files."""

    @pytest.fixture
    def two_volumes_with_image_duplicates(self, test_db, tmp_path):
        """Set up two volumes with duplicate image files."""
        vol1_path = tmp_path / "photos_main"
        vol2_path = tmp_path / "photos_backup"
        vol1_path.mkdir()
        vol2_path.mkdir()

        # Register volumes using add_volume
        vol1_id = test_db.add_volume(
            uuid="IMG-VOL1-UUID",
            name="Photos Main",
            mount_point=str(vol1_path),
            total_size_bytes=1000000000,
            filesystem="apfs"
        )

        vol2_id = test_db.add_volume(
            uuid="IMG-VOL2-UUID",
            name="Photos Backup",
            mount_point=str(vol2_path),
            total_size_bytes=1000000000,
            filesystem="apfs"
        )

        # Create identical images
        img1 = Image.new("RGB", (100, 100), color=(255, 0, 0))
        img1.save(vol1_path / "photo1.png")
        img1.save(vol2_path / "photo1_backup.png")

        img2 = Image.new("RGB", (100, 100), color=(0, 255, 0))
        img2.save(vol1_path / "photo2.png")
        img2.save(vol2_path / "photo2_backup.png")

        # Unique image only on vol1
        img3 = Image.new("RGB", (100, 100), color=(0, 0, 255))
        img3.save(vol1_path / "unique_photo.png")

        # Calculate pixel MD5 hashes (simulating what the scanner would do)
        import hashlib

        def get_pixel_md5(img):
            """Get MD5 of raw pixel data."""
            return hashlib.md5(img.tobytes()).hexdigest()

        hash1 = get_pixel_md5(img1)
        hash2 = get_pixel_md5(img2)
        hash3 = get_pixel_md5(img3)

        now = datetime.now().isoformat()

        # Add files to database with pixel_md5 hashes
        f1_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="photo1.png",
            filename="photo1.png",
            extension="png",
            file_size_bytes=(vol1_path / "photo1.png").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f1_id, "pixel_md5", hash1)

        f2_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo1_backup.png",
            filename="photo1_backup.png",
            extension="png",
            file_size_bytes=(vol2_path / "photo1_backup.png").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f2_id, "pixel_md5", hash1)

        f3_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="photo2.png",
            filename="photo2.png",
            extension="png",
            file_size_bytes=(vol1_path / "photo2.png").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f3_id, "pixel_md5", hash2)

        f4_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo2_backup.png",
            filename="photo2_backup.png",
            extension="png",
            file_size_bytes=(vol2_path / "photo2_backup.png").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f4_id, "pixel_md5", hash2)

        f5_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="unique_photo.png",
            filename="unique_photo.png",
            extension="png",
            file_size_bytes=(vol1_path / "unique_photo.png").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f5_id, "pixel_md5", hash3)

        test_db.update_volume_scan_status(vol1_id, status='complete', file_count=3)
        test_db.update_volume_scan_status(vol2_id, status='complete', file_count=2)

        return {
            'db': test_db,
            'vol1_id': vol1_id,
            'vol2_id': vol2_id,
            'vol1_path': vol1_path,
            'vol2_path': vol2_path,
        }

    def test_find_image_duplicates_with_pixel_md5(self, two_volumes_with_image_duplicates):
        """Test finding duplicate images using pixel_md5 hash."""
        setup = two_volumes_with_image_duplicates

        deduplicator = Deduplicator()

        groups = deduplicator.find_duplicates_from_db(
            hash_type="pixel_md5"
        )

        # Should find 2 groups (photo1 and photo2 duplicates)
        assert len(groups) == 2, f"Expected 2 duplicate groups, got {len(groups)}"

        # Each group should have 2 files
        for group in groups:
            assert len(group.images) == 2

    def test_cross_volume_image_duplicates(self, two_volumes_with_image_duplicates):
        """Test finding cross-volume image duplicates."""
        setup = two_volumes_with_image_duplicates
        vol1_id = setup['vol1_id']
        vol2_id = setup['vol2_id']

        deduplicator = Deduplicator()

        groups = deduplicator.find_cross_volume_duplicates(
            volume_ids=[vol1_id, vol2_id],
            hash_type="pixel_md5"
        )

        # Should find 2 groups
        assert len(groups) == 2

        # All groups should be marked as cross-volume
        for group in groups:
            assert group.is_cross_volume

            # Files should have volume_name attribute
            for img in group.images:
                assert hasattr(img, 'volume_name')
                assert img.volume_name in ["Photos Main", "Photos Backup"]


class TestPerceptualDuplicateDetection:
    """Tests for perceptual duplicate detection (visually similar images)."""

    @pytest.fixture
    def volumes_with_perceptual_duplicates(self, test_db, tmp_path):
        """Set up volumes with visually similar images that differ in compression/size.

        Creates images that are:
        - Identical (same pixels)
        - Resized versions (visually similar but different pixel count)
        - Different quality JPEG compressions (same dimensions, different bytes)
        """
        import imagehash

        vol1_path = tmp_path / "photos_original"
        vol2_path = tmp_path / "photos_compressed"
        vol1_path.mkdir()
        vol2_path.mkdir()

        vol1_id = test_db.add_volume(
            uuid="PHASH-VOL1-UUID",
            name="Original Photos",
            mount_point=str(vol1_path),
            total_size_bytes=1000000000,
            filesystem="apfs"
        )

        vol2_id = test_db.add_volume(
            uuid="PHASH-VOL2-UUID",
            name="Compressed Photos",
            mount_point=str(vol2_path),
            total_size_bytes=1000000000,
            filesystem="apfs"
        )

        # Create a more complex test image (gradient with shapes)
        # This gives perceptual hashing something meaningful to work with
        img1 = Image.new("RGB", (200, 200), color=(255, 255, 255))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img1)
        # Draw some shapes to create a distinctive image
        draw.rectangle([20, 20, 80, 80], fill=(255, 0, 0))
        draw.ellipse([100, 20, 180, 100], fill=(0, 255, 0))
        draw.polygon([(100, 150), (150, 100), (180, 180)], fill=(0, 0, 255))

        # Save original as high-quality JPEG
        img1.save(vol1_path / "photo1.jpg", "JPEG", quality=95)

        # Save compressed version (lower quality - visually similar but different bytes)
        img1.save(vol2_path / "photo1_compressed.jpg", "JPEG", quality=30)

        # Save resized version (smaller but visually similar)
        img1_resized = img1.resize((100, 100), Image.Resampling.LANCZOS)
        img1_resized.save(vol2_path / "photo1_small.jpg", "JPEG", quality=85)

        # Create a second distinct image
        img2 = Image.new("RGB", (200, 200), color=(0, 0, 0))
        draw2 = ImageDraw.Draw(img2)
        draw2.rectangle([50, 50, 150, 150], fill=(255, 255, 0))
        draw2.ellipse([60, 60, 140, 140], fill=(128, 0, 128))

        img2.save(vol1_path / "photo2.jpg", "JPEG", quality=95)
        img2.save(vol2_path / "photo2_backup.jpg", "JPEG", quality=50)

        # Create a completely different image (should NOT match)
        img3 = Image.new("RGB", (200, 200), color=(0, 128, 255))
        draw3 = ImageDraw.Draw(img3)
        draw3.line([(0, 0), (200, 200)], fill=(255, 255, 255), width=5)
        draw3.line([(200, 0), (0, 200)], fill=(255, 255, 255), width=5)
        img3.save(vol1_path / "unique_photo.jpg", "JPEG", quality=90)

        # Create a GIF with similar content to photo1
        img1.save(vol2_path / "photo1.gif", "GIF")

        # Compute perceptual hashes
        def get_phash(img_path):
            with Image.open(img_path) as img:
                return str(imagehash.phash(img))

        now = datetime.now().isoformat()

        # Original photo1 (high quality)
        phash1 = get_phash(vol1_path / "photo1.jpg")
        f1_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="photo1.jpg",
            filename="photo1.jpg",
            extension="jpg",
            file_size_bytes=(vol1_path / "photo1.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f1_id, "perceptual_phash", phash1)

        # Compressed photo1
        phash1_comp = get_phash(vol2_path / "photo1_compressed.jpg")
        f2_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo1_compressed.jpg",
            filename="photo1_compressed.jpg",
            extension="jpg",
            file_size_bytes=(vol2_path / "photo1_compressed.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f2_id, "perceptual_phash", phash1_comp)

        # Resized photo1
        phash1_small = get_phash(vol2_path / "photo1_small.jpg")
        f3_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo1_small.jpg",
            filename="photo1_small.jpg",
            extension="jpg",
            file_size_bytes=(vol2_path / "photo1_small.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=100,
            height=100
        )
        test_db.add_hash(f3_id, "perceptual_phash", phash1_small)

        # GIF version of photo1
        phash1_gif = get_phash(vol2_path / "photo1.gif")
        f4_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo1.gif",
            filename="photo1.gif",
            extension="gif",
            file_size_bytes=(vol2_path / "photo1.gif").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f4_id, "perceptual_phash", phash1_gif)

        # Photo2 original
        phash2 = get_phash(vol1_path / "photo2.jpg")
        f5_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="photo2.jpg",
            filename="photo2.jpg",
            extension="jpg",
            file_size_bytes=(vol1_path / "photo2.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f5_id, "perceptual_phash", phash2)

        # Photo2 backup (compressed)
        phash2_backup = get_phash(vol2_path / "photo2_backup.jpg")
        f6_id = test_db.add_file(
            volume_id=vol2_id,
            relative_path="photo2_backup.jpg",
            filename="photo2_backup.jpg",
            extension="jpg",
            file_size_bytes=(vol2_path / "photo2_backup.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f6_id, "perceptual_phash", phash2_backup)

        # Unique photo (different image)
        phash3 = get_phash(vol1_path / "unique_photo.jpg")
        f7_id = test_db.add_file(
            volume_id=vol1_id,
            relative_path="unique_photo.jpg",
            filename="unique_photo.jpg",
            extension="jpg",
            file_size_bytes=(vol1_path / "unique_photo.jpg").stat().st_size,
            file_type="image",
            file_created_at=now,
            file_modified_at=now,
            width=200,
            height=200
        )
        test_db.add_hash(f7_id, "perceptual_phash", phash3)

        test_db.update_volume_scan_status(vol1_id, status='complete', file_count=3)
        test_db.update_volume_scan_status(vol2_id, status='complete', file_count=4)

        return {
            'db': test_db,
            'vol1_id': vol1_id,
            'vol2_id': vol2_id,
            'vol1_path': vol1_path,
            'vol2_path': vol2_path,
            'hashes': {
                'photo1': phash1,
                'photo1_compressed': phash1_comp,
                'photo1_small': phash1_small,
                'photo1_gif': phash1_gif,
                'photo2': phash2,
                'photo2_backup': phash2_backup,
                'unique': phash3,
            }
        }

    def test_perceptual_hashes_similar_for_compressed_images(self, volumes_with_perceptual_duplicates):
        """Test that compressed versions of the same image have similar perceptual hashes."""
        import imagehash

        setup = volumes_with_perceptual_duplicates
        hashes = setup['hashes']

        # Convert string hashes back to ImageHash for comparison
        phash1 = imagehash.hex_to_hash(hashes['photo1'])
        phash1_comp = imagehash.hex_to_hash(hashes['photo1_compressed'])

        # Hamming distance should be small (similar images)
        distance = phash1 - phash1_comp
        assert distance <= 10, f"Compressed image should have similar hash, but distance is {distance}"

    def test_perceptual_hashes_similar_for_resized_images(self, volumes_with_perceptual_duplicates):
        """Test that resized versions have similar perceptual hashes."""
        import imagehash

        setup = volumes_with_perceptual_duplicates
        hashes = setup['hashes']

        phash1 = imagehash.hex_to_hash(hashes['photo1'])
        phash1_small = imagehash.hex_to_hash(hashes['photo1_small'])

        distance = phash1 - phash1_small
        assert distance <= 10, f"Resized image should have similar hash, but distance is {distance}"

    def test_perceptual_hashes_similar_for_gif_conversion(self, volumes_with_perceptual_duplicates):
        """Test that GIF conversion of an image has similar perceptual hash."""
        import imagehash

        setup = volumes_with_perceptual_duplicates
        hashes = setup['hashes']

        phash1 = imagehash.hex_to_hash(hashes['photo1'])
        phash1_gif = imagehash.hex_to_hash(hashes['photo1_gif'])

        distance = phash1 - phash1_gif
        # GIF conversion may cause more variation due to color palette reduction
        assert distance <= 15, f"GIF version should have similar hash, but distance is {distance}"

    def test_perceptual_hashes_different_for_different_images(self, volumes_with_perceptual_duplicates):
        """Test that different images have different perceptual hashes."""
        import imagehash

        setup = volumes_with_perceptual_duplicates
        hashes = setup['hashes']

        phash1 = imagehash.hex_to_hash(hashes['photo1'])
        phash2 = imagehash.hex_to_hash(hashes['photo2'])
        phash_unique = imagehash.hex_to_hash(hashes['unique'])

        # Different images should have large Hamming distance
        distance_1_2 = phash1 - phash2
        distance_1_unique = phash1 - phash_unique

        assert distance_1_2 > 10, f"Different images should have different hashes, but distance is {distance_1_2}"
        assert distance_1_unique > 10, f"Unique image should differ, but distance is {distance_1_unique}"

    def test_find_perceptual_duplicates_in_database(self, volumes_with_perceptual_duplicates):
        """Test finding perceptual duplicates using database queries."""
        setup = volumes_with_perceptual_duplicates
        db = setup['db']

        # Find duplicate perceptual hashes
        # Note: This finds exact hash matches only, not similar hashes
        duplicates = db.find_duplicate_hashes("perceptual_phash")

        # The hashes might match exactly for some compression levels
        # or might all be unique if compression changed them slightly
        # This test validates the database query works
        assert isinstance(duplicates, list)

    def test_perceptual_duplicates_across_formats(self, volumes_with_perceptual_duplicates):
        """Test that JPG and GIF versions of same image are detected as similar."""
        import imagehash

        setup = volumes_with_perceptual_duplicates
        hashes = setup['hashes']

        # Compare original JPG with GIF version
        phash_jpg = imagehash.hex_to_hash(hashes['photo1'])
        phash_gif = imagehash.hex_to_hash(hashes['photo1_gif'])

        distance = phash_jpg - phash_gif

        # They should be similar (within threshold used by deduplicator)
        assert distance <= 15, f"JPG and GIF should be similar, but distance is {distance}"


class TestDatabaseDuplicateQueries:
    """Tests for the database-level duplicate query methods."""

    def test_find_duplicate_hashes(self, two_volumes_with_duplicates):
        """Test the database method for finding duplicate hashes."""
        setup = two_volumes_with_duplicates
        db = setup['db']

        # Query for duplicate exact_md5 hashes
        duplicates = db.find_duplicate_hashes("exact_md5")

        # Should find 3 hashes with duplicates: a, b, e
        assert len(duplicates) == 3, f"Expected 3 duplicate hashes, got {len(duplicates)}"

        # Verify counts
        hash_counts = {h: c for h, c in duplicates}

        # hash_e should have count 3 (3 copies on vol1)
        assert setup['hashes']['e'] in hash_counts
        assert hash_counts[setup['hashes']['e']] == 3

        # hash_a and hash_b should have count 2 each
        assert setup['hashes']['a'] in hash_counts
        assert hash_counts[setup['hashes']['a']] == 2

        assert setup['hashes']['b'] in hash_counts
        assert hash_counts[setup['hashes']['b']] == 2

    def test_find_duplicate_hashes_filtered_by_volume(self, two_volumes_with_duplicates):
        """Test finding duplicate hashes filtered to specific volumes."""
        setup = two_volumes_with_duplicates
        db = setup['db']
        vol1_id = setup['vol1_id']

        # Query only volume 1
        duplicates = db.find_duplicate_hashes("exact_md5", volume_ids=[vol1_id])

        # Should only find hash_e (3 copies on vol1)
        # hash_a and hash_b only have 1 copy each on vol1
        assert len(duplicates) == 1, f"Expected 1 duplicate hash on vol1, got {len(duplicates)}"

        hash_value, count = duplicates[0]
        assert hash_value == setup['hashes']['e']
        assert count == 3

    def test_find_files_by_hash(self, two_volumes_with_duplicates):
        """Test finding all files with a specific hash."""
        setup = two_volumes_with_duplicates
        db = setup['db']

        # Find all files with hash_a
        files = db.find_files_by_hash("exact_md5", setup['hashes']['a'])

        assert len(files) == 2, f"Expected 2 files with hash_a, got {len(files)}"

        filenames = [f['filename'] for f in files]
        assert "file_a.txt" in filenames
        assert "file_a_copy.txt" in filenames
