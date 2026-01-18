# Duplicate Image Finder

A macOS desktop application for finding and managing exact duplicate images within directories.

## Features

- **Exact Duplicate Detection**: Uses MD5 file hashing to find byte-for-byte identical files
- **Intra-Directory Focus**: Processes each directory separately to find duplicates within the same folder
- **Extension-Aware**: Only compares files of the same type (JPG vs JPG, not JPG vs RAW)
- **Smart Keep Suggestions**: Automatically suggests keeping the larger file
- **Real-Time Progress**: Shows progress as each directory is processed with incremental results
- **Finder Integration**: Right-click to open files in Finder or view with default app
- **Batch Operations**: Move duplicates to a separate folder or delete them
- **CSV Export**: Export results for external analysis

## Supported File Types

- JPEG (`.jpg`, `.jpeg`)
- GIF (`.gif`)
- TIFF (`.tif`, `.tiff`)
- PNG (`.png`)
- BMP (`.bmp`)
- WebP (`.webp`)
- RAW formats: Canon (`.cr2`, `.crw`, `.cr3`), Fuji (`.raf`), generic (`.raw`)

## Installation

### Requirements

- Python 3.9+
- macOS (uses native Finder integration)

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
```

## Usage

### Running the Application

```bash
python src/main.py
```

### Workflow

1. **Select Directory**: Click "Browse" to choose a root directory to scan
2. **Scan**: Click "Scan for Duplicates" to begin the analysis
3. **Review Results**: Duplicates are grouped and displayed with:
   - File name, size, resolution, and path
   - Suggested action (KEEP or DELETE) based on file size
4. **Adjust Selections**: Check/uncheck files to customize which to keep
5. **Take Action**:
   - **Move Selected**: Moves checked files to a `_duplicates` folder alongside the originals
   - **Delete Selected**: Permanently deletes checked files
   - **Export CSV**: Saves results to a CSV file

### Context Menu

Right-click on any file in the results to:
- **Show in Finder**: Opens Finder with the file selected
- **Open File**: Opens the file with the default application

## How It Works

### Duplicate Detection

The application uses MD5 hashing on file contents to find exact duplicates:

1. Scans the selected directory recursively for supported image files
2. Groups files by directory, then by extension type
3. Computes MD5 hash for each file in parallel (using all CPU cores)
4. Files with identical hashes are grouped as duplicates

This approach:
- Finds only true byte-for-byte duplicates (not visually similar images)
- Is fast because it reads raw file bytes without image decoding
- Works regardless of filename differences

### Keep/Delete Suggestions

For each duplicate group, the application suggests keeping the file with:
1. **Largest file size** (primary criteria)
2. **Highest resolution** (tiebreaker)

## Project Structure

```
Dedupe/
├── src/
│   ├── main.py                 # Application entry point
│   ├── core/
│   │   ├── scanner.py          # File discovery
│   │   ├── deduplicator.py     # MD5 hash-based duplicate detection
│   │   ├── analyzer.py         # File analysis utilities
│   │   └── file_operations.py  # Move/delete operations
│   ├── models/
│   │   ├── image_file.py       # Image metadata model
│   │   └── duplicate_group.py  # Duplicate group model
│   ├── ui/
│   │   ├── main_window.py      # Main application window
│   │   ├── results_view.py     # Duplicate results display
│   │   ├── image_preview.py    # Side-by-side image preview
│   │   ├── progress_panel.py   # Progress indicator
│   │   └── directory_selector.py
│   └── utils/
│       └── export.py           # CSV export
├── tests/
│   ├── conftest.py             # Test fixtures
│   ├── test_scanner.py
│   └── sample_images/          # Test images
├── requirements.txt
└── README.md
```

## Running Tests

```bash
pytest tests/
```

## License

MIT License
