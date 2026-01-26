# Drive-Centric Dedupe with Persistent Hash Database

## Overview
Transform the app from directory-based scanning to drive-centric architecture with SQLite hash database. Enable scanning all personal files (images, videos, documents), uniquely identify drives, and persist hashes for instant re-recognition.

## Database Schema

**Location**: `~/.dedupe/dedupe.db`

### Tables
1. **volumes** - Drive identification
   - `uuid` (from macOS diskutil), `name`, `mount_point`, `is_internal`
   - `last_scan_at`, `file_count`, `scan_status`

2. **files** - All scanned files
   - `volume_id` (FK), `relative_path`, `filename`, `extension`
   - `file_size_bytes`, `file_type` (image/video/document/audio)
   - `width`, `height`, `modified_at`, `indexed_at`

3. **hashes** - Multiple hash types per file
   - `file_id` (FK), `hash_type`, `hash_value`, `computed_at`
   - Types: `exact_md5`, `pixel_md5`, `perceptual_phash`, etc.

4. **duplicate_groups** / **duplicate_group_files** - Cached results

## Hash Strategy by File Type

| Extension | Hash Type | Reason |
|-----------|-----------|--------|
| jpg, jpeg, gif | perceptual (pHash) | Visual similarity for compressed variants |
| png, bmp, webp, heic, tiff | exact (pixel MD5) | Lossless, exact match preferred |
| RAW (cr2, raf, dng, etc.) | exact (pixel MD5) | Large files, exact match |
| mp4, mov, mkv, avi | exact (file MD5) | Full file hash |
| pdf, doc, docx, xls, xlsx | exact (file MD5) | Full file hash |
| mp3, wav, flac | exact (file MD5) | Full file hash |

## File Filtering Rules

### Include (Personal Files)
- Images: jpg, jpeg, gif, png, bmp, webp, heic, heif, tiff, raw variants
- Videos: mp4, mov, avi, mkv, wmv, m4v, mts
- Documents: pdf, doc, docx, xls, xlsx, ppt, pptx, txt, rtf, pages, numbers
- Audio: mp3, wav, flac, aac, m4a

### Exclude (System/App Files)
- **Paths**: `/Applications`, `/System`, `/Library`, `~/Library`, `.Trash`, `node_modules`, `.git`, `__pycache__`
- **Hidden files**: Anything starting with `.` (like .DS_Store)
- **App bundles**: Skip contents of `.app` directories
- **Extensions**: app, pkg, dmg, exe, dll, dylib, db, sqlite, log
- **Small files**: < 1KB for images, < 100 bytes for documents

## Drive Identification (macOS)

Use `diskutil info -plist <mount_point>` to get:
- **VolumeUUID**: Unique identifier that persists across remounts
- Store **relative paths** within volume (not absolute)
- When drive remounts elsewhere, paths still resolve correctly

## New UI Workflow

### Startup Screen (replaces Session Picker)
```
┌─────────────────────────────────────────┐
│   Duplicate Finder                      │
├─────────────────────────────────────────┤
│ Connected Drives:                       │
│  ┌─────────────────────────────────┐   │
│  │ 💾 Macintosh HD (internal)      │   │
│  │    245,000 files indexed        │   │
│  │    Last scan: 2 days ago        │   │
│  ├─────────────────────────────────┤   │
│  │ 💿 External SSD                 │   │
│  │    12,500 files indexed         │   │
│  │    Last scan: 1 week ago        │   │
│  ├─────────────────────────────────┤   │
│  │ 💿 Photo Backup                 │   │
│  │    Not yet scanned              │   │
│  └─────────────────────────────────┘   │
│                                         │
│ [Scan Selected Drive]  [Find Duplicates]│
│ [Scan New Drive]       [Cross-Drive]    │
└─────────────────────────────────────────┘
```

### Actions
1. **Scan Drive**: Index all files, compute hashes, store in DB
2. **Find Duplicates**: Query DB for duplicates on selected drive(s)
3. **Cross-Drive Duplicates**: Find files that exist on multiple drives

## Files to Create

| File | Purpose |
|------|---------|
| `src/core/database.py` | SQLite manager, schema, CRUD operations |
| `src/core/volume_manager.py` | macOS drive detection via diskutil |
| `src/core/file_classifier.py` | Determine file type and hash strategy |
| `src/utils/file_filters.py` | System file exclusion logic |
| `src/models/scanned_file.py` | Generalized file model (replaces ImageFile) |
| `src/ui/drive_manager.py` | Main drive selection/management UI |

## Files to Modify

| File | Changes |
|------|---------|
| `src/core/scanner.py` | Add all file types, integrate filters |
| `src/core/deduplicator.py` | Use DB for hash caching, multi-hash support |
| `src/ui/main_window.py` | Drive-centric workflow |
| `src/ui/results_view.py` | Show volume info per file |
| `requirements.txt` | No new deps needed (sqlite3 is built-in) |

## Implementation Phases

### Phase 1: Database Foundation
- Create `database.py` with schema and connection management
- Create models: `scanned_file.py`
- Thread-safe SQLite with connection pooling

### Phase 2: Volume Management
- Create `volume_manager.py` with diskutil integration
- Volume UUID detection and tracking
- Store relative paths for portability

### Phase 3: File Filtering
- Create `file_filters.py` with exclusion rules
- Create `file_classifier.py` for type/hash strategy
- Integrate with scanner

### Phase 4: Hash Integration
- Refactor deduplicator to use DB cache
- Implement hash-by-type strategy
- Only compute hashes for new/modified files

### Phase 5: UI Transformation
- Create `drive_manager.py` as new entry point
- Update main_window for drive-centric flow
- Migrate session picker to drive picker

## Verification

1. **Database**: Run app, scan a folder, check `~/.dedupe/dedupe.db` exists with data
2. **Drive Detection**: Verify internal + external drives appear in UI
3. **Hash Persistence**: Scan drive, close app, reopen - hashes should load from DB instantly
4. **File Filtering**: Confirm .DS_Store, .app contents, node_modules are skipped
5. **Cross-Drive**: Plug in external drive, find files that exist on both drives
