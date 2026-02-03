"""EXIF metadata extraction from image files."""

from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import os


class ExifExtractor:
    """Extracts EXIF date metadata from image files.

    Supports standard image formats (JPEG, TIFF, PNG, WEBP) via PIL,
    RAW formats via rawpy, and HEIC/HEIF via pillow-heif if available.
    """

    # EXIF tag IDs for dates
    DATETIME_ORIGINAL = 36867      # DateTimeOriginal - when photo was taken
    DATETIME_DIGITIZED = 36868     # DateTimeDigitized - when digitized
    DATETIME = 306                 # DateTime - last modified in camera

    # EXIF datetime format (note: colons in date part, not dashes)
    EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"

    # RAW file extensions
    RAW_EXTENSIONS = {
        '.cr2', '.cr3', '.crw',  # Canon
        '.nef', '.nrw',          # Nikon
        '.arw', '.srf', '.sr2',  # Sony
        '.raf',                   # Fujifilm
        '.orf',                   # Olympus
        '.rw2',                   # Panasonic
        '.pef', '.ptx',          # Pentax
        '.dng',                   # Adobe
        '.x3f',                   # Sigma
        '.3fr', '.fff',          # Hasselblad
        '.mef',                   # Mamiya
        '.mrw',                   # Minolta
        '.kdc', '.dcr',          # Kodak
        '.rwl',                   # Leica
        '.iiq',                   # Phase One
        '.erf',                   # Epson
    }

    def get_dates(self, file_path: Path) -> Tuple[Optional[datetime], Optional[datetime], datetime]:
        """
        Extract date information from an image file.

        Args:
            file_path: Path to the image file

        Returns:
            Tuple of (dateTimeOriginal, dateTimeDigitized, fallback_date)
            - dateTimeOriginal: When the photo was taken (from EXIF), or None
            - dateTimeDigitized: When the photo was digitized (from EXIF), or None
            - fallback_date: File's last modified date (always available)
        """
        file_path = Path(file_path)

        # Always get the fallback date (file modification time)
        fallback_date = self._get_file_modified_date(file_path)

        # Try to extract EXIF dates
        date_original = None
        date_digitized = None

        try:
            exif_data = self._extract_exif(file_path)
            if exif_data:
                date_original = self._parse_exif_date(exif_data.get(self.DATETIME_ORIGINAL))
                date_digitized = self._parse_exif_date(exif_data.get(self.DATETIME_DIGITIZED))
        except Exception:
            pass  # Return None for EXIF dates, fallback still available

        return (date_original, date_digitized, fallback_date)

    def _extract_exif(self, file_path: Path) -> Optional[Dict[int, Any]]:
        """
        Extract raw EXIF data from image.

        Tries PIL first for standard formats, then rawpy for RAW files.

        Args:
            file_path: Path to the image file

        Returns:
            Dictionary mapping EXIF tag IDs to values, or None if extraction failed
        """
        extension = file_path.suffix.lower()

        # Try RAW-specific extraction first for RAW files
        if extension in self.RAW_EXTENSIONS:
            exif = self._extract_exif_from_raw(file_path)
            if exif:
                return exif

        # Try PIL for standard formats (and as fallback for RAW)
        return self._extract_exif_with_pil(file_path)

    def _extract_exif_with_pil(self, file_path: Path) -> Optional[Dict[int, Any]]:
        """
        Extract EXIF data using PIL/Pillow.

        Works for JPEG, TIFF, PNG, WEBP, and some other formats.
        """
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                exif = img._getexif()
                if exif:
                    return exif

                # Some formats store EXIF in 'exif' key of info dict
                if hasattr(img, 'info') and 'exif' in img.info:
                    # Try to parse the raw EXIF bytes
                    try:
                        from PIL.ExifTags import TAGS
                        exif_bytes = img.info['exif']
                        # This is raw bytes, _getexif() should have handled it
                        # but try getexif() method (newer PIL)
                        if hasattr(img, 'getexif'):
                            exif_data = img.getexif()
                            if exif_data:
                                return dict(exif_data)
                    except Exception:
                        pass

        except ImportError:
            pass
        except Exception:
            pass

        return None

    def _extract_exif_from_raw(self, file_path: Path) -> Optional[Dict[int, Any]]:
        """
        Extract EXIF data from RAW files using rawpy.

        RAW files often have EXIF data in embedded JPEG thumbnails.
        """
        try:
            import rawpy
            import io
            from PIL import Image

            with rawpy.imread(str(file_path)) as raw:
                # Try to get embedded thumbnail which usually has EXIF
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        # Parse the JPEG thumbnail for EXIF
                        thumb_bytes = io.BytesIO(thumb.data)
                        with Image.open(thumb_bytes) as thumb_img:
                            exif = thumb_img._getexif()
                            if exif:
                                return exif
                except Exception:
                    pass

        except ImportError:
            pass
        except Exception:
            pass

        return None

    def _parse_exif_date(self, date_value: Any) -> Optional[datetime]:
        """
        Parse EXIF date value to datetime object.

        EXIF dates are typically strings in "YYYY:MM:DD HH:MM:SS" format,
        but can sometimes be bytes or other types.

        Args:
            date_value: The EXIF date value (string, bytes, or other)

        Returns:
            datetime object or None if parsing failed
        """
        if date_value is None:
            return None

        # Convert bytes to string if necessary
        if isinstance(date_value, bytes):
            try:
                date_value = date_value.decode('utf-8', errors='ignore')
            except Exception:
                return None

        if not isinstance(date_value, str):
            return None

        # Strip any null characters or whitespace
        date_str = date_value.strip('\x00').strip()

        if not date_str:
            return None

        try:
            return datetime.strptime(date_str, self.EXIF_DATETIME_FORMAT)
        except (ValueError, TypeError):
            # Try alternative formats
            alternative_formats = [
                "%Y-%m-%d %H:%M:%S",      # ISO format
                "%Y/%m/%d %H:%M:%S",      # Slash format
                "%Y:%m:%d",               # Date only
                "%Y-%m-%d",               # ISO date only
            ]
            for fmt in alternative_formats:
                try:
                    return datetime.strptime(date_str, fmt)
                except (ValueError, TypeError):
                    continue

        return None

    def _get_file_modified_date(self, file_path: Path) -> datetime:
        """
        Get file's last modified date.

        Args:
            file_path: Path to the file

        Returns:
            datetime of file's last modification
        """
        try:
            return datetime.fromtimestamp(os.path.getmtime(file_path))
        except OSError:
            # If file doesn't exist or other error, return current time
            return datetime.now()
