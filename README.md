# Dedupe - Duplicate File Finder

A macOS desktop application for finding and managing duplicate files across multiple drives with persistent database storage.

## Features

### Drive-Centric Architecture
- **Multi-Drive Support**: Scan and index multiple drives (internal, external, network)
- **Persistent Database**: SQLite database stores file metadata and hashes for fast re-scanning
- **Volume Tracking**: Tracks drives by UUID so files are found even if mount points change
- **Incremental Scans**: Only re-hashes files that have changed since last scan
- **Resume Support**: Interrupted scans can be resumed from where they left off

### Duplicate Detection
- **Multiple Hash Types**:
  - `pixel_md5`: MD5 of image pixel data (ignores EXIF metadata)
  - `perceptual_phash`: Perceptual hash for finding visually similar images
  - `exact_md5`: Full file MD5 for non-image files
- **Cross-Drive Detection**: Find duplicates that exist on different drives
- **Within-Drive Detection**: Find duplicates within a single drive
- **Extension-Aware**: Only compares files of the same type (JPG vs JPG, not JPG vs RAW)

### File Type Management
- **Configurable Extensions**: Choose which file types to index
- **Three Categories**:
  - **Include**: File types that are indexed and checked for duplicates
  - **Exclude**: File types that are always skipped
  - **Unknown**: New file types encountered during scanning
- **Directory Discovery**: See which directories contain specific file types
- **Quick Directory Scan**: Collect directory info for unknown/excluded extensions without full indexing

### Smart Suggestions
- **Keep Largest**: Suggests keeping the larger file (default)
- **Keep Shortest Name**: Suggests keeping the file with shortest filename (for merge operations)
- **Cross-Volume Awareness**: Shows which drive each duplicate is on

### Set Operations
- **Difference (B − A)**: Find files that exist in volume B but not in volume A
- **Intersection (A ∩ B)**: Find files that exist in both volumes
- **Hash-Based Comparison**: Uses exact_md5 or pixel_md5 for file matching
- **Subfolder Filtering**: Optionally limit operations to specific subdirectories
- **Move to A**: Move difference files to volume A, organized by EXIF date (YYYY/MM-DD)
- **Smart Directory Reuse**: Reuses existing directories with date descriptions (e.g., "05-03 England wedding")

### EXIF Date Organization
- **Automatic Date Extraction**: Extracts DateTimeOriginal from EXIF metadata
- **Fallback Support**: Uses DateTimeDigitized or file modification date if EXIF unavailable
- **RAW Support**: Works with CR2, NEF, ARW, RAF, DNG and other RAW formats
- **HEIC/HEIF Support**: Extracts dates from Apple's HEIC format

### User Interface
- **Tabbed Interface**:
  - **Drives Tab**: Manage and scan drives
  - **File Types Tab**: Configure which extensions to index
  - **Duplicates Tab**: Find and manage duplicates
  - **Set Operations Tab**: Compare volumes using set algebra (difference, intersection)
- **Duplicate Group Viewer**: Double-click any duplicate group to see all images side-by-side for comparison
- **Real-Time Progress**: Shows progress during scanning with file counts
- **Batch Operations**: Select multiple files for trash/delete operations
- **Finder Integration**: Double-click directories to open in Finder

## Supported File Types

### Images (Perceptual + Pixel Hash)
- JPEG (`.jpg`, `.jpeg`)
- GIF (`.gif`)

### Images (Pixel Hash)
- PNG (`.png`)
- TIFF (`.tif`, `.tiff`)
- BMP (`.bmp`)
- WebP (`.webp`)
- HEIC/HEIF (`.heic`, `.heif`)
- RAW formats: Canon (`.cr2`, `.cr3`), Nikon (`.nef`), Sony (`.arw`), Fuji (`.raf`), and more

### Other Media (Exact Hash)
- Video: `.mp4`, `.mov`, `.avi`, `.mkv`, `.wmv`, `.flv`, `.webm`, etc.
- Audio: `.mp3`, `.wav`, `.flac`, `.aac`, `.m4a`, `.ogg`, etc.
- Documents: `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.ppt`, `.pptx`, etc.
- Archives: `.zip`, `.rar`, `.7z`, `.tar`, `.gz`, etc.

## Installation

### Requirements

- Python 3.9+
- macOS (uses native Finder integration for trash)

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd Dedupe

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Dependencies

```
PyQt6>=6.6.0
Pillow>=10.0.0
numpy>=1.24.0
rawpy>=0.19.0
imagehash>=4.3.0
send2trash>=1.8.0
```

## Usage

### Running the Application

```bash
python src/main.py
```

### Workflow

#### 1. Scan Drives (Drives Tab)
1. Connected drives appear in the drives list
2. Click **"Scan Drive"** to index a drive
3. Progress shows files scanned and hashes computed
4. Scan can be paused/resumed if interrupted

