#!/usr/bin/python

import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, 
    QPushButton, QSplitter, QLabel, QLineEdit, QMenu, QMessageBox, QComboBox,
    QFileDialog
)
from PyQt6.QtCore import Qt, QItemSelectionModel
from PyQt6.QtGui import QIcon

from bdsm import *


class ReorderOnlyTable(QTableWidget):
    """Custom QTableWidget that intelligently handles drag-drop reordering"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drag_row = -1
        self._drop_row = -1
    
    def is_separator_row(self, row):
        """Check if a row is a separator"""
        name_item = self.item(row, 2)
        if name_item:
            return name_item.data(Qt.ItemDataRole.UserRole) == "separator"
        return False
    
    def update_priority_numbers(self):
        """Update priority numbers to match current row order (skip separators)"""
        priority = 1
        for row in range(self.rowCount()):
            if self.is_separator_row(row):
                continue  # Skip separators
            priority_item = self.item(row, 0)
            if priority_item:
                priority_item.setText(str(priority))
                priority += 1
    
    def get_separator_children(self, separator_row):
        """Get all rows that belong to a separator (until next separator or end)"""
        children = []
        for r in range(separator_row + 1, self.rowCount()):
            if self.is_separator_row(r):
                break
            children.append(r)
        return children

    def collect_row_data(self, row):
        """Collect all data from a row for later reconstruction"""
        from PyQt6.QtGui import QColor, QBrush
        
        is_sep = self.is_separator_row(row)
        if is_sep:
            return {
                'is_separator': True,
                'name': self.item(row, 2).data(Qt.ItemDataRole.UserRole + 1),
                'collapse_state': self.item(row, 0).text(),
                'hidden': self.isRowHidden(row)
            }
        else:
            return {
                'is_separator': False,
                'name': self.item(row, 2).text(),
                'checkbox': self.item(row, 1).checkState(),
                'hidden': self.isRowHidden(row)
            }

    def create_row_from_data(self, row, data):
        """Create a row from collected data"""
        from PyQt6.QtGui import QFont
        
        if data['is_separator']:
            priority_item = QTableWidgetItem(data['collapse_state'])
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem("")
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.setItem(row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(data['name'])
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setData(Qt.ItemDataRole.UserRole, "separator")
            name_item.setData(Qt.ItemDataRole.UserRole + 1, data['name'])
            self.setItem(row, 2, name_item)
        else:
            priority_item = QTableWidgetItem("")
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.setItem(row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(data['checkbox'])
            self.setItem(row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(data['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 2, name_item)
        
        if data['hidden']:
            self.setRowHidden(row, True)

    def dropEvent(self, event):
        from PyQt6.QtGui import QFont
        
        # Get drop position info
        drop_pos = event.position().toPoint()
        index = self.indexAt(drop_pos)
        
        # Get all selected rows (unique, sorted)
        selected = self.selectedItems()
        if not selected:
            event.ignore()
            return
        
        selected_rows = sorted(set(item.row() for item in selected))
        
        # Determine drop target
        if not index.isValid():
            # Dropping in empty space - target is end
            target_row = self.rowCount()
        else:
            drop_row = index.row()
            rect = self.visualRect(index)
            y = drop_pos.y()
            
            # Determine if dropping in top half or bottom half of the row
            mid_point = rect.top() + rect.height() / 2
            if y < mid_point:
                # Top half - insert before this row
                target_row = drop_row
            else:
                # Bottom half - insert after this row
                target_row = drop_row + 1
        
        event.ignore()
        
        # Check if dropping within a contiguous selection (no-op)
        if len(selected_rows) > 0:
            min_sel = min(selected_rows)
            max_sel = max(selected_rows)
            # Check if selection is contiguous and target is within it
            if selected_rows == list(range(min_sel, max_sel + 1)):
                if min_sel <= target_row <= max_sel + 1:
                    return
        
        # Collect data for all selected rows before removing
        rows_data = []
        for row in selected_rows:
            rows_data.append(self.collect_row_data(row))
        
        # Remove rows from bottom to top to preserve indices
        for row in reversed(selected_rows):
            self.removeRow(row)
        
        # Adjust target based on how many rows were removed before it
        rows_removed_before_target = sum(1 for r in selected_rows if r < target_row)
        adjusted_target = target_row - rows_removed_before_target
        
        # Insert all rows at the new position
        new_selection_rows = []
        for i, data in enumerate(rows_data):
            insert_row = adjusted_target + i
            self.insertRow(insert_row)
            self.create_row_from_data(insert_row, data)
            new_selection_rows.append(insert_row)
        
        # Select all moved rows
        self.clearSelection()
        selection_model = self.selectionModel()
        for row in new_selection_rows:
            for col in range(self.columnCount()):
                idx = self.model().index(row, col)
                selection_model.select(idx, QItemSelectionModel.SelectionFlag.Select)
        
        self.update_priority_numbers()
        
        if self.selectedItems():
            self.itemChanged.emit(self.selectedItems()[0])


class BDSM(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BrainDead Simple Modloader (BDSM "+VERSION+")")
        self.setWindowIcon(QIcon("logo.png"))
        self.resize(1000, 600)
        
        # Flag to prevent recursive saves during initialization
        self._loading = True
        
        # UI scaling factor
        self._scale_factor = 1.0
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Splitter for left panel and main content
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel (plugins list and file explorer)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Vertical splitter for left panel
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_layout.addWidget(left_splitter)
        
        # Top section - File explorer
        file_explorer_widget = QWidget()
        file_explorer_layout = QVBoxLayout(file_explorer_widget)
        file_explorer_layout.setContentsMargins(0, 0, 0, 0)
        
        # Label for file explorer
        self.explorer_label = QLabel("Select a mod to view files")
        self.explorer_label.setStyleSheet("padding: 5px; font-weight: bold;")
        self.explorer_label.setWordWrap(True)  # Enable word wrapping for long mod names
        file_explorer_layout.addWidget(self.explorer_label)
        
        self.file_explorer = QTreeWidget()
        self.file_explorer.setHeaderLabel("Mod Files")
        self.file_explorer.setHeaderHidden(True)  # Hide the header
        self.file_explorer.itemDoubleClicked.connect(self.on_file_explorer_double_click)
        file_explorer_layout.addWidget(self.file_explorer)
        
        left_splitter.addWidget(file_explorer_widget)

        # Bottom section - Plugins list
        plugins_widget = QWidget()
        plugins_layout = QVBoxLayout(plugins_widget)
        plugins_layout.setContentsMargins(0, 0, 0, 0)
        
        self.plugins_label = QLabel("Loaded Plugins")
        self.plugins_label.setStyleSheet("padding: 5px; font-weight: bold;")
        plugins_layout.addWidget(self.plugins_label)
        
        self.plugins_list = QTreeWidget()
        self.plugins_list.setHeaderHidden(True)
        plugins_layout.addWidget(self.plugins_list)
        
        left_splitter.addWidget(plugins_widget)
        
        # Set initial sizes for left splitter (plugins list : file explorer)
        left_splitter.setSizes([400, 200])
        
        splitter.addWidget(left_panel)
        
        # Right panel (mod list)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Load order preset dropdown
        preset_layout = QHBoxLayout()
        
        # Settings button
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(30)
        self.settings_button.setToolTip("Open Settings")
        self.settings_button.clicked.connect(self.open_settings)
        preset_layout.addWidget(self.settings_button)
        
        preset_label = QLabel("Load Order:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("loadorder.txt")
        # Add more presets here later
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        right_layout.addLayout(preset_layout)
        
        # Mod table - with ReorderOnlyTable subclass for drag-drop
        self.mod_table = ReorderOnlyTable(0, 3)
        self.mod_table.setHorizontalHeaderLabels(["#", "", "Mod Name"])
        self.mod_table.verticalHeader().setVisible(False)  # Hide row numbers
        self.mod_table.itemSelectionChanged.connect(self.on_mod_selected)
        self.mod_table.itemChanged.connect(self.on_item_changed)
        self.mod_table.cellClicked.connect(self.on_cell_clicked)
        self.mod_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mod_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)  # Allow multi-select
        self.mod_table.setDragEnabled(True)
        self.mod_table.setAcceptDrops(True)
        self.mod_table.setDragDropOverwriteMode(False)
        self.mod_table.setDropIndicatorShown(True)
        self.mod_table.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        self.mod_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mod_table.customContextMenuRequested.connect(self.show_context_menu)
        self.mod_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.mod_table.setSortingEnabled(False)  # We'll handle sorting manually
        
        # Enable F2 key for renaming
        self.mod_table.keyPressEvent = self.table_key_press_event
        
        right_layout.addWidget(self.mod_table)
        
        # Track sorting state
        self._is_sorted_alphabetically = False
        self._sort_ascending = True  # Track sort direction
        
        # Search box at bottom
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search mods...")
        self.search_box.textChanged.connect(self.filter_mods)
        right_layout.addWidget(self.search_box)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(40)
        self.add_button.setToolTip("Add Mod")
        self.move_up_button = QPushButton("↑")
        self.move_up_button.setFixedWidth(40)
        self.move_up_button.setToolTip("Move Up")
        self.move_down_button = QPushButton("↓")
        self.move_down_button.setFixedWidth(40)
        self.move_down_button.setToolTip("Move Down")
        self.enable_button = QPushButton("Enable All")
        self.disable_button = QPushButton("Disable All")
        
        # Vertical separator
        separator = QLabel("|")
        separator.setStyleSheet("color: gray; font-size: 20px; padding: 0px; margin: 0px 5px;")
        separator.setFixedWidth(10)
        
        self.save_button = QPushButton("Save Load Order")
        self.load_button = QPushButton("Load Mods")
        self.unload_button = QPushButton("Unload Mods")
        
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.move_up_button)
        button_layout.addWidget(self.move_down_button)
        button_layout.addWidget(self.enable_button)
        button_layout.addWidget(self.disable_button)
        button_layout.addWidget(separator)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.unload_button)
        right_layout.addLayout(button_layout)
        
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])
        
        # Track which rows are separators and their collapsed state
        self._separator_rows = {}  # row -> collapsed state
        
        # Populate table with load order
        mods = load_list() 
        for mod in mods: 
            if mod.startswith('#'):  # Separator
                self.add_separator(mod[1:].strip())  # Remove # and whitespace
            elif mod.startswith('*') or mod.startswith('~'):  # Disabled mods
                self.add_mod(mod.lstrip("*~"), False)
            else: 
                self.add_mod(mod, True)
        
        # Make checkbox column smaller
        header = self.mod_table.horizontalHeader()
        header.setMinimumSectionSize(15)
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        self.mod_table.setColumnWidth(0, 40)  # Priority number column
        self.mod_table.setColumnWidth(1, 25)  # Checkbox column
        self.mod_table.setColumnWidth(2, 600)  # Mod name column
        
        # Connect buttons
        self.add_button.clicked.connect(self.add_mod_dialog)
        self.enable_button.clicked.connect(self.enable_all)
        self.disable_button.clicked.connect(self.disable_all)
        self.save_button.clicked.connect(self.save_load_order)
        self.move_up_button.clicked.connect(self.move_mod_up)
        self.move_down_button.clicked.connect(self.move_mod_down)
        self.load_button.clicked.connect(self.load_mods)
        self.unload_button.clicked.connect(self.unload_mods)
        
        # Initially disable move buttons
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
        
        # Status bar
        self.statusBar().showMessage("Ready")
        self.update_status()
        self.update_unload_button_state()
        self.load_plugins_list()
        
        # Finished loading - enable auto-save
        self._loading = False

    def open_settings(self):
        """Open the config.txt file with the system's default text editor"""
        import subprocess
        import platform
        
        config_path = Path(CONFIG_FILE)
        
        if not config_path.exists():
            QMessageBox.warning(self, "Error", f"Config file not found:\n{config_path}")
            return
        
        try:
            if platform.system() == 'Windows':
                subprocess.run(['start', '', str(config_path)], shell=True)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(config_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(config_path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open config file:\n{str(e)}")

    def load_plugins_list(self):
        """Load plugins from BACKUP_DIR/Plugins.txt or plugins.txt"""
        self.plugins_list.clear()
        
        try:
            backup_path = Path(BACKUP_DIR)
            plugins_file = None
            
            # Check for Plugins.txt or plugins.txt
            for filename in ['Plugins.txt', 'plugins.txt']:
                potential_path = backup_path / filename
                if potential_path.exists():
                    plugins_file = potential_path
                    break
            
            if plugins_file:
                with open(plugins_file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            item = QTreeWidgetItem([line])
                            self.plugins_list.addTopLevelItem(item)
        except Exception:
            pass  # Just show empty list on any error

    def update_unload_button_state(self):
        """Enable/disable unload button based on whether BACKUP_DIR has content"""
        try:
            backup_path = Path(BACKUP_DIR)
            if backup_path.exists() and any(backup_path.iterdir()):
                self.unload_button.setEnabled(True)
            else:
                self.unload_button.setEnabled(False)
        except Exception:
            self.unload_button.setEnabled(False)

    def on_mod_selected(self):
        """Handle mod selection and update file explorer"""
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            self.file_explorer.clear()
            self.explorer_label.setText("Select a mod to view files")
            # Disable move buttons when nothing selected
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
            return
        
        # Get the selected rows
        selected_rows = sorted(set(item.row() for item in selected_items))
        
        # Check if any separator is selected
        has_separator = any(self.is_separator_row(row) for row in selected_rows)
        
        # Get the first selected mod name (from column 2)
        row = selected_rows[0]
        
        # Check if it's a separator
        if self.is_separator_row(row):
            self.file_explorer.clear()
            self.explorer_label.setText("Select a mod to view files")
        
        name_item = self.mod_table.item(row, 2)
        
        # Check if item exists (can be None during drag operations)
        if not name_item:
            return
            
        mod_name = name_item.text()
        
        # Update move button states - disable if sorted alphabetically OR if any separator is selected
        if self._is_sorted_alphabetically or has_separator:
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
        else:
            self.move_up_button.setEnabled(min(selected_rows) > 0)
            self.move_down_button.setEnabled(max(selected_rows) < self.mod_table.rowCount() - 1)
        
        # Build the path
        mod_path = Path(SOURCE_DIR) / Path(mod_name)
        
        # Update label to show mod name only (or count if multiple)
        if len(selected_rows) > 1:
            self.explorer_label.setText(f"{len(selected_rows)} mods selected")
            self.file_explorer.clear()
        elif not self.is_separator_row(row):
            self.explorer_label.setText(mod_name)
            # Populate file explorer
            self.populate_file_explorer(mod_path)
    
    def populate_file_explorer(self, path):
        """Populate the file explorer tree with directory contents"""
        self.file_explorer.clear()
        
        if not path.exists():
            #item = QTreeWidgetItem([f"Path error: {path}"])
            #self.file_explorer.addTopLevelItem(item)
            return
        
        if not path.is_dir():
            item = QTreeWidgetItem([f"Not a directory: {path}"])
            self.file_explorer.addTopLevelItem(item)
            return
        
        # Add directory contents recursively
        self.add_directory_to_tree(path, self.file_explorer.invisibleRootItem())
        self.file_explorer.expandAll()
    
    def add_directory_to_tree(self, directory, parent_item):
        """Recursively add directory contents to tree"""
        try:
            # Get all items in directory, sorted (folders first, then files)
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            
            for item in items:
                if item.is_dir():
                    # Add folder
                    folder_item = QTreeWidgetItem(parent_item, [f"{item.name}"])
                    # Recursively add contents
                    self.add_directory_to_tree(item, folder_item)
                else:
                    # Add file
                    file_item = QTreeWidgetItem(parent_item, [f"{item.name}"])
        except PermissionError:
            error_item = QTreeWidgetItem(parent_item, ["[Permission Denied]"])
        
    def add_mod(self, name, enabled, is_separator=False):
        row = self.mod_table.rowCount()
        self.mod_table.insertRow(row)
        
        if is_separator:
            # Separator row - clean look with bold text
            from PyQt6.QtGui import QFont
            
            priority_item = QTableWidgetItem("▼")  # Collapse indicator
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(row, 0, priority_item)
            
            # Empty checkbox column for separator
            checkbox_item = QTableWidgetItem("")
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.mod_table.setItem(row, 1, checkbox_item)
            
            # Separator name - bold font
            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setData(Qt.ItemDataRole.UserRole, "separator")  # Mark as separator
            name_item.setData(Qt.ItemDataRole.UserRole + 1, name)  # Store original name
            self.mod_table.setItem(row, 2, name_item)
            
            # Track this separator
            self._separator_rows[row] = False  # Not collapsed
        else:
            # Normal mod row
            # Count existing non-separator rows to get correct priority
            priority = 1
            for r in range(row):
                if not self.is_separator_row(r):
                    priority += 1
            
            # Priority number item
            priority_item = QTableWidgetItem(str(priority))
            priority_item.setFlags(priority_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(row, 0, priority_item)
            
            # Checkbox item
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.mod_table.setItem(row, 1, checkbox_item)
            
            # Mod name item - disable editing to prevent drag issues
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mod_table.setItem(row, 2, name_item)

    def add_separator(self, name="New Separator"):
        """Add a separator row"""
        self.add_mod(name, False, is_separator=True)

    def is_separator_row(self, row):
        """Check if a row is a separator"""
        name_item = self.mod_table.item(row, 2)
        if name_item:
            return name_item.data(Qt.ItemDataRole.UserRole) == "separator"
        return False

    def get_separator_name(self, row):
        """Get the original name of a separator"""
        name_item = self.mod_table.item(row, 2)
        if name_item:
            return name_item.data(Qt.ItemDataRole.UserRole + 1)
        return ""

    def toggle_separator_collapse(self, row):
        """Toggle collapse state of a separator and hide/show mods beneath it"""
        if not self.is_separator_row(row):
            return
        
        # Find the next separator or end of list
        next_separator = self.mod_table.rowCount()
        for r in range(row + 1, self.mod_table.rowCount()):
            if self.is_separator_row(r):
                next_separator = r
                break
        
        # Get current collapsed state
        priority_item = self.mod_table.item(row, 0)
        is_collapsed = priority_item.text() == "▶"
        
        # Toggle state
        if is_collapsed:
            # Expand - show rows
            priority_item.setText("▼")
            for r in range(row + 1, next_separator):
                self.mod_table.setRowHidden(r, False)
        else:
            # Collapse - hide rows
            priority_item.setText("▶")
            for r in range(row + 1, next_separator):
                self.mod_table.setRowHidden(r, True)

    def add_mod_dialog(self):
        """Open file dialog to select and install mod(s)"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Mod Archive(s)",
            "",
            "Mod Archives (*.7z *.zip *.rar);;All Files (*)"
        )
        
        if file_paths:
            # Sort by file modification time (oldest first)
            file_paths.sort(key=lambda p: Path(p).stat().st_mtime)
            
            installed_count = 0
            failed_files = []
            
            for file_path in file_paths:
                try:
                    name = install_mod(file_path)
                    if name:
                        self.add_mod(name, enabled=True)
                        installed_count += 1
                except Exception as e:
                    failed_files.append((Path(file_path).name, str(e)))
            
            if installed_count > 0:
                self.update_status()
                self.auto_save_load_order()
                if RELOAD_ON_INSTALL: self.load_mods()
                self.statusBar().showMessage(f"Successfully installed {installed_count} mod(s)", 3000)
            
            if failed_files:
                error_msg = "Failed to install the following mods:\n\n"
                for filename, error in failed_files:
                    error_msg += f"• {filename}: {error}\n"
                QMessageBox.warning(self, "Installation Errors", error_msg)

    def load_mods(self):
        """Load mods by running restore() then perform_copy()"""
        try:
            restore()
            perform_copy()
            self.update_unload_button_state()
            self.load_plugins_list()
            self.statusBar().showMessage("Mods loaded successfully", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load mods:\n{str(e)}")

    def unload_mods(self):
        """Unload mods by running restore()"""
        try:
            restore()
            self.update_unload_button_state()
            self.load_plugins_list()
            self.statusBar().showMessage("Mods unloaded successfully", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Unload Error", f"Failed to unload mods:\n{str(e)}")

    def enable_all(self):
        for row in range(self.mod_table.rowCount()):
            if not self.is_separator_row(row):
                self.mod_table.item(row, 1).setCheckState(Qt.CheckState.Checked)
        self.update_status()
        self.auto_save_load_order()
            
    def disable_all(self):
        for row in range(self.mod_table.rowCount()):
            if not self.is_separator_row(row):
                self.mod_table.item(row, 1).setCheckState(Qt.CheckState.Unchecked)
        self.update_status()
        self.auto_save_load_order()

    def move_mod_up(self):
        """Move selected mod(s)/separator(s) up in load order"""
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or min(selected_rows) <= 0:
            return
        
        # Move each row up, starting from the top
        for row in selected_rows:
            self.move_row(row, row - 1)
        
        # Reselect the moved rows
        self.mod_table.clearSelection()
        selection_model = self.mod_table.selectionModel()
        for row in selected_rows:
            new_row = row - 1
            for col in range(self.mod_table.columnCount()):
                idx = self.mod_table.model().index(new_row, col)
                selection_model.select(idx, QItemSelectionModel.SelectionFlag.Select)
        
        self.update_priority_numbers()
        self.auto_save_load_order()

    def move_mod_down(self):
        """Move selected mod(s)/separator(s) down in load order"""
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or max(selected_rows) >= self.mod_table.rowCount() - 1:
            return
        
        # Move each row down, starting from the bottom
        for row in reversed(selected_rows):
            self.move_row(row, row + 1)
        
        # Reselect the moved rows
        self.mod_table.clearSelection()
        selection_model = self.mod_table.selectionModel()
        for row in selected_rows:
            new_row = row + 1
            for col in range(self.mod_table.columnCount()):
                idx = self.mod_table.model().index(new_row, col)
                selection_model.select(idx, QItemSelectionModel.SelectionFlag.Select)
        
        self.update_priority_numbers()
        self.auto_save_load_order()

    def get_separator_children_rows(self, separator_row):
        """Get all rows that belong to a separator (until next separator or end)"""
        children = []
        for r in range(separator_row + 1, self.mod_table.rowCount()):
            if self.is_separator_row(r):
                break
            children.append(r)
        return children

    def _create_row_from_data(self, row, data):
        """Create a row from collected data (helper for SimpleMO2)"""
        from PyQt6.QtGui import QFont
        
        if data['is_separator']:
            priority_item = QTableWidgetItem(data['collapse_state'])
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem("")
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.mod_table.setItem(row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(data['name'])
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setData(Qt.ItemDataRole.UserRole, "separator")
            name_item.setData(Qt.ItemDataRole.UserRole + 1, data['name'])
            self.mod_table.setItem(row, 2, name_item)
        else:
            priority_item = QTableWidgetItem("")
            priority_item.setFlags(priority_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(data['checkbox'])
            self.mod_table.setItem(row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(data['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mod_table.setItem(row, 2, name_item)
        
        if data['hidden']:
            self.mod_table.setRowHidden(row, True)

    def move_row(self, from_row, to_row):
        """Move a row from one position to another, shifting others"""
        from PyQt6.QtGui import QFont
        
        # Check if this is a separator
        is_sep = self.is_separator_row(from_row)
        
        if is_sep:
            # Store separator data
            separator_name = self.get_separator_name(from_row)
            collapse_state = self.mod_table.item(from_row, 0).text()
            
            # Remove the row
            self.mod_table.removeRow(from_row)
            
            # Insert at new position
            self.mod_table.insertRow(to_row)
            
            # Recreate separator row
            priority_item = QTableWidgetItem(collapse_state)
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(to_row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem("")
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.mod_table.setItem(to_row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(separator_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setData(Qt.ItemDataRole.UserRole, "separator")
            name_item.setData(Qt.ItemDataRole.UserRole + 1, separator_name)
            self.mod_table.setItem(to_row, 2, name_item)
        else:
            # Store normal mod data
            checkbox_state = self.mod_table.item(from_row, 1).checkState()
            mod_name = self.mod_table.item(from_row, 2).text()
            
            # Remove the row
            self.mod_table.removeRow(from_row)
            
            # Insert at new position
            self.mod_table.insertRow(to_row)
            
            # Create new items with the stored data
            priority_item = QTableWidgetItem("")
            priority_item.setFlags(priority_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(to_row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox_item.setCheckState(checkbox_state)
            self.mod_table.setItem(to_row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(mod_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.mod_table.setItem(to_row, 2, name_item)
        
        # Update all priority numbers to match current order
        self.update_priority_numbers()

    def auto_save_load_order(self):
        """Automatically save load order after changes"""
        # Don't save during initial loading
        if self._loading:
            return
            
        try:
            # If sorted alphabetically, restore to priority order first before saving
            if self._is_sorted_alphabetically:
                # Collect all data with priority numbers
                mods_data = []
                for row in range(self.mod_table.rowCount()):
                    is_sep = self.is_separator_row(row)
                    priority_text = self.mod_table.item(row, 0).text()
                    
                    if is_sep:
                        separator_name = self.get_separator_name(row)
                        # Separators use collapse indicator, not priority - use a large number + row to maintain relative order
                        mods_data.append((float('inf'), row, '#' + separator_name, True))
                    else:
                        try:
                            priority_num = int(priority_text)
                        except ValueError:
                            priority_num = row
                        mod_name = self.mod_table.item(row, 2).text()
                        is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                        if not is_enabled:
                            mod_name = '~' + mod_name
                        mods_data.append((priority_num, row, mod_name, False))
                
                # Sort by priority number (separators will be at end due to inf)
                # We need to interleave separators back in their correct positions
                # This is complex - just reload from file and update enabled states
                original_mods = load_list()
                enabled_lookup = {}
                for row in range(self.mod_table.rowCount()):
                    if not self.is_separator_row(row):
                        mod_name = self.mod_table.item(row, 2).text()
                        is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                        enabled_lookup[mod_name] = is_enabled
                
                mods = []
                for mod in original_mods:
                    if mod.startswith('#'):
                        mods.append(mod)
                    else:
                        clean_name = mod.lstrip('*~')
                        if clean_name in enabled_lookup:
                            if enabled_lookup[clean_name]:
                                mods.append(clean_name)
                            else:
                                mods.append('~' + clean_name)
                        else:
                            mods.append(mod)
            else:
                # Normal case: save in current table order
                mods = []
                for row in range(self.mod_table.rowCount()):
                    if self.is_separator_row(row):
                        mods.append('#' + self.get_separator_name(row))
                    else:
                        mod_name = self.mod_table.item(row, 2).text()
                        is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                        
                        if not is_enabled:
                            mod_name = '~' + mod_name
                        mods.append(mod_name)
            
            save_to_loadorder(mods)
            self.statusBar().showMessage("Load order auto-saved", 2000)
        except Exception as e:
            self.statusBar().showMessage(f"Auto-save failed: {str(e)}", 3000)

    def save_load_order(self):
        """Save current load order to file (manual save)"""
        if self._is_sorted_alphabetically:
            # When sorted alphabetically, reload from file and update enabled states
            original_mods = load_list()
            enabled_lookup = {}
            for row in range(self.mod_table.rowCount()):
                if not self.is_separator_row(row):
                    mod_name = self.mod_table.item(row, 2).text()
                    is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                    enabled_lookup[mod_name] = is_enabled
            
            mods = []
            for mod in original_mods:
                if mod.startswith('#'):
                    mods.append(mod)
                else:
                    clean_name = mod.lstrip('*~')
                    if clean_name in enabled_lookup:
                        if enabled_lookup[clean_name]:
                            mods.append(clean_name)
                        else:
                            mods.append('~' + clean_name)
                    else:
                        mods.append(mod)
        else:
            # Normal case: save in current table order
            mods = []
            for row in range(self.mod_table.rowCount()):
                if self.is_separator_row(row):
                    mods.append('#' + self.get_separator_name(row))
                else:
                    mod_name = self.mod_table.item(row, 2).text()
                    is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                    
                    if not is_enabled:
                        mod_name = '~' + mod_name
                    mods.append(mod_name)
        
        try:
            save_to_loadorder(mods)
            self.statusBar().showMessage("Load order saved successfully", 3000)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save load order:\n{str(e)}")

    def on_item_changed(self, item):
        """Auto-update status and save when checkbox state changes"""
        if item and item.column() == 1:  # Checkbox column
            self.update_status()
            self.auto_save_load_order()

    def on_cell_clicked(self, row, column):
        """Handle cell clicks, especially for checkbox column with multiple selections"""
        # Check if clicking on a separator's collapse button (column 0)
        if column == 0 and self.is_separator_row(row):
            self.toggle_separator_collapse(row)
            return
        
        if column != 1:  # Only handle checkbox column clicks for non-separators
            return
        
        # Skip if it's a separator row
        if self.is_separator_row(row):
            return
        
        selected_rows = set()
        for item in self.mod_table.selectedItems():
            selected_rows.add(item.row())
        
        # Only do special handling if multiple rows are selected and clicked row is one of them
        if len(selected_rows) > 1 and row in selected_rows:
            # Get the new state of the clicked checkbox (it was just toggled by Qt)
            new_state = self.mod_table.item(row, 1).checkState()
            
            # Apply the same state to all other selected rows (skip separators)
            self._loading = True  # Prevent multiple auto-saves
            for selected_row in selected_rows:
                if selected_row != row and not self.is_separator_row(selected_row):
                    self.mod_table.item(selected_row, 1).setCheckState(new_state)
            self._loading = False
            
            self.update_status()
            self.auto_save_load_order()

    def update_status(self):
        """Update status bar with mod counts"""
        total = 0
        enabled = 0
        for row in range(self.mod_table.rowCount()):
            if not self.is_separator_row(row):
                total += 1
                if self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked:
                    enabled += 1
        self.statusBar().showMessage(f"Mods: {enabled}/{total} enabled")

    def filter_mods(self, text):
        """Filter visible rows based on search text"""
        for row in range(self.mod_table.rowCount()):
            mod_name = self.mod_table.item(row, 2).text()
            matches = text.lower() in mod_name.lower()
            self.mod_table.setRowHidden(row, not matches)
    
    def update_priority_numbers(self):
        """Update priority numbers to match current row order (skip separators)"""
        priority = 1
        for row in range(self.mod_table.rowCount()):
            if self.is_separator_row(row):
                continue  # Skip separators
            priority_item = self.mod_table.item(row, 0)
            if priority_item:
                priority_item.setText(str(priority))
                priority += 1

    def on_header_clicked(self, logical_index):
        """Handle header clicks for sorting"""
        if logical_index == 0:  # # column - restore priority order
            if self._is_sorted_alphabetically:
                self.restore_priority_order()
        elif logical_index == 2:  # Mod Name column - sort alphabetically
            if self._is_sorted_alphabetically:
                # Toggle sort direction if already sorted
                self._sort_ascending = not self._sort_ascending
            else:
                # First time sorting, default to ascending
                self._sort_ascending = True
            self.sort_alphabetically()

    def sort_alphabetically(self):
        """Sort mods alphabetically and disable reordering"""
        self._is_sorted_alphabetically = True
        
        # Disable drag and drop
        self.mod_table.setDragEnabled(False)
        self.mod_table.setAcceptDrops(False)
        
        # Disable move buttons
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
        
        # Collect all mods with their data (including priority number and separator status)
        mods_data = []
        for row in range(self.mod_table.rowCount()):
            is_sep = self.is_separator_row(row)
            priority_num = self.mod_table.item(row, 0).text()
            checkbox_state = self.mod_table.item(row, 1).checkState()
            mod_name = self.mod_table.item(row, 2).text()
            if is_sep:
                separator_name = self.get_separator_name(row)
                mods_data.append((priority_num, mod_name, checkbox_state, True, separator_name))
            else:
                mods_data.append((priority_num, mod_name, checkbox_state, False, None))
        
        # Sort by name (case-insensitive)
        mods_data.sort(key=lambda x: x[1].lower(), reverse=not self._sort_ascending)
        
        # Clear and repopulate table
        self.mod_table.setRowCount(0)
        for priority_num, mod_name, checkbox_state, is_sep, separator_name in mods_data:
            row = self.mod_table.rowCount()
            self.mod_table.insertRow(row)
            
            if is_sep:
                # Recreate separator row with proper formatting
                from PyQt6.QtGui import QFont
                
                priority_item = QTableWidgetItem(priority_num)
                priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.mod_table.setItem(row, 0, priority_item)
                
                checkbox_item = QTableWidgetItem("")
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                self.mod_table.setItem(row, 1, checkbox_item)
                
                name_item = QTableWidgetItem(separator_name)
                name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                name_item.setData(Qt.ItemDataRole.UserRole, "separator")
                name_item.setData(Qt.ItemDataRole.UserRole + 1, separator_name)
                self.mod_table.setItem(row, 2, name_item)
            else:
                # Normal mod row
                priority_item = QTableWidgetItem(priority_num)
                priority_item.setFlags(priority_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.mod_table.setItem(row, 0, priority_item)
                
                checkbox_item = QTableWidgetItem()
                checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                checkbox_item.setCheckState(checkbox_state)
                self.mod_table.setItem(row, 1, checkbox_item)
                
                name_item = QTableWidgetItem(mod_name)
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.mod_table.setItem(row, 2, name_item)
        
        # Update header label with sort direction arrow
        arrow = "↑" if self._sort_ascending else "↓"
        self.mod_table.setHorizontalHeaderLabels(["#", "", f"Mod Name {arrow}"])
        
        direction = "ascending" if self._sort_ascending else "descending"
        self.statusBar().showMessage(f"Sorted alphabetically {direction} (reordering disabled)", 3000)

    def restore_priority_order(self):
        """Restore priority order from saved load order"""
        self._is_sorted_alphabetically = False
        
        # Re-enable drag and drop
        self.mod_table.setDragEnabled(True)
        self.mod_table.setAcceptDrops(True)
        
        # Clear table
        self.mod_table.setRowCount(0)
        self._separator_rows = {}
        
        # Reload from load order file
        self._loading = True
        mods = load_list()
        for mod in mods:
            if mod.startswith('#'):
                self.add_separator(mod[1:].strip())
            elif mod.startswith('*') or mod.startswith('~'):
                self.add_mod(mod.lstrip("*~"), False)
            else:
                self.add_mod(mod, True)
        self._loading = False
        
        # Reset header label without arrow
        self.mod_table.setHorizontalHeaderLabels(["#", "", "Mod Name"])
        
        self.statusBar().showMessage("Restored priority order (reordering enabled)", 3000)

    def show_context_menu(self, position):
        """Show right-click context menu for mods"""
        menu = QMenu()
        
        # Get clicked row
        index = self.mod_table.indexAt(position)
        clicked_row = index.row() if index.isValid() else -1
        
        # Check if clicked on a separator
        is_on_separator = clicked_row >= 0 and self.is_separator_row(clicked_row)
        
        if is_on_separator:
            # Separator-specific menu
            rename_sep_action = menu.addAction("Rename")
            remove_sep_action = menu.addAction("Delete")
            menu.addSeparator()
            add_sep_above_action = menu.addAction("Add Separator Above")
            add_sep_below_action = menu.addAction("Add Separator Below")
            
            action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
            
            if action == rename_sep_action:
                self.rename_separator(clicked_row)
            elif action == remove_sep_action:
                self.remove_separator(clicked_row)
            elif action == add_sep_above_action:
                self.add_separator_at(clicked_row)
            elif action == add_sep_below_action:
                self.add_separator_at(clicked_row + 1)
        else:
            # Normal mod menu
            if not self.mod_table.selectedItems():
                # No selection - only show add separator option
                add_sep_action = menu.addAction("Add Separator Here")
                action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
                if action == add_sep_action:
                    self.add_separator_at(clicked_row if clicked_row >= 0 else self.mod_table.rowCount())
                return
            
            # Add actions
            move_up_action = menu.addAction("Move Up")
            move_down_action = menu.addAction("Move Down")
            menu.addSeparator()
            enable_action = menu.addAction("Enable")
            disable_action = menu.addAction("Disable")
            menu.addSeparator()
            add_sep_above_action = menu.addAction("Add Separator Above")
            add_sep_below_action = menu.addAction("Add Separator Below")
            menu.addSeparator()
            rename_action = menu.addAction("Rename")
            remove_action = menu.addAction("Delete")
            open_folder_action = menu.addAction("Open Folder")
            
            # Show menu and handle selection
            action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
            
            if action == rename_action:
                self.rename_selected_mod()
            elif action == move_up_action:
                self.move_mod_up()
            elif action == move_down_action:
                self.move_mod_down()
            elif action == enable_action:
                self.enable_selected_mods()
            elif action == disable_action:
                self.disable_selected_mods()
            elif action == add_sep_above_action:
                selected = self.mod_table.selectedItems()
                if selected:
                    self.add_separator_at(selected[0].row())
            elif action == add_sep_below_action:
                selected = self.mod_table.selectedItems()
                if selected:
                    self.add_separator_at(selected[0].row() + 1)
            elif action == remove_action:
                self.remove_selected_mod()
            elif action == open_folder_action:
                self.open_mod_folder()

    def add_separator_at(self, row):
        """Add a separator at a specific row"""
        from PyQt6.QtWidgets import QInputDialog
        from PyQt6.QtGui import QFont
        
        name, ok = QInputDialog.getText(
            self,
            "Add Separator",
            "Separator name:",
            QLineEdit.EchoMode.Normal,
            "New Separator"
        )
        
        if ok and name:
            # Insert row at position
            self.mod_table.insertRow(row)
            
            # Set up separator row
            priority_item = QTableWidgetItem("▼")
            priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mod_table.setItem(row, 0, priority_item)
            
            checkbox_item = QTableWidgetItem("")
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.mod_table.setItem(row, 1, checkbox_item)
            
            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setData(Qt.ItemDataRole.UserRole, "separator")
            name_item.setData(Qt.ItemDataRole.UserRole + 1, name)
            self.mod_table.setItem(row, 2, name_item)
            
            self.update_priority_numbers()
            self.auto_save_load_order()

    def rename_separator(self, row):
        """Rename a separator"""
        from PyQt6.QtWidgets import QInputDialog
        
        old_name = self.get_separator_name(row)
        
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Separator",
            "New name:",
            QLineEdit.EchoMode.Normal,
            old_name
        )
        
        if ok and new_name:
            name_item = self.mod_table.item(row, 2)
            name_item.setText(new_name)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, new_name)
            self.auto_save_load_order()

    def remove_separator(self, row):
        """Remove a separator (keeps mods beneath it)"""
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            "Remove this separator?\n(Mods beneath it will remain)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # First, unhide any mods that were collapsed under this separator
            # Find the next separator or end of list
            next_separator = self.mod_table.rowCount()
            for r in range(row + 1, self.mod_table.rowCount()):
                if self.is_separator_row(r):
                    next_separator = r
                    break
            
            # Unhide all rows between this separator and the next one
            for r in range(row + 1, next_separator):
                self.mod_table.setRowHidden(r, False)
            
            # Now remove the separator
            self.mod_table.removeRow(row)
            self.update_priority_numbers()
            self.auto_save_load_order()

    def enable_selected_mods(self):
        """Enable selected mods"""
        for item in self.mod_table.selectedItems():
            if item.column() == 2:  # Mod name column
                self.mod_table.item(item.row(), 1).setCheckState(Qt.CheckState.Checked)
        self.update_status()
        self.auto_save_load_order()

    def disable_selected_mods(self):
        """Disable selected mods"""
        for item in self.mod_table.selectedItems():
            if item.column() == 2:  # Mod name column
                self.mod_table.item(item.row(), 1).setCheckState(Qt.CheckState.Unchecked)
        self.update_status()
        self.auto_save_load_order()

    def table_key_press_event(self, event):
        """Handle key press events on the mod table"""
        if event.key() == Qt.Key.Key_F2:
            self.rename_selected_mod()
        elif event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle_selected_mods()
        elif event.key() == Qt.Key.Key_Delete:
            self.delete_selected_items()
        else:
            # Call the original key press event
            QTableWidget.keyPressEvent(self.mod_table, event)

    def delete_selected_items(self):
        """Delete selected mods or separators"""
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()), reverse=True)
        
        if not selected_rows:
            return
        
        # Check if any separators are selected
        has_separator = any(self.is_separator_row(row) for row in selected_rows)
        has_mod = any(not self.is_separator_row(row) for row in selected_rows)
        
        if has_separator and has_mod:
            msg = "Remove selected mods and separators from load order?"
        elif has_separator:
            msg = "Remove selected separator(s) from load order?\n(Mods beneath will remain)"
        else:
            msg = "Remove selected mod(s) from load order?\n(This will not delete the mod files)"
        
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for row in selected_rows:
                # If it's a separator, unhide its children first
                if self.is_separator_row(row):
                    children = self.get_separator_children_rows(row)
                    for child_row in children:
                        self.mod_table.setRowHidden(child_row, False)
                self.mod_table.removeRow(row)
            
            self.update_priority_numbers()
            self.update_status()
            self.auto_save_load_order()
            if RELOAD_ON_INSTALL: self.load_mods

    def toggle_selected_mods(self):
        """Toggle enabled/disabled state for all selected mods"""
        selected_rows = set()
        for item in self.mod_table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            return
        
        # Check if majority are enabled or disabled to determine toggle direction
        enabled_count = sum(1 for row in selected_rows 
                          if self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked)
        
        # If more than half are enabled, disable all; otherwise enable all
        new_state = Qt.CheckState.Unchecked if enabled_count > len(selected_rows) / 2 else Qt.CheckState.Checked
        
        for row in selected_rows:
            self.mod_table.item(row, 1).setCheckState(new_state)
        
        self.update_status()
        self.auto_save_load_order()

    def rename_selected_mod(self):
        """Rename the selected mod using an input dialog"""
        from PyQt6.QtWidgets import QInputDialog
        
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        old_name = self.mod_table.item(row, 2).text()
        
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Mod",
            "Enter new name:",
            QLineEdit.EchoMode.Normal,
            old_name
        )
        
        if ok and new_name and new_name != old_name:
            try:
                # Call the rename function from bd_modloader
                rename_mod(old_name, new_name)
                
                # Update the table
                self.mod_table.item(row, 2).setText(new_name)
                
                # Update file explorer label if this mod is selected
                self.explorer_label.setText(new_name)
                
                # Refresh file explorer
                mod_path = Path(SOURCE_DIR) / Path(new_name)
                self.populate_file_explorer(mod_path)
                
                # Auto-save the load order
                self.auto_save_load_order()
                
                self.statusBar().showMessage(f"Renamed '{old_name}' to '{new_name}'", 3000)
            except Exception as e:
                QMessageBox.warning(self, "Rename Error", f"Failed to rename mod:\n{str(e)}")

    def remove_selected_mod(self):
        """Remove selected mod(s) from list"""
        self.delete_selected_items()

    def open_mod_folder(self):
        """Open selected mod's folder in system file explorer"""
        import subprocess
        import platform
        
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        mod_path = Path(SOURCE_DIR) / Path(mod_name)
        
        if not mod_path.exists():
            QMessageBox.warning(self, "Error", f"Mod folder not found:\n{mod_path}")
            return
        
        try:
            if platform.system() == 'Windows':
                subprocess.run(['explorer', str(mod_path)])
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(mod_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(mod_path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder:\n{str(e)}")

    def on_file_explorer_double_click(self, item, column):
        """Handle double-click on file explorer items"""
        import subprocess
        import platform
        
        # Build the full path by traversing up the tree
        path_parts = [item.text(0)]
        parent = item.parent()
        while parent:
            path_parts.insert(0, parent.text(0))
            parent = parent.parent()
        
        # Get the selected mod name to build the base path
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        
        # Build full path
        full_path = Path(SOURCE_DIR) / mod_name / Path(*path_parts)
        
        if not full_path.exists():
            QMessageBox.warning(self, "Error", f"Path not found:\n{full_path}")
            return
        
        try:
            if platform.system() == 'Windows':
                if full_path.is_dir():
                    subprocess.run(['explorer', str(full_path)])
                else:
                    subprocess.run(['start', '', str(full_path)], shell=True)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(full_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(full_path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open:\n{str(e)}")

    def dragEnterEvent(self, event):
        """Check if dragged content contains valid archive files"""
        if event.mimeData().hasUrls():
            # Check if any URL is a valid archive file
            valid_extensions = {'.7z', '.zip', '.rar'}
            for url in event.mimeData().urls():
                file_path = Path(url.toLocalFile())
                if file_path.suffix.lower() in valid_extensions:
                    event.acceptProposedAction()
                    # Add visual feedback
                    self.setStyleSheet("QMainWindow { border: 3px dashed #4CAF50; }")
                    return
        event.ignore()
    
    def dragLeaveEvent(self, event):
        """Remove visual feedback when drag leaves"""
        self.setStyleSheet("")
    
    def dragMoveEvent(self, event):
        """Accept drag move events"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def closeEvent(self, event):
        """Save load order when closing application"""
        self.save_load_order()
        event.accept()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for UI scaling"""
        from PyQt6.QtGui import QFont
        
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):  # Ctrl+ (= is for keyboards without numpad)
                self._scale_factor = min(2.0, self._scale_factor + 0.1)
                self.apply_scale()
            elif event.key() == Qt.Key.Key_Minus:  # Ctrl-
                self._scale_factor = max(0.5, self._scale_factor - 0.1)
                self.apply_scale()
            elif event.key() == Qt.Key.Key_0:  # Ctrl+0 to reset
                self._scale_factor = 1.0
                self.apply_scale()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def apply_scale(self):
        """Apply the current scale factor to the UI"""
        from PyQt6.QtGui import QFont
        
        app = QApplication.instance()
        base_size = 9  # Base font size in points
        new_size = int(base_size * self._scale_factor)
        
        font = app.font()
        font.setPointSize(new_size)
        app.setFont(font)
        
        # Update labels with custom stylesheets
        scaled_label_size = int(new_size * 1.1)  # Slightly larger for headers
        self.explorer_label.setStyleSheet(f"padding: 5px; font-weight: bold; font-size: {scaled_label_size}pt;")
        self.plugins_label.setStyleSheet(f"padding: 5px; font-weight: bold; font-size: {scaled_label_size}pt;")
        
        self.statusBar().showMessage(f"UI Scale: {int(self._scale_factor * 100)}%", 2000)

    def dropEvent(self, event):
        """Handle file drops only"""
        # Only handle external file drops
        if event.mimeData().hasUrls():
            self.handle_file_drop(event)
        else:
            event.ignore()

    def handle_file_drop(self, event):
        """Handle dropped archive files"""
        valid_extensions = {'.7z', '.zip', '.rar'}
        installed_count = 0
        failed_files = []
        
        # Collect valid files
        valid_files = []
        for url in event.mimeData().urls():
            file_path = Path(url.toLocalFile())
            if file_path.suffix.lower() in valid_extensions and file_path.is_file():
                valid_files.append(file_path)
        
        # Sort by file modification time (oldest first)
        valid_files.sort(key=lambda p: p.stat().st_mtime)
        
        for file_path in valid_files:
            try:
                name = install_mod(str(file_path))
                if name:
                    self.add_mod(name, enabled=True)
                    installed_count += 1
            except Exception as e:
                failed_files.append((file_path.name, str(e)))
        
        # Remove visual feedback
        self.setStyleSheet("")
        
        # Show results
        if installed_count > 0:
            self.update_status()
            self.auto_save_load_order()
            if RELOAD_ON_INSTALL: restore(); perform_copy()
            self.statusBar().showMessage(f"Successfully installed {installed_count} mod(s)", 3000)
        
        if failed_files:
            error_msg = "Failed to install the following mods:\n\n"
            for filename, error in failed_files:
                error_msg += f"• {filename}: {error}\n"
            QMessageBox.warning(self, "Installation Errors", error_msg)
        
        event.acceptProposedAction()


if __name__ == "__main__":
    # TODO: gui prompt for config creation
    read_cfg()
    app = QApplication(sys.argv)
    window = BDSM()
    window.show()
    sys.exit(app.exec())
