"""Export functionality for duplicate detection results."""

import csv
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from ..models.duplicate_group import DuplicateGroup
from ..models.image_file import ImageFile


class ResultsExporter:
    """Exports duplicate detection results to various formats."""

    def export_to_csv(
        self,
        groups: List[DuplicateGroup],
        output_path: Path,
        include_scores: bool = True
    ) -> bool:
        """
        Export duplicate groups to CSV file.

        CSV columns:
        - group_id: Numeric identifier for the duplicate group
        - file1_path: Path to first file in pair
        - file2_path: Path to second file in pair
        - file1_size: Size of first file
        - file2_size: Size of second file
        - file1_resolution: Resolution of first file
        - file2_resolution: Resolution of second file
        - similarity_score: Similarity between the pair
        - suggested_keep: Which file is suggested to keep
        - suggested_action: KEEP or DELETE for file1

        Args:
            groups: List of DuplicateGroup objects.
            output_path: Path for the output CSV file.
            include_scores: Whether to include similarity scores.

        Returns:
            True if export was successful.
        """
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Write header
                header = [
                    "group_id",
                    "file1_path",
                    "file2_path",
                    "file1_size_bytes",
                    "file2_size_bytes",
                    "file1_resolution",
                    "file2_resolution",
                    "file1_dimensions",
                    "file2_dimensions",
                ]

                if include_scores:
                    header.append("similarity_score")

                header.extend([
                    "suggested_keep",
                    "file1_action"
                ])

                writer.writerow(header)

                # Write data for each duplicate pair
                for group in groups:
                    if len(group.images) < 2:
                        continue

                    suggested_keep = group.suggested_keep

                    # Generate all pairs in the group
                    for i, img1 in enumerate(group.images):
                        for img2 in group.images[i + 1:]:
                            # Get similarity score if available
                            score = group.get_similarity(img1, img2)

                            # Determine suggested action for img1
                            if suggested_keep:
                                if img1 == suggested_keep:
                                    action = "KEEP"
                                else:
                                    action = "DELETE"
                            else:
                                action = "UNKNOWN"

                            row = [
                                group.group_id,
                                str(img1.path),
                                str(img2.path),
                                img1.file_size,
                                img2.file_size,
                                img1.resolution,
                                img2.resolution,
                                img1.dimensions_str,
                                img2.dimensions_str,
                            ]

                            if include_scores:
                                row.append(f"{score:.4f}" if score else "N/A")

                            row.extend([
                                str(suggested_keep.path) if suggested_keep else "N/A",
                                action
                            ])

                            writer.writerow(row)

            return True

        except Exception as e:
            print(f"Export failed: {e}")
            return False

    def export_summary(
        self,
        groups: List[DuplicateGroup],
        output_path: Path,
        root_dir: Optional[Path] = None
    ) -> bool:
        """
        Export a summary report of duplicate detection results.

        Args:
            groups: List of DuplicateGroup objects.
            output_path: Path for the output text file.
            root_dir: Optional root directory for context.

        Returns:
            True if export was successful.
        """
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            total_files = sum(len(g) for g in groups)
            total_duplicates = sum(len(g.suggested_delete) for g in groups)
            potential_savings = sum(g.potential_savings for g in groups)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("=" * 60 + "\n")
                f.write("DUPLICATE IMAGE FINDER - SUMMARY REPORT\n")
                f.write("=" * 60 + "\n\n")

                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                if root_dir:
                    f.write(f"Root Directory: {root_dir}\n")
                f.write("\n")

                f.write("-" * 40 + "\n")
                f.write("STATISTICS\n")
                f.write("-" * 40 + "\n")
                f.write(f"Total duplicate groups: {len(groups)}\n")
                f.write(f"Total files in groups: {total_files}\n")
                f.write(f"Suggested for deletion: {total_duplicates}\n")
                f.write(f"Potential space savings: {self._format_size(potential_savings)}\n")
                f.write("\n")

                # Intra vs cross directory
                intra = [g for g in groups if g.is_intra_directory]
                cross = [g for g in groups if not g.is_intra_directory]

                f.write(f"Intra-directory groups: {len(intra)}\n")
                f.write(f"Cross-directory groups: {len(cross)}\n")
                f.write("\n")

                f.write("-" * 40 + "\n")
                f.write("DUPLICATE GROUPS\n")
                f.write("-" * 40 + "\n\n")

                for group in groups:
                    f.write(f"Group {group.group_id} ({group.file_count} files)\n")
                    f.write(f"  Type: {'Intra-directory' if group.is_intra_directory else 'Cross-directory'}\n")
                    if group.directory:
                        f.write(f"  Directory: {group.directory}\n")
                    f.write(f"  Potential savings: {group.potential_savings_str}\n")
                    f.write(f"  Average similarity: {group.get_average_similarity():.2%}\n")
                    f.write("\n")

                    for img in group.images:
                        status = "[KEEP]" if img == group.suggested_keep else "[DELETE]"
                        f.write(f"    {status} {img.filename}\n")
                        f.write(f"           Path: {img.path}\n")
                        f.write(f"           Size: {img.file_size_str}\n")
                        f.write(f"           Resolution: {img.dimensions_str}\n")
                        f.write("\n")

                    f.write("-" * 40 + "\n\n")

            return True

        except Exception as e:
            print(f"Summary export failed: {e}")
            return False

    def export_file_list(
        self,
        images: List[ImageFile],
        output_path: Path,
        action: str = "delete"
    ) -> bool:
        """
        Export a simple list of file paths (for scripting).

        Args:
            images: List of ImageFile objects.
            output_path: Path for the output file.
            action: Description of what to do with these files.

        Returns:
            True if export was successful.
        """
        try:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# Files to {action}\n")
                f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total files: {len(images)}\n\n")

                for img in images:
                    f.write(f"{img.path}\n")

            return True

        except Exception as e:
            print(f"File list export failed: {e}")
            return False

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