#### 2. Configure File Types (File Types Tab)
1. Review which extensions are being indexed
2. Move extensions between Include/Exclude/Unknown lists
3. Click **"Collect Directory Info"** to find where unknown extensions are located
4. Double-click any extension to see directories containing those files
5. Click **"Save Changes"** to apply

#### 3. Find Duplicates (Duplicates Tab)
1. Select mode:
   - **Within a source**: Find duplicates on one drive
   - **Between two sources**: Find duplicates across two drives
2. Select drive(s) from dropdown
3. Click **"Find Duplicates"**
4. Review results grouped by duplicate sets
5. Double-click a duplicate group to see all images side-by-side
6. Check/uncheck files to customize selections
7. Click **"Move Selected to Trash"** to remove duplicates

#### 4. Set Operations (Set Operations Tab)
1. Select operation type:
   - **Difference (B − A)**: Files in B not in A
   - **Intersection (A ∩ B)**: Files in both
2. Select Source A and Source B volumes
3. Optionally filter to specific subfolders using **"Filter to Folder..."**
4. Choose comparison method (File Hash or Pixel Hash)
5. Click **"Execute Operation"**
6. Review results and select files
7. Options:
   - **Move Selected to Trash**: Delete selected files
   - **Move Selected to A**: Move files to A, organized by EXIF date (YYYY/MM-DD)

### Database Location

The SQLite database is stored at:
```
~/.dedupe/dedupe.db
```

This contains all indexed file metadata and hashes. Delete this file to start fresh.

## How It Works

### Scanning Process

1. **Volume Detection**: Identifies drive by UUID for persistent tracking
2. **File Discovery**: Walks filesystem, filtering by extension
3. **Metadata Collection**: Stores file size, dates, dimensions (for images)
4. **Hash Computation**: Multi-threaded hash computation based on file type:
   - Images: Perceptual hash (pHash) + pixel MD5
   - Other files: Full file MD5
5. **Database Storage**: All data persisted to SQLite for fast future lookups

### Duplicate Detection

1. **Hash Lookup**: Queries database for hash values that appear multiple times
2. **Group Formation**: Files with identical hashes are grouped together
3. **Cross-Volume Check**: Optionally filters to only show duplicates spanning multiple drives
4. **Suggestion**: Determines which file to keep based on strategy (size or name length)

## Project Structure

```
Dedupe/
├── src/
│   ├── main.py                    # Application entry point
│   ├── core/
│   │   ├── database.py            # SQLite database manager
│   │   ├── file_scanner.py        # Multi-threaded file scanner
│   │   ├── file_classifier.py     # File type and hash strategy
│   │   ├── deduplicator.py        # Duplicate detection logic
│   │   ├── volume_manager.py      # Drive/volume management
│   │   ├── file_operations.py     # Move/delete/trash operations
│   │   ├── scanner.py             # Legacy scanner (compatibility)
│   │   └── analyzer.py            # File analysis utilities
│   ├── models/
│   │   ├── image_file.py          # Image file model
│   │   ├── scanned_file.py        # Generic scanned file model
│   │   └── duplicate_group.py     # Duplicate group model
│   ├── ui/
│   │   ├── unified_window.py      # Main tabbed window (includes SetOperationsTab)
│   │   ├── duplicate_group_viewer.py  # Side-by-side duplicate comparison popup
│   │   ├── duplicate_comparison_dialog.py  # Source/destination duplicate resolution
│   │   ├── main_window.py         # Legacy main window
│   │   ├── results_view.py        # Duplicate results display
│   │   ├── image_preview.py       # Image preview panel
│   │   ├── drive_manager.py       # Drive management UI
│   │   ├── file_types_manager.py  # File types configuration UI
│   │   ├── progress_panel.py      # Progress indicator
│   │   └── directory_selector.py  # Directory picker
│   └── utils/
│       ├── exif_extractor.py      # EXIF date extraction from images
│       ├── file_mover.py          # File moving with EXIF date organization
│       ├── file_filters.py        # File filtering logic
│       └── export.py              # CSV export
├── tests/
│   ├── conftest.py                # Test fixtures
│   └── test_*.py                  # Test files
├── requirements.txt
└── README.md
```

## Database Schema

### Key Tables

- **volumes**: Registered drives with UUID, name, mount point
- **files**: Indexed files with metadata (path, size, dates, dimensions)
- **hashes**: Computed hashes linked to files (supports multiple hash types per file)
- **scan_sessions**: Scan history and progress tracking
- **custom_extensions**: User-configured include/exclude extensions
- **unknown_extensions**: Extensions encountered but not categorized
- **extension_sample_paths**: Directory locations for unknown/excluded extensions

## Running Tests

```bash
pytest tests/
```

## License

MIT License
