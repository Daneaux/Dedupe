"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
import tempfile
import shutil

from PIL import Image
import numpy as np


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def sample_images_dir(temp_dir):
    """Create sample images for testing."""
    # Create subdirectories
    exact_dir = temp_dir / "exact_duplicates"
    near_dir = temp_dir / "near_duplicates"
    different_dir = temp_dir / "different"

    exact_dir.mkdir()
    near_dir.mkdir()
    different_dir.mkdir()

    # Create exact duplicates (same image, different names)
    img1 = create_test_image(500, 500, color=(255, 0, 0))
    img1.save(exact_dir / "image_a.jpg", quality=95)
    img1.save(exact_dir / "image_a_copy.jpg", quality=95)
    img1.save(exact_dir / "image_a_another.jpg", quality=95)

    # Create near duplicates (resized versions)
    img2 = create_test_image(800, 600, color=(0, 255, 0))
    img2.save(near_dir / "photo_original.jpg", quality=95)

    img2_small = img2.resize((400, 300), Image.Resampling.LANCZOS)
    img2_small.save(near_dir / "photo_resized.jpg", quality=85)

    img2_tiny = img2.resize((200, 150), Image.Resampling.LANCZOS)
    img2_tiny.save(near_dir / "photo_thumbnail.jpg", quality=75)

    # Create different images
    img3 = create_test_image(600, 400, color=(0, 0, 255))
    img3.save(different_dir / "unique_image.jpg", quality=95)

    img4 = create_test_image(600, 400, color=(255, 255, 0))
    img4.save(different_dir / "another_unique.jpg", quality=95)

    return temp_dir


@pytest.fixture
def mixed_format_images(temp_dir):
    """Create images in various formats."""
    # JPEG
    img = create_test_image(400, 300, color=(128, 64, 192))
    img.save(temp_dir / "test.jpg", quality=90)
    img.save(temp_dir / "test.jpeg", quality=90)

    # PNG
    img.save(temp_dir / "test.png")

    # GIF
    img.save(temp_dir / "test.gif")

    # TIFF
    img.save(temp_dir / "test.tiff")

    # BMP
    img.save(temp_dir / "test.bmp")

    # Create a text file (should be ignored)
    (temp_dir / "readme.txt").write_text("This is not an image")

    return temp_dir


def create_test_image(width: int, height: int, color: tuple = None) -> Image.Image:
    """
    Create a test image with some pattern.

    Args:
        width: Image width
        height: Image height
        color: Optional base color (r, g, b)

    Returns:
        PIL Image
    """
    if color is None:
        color = (128, 128, 128)

    # Create image with gradient and pattern
    img = Image.new("RGB", (width, height), color)
    pixels = img.load()

    # Add some pattern to make images distinct
    for x in range(width):
        for y in range(height):
            # Create a simple gradient pattern
            r = (color[0] + x % 128) % 256
            g = (color[1] + y % 128) % 256
            b = (color[2] + (x + y) % 64) % 256
            pixels[x, y] = (r, g, b)

    return img
