"""Integration test for Set Operations B-A difference with MOV files.

This test uses the actual product code to:
1. Scan two folders (A and B) as separate volumes
2. Index files and compute hashes
3. Run B-A difference
4. Verify that duplicate MOV files are NOT in the results

Test structure (SampleHierarchy):
- A/2009-12-27 16.17.01.mov
- B/SubB/2009-12-27 16.17.01.mov

Both MOV files are byte-identical (same MD5 hash).
"""

import pytest
from pathlib import Path

from src.core.database import DatabaseManager
from src.core.file_scanner import FileScanner
from src.core.volume_manager import VolumeInfo
from src.core.file_classifier import HashType


# Path to test hierarchy
SAMPLE_HIERARCHY = Path(__file__).parent / "SampleHierarchy"


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database."""
    db_path = tmp_path / "test_setdiff.db"
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_path)
    DatabaseManager._instance = db
    yield db
    DatabaseManager.reset_instance()


@pytest.fixture
def scanned_volumes(test_db):
    """Scan both A and B folders as separate volumes."""
    folder_a = SAMPLE_HIERARCHY / "A"
    folder_b = SAMPLE_HIERARCHY / "B"

    assert folder_a.exists(), f"Test folder A not found: {folder_a}"
    assert folder_b.exists(), f"Test folder B not found: {folder_b}"

    # Create volume info for A
    vol_a_info = VolumeInfo(
        uuid="test-vol-A",
        name="Volume A",
        mount_point=folder_a,
        is_internal=True,
        total_bytes=1000000000,
        available_bytes=500000000,
        filesystem="APFS"
    )

    # Create volume info for B
    vol_b_info = VolumeInfo(
        uuid="test-vol-B",
        name="Volume B",
        mount_point=folder_b,
        is_internal=True,
        total_bytes=1000000000,
        available_bytes=500000000,
        filesystem="APFS"
    )

    # Create scanner with single-threaded hashing for determinism
    scanner = FileScanner(
        db_manager=test_db,
        hash_workers=1
    )

    # Scan volume A
    session_a, stats_a = scanner.scan_volume(vol_a_info, scan_path=folder_a)
    print(f"\nVolume A scan: {stats_a}")

    # Scan volume B
    session_b, stats_b = scanner.scan_volume(vol_b_info, scan_path=folder_b)
    print(f"Volume B scan: {stats_b}")

    # Get volume IDs
    vol_a = test_db.get_volume_by_uuid("test-vol-A")
    vol_b = test_db.get_volume_by_uuid("test-vol-B")

    assert vol_a is not None, "Volume A not created"
    assert vol_b is not None, "Volume B not created"

    return {
        'db': test_db,
        'vol_a_id': vol_a['id'],
        'vol_b_id': vol_b['id'],
        'stats_a': stats_a,
        'stats_b': stats_b,
    }


class TestSetDifferenceWithMOV:
    """Test B-A difference with real MOV files that exist in both volumes."""

    def test_volumes_scanned_correctly(self, scanned_volumes):
        """Verify both volumes were scanned and have files."""
        db = scanned_volumes['db']

        files_a = db.get_files_by_volume(scanned_volumes['vol_a_id'])
        files_b = db.get_files_by_volume(scanned_volumes['vol_b_id'])

        print(f"\nFiles in A: {[f['filename'] for f in files_a]}")
        print(f"Files in B: {[f['filename'] for f in files_b]}")

        assert len(files_a) > 0, "Volume A should have files"
        assert len(files_b) > 0, "Volume B should have files"

    def test_mov_files_have_hashes(self, scanned_volumes):
        """Verify MOV files have exact_md5 hashes computed."""
        db = scanned_volumes['db']

        # Get all files
        files_a = db.get_files_by_volume(scanned_volumes['vol_a_id'])
        files_b = db.get_files_by_volume(scanned_volumes['vol_b_id'])

        # Find MOV files
        mov_files_a = [f for f in files_a if f['extension'] and f['extension'].lower() == 'mov']
        mov_files_b = [f for f in files_b if f['extension'] and f['extension'].lower() == 'mov']

        print(f"\nMOV files in A: {mov_files_a}")
        print(f"MOV files in B: {mov_files_b}")

        assert len(mov_files_a) > 0, "Volume A should have MOV files"
        assert len(mov_files_b) > 0, "Volume B should have MOV files"

        # Check hashes for MOV files in A
        for mov in mov_files_a:
            hashes = db.get_all_hashes_for_file(mov['id'])
            print(f"Hashes for {mov['filename']} (A): {hashes}")
            assert 'exact_md5' in hashes, f"MOV file {mov['filename']} should have exact_md5 hash"

        # Check hashes for MOV files in B
        for mov in mov_files_b:
            hashes = db.get_all_hashes_for_file(mov['id'])
            print(f"Hashes for {mov['filename']} (B): {hashes}")
            assert 'exact_md5' in hashes, f"MOV file {mov['filename']} should have exact_md5 hash"

    def test_duplicate_mov_has_same_hash(self, scanned_volumes):
        """Verify the duplicate MOV files have the same hash in both volumes."""
        db = scanned_volumes['db']

        files_a = db.get_files_by_volume(scanned_volumes['vol_a_id'])
        files_b = db.get_files_by_volume(scanned_volumes['vol_b_id'])

        # Find the specific duplicate MOV file
        mov_a = next((f for f in files_a if '2009-12-27 16.17.01' in f['filename']), None)
        mov_b = next((f for f in files_b if '2009-12-27 16.17.01' in f['filename']), None)

        assert mov_a is not None, "Should find 2009-12-27 16.17.01.mov in A"
        assert mov_b is not None, "Should find 2009-12-27 16.17.01.mov in B"

        hash_a = db.get_hash(mov_a['id'], 'exact_md5')
        hash_b = db.get_hash(mov_b['id'], 'exact_md5')

        print(f"\nHash A: {hash_a}")
        print(f"Hash B: {hash_b}")

        assert hash_a is not None, "MOV in A should have exact_md5 hash"
        assert hash_b is not None, "MOV in B should have exact_md5 hash"
        assert hash_a == hash_b, "Duplicate MOV files should have same hash"

    def test_b_minus_a_excludes_duplicates(self, scanned_volumes):
        """
        CRITICAL TEST: B - A should NOT include files that exist in both volumes.

        The MOV file exists in both A and B with the same hash.
        When we run B - A (files in B not in A), the duplicate MOV should NOT appear.
        """
        db = scanned_volumes['db']
        vol_a_id = scanned_volumes['vol_a_id']
        vol_b_id = scanned_volumes['vol_b_id']

        # Run B - A difference with exact_md5
        diff_results = db.get_set_difference(vol_b_id, vol_a_id, 'exact_md5')

        print(f"\nB - A results ({len(diff_results)} files):")
        for r in diff_results:
            print(f"  - {r['filename']} (path: {r['relative_path']})")

        # The duplicate MOV file should NOT be in the results
        duplicate_mov_in_results = [
            r for r in diff_results
            if '2009-12-27 16.17.01' in r['filename']
        ]

        assert len(duplicate_mov_in_results) == 0, (
            f"Duplicate MOV file should NOT appear in B - A results!\n"
            f"Found: {duplicate_mov_in_results}\n"
            f"This file exists in both volumes with the same hash."
        )

    def test_b_minus_a_includes_unique_files(self, scanned_volumes):
        """B - A should include files that are ONLY in B (not in A)."""
        db = scanned_volumes['db']
        vol_a_id = scanned_volumes['vol_a_id']
        vol_b_id = scanned_volumes['vol_b_id']

        # Get all files in B
        files_b = db.get_files_by_volume(vol_b_id)

        # Get hashes for A
        files_a = db.get_files_by_volume(vol_a_id)
        hashes_in_a = set()
        for f in files_a:
            h = db.get_hash(f['id'], 'exact_md5')
            if h:
                hashes_in_a.add(h)

        # Find files in B that are truly unique (hash not in A)
        unique_to_b = []
        for f in files_b:
            h = db.get_hash(f['id'], 'exact_md5')
            if h and h not in hashes_in_a:
                unique_to_b.append(f['filename'])

        print(f"\nFiles truly unique to B: {unique_to_b}")

        # Run B - A
        diff_results = db.get_set_difference(vol_b_id, vol_a_id, 'exact_md5')
        diff_filenames = [r['filename'] for r in diff_results]

        print(f"B - A result filenames: {diff_filenames}")

        # All unique files should be in the diff results
        for unique_file in unique_to_b:
            assert unique_file in diff_filenames, (
                f"File '{unique_file}' is unique to B and should appear in B - A results"
            )


class TestDebugQuery:
    """Debug tests to understand the exact SQL behavior."""

    def test_debug_sql_query(self, scanned_volumes):
        """Run the query step by step to debug."""
        db = scanned_volumes['db']
        vol_a_id = scanned_volumes['vol_a_id']
        vol_b_id = scanned_volumes['vol_b_id']

        with db.cursor() as cursor:
            # Step 1: What hashes exist in A?
            cursor.execute("""
                SELECT f.filename, h.hash_type, h.hash_value
                FROM files f
                JOIN hashes h ON f.id = h.file_id
                WHERE f.volume_id = ? AND f.is_deleted = 0 AND h.hash_type = 'exact_md5'
            """, (vol_a_id,))
            hashes_a = cursor.fetchall()
            print(f"\nHashes in A:")
            for row in hashes_a:
                print(f"  {row[0]}: {row[2]}")

            # Step 2: What hashes exist in B?
            cursor.execute("""
                SELECT f.filename, h.hash_type, h.hash_value
                FROM files f
                JOIN hashes h ON f.id = h.file_id
                WHERE f.volume_id = ? AND f.is_deleted = 0 AND h.hash_type = 'exact_md5'
            """, (vol_b_id,))
            hashes_b = cursor.fetchall()
            print(f"\nHashes in B:")
            for row in hashes_b:
                print(f"  {row[0]}: {row[2]}")

            # Step 3: Check if NOT EXISTS works
            cursor.execute("""
                SELECT f.filename, h.hash_value
                FROM files f
                JOIN hashes h ON f.id = h.file_id
                WHERE f.volume_id = ? AND f.is_deleted = 0 AND h.hash_type = 'exact_md5'
                AND NOT EXISTS (
                    SELECT 1 FROM hashes h2
                    JOIN files f2 ON h2.file_id = f2.id
                    WHERE f2.volume_id = ? AND f2.is_deleted = 0
                      AND h2.hash_type = 'exact_md5' AND h2.hash_value = h.hash_value
                )
            """, (vol_b_id, vol_a_id))
            diff_results = cursor.fetchall()
            print(f"\nB - A via NOT EXISTS:")
            for row in diff_results:
                print(f"  {row[0]}: {row[1]}")

            # Step 4: Check if there are any NULL hashes
            cursor.execute("""
                SELECT COUNT(*) FROM hashes WHERE hash_value IS NULL
            """)
            null_count = cursor.fetchone()[0]
            print(f"\nNULL hash count: {null_count}")
