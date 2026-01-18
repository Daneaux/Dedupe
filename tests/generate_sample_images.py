#!/usr/bin/env python3
"""Generate sample test images for manual testing."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import random


def create_image_with_pattern(
    width: int,
    height: int,
    base_color: tuple,
    pattern: str = "gradient"
) -> Image.Image:
    """Create an image with a specific pattern."""
    img = Image.new("RGB", (width, height), base_color)
    draw = ImageDraw.Draw(img)

    if pattern == "gradient":
        # Horizontal gradient
        for x in range(width):
            r = int(base_color[0] * (1 - x / width) + 255 * (x / width))
            g = int(base_color[1] * (1 - x / width) + 128 * (x / width))
            b = int(base_color[2] * (1 - x / width) + 64 * (x / width))
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            draw.line([(x, 0), (x, height)], fill=(r, g, b))

    elif pattern == "circles":
        # Random circles
        for _ in range(20):
            x = random.randint(0, width)
            y = random.randint(0, height)
            r = random.randint(20, 100)
            color = (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255)
            )
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    elif pattern == "stripes":
        # Vertical stripes
        stripe_width = 40
        for i in range(0, width, stripe_width * 2):
            color = (
                (base_color[0] + 100) % 256,
                (base_color[1] + 100) % 256,
                (base_color[2] + 100) % 256
            )
            draw.rectangle([i, 0, i + stripe_width, height], fill=color)

    return img


def generate_sample_images():
    """Generate sample images for testing."""
    # Create output directory
    output_dir = Path(__file__).parent / "sample_images"
    output_dir.mkdir(exist_ok=True)

    # Create subdirectories
    (output_dir / "exact_duplicates").mkdir(exist_ok=True)
    (output_dir / "near_duplicates").mkdir(exist_ok=True)
    (output_dir / "different").mkdir(exist_ok=True)

    print("Generating sample test images...")

    # 1. Exact duplicates - same image, different names
    print("Creating exact duplicates...")
    img1 = create_image_with_pattern(800, 600, (100, 150, 200), "gradient")
    img1.save(output_dir / "exact_duplicates" / "sunset_original.jpg", quality=95)
    img1.save(output_dir / "exact_duplicates" / "sunset_copy.jpg", quality=95)
    img1.save(output_dir / "exact_duplicates" / "IMG_2024_sunset.jpg", quality=95)

    # 2. Near duplicates - resized versions
    print("Creating near duplicates (resized)...")
    img2 = create_image_with_pattern(1920, 1080, (200, 100, 50), "circles")
    img2.save(output_dir / "near_duplicates" / "photo_fullres.jpg", quality=95)

    img2_medium = img2.resize((1280, 720), Image.Resampling.LANCZOS)
    img2_medium.save(output_dir / "near_duplicates" / "photo_medium.jpg", quality=90)

    img2_small = img2.resize((640, 360), Image.Resampling.LANCZOS)
    img2_small.save(output_dir / "near_duplicates" / "photo_thumbnail.jpg", quality=80)

    img2_tiny = img2.resize((320, 180), Image.Resampling.LANCZOS)
    img2_tiny.save(output_dir / "near_duplicates" / "photo_tiny.jpg", quality=70)

    # 3. Near duplicates - different quality
    print("Creating near duplicates (different quality)...")
    img3 = create_image_with_pattern(1200, 900, (50, 200, 100), "stripes")
    img3.save(output_dir / "near_duplicates" / "landscape_high.jpg", quality=98)
    img3.save(output_dir / "near_duplicates" / "landscape_medium.jpg", quality=75)
    img3.save(output_dir / "near_duplicates" / "landscape_low.jpg", quality=50)

    # 4. Different images
    print("Creating different images...")
    img4 = create_image_with_pattern(800, 600, (255, 100, 100), "gradient")
    img4.save(output_dir / "different" / "red_sunset.jpg", quality=90)

    img5 = create_image_with_pattern(800, 600, (100, 255, 100), "circles")
    img5.save(output_dir / "different" / "green_abstract.jpg", quality=90)

    img6 = create_image_with_pattern(800, 600, (100, 100, 255), "stripes")
    img6.save(output_dir / "different" / "blue_lines.jpg", quality=90)

    img7 = create_image_with_pattern(1024, 768, (200, 200, 50), "gradient")
    img7.save(output_dir / "different" / "yellow_scene.jpg", quality=90)

    # Summary
    total_files = sum(1 for _ in output_dir.rglob("*.jpg"))
    print(f"\nGenerated {total_files} sample images in: {output_dir}")
    print("\nDirectory structure:")
    print("  exact_duplicates/   - 3 identical images with different names")
    print("  near_duplicates/    - 7 images (resized versions, different quality)")
    print("  different/          - 4 unique images")


if __name__ == "__main__":
    generate_sample_images()
