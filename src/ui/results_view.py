"""Results view for displaying duplicate groups."""

from typing import List, Dict, Set, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QCheckBox, QFrame, QHeaderView, QComboBox,
    QAbstractItemView, QMenu
)
from PyQt6.QtCore import Qt, pyqtSignal, QProcess
from PyQt6.QtGui import QColor, QBrush, QIcon, QPixmap, QAction

from ..models.duplicate_group import DuplicateGroup
from ..models.image_file import ImageFile


class ResultsView(QWidget):
    """View for displaying duplicate detection results."""

    selection_changed = pyqtSignal(list)  # Emits list of selected ImageFiles
    images_for_preview = pyqtSignal(list)  # Emits list of images to preview

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: List[DuplicateGroup] = []
        self._selected_for_action: Set[str] = set()  # Paths of files selected for deletion/move
        self._setup_ui()

    def _setup_ui(self):
        """Set up the results view UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()

        # Filter dropdown
        self.filter_label = QLabel("Show:")
        toolbar.addWidget(self.filter_label)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Duplicates",
            "Intra-directory Only",
            "Cross-directory Only"
        ])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.filter_combo)

        toolbar.addStretch()

        # Summary label
        self.summary_label = QLabel("No duplicates found")
        toolbar.addWidget(self.summary_label)

        layout.addLayout(toolbar)

        # Tree widget for results
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "Name", "Size", "Resolution", "Path", "Action"
        ])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)

        # Set column widths
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.tree.setColumnWidth(0, 200)

        # Enable context menu
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.tree, stretch=1)

        # Action buttons
        button_layout = QHBoxLayout()

        self.select_keepers_btn = QPushButton("Select All Keepers")
        self.select_keepers_btn.clicked.connect(self._select_all_keepers)
        button_layout.addWidget(self.select_keepers_btn)

        self.select_suggested_btn = QPushButton("Select Suggested Deletes")
        self.select_suggested_btn.clicked.connect(self._select_suggested_deletes)
        button_layout.addWidget(self.select_suggested_btn)

        self.clear_selection_btn = QPushButton("Clear Selection")
        self.clear_selection_btn.clicked.connect(self._clear_selection)
        button_layout.addWidget(self.clear_selection_btn)

        button_layout.addStretch()

        self.selected_count_label = QLabel("Selected: 0 files")
        button_layout.addWidget(self.selected_count_label)

        layout.addLayout(button_layout)

    def set_groups(self, groups: List[DuplicateGroup]):
        """
        Set the duplicate groups to display (replaces all existing).

        Args:
            groups: List of DuplicateGroup objects.
        """
        self._groups = groups
        self._selected_for_action.clear()
        self._populate_tree()
        self._update_summary()

    def add_groups(self, new_groups: List[DuplicateGroup]):
        """
        Add new duplicate groups to the display (incremental update).

        Args:
            new_groups: List of new DuplicateGroup objects to add.
        """
        if not new_groups:
            return

        self._groups.extend(new_groups)

        # Add new groups to tree without clearing
        self.tree.blockSignals(True)

        filter_mode = self.filter_combo.currentIndex()

        for group in new_groups:
            # Apply filter
            if filter_mode == 1 and not group.is_intra_directory:
                continue
            if filter_mode == 2 and group.is_intra_directory:
                continue

            # Create group item
            group_item = QTreeWidgetItem()
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", group.group_id))

            group_type = "Intra-dir" if group.is_intra_directory else "Cross-dir"
            dir_name = group.directory.name if group.directory else "mixed"
            group_item.setText(0, f"[{dir_name}] Group {group.group_id} ({group.file_count} files)")
            group_item.setText(4, f"Savings: {group.potential_savings_str}")

            # Expand group item
            group_item.setExpanded(True)

            self.tree.addTopLevelItem(group_item)

            # Add image items
            for image in group.images:
                is_keep = image == group.suggested_keep
                img_item = self._create_image_item(image, is_keep, group.group_id)
                group_item.addChild(img_item)

        self.tree.blockSignals(False)
        self._update_summary()

        # Scroll to show latest additions
        if self.tree.topLevelItemCount() > 0:
            last_item = self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
            self.tree.scrollToItem(last_item)

    def _populate_tree(self):
        """Populate the tree with duplicate groups."""
        self.tree.blockSignals(True)
        self.tree.clear()

        filter_mode = self.filter_combo.currentIndex()

        for group in self._groups:
            # Apply filter
            if filter_mode == 1 and not group.is_intra_directory:
                continue
            if filter_mode == 2 and group.is_intra_directory:
                continue

            # Create group item
            group_item = QTreeWidgetItem()
            group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", group.group_id))

            group_type = "Intra-dir" if group.is_intra_directory else "Cross-dir"
            group_item.setText(0, f"Group {group.group_id} ({group.file_count} files) - {group_type}")
            group_item.setText(4, f"Savings: {group.potential_savings_str}")

            # Expand group item
            group_item.setExpanded(True)

            self.tree.addTopLevelItem(group_item)

            # Add image items
            for image in group.images:
                is_keep = image == group.suggested_keep
                img_item = self._create_image_item(image, is_keep, group.group_id)
                group_item.addChild(img_item)

        self.tree.blockSignals(False)

    def _create_image_item(
        self,
        image: ImageFile,
        is_suggested_keep: bool,
        group_id: int
    ) -> QTreeWidgetItem:
        """Create a tree item for an image."""
        item = QTreeWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, Qt.ItemDataRole.UserRole, ("image", str(image.path)))

        # Set checkbox state (unchecked = keep, checked = delete)
        if is_suggested_keep:
            item.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            item.setCheckState(0, Qt.CheckState.Checked)
            self._selected_for_action.add(str(image.path))

        # Set text
        item.setText(0, image.filename)
        item.setText(1, image.file_size_str)
        item.setText(2, image.dimensions_str)
        item.setText(3, str(image.directory))
        item.setText(4, "KEEP" if is_suggested_keep else "DELETE")

        # Style the action column based on recommendation
        if is_suggested_keep:
            item.setForeground(4, QBrush(QColor("green")))
        else:
            item.setForeground(4, QBrush(QColor("red")))

        return item

    def _apply_filter(self):
        """Apply the current filter and repopulate."""
        self._populate_tree()

    def _update_summary(self):
        """Update the summary label."""
        total_groups = len(self._groups)
        total_files = sum(len(g) for g in self._groups)
        potential_savings = sum(g.potential_savings for g in self._groups)

        self.summary_label.setText(
            f"{total_groups} groups, {total_files} files, "
            f"potential savings: {self._format_size(potential_savings)}"
        )

    def _on_selection_changed(self):
        """Handle tree selection change."""
        selected_items = self.tree.selectedItems()
        images = []

        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "image":
                path = data[1]
                # Find the image in groups
                for group in self._groups:
                    for img in group.images:
                        if str(img.path) == path:
                            images.append(img)
                            break

        self.selection_changed.emit(images)

        # Emit for preview (first two)
        if len(images) >= 1:
            self.images_for_preview.emit(images[:2])

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        """Handle item checkbox change."""
        if column != 0:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "image":
            return

        path = data[1]
        is_checked = item.checkState(0) == Qt.CheckState.Checked

        if is_checked:
            self._selected_for_action.add(path)
            item.setText(4, "DELETE")
            item.setForeground(4, QBrush(QColor("red")))
        else:
            self._selected_for_action.discard(path)
            item.setText(4, "KEEP")
            item.setForeground(4, QBrush(QColor("green")))

        self._update_selected_count()

    def _select_all_keepers(self):
        """Uncheck all suggested keepers (mark as keep)."""
        self.tree.blockSignals(True)

        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                # Find if this is a keeper
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data[0] == "image":
                    path = data[1]
                    # Check if it's a suggested keep
                    for group in self._groups:
                        if group.suggested_keep and str(group.suggested_keep.path) == path:
                            child.setCheckState(0, Qt.CheckState.Unchecked)
                            self._selected_for_action.discard(path)
                            child.setText(4, "KEEP")
                            child.setForeground(4, QBrush(QColor("green")))
                            break

        self.tree.blockSignals(False)
        self._update_selected_count()

    def _select_suggested_deletes(self):
        """Check all suggested deletes."""
        self.tree.blockSignals(True)

        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data[0] == "image":
                    path = data[1]
                    # Check if it's NOT a suggested keep
                    is_keeper = False
                    for group in self._groups:
                        if group.suggested_keep and str(group.suggested_keep.path) == path:
                            is_keeper = True
                            break

                    if not is_keeper:
                        child.setCheckState(0, Qt.CheckState.Checked)
                        self._selected_for_action.add(path)
                        child.setText(4, "DELETE")
                        child.setForeground(4, QBrush(QColor("red")))

        self.tree.blockSignals(False)
        self._update_selected_count()

    def _clear_selection(self):
        """Clear all selections (uncheck all)."""
        self.tree.blockSignals(True)

        for i in range(self.tree.topLevelItemCount()):
            group_item = self.tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setText(4, "KEEP")
                child.setForeground(4, QBrush(QColor("green")))

        self._selected_for_action.clear()
        self.tree.blockSignals(False)
        self._update_selected_count()

    def _update_selected_count(self):
        """Update the selected count label."""
        count = len(self._selected_for_action)
        self.selected_count_label.setText(f"Selected for action: {count} files")

    def get_selected_for_action(self) -> List[ImageFile]:
        """Get list of images selected for deletion/move."""
        images = []
        for group in self._groups:
            for img in group.images:
                if str(img.path) in self._selected_for_action:
                    images.append(img)
        return images

    def clear(self):
        """Clear all results."""
        self._groups = []
        self._selected_for_action.clear()
        self.tree.clear()
        self.summary_label.setText("No duplicates found")
        self._update_selected_count()

    def _format_size(self, size: int) -> str:
        """Format size in bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _show_context_menu(self, position):
        """Show context menu for tree items."""
        item = self.tree.itemAt(position)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "image":
            return

        file_path = data[1]

        menu = QMenu(self)

        # Open in Finder action
        open_finder_action = QAction("Show in Finder", self)
        open_finder_action.triggered.connect(lambda: self._open_in_finder(file_path))
        menu.addAction(open_finder_action)

        # Open file action
        open_file_action = QAction("Open File", self)
        open_file_action.triggered.connect(lambda: self._open_file(file_path))
        menu.addAction(open_file_action)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _open_in_finder(self, file_path: str):
        """Open the file's location in Finder and select it."""
        QProcess.startDetached("open", ["-R", file_path])

    def _open_file(self, file_path: str):
        """Open the file with the default application."""
        QProcess.startDetached("open", [file_path])
