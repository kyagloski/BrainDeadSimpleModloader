#!/usr/bin/python

import sys
import subprocess
import platform
from pathlib import Path
from collections import OrderedDict
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, 
    QPushButton, QSplitter, QLabel, QLineEdit, QMenu, QMessageBox, QComboBox,
    QFileDialog, QInputDialog, QTextEdit
)
from PyQt6.QtCore import Qt, QItemSelectionModel, QObject, QThread, QWaitCondition, pyqtSignal, QMutex, QMutexLocker, QTimer
from PyQt6.QtGui import QIcon, QFont, QTextCursor

try:
    sys.path.append(str(Path(__file__).parent.parent))
    from ..bdsm import *
except:
    from bdsm import *

SHOW_MSG_TIME = 10000000


class StdoutRedirector(QObject):
    text_written = pyqtSignal(str)
    
    def __init__(self, original_stdout):
        super().__init__()
        self.original_stdout = original_stdout
    
    def write(self, text):
        if text.strip():
            self.text_written.emit(text)
        if self.original_stdout:
            self.original_stdout.write(text)
    
    def flush(self):
        if self.original_stdout:
            self.original_stdout.flush()

class CommandExecutorThread(QThread):
    commands_finished = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.commands = {}  # Dict to store latest version of each unique command
        self.mutex = QMutex()
        self.timer = None
        self.is_running = True
        
    def add_command(self, command_id, command_data):
        with QMutexLocker(self.mutex):
            # Store/update the latest version of this command
            self.commands[command_id] = command_data
        self.reset_timer()
        
    def reset_timer(self):
        if self.timer: self.timer.stop()
        self.timer = QTimer()
        self.timer.timeout.connect(self.execute_commands)
        self.timer.setSingleShot(True)
        self.timer.start(OPERATION_TIMEOUT)
        
    def execute_commands(self):
        with QMutexLocker(self.mutex):
            commands_to_execute = self.commands.copy()
            self.commands.clear()
        for command_id, command_data in commands_to_execute.items():
            result = self.process_command(command_id, command_data)
        self.commands_finished.emit()
            
    def process_command(self, command_id, command_data):
        command_id(*command_data) 
        return f"Executed: {command_id} with data: {command_data}"
        
    def run(self):
        self.exec()
        
    def stop(self):
        self.is_running = False
        if self.timer: self.timer.stop()
        self.quit()
        self.wait()

class ReorderOnlyTable(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drag_row = -1
        self._drop_row = -1
    
    def is_separator_row(self, row):
        name_item = self.item(row, 2)
        return name_item and name_item.data(Qt.ItemDataRole.UserRole) == "separator"
    
    def update_priority_numbers(self):
        priority = 1
        for row in range(self.rowCount()):
            if self.is_separator_row(row):
                continue
            priority_item = self.item(row, 0)
            if priority_item:
                priority_item.setText(str(priority))
                priority += 1
    
    def get_separator_children(self, separator_row):
        children = []
        for r in range(separator_row + 1, self.rowCount()):
            if self.is_separator_row(r):
                break
            children.append(r)
        return children

    def collect_row_data(self, row):
        is_sep = self.is_separator_row(row)
        if is_sep:
            return {
                'is_separator': True,
                'name': self.item(row, 2).data(Qt.ItemDataRole.UserRole + 1),
                'collapse_state': self.item(row, 0).text(),
                'hidden': self.isRowHidden(row)
            }
        return {
            'is_separator': False,
            'name': self.item(row, 2).text(),
            'checkbox': self.item(row, 1).checkState(),
            'hidden': self.isRowHidden(row)
        }

    def create_row_from_data(self, row, data):
        if data['is_separator']:
            self._create_separator_items(row, data['collapse_state'], data['name'])
        else:
            self._create_mod_items(row, data['name'], data['checkbox'])
        
        if data['hidden']:
            self.setRowHidden(row, True)
    
    def _create_separator_items(self, row, collapse_state, name):
        priority_item = QTableWidgetItem(collapse_state)
        priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 0, priority_item)
        
        checkbox_item = QTableWidgetItem("")
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        self.setItem(row, 1, checkbox_item)
        
        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        font = name_item.font()
        font.setBold(True)
        name_item.setFont(font)
        name_item.setData(Qt.ItemDataRole.UserRole, "separator")
        name_item.setData(Qt.ItemDataRole.UserRole + 1, name)
        self.setItem(row, 2, name_item)
    
    def _create_mod_items(self, row, name, checkbox_state=None):
        priority_item = QTableWidgetItem("")
        priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 0, priority_item)
        
        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        if checkbox_state is not None:
            checkbox_item.setCheckState(checkbox_state)
        self.setItem(row, 1, checkbox_item)
        
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, 2, name_item)

    def dropEvent(self, event):
        drop_pos = event.position().toPoint()
        index = self.indexAt(drop_pos)
        
        selected = self.selectedItems()
        if not selected:
            event.ignore()
            return
        
        selected_rows = sorted(set(item.row() for item in selected))
        
        if not index.isValid():
            target_row = self.rowCount()
        else:
            drop_row = index.row()
            rect = self.visualRect(index)
            y = drop_pos.y()
            mid_point = rect.top() + rect.height() / 2
            target_row = drop_row if y < mid_point else drop_row + 1
        
        event.ignore()
        
        if len(selected_rows) > 0:
            min_sel = min(selected_rows)
            max_sel = max(selected_rows)
            if selected_rows == list(range(min_sel, max_sel + 1)):
                if min_sel <= target_row <= max_sel + 1:
                    return
        
        rows_data = [self.collect_row_data(row) for row in selected_rows]
        
        for row in reversed(selected_rows):
            self.removeRow(row)
        
        rows_removed_before_target = sum(1 for r in selected_rows if r < target_row)
        adjusted_target = target_row - rows_removed_before_target
        
        new_selection_rows = []
        for i, data in enumerate(rows_data):
            insert_row = adjusted_target + i
            self.insertRow(insert_row)
            self.create_row_from_data(insert_row, data)
            new_selection_rows.append(insert_row)
        
        self.clearSelection()
        selection_model = self.selectionModel()
        for row in new_selection_rows:
            for col in range(self.columnCount()):
                idx = self.model().index(row, col)
                selection_model.select(idx, QItemSelectionModel.SelectionFlag.Select)
        
        self.update_priority_numbers()
        
        if self.selectedItems():
            self.itemChanged.emit(self.selectedItems()[0])


class ModLoaderUserInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.command_queue = OrderedDict() # ordered set

        self.setWindowTitle("BrainDead Simple Modloader (BDSM "+VERSION+")")
        self.setWindowIcon(QIcon("logo.png"))
        self.resize(1000, 600)
        
        self._loading = True
        self._scale_factor = 1.0
        self._separator_rows = {}
        self._is_sorted_alphabetically = False
        self._sort_ascending = True
        
        self.setAcceptDrops(True)
        self._init_ui()
        self._setup_stdout_redirect()
        self._load_initial_data()
        self._loading = False

        # Create the command executor thread
        self.executor = CommandExecutorThread()
        self.executor.commands_finished.connect(self.load_plugins_list)
        self.executor.start()

    def _setup_stdout_redirect(self):
        self._stdout_redirector = StdoutRedirector(sys.stdout)
        self._stdout_redirector.text_written.connect(self._append_log)
        sys.stdout = self._stdout_redirector

    def _append_log(self, text):
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        self.log_output.insertPlainText(text + "\n")
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        QApplication.processEvents()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Main vertical splitter for content and log
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(main_splitter)
        
        # Upper content area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        content_layout.addWidget(splitter)
        
        splitter.addWidget(self._create_left_panel())
        splitter.addWidget(self._create_right_panel())
        splitter.setSizes([300, 700])
        
        main_splitter.addWidget(content_widget)
        
        # Log output panel
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)
        
        self.log_label = QLabel("Log")
        self.log_label.setStyleSheet("padding: 5px; font-weight: bold;")
        log_layout.addWidget(self.log_label)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Click '+' or drag archive to install mods!")
        self.log_output.setStyleSheet("QTextEdit { font-family: monospace; }")
        log_layout.addWidget(self.log_output)
        
        main_splitter.addWidget(log_widget)
        main_splitter.setSizes([500, 100])
        
        self.statusBar().setContentsMargins(0,0,0,0)
        self.statusBar().showMessage("Ready!", SHOW_MSG_TIME)

    def _create_left_panel(self):
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_layout.addWidget(left_splitter)
        
        left_splitter.addWidget(self._create_file_explorer())
        left_splitter.addWidget(self._create_plugins_list())
        left_splitter.setSizes([400, 200])
        
        return left_panel

    def _create_file_explorer(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.explorer_label = QLabel("Select a mod to view files")
        self.explorer_label.setStyleSheet("padding: 5px; font-weight: bold;")
        self.explorer_label.setWordWrap(True)
        layout.addWidget(self.explorer_label)
        
        self.file_explorer = QTreeWidget()
        self.file_explorer.setHeaderLabel("Mod Files")
        self.file_explorer.setHeaderHidden(True)
        self.file_explorer.itemDoubleClicked.connect(self.on_file_explorer_double_click)
        layout.addWidget(self.file_explorer)
        
        return widget

    def _create_plugins_list(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.plugins_label = QLabel("Loaded Plugins")
        self.plugins_label.setStyleSheet("padding: 5px; font-weight: bold;")
        layout.addWidget(self.plugins_label)
        
        self.plugins_list = QTreeWidget()
        self.plugins_list.setHeaderHidden(True)
        layout.addWidget(self.plugins_list)
        
        return widget

    def _create_right_panel(self):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        right_layout.addLayout(self._create_preset_layout())
        right_layout.addWidget(self._create_mod_table())
        right_layout.addWidget(self._create_search_box())
        right_layout.addLayout(self._create_button_layout())
        
        return right_panel

    def _create_preset_layout(self):
        preset_layout = QHBoxLayout()
        
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(30)
        self.settings_button.setToolTip("Open Settings")
        self.settings_button.clicked.connect(self.open_settings)
        preset_layout.addWidget(self.settings_button)
        
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(150)
        self.preset_combo.addItem("load_order.txt")
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        
        return preset_layout

    def _create_mod_table(self):
        self.mod_table = ReorderOnlyTable(0, 3)
        self.mod_table.setHorizontalHeaderLabels(["#", "", "Mod Name"])
        self.mod_table.verticalHeader().setVisible(False)
        self.mod_table.itemSelectionChanged.connect(self.on_mod_selected)
        self.mod_table.itemChanged.connect(self.on_item_changed)
        self.mod_table.cellClicked.connect(self.on_cell_clicked)
        self.mod_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.mod_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.mod_table.setDragEnabled(True)
        self.mod_table.setAcceptDrops(True)
        self.mod_table.setDragDropOverwriteMode(False)
        self.mod_table.setDropIndicatorShown(True)
        self.mod_table.setDragDropMode(QTableWidget.DragDropMode.InternalMove)
        self.mod_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.mod_table.customContextMenuRequested.connect(self.show_context_menu)
        self.mod_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.mod_table.setSortingEnabled(False)
        self.mod_table.horizontalHeader().setStretchLastSection(True)
        self.mod_table.keyPressEvent = self.table_key_press_event
        
        header = self.mod_table.horizontalHeader()
        header.setMinimumSectionSize(15)
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        self.mod_table.setColumnWidth(0, 40)
        self.mod_table.setColumnWidth(1, 25)
        self.mod_table.setColumnWidth(2, 500)
        
        return self.mod_table

    def _create_search_box(self):
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter")
        self.search_box.textChanged.connect(self.filter_mods)
        return self.search_box

    def _create_button_layout(self):
        button_layout = QHBoxLayout()
        
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(40)
        self.add_button.setToolTip("Add Mod")
        self.add_button.clicked.connect(self.add_mod_dialog)
        
        self.move_up_button = QPushButton("↑")
        self.move_up_button.setFixedWidth(40)
        self.move_up_button.setToolTip("Move Up")
        self.move_up_button.clicked.connect(self.move_mod_up)
        self.move_up_button.setEnabled(False)
        
        self.move_down_button = QPushButton("↓")
        self.move_down_button.setFixedWidth(40)
        self.move_down_button.setToolTip("Move Down")
        self.move_down_button.clicked.connect(self.move_mod_down)
        self.move_down_button.setEnabled(False)
        
        self.enable_button = QPushButton("Enable All")
        self.enable_button.clicked.connect(self.enable_all)
        
        self.disable_button = QPushButton("Disable All")
        self.disable_button.clicked.connect(self.disable_all)
        
        separator = QLabel("|")
        separator.setStyleSheet("color: gray; font-size: 20px; padding: 0px; margin: 0px 5px;")
        separator.setFixedWidth(30)
        
        self.save_button = QPushButton("Save Load Order")
        self.save_button.clicked.connect(self.save_load_order)
        
        self.load_button = QPushButton("Load Mods")
        self.load_button.clicked.connect(self.load_mods)
        
        self.unload_button = QPushButton("Unload Mods")
        self.unload_button.clicked.connect(self.unload_mods)
        
        for btn in [self.add_button, self.move_up_button, self.move_down_button, 
                    self.enable_button, self.disable_button, separator, 
                    self.save_button, self.load_button, self.unload_button]:
            button_layout.addWidget(btn)
        
        return button_layout

    def _load_initial_data(self):
        mods = load_list()
        for mod in mods:
            if mod.startswith('#'):
                self.add_separator(mod[1:].strip())
            elif mod.startswith('*') or mod.startswith('~'):
                self.add_mod(mod.lstrip("*~"), False)
            else:
                self.add_mod(mod, True)
        
        self.update_status()
        self.update_unload_button_state()
        self.load_plugins_list()

    def _open_path(self, path):
        """Open a path with system's default application"""
        try:
            if platform.system() == 'Windows':
                if path.is_dir():
                    subprocess.run(['explorer', str(path)])
                else:
                    subprocess.run(['start', '', str(path)], shell=True)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', str(path)])
            else:
                subprocess.run(['xdg-open', str(path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open:\n{str(e)}")

    def open_settings(self):
        config_path = Path(CONFIG_FILE)
        if not config_path.exists():
            QMessageBox.warning(self, "Error", f"Config file not found:\n{config_path}")
            return
        self._open_path(config_path)

    def load_plugins_list(self):
        self.plugins_list.clear()
        try:
            backup_path = Path(BACKUP_DIR)
            plugins_file = None
            
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
                            self.plugins_list.addTopLevelItem(QTreeWidgetItem([line]))
        except Exception:
            pass

    def update_unload_button_state(self):
        try:
            backup_path = Path(BACKUP_DIR)
            self.unload_button.setEnabled(backup_path.exists() and any(backup_path.iterdir()))
        except Exception:
            self.unload_button.setEnabled(False)

    def on_mod_selected(self):
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            self.file_explorer.clear()
            self.explorer_label.setText("Select a mod to view files")
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
            return
        
        selected_rows = sorted(set(item.row() for item in selected_items))
        has_separator = any(self.is_separator_row(row) for row in selected_rows)
        row = selected_rows[0]
        
        if self.is_separator_row(row):
            self.file_explorer.clear()
            self.explorer_label.setText("Select a mod to view files")
        
        name_item = self.mod_table.item(row, 2)
        if not name_item:
            return
            
        mod_name = name_item.text()
        
        if self._is_sorted_alphabetically or has_separator:
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
        else:
            self.move_up_button.setEnabled(min(selected_rows) > 0)
            self.move_down_button.setEnabled(max(selected_rows) < self.mod_table.rowCount() - 1)
        
        if len(selected_rows) > 1:
            self.explorer_label.setText(f"{len(selected_rows)} mods selected")
            self.file_explorer.clear()
        elif not self.is_separator_row(row):
            self.explorer_label.setText(mod_name)
            self.populate_file_explorer(Path(SOURCE_DIR) / Path(mod_name))
    
    def populate_file_explorer(self, path):
        self.file_explorer.clear()
        if not path.exists() or not path.is_dir():
            return
        self.add_directory_to_tree(path, self.file_explorer.invisibleRootItem())
        self.file_explorer.expandAll()
    
    def add_directory_to_tree(self, directory, parent_item):
        try:
            items = sorted(directory.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            for item in items:
                item_widget = QTreeWidgetItem(parent_item, [item.name])
                if item.is_dir():
                    self.add_directory_to_tree(item, item_widget)
        except PermissionError:
            QTreeWidgetItem(parent_item, ["[Permission Denied]"])
        
    def add_mod(self, name, enabled, is_separator=False):
        row = self.mod_table.rowCount()
        self.mod_table.insertRow(row)
        
        if is_separator:
            self.mod_table._create_separator_items(row, "▼", name)
            self._separator_rows[row] = False
        else:
            priority = sum(1 for r in range(row) if not self.is_separator_row(r)) + 1
            self.mod_table._create_mod_items(row, name, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.mod_table.item(row, 0).setText(str(priority))

    def add_separator(self, name="New Separator"):
        self.add_mod(name, False, is_separator=True)

    def is_separator_row(self, row):
        name_item = self.mod_table.item(row, 2)
        return name_item and name_item.data(Qt.ItemDataRole.UserRole) == "separator"

    def get_separator_name(self, row):
        name_item = self.mod_table.item(row, 2)
        return name_item.data(Qt.ItemDataRole.UserRole + 1) if name_item else ""

    def toggle_separator_collapse(self, row):
        if not self.is_separator_row(row):
            return
        
        next_separator = self.mod_table.rowCount()
        for r in range(row + 1, self.mod_table.rowCount()):
            if self.is_separator_row(r):
                next_separator = r
                break
        
        priority_item = self.mod_table.item(row, 0)
        is_collapsed = priority_item.text() == "▶"
        
        priority_item.setText("▼" if is_collapsed else "▶")
        for r in range(row + 1, next_separator):
            self.mod_table.setRowHidden(r, not is_collapsed)

    def _show_installation_results(self, installed_count, failed_files):
        """Show results of mod installation"""
        if installed_count > 0:
            self.update_status()
            self.auto_save_load_order()
            if RELOAD_ON_INSTALL:
                #restore()
                #perform_copy()
                self.executor.add_command(perform_copy, tuple())
            self.statusBar().showMessage(f"Successfully installed {installed_count} mod(s)", SHOW_MSG_TIME)
        
        if failed_files:
            error_msg = "Failed to install the following mods:\n\n"
            error_msg += "\n".join(f"• {fn}: {err}" for fn, err in failed_files)
            QMessageBox.warning(self, "Installation Errors", error_msg)

    def add_mod_dialog(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Mod Archive(s)", "",
            "Mod Archives (*.7z *.zip *.rar);;All Files (*)"
        )
        if not file_paths: return
        file_paths.sort(key=lambda p: Path(p).stat().st_mtime)
        installed_count = 0
        failed_files = []
        
        for file_path in file_paths:
            try:
                name = install_mod(file_path, gui=True, parent=self)
                if name:
                    self.add_mod(name, enabled=True)
                    installed_count += 1
            except Exception as e:
                failed_files.append((Path(file_path).name, str(e)))
        self._show_installation_results(installed_count, failed_files)


    def load_mods(self):
        try:
            #restore()
            read_cfg(sync=False) # check for update
            #perform_copy()
            self.executor.add_command(perform_copy, tuple())
            self.update_unload_button_state()
            self.load_plugins_list()
            self.statusBar().showMessage("Mods loaded successfully", SHOW_MSG_TIME)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load mods:\n{str(e)}")

    def unload_mods(self):
        try:
            read_cfg(sync=False) # check for update
            #restore()
            self.executor.add_command(restore, tuple())
            self.update_unload_button_state()
            self.load_plugins_list()
            self.statusBar().showMessage("Mods unloaded successfully", SHOW_MSG_TIME)
        except Exception as e:
            QMessageBox.warning(self, "Unload Error", f"Failed to unload mods:\n{str(e)}")

    def _set_all_mods_state(self, state):
        """Set checkbox state for all non-separator mods"""
        for row in range(self.mod_table.rowCount()):
            if not self.is_separator_row(row):
                self.mod_table.item(row, 1).setCheckState(state)
        self.update_status()
        self.auto_save_load_order()

    def enable_all(self):
        self._set_all_mods_state(Qt.CheckState.Checked)
            
    def disable_all(self):
        self._set_all_mods_state(Qt.CheckState.Unchecked)

    def _reselect_rows(self, rows):
        """Reselect rows after a move operation"""
        self.mod_table.clearSelection()
        selection_model = self.mod_table.selectionModel()
        for row in rows:
            for col in range(self.mod_table.columnCount()):
                idx = self.mod_table.model().index(row, col)
                selection_model.select(idx, QItemSelectionModel.SelectionFlag.Select)

    def move_mod_up(self):
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or min(selected_rows) <= 0:
            return
        for row in selected_rows:
            self.move_row(row, row - 1)
        self._reselect_rows([row - 1 for row in selected_rows])
        self.update_priority_numbers()
        self.auto_save_load_order()

    def move_mod_down(self):
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or max(selected_rows) >= self.mod_table.rowCount() - 1:
            return
        for row in reversed(selected_rows):
            self.move_row(row, row + 1)
        self._reselect_rows([row + 1 for row in selected_rows])
        self.update_priority_numbers()
        self.auto_save_load_order()

    def get_separator_children_rows(self, separator_row):
        children = []
        for r in range(separator_row + 1, self.mod_table.rowCount()):
            if self.is_separator_row(r):
                break
            children.append(r)
        return children

    def move_row(self, from_row, to_row):
        is_sep = self.is_separator_row(from_row)
        
        if is_sep:
            separator_name = self.get_separator_name(from_row)
            collapse_state = self.mod_table.item(from_row, 0).text()
            self.mod_table.removeRow(from_row)
            self.mod_table.insertRow(to_row)
            self.mod_table._create_separator_items(to_row, collapse_state, separator_name)
        else:
            checkbox_state = self.mod_table.item(from_row, 1).checkState()
            mod_name = self.mod_table.item(from_row, 2).text()
            self.mod_table.removeRow(from_row)
            self.mod_table.insertRow(to_row)
            self.mod_table._create_mod_items(to_row, mod_name, checkbox_state)
        
        self.update_priority_numbers()

    def _collect_load_order(self):
        """Collect current load order from table, handling sorted state"""
        if self._is_sorted_alphabetically:
            original_mods = load_list()
            enabled_lookup = {
                self.mod_table.item(row, 2).text(): 
                self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                for row in range(self.mod_table.rowCount())
                if not self.is_separator_row(row)
            }
            mods = []
            for mod in original_mods:
                if mod.startswith('#'):
                    mods.append(mod)
                else:
                    clean_name = mod.lstrip('*~')
                    if clean_name in enabled_lookup:
                        mods.append(clean_name if enabled_lookup[clean_name] else '~' + clean_name)
                    else:
                        mods.append(mod)
        else:
            mods = []
            for row in range(self.mod_table.rowCount()):
                if self.is_separator_row(row):
                    mods.append('#' + self.get_separator_name(row))
                else:
                    if not self.mod_table.item(row,2): continue
                    mod_name = self.mod_table.item(row, 2).text()
                    is_enabled = self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked
                    mods.append(mod_name if is_enabled else '~' + mod_name)
        return mods

    def auto_save_load_order(self):
        global RELOAD_ON_INSTALL
        if self._loading: return
        try:
            mods = self._collect_load_order()
            read_cfg(sync=False) # check for update
            # manually read cfg for param because this shit is broke somehow
            with open("config.yaml", "r") as f: cfg_dict = yaml.safe_load(f)
            RELOAD_ON_INSTALL = cfg_dict["RELOAD_ON_INSTALL"]
            if RELOAD_ON_INSTALL: 
                #save_to_loadorder(mods)
                self.save_load_order()
                self.load_mods()
                self.statusBar().showMessage("Load order auto-saved", SHOW_MSG_TIME)
        except Exception as e:
            print("error: encountered exception: "+str(e)+" during autosave!")
            self.statusBar().showMessage(f"Auto-save failed: {str(e)}", SHOW_MSG_TIME)

    def save_load_order(self):
        try:
            mods = self._collect_load_order()
            read_cfg(sync=False) # check for update
            save_to_loadorder(mods)
            self.statusBar().showMessage("Load order saved successfully", SHOW_MSG_TIME)
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save load order:\n{str(e)}")

    def on_item_changed(self, item):
        if item and item.column() == 1:
            self.update_status()
            self.auto_save_load_order()

    def on_cell_clicked(self, row, column):
        if column == 0 and self.is_separator_row(row):
            self.toggle_separator_collapse(row)
            return
        
        if column != 1 or self.is_separator_row(row):
            return
        
        selected_rows = set(item.row() for item in self.mod_table.selectedItems())
        
        if len(selected_rows) > 1 and row in selected_rows:
            new_state = self.mod_table.item(row, 1).checkState()
            self._loading = True
            for selected_row in selected_rows:
                if selected_row != row and not self.is_separator_row(selected_row):
                    self.mod_table.item(selected_row, 1).setCheckState(new_state)
            self._loading = False
            self.update_status()
            self.auto_save_load_order()

    def update_status(self):
        total = sum(1 for row in range(self.mod_table.rowCount()) if not self.is_separator_row(row))
        enabled = sum(1 for row in range(self.mod_table.rowCount()) 
                     if not self.is_separator_row(row) and 
                     self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked)
        self.statusBar().showMessage(f"Mods: {enabled}/{total} enabled", SHOW_MSG_TIME)

    def filter_mods(self, text):
        for row in range(self.mod_table.rowCount()):
            mod_name = self.mod_table.item(row, 2).text()
            self.mod_table.setRowHidden(row, text.lower() not in mod_name.lower())
    
    def update_priority_numbers(self):
        priority = 1
        for row in range(self.mod_table.rowCount()):
            if self.is_separator_row(row):
                continue
            priority_item = self.mod_table.item(row, 0)
            if priority_item:
                priority_item.setText(str(priority))
                priority += 1

    def on_header_clicked(self, logical_index):
        if logical_index == 0:
            if self._is_sorted_alphabetically:
                self.restore_priority_order()
        elif logical_index == 2:
            self._sort_ascending = not self._sort_ascending if self._is_sorted_alphabetically else True
            self.sort_alphabetically()

    def sort_alphabetically(self):
        self._is_sorted_alphabetically = True
        self.mod_table.setDragEnabled(False)
        self.mod_table.setAcceptDrops(False)
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
        
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
        
        mods_data.sort(key=lambda x: x[1].lower(), reverse=not self._sort_ascending)
        
        self.mod_table.setRowCount(0)
        for priority_num, mod_name, checkbox_state, is_sep, separator_name in mods_data:
            row = self.mod_table.rowCount()
            self.mod_table.insertRow(row)
            
            if is_sep:
                self.mod_table._create_separator_items(row, priority_num, separator_name)
            else:
                self.mod_table._create_mod_items(row, mod_name, checkbox_state)
                self.mod_table.item(row, 0).setText(priority_num)
        
        arrow = "↑" if self._sort_ascending else "↓"
        self.mod_table.setHorizontalHeaderLabels(["#", "", f"Mod Name {arrow}"])
        direction = "ascending" if self._sort_ascending else "descending"
        self.statusBar().showMessage(f"Sorted alphabetically {direction} (reordering disabled)", SHOW_MSG_TIME)

    def restore_priority_order(self):
        self._is_sorted_alphabetically = False
        self.mod_table.setDragEnabled(True)
        self.mod_table.setAcceptDrops(True)
        self.mod_table.setRowCount(0)
        self._separator_rows = {}
        
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
        
        self.mod_table.setHorizontalHeaderLabels(["#", "", "Mod Name"])
        self.statusBar().showMessage("Restored priority order (reordering enabled)", SHOW_MSG_TIME)

    def show_context_menu(self, position):
        menu = QMenu()
        index = self.mod_table.indexAt(position)
        clicked_row = index.row() if index.isValid() else -1
        is_on_separator = clicked_row >= 0 and self.is_separator_row(clicked_row)
        
        if is_on_separator:
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
            if not self.mod_table.selectedItems():
                add_sep_action = menu.addAction("Add Separator Here")
                action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
                if action == add_sep_action:
                    self.add_separator_at(clicked_row if clicked_row >= 0 else self.mod_table.rowCount())
                return
            
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
        name, ok = QInputDialog.getText(
            self, "Add Separator", "Separator name:",
            QLineEdit.EchoMode.Normal, "New Separator")
        if ok and name:
            self.mod_table.insertRow(row)
            self.mod_table._create_separator_items(row, "▼", name)
            self.update_priority_numbers()
            self.auto_save_load_order()

    def rename_separator(self, row):
        old_name = self.get_separator_name(row)
        new_name, ok = QInputDialog.getText(
            self, "Rename Separator", "New name:",
            QLineEdit.EchoMode.Normal, old_name)
        if ok and new_name:
            name_item = self.mod_table.item(row, 2)
            name_item.setText(new_name)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, new_name)
            self.auto_save_load_order()

    def remove_separator(self, row):
        reply = QMessageBox.question(
            self, "Confirm Removal",
            "Remove this separator?\n(Mods beneath it will remain)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            next_separator = self.mod_table.rowCount()
            for r in range(row + 1, self.mod_table.rowCount()):
                if self.is_separator_row(r):
                    next_separator = r
                    break
            for r in range(row + 1, next_separator):
                self.mod_table.setRowHidden(r, False)
            self.mod_table.removeRow(row)
            self.update_priority_numbers()
            self.auto_save_load_order()

    def _set_selected_mods_state(self, state):
        """Set checkbox state for all selected mods"""
        for item in self.mod_table.selectedItems():
            if item.column() == 2:
                self.mod_table.item(item.row(), 1).setCheckState(state)
        self.update_status()
        self.auto_save_load_order()

    def _collapse_selected_separators(self, row):
        priority_item = self.mod_table.item(row, 0)
        if priority_item.text() == "▼": self.toggle_separator_collapse(row)
    
    def _expand_selected_separators(self, row):
        priority_item = self.mod_table.item(row, 0)
        if priority_item.text() == "▶": self.toggle_separator_collapse(row)

    def enable_selected_mods(self):
        self._set_selected_mods_state(Qt.CheckState.Checked)

    def disable_selected_mods(self):
        self._set_selected_mods_state(Qt.CheckState.Unchecked)

    def table_key_press_event(self, event):
        try: row=self.mod_table.selectedItems()[0].row()
        except: row=None
        if event.key() == Qt.Key.Key_F2:
            if self.mod_table.is_separator_row(row): self.rename_separator(row)
            else: self.rename_selected_mod()
        elif event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle_selected_mods()
        elif event.key() == Qt.Key.Key_Delete: self.delete_selected_items()
        elif event.key() == Qt.Key.Key_Left:   self._collapse_selected_separators(row)
        elif event.key() == Qt.Key.Key_Right:  self._expand_selected_separators(row)
        else: QTableWidget.keyPressEvent(self.mod_table, event)

    def delete_selected_items(self):
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()), reverse=True)
        if not selected_rows:
            return
        
        has_separator = any(self.is_separator_row(row) for row in selected_rows)
        has_mod = any(not self.is_separator_row(row) for row in selected_rows)
        
        if has_separator and has_mod:
            msg = "Remove selected mods and separators from load order?"
        elif has_separator:
            msg = "Remove selected separator(s) from load order?\n(Mods beneath will remain)"
        else:
            msg = "Remove selected mod(s) from load order?\n(This will not delete the mod files)"
        
        reply = QMessageBox.question(
            self, "Confirm Removal", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            for row in selected_rows:
                if self.is_separator_row(row):
                    children = self.get_separator_children_rows(row)
                    for child_row in children:
                        self.mod_table.setRowHidden(child_row, False)
                mod_name = self.mod_table.collect_row_data(row)["name"]
                delete_mod(mod_name, gui=True)
                self.mod_table.removeRow(row)
            
            self.update_priority_numbers()
            self.update_status()
            self.auto_save_load_order()
            read_cfg() # check for update
            if RELOAD_ON_INSTALL:
                self.load_mods()

    def toggle_selected_mods(self):
        selected_rows = set(item.row() for item in self.mod_table.selectedItems())
        if not selected_rows:
            return
        
        enabled_count = sum(1 for row in selected_rows 
                          if self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked)
        new_state = Qt.CheckState.Unchecked if enabled_count > len(selected_rows) / 2 else Qt.CheckState.Checked
        
        for row in selected_rows:
            row_data = self.mod_table.collect_row_data(row)
            if row_data["is_separator"]:
                continue
            self.mod_table.item(row, 1).setCheckState(new_state)
        
        self.update_status()
        #self.auto_save_load_order() # this happens elsewhere (maybe uncomment)
        read_cfg(sync=False) # check for update
        if RELOAD_ON_INSTALL:
            self.load_mods()

    def rename_selected_mod(self):
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        old_name = self.mod_table.item(row, 2).text()
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Mod", "Enter new name:",
            QLineEdit.EchoMode.Normal, old_name
        )
        
        if ok and new_name and new_name != old_name:
            try:
                rename_mod(old_name, new_name)
                self.mod_table.item(row, 2).setText(new_name)
                self.explorer_label.setText(new_name)
                self.populate_file_explorer(Path(SOURCE_DIR) / Path(new_name))
                self.auto_save_load_order()
                self.statusBar().showMessage(f"Renamed '{old_name}' to '{new_name}'", SHOW_MSG_TIME)
            except Exception as e:
                QMessageBox.warning(self, "Rename Error", f"Failed to rename mod:\n{str(e)}")

    def remove_selected_mod(self):
        self.delete_selected_items()

    def open_mod_folder(self):
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        mod_path = Path(SOURCE_DIR) / Path(mod_name)
        
        if not mod_path.exists():
            QMessageBox.warning(self, "Error", f"Mod folder not found:\n{mod_path}")
            return
        
        self._open_path(mod_path)

    def on_file_explorer_double_click(self, item, column):
        path_parts = [item.text(0)]
        parent = item.parent()
        while parent:
            path_parts.insert(0, parent.text(0))
            parent = parent.parent()
        
        selected_items = self.mod_table.selectedItems()
        if not selected_items:
            return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        full_path = Path(SOURCE_DIR) / mod_name / Path(*path_parts)
        
        if not full_path.exists():
            QMessageBox.warning(self, "Error", f"Path not found:\n{full_path}")
            return
        
        self._open_path(full_path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            valid_extensions = {'.7z', '.zip', '.rar'}
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).suffix.lower() in valid_extensions:
                    event.acceptProposedAction()
                    self.setStyleSheet("QMainWindow { border: 3px dashed #4CAF50; }")
                    return
        event.ignore()
    
    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
    
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def closeEvent(self, event):
        sys.stdout = self._stdout_redirector.original_stdout
        self.save_load_order()
        event.accept()

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._scale_factor = min(2.0, self._scale_factor + 0.1)
                self.apply_scale()
            elif event.key() == Qt.Key.Key_Minus:
                self._scale_factor = max(0.5, self._scale_factor - 0.1)
                self.apply_scale()
            elif event.key() == Qt.Key.Key_0:
                self._scale_factor = 1.0
                self.apply_scale()
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def apply_scale(self):
        app = QApplication.instance()
        base_size = 9
        new_size = int(base_size * self._scale_factor)
        
        font = app.font()
        font.setPointSize(new_size)
        app.setFont(font)
        
        scaled_label_size = int(new_size * 1.1)
        self.explorer_label.setStyleSheet(f"padding: 5px; font-weight: bold; font-size: {scaled_label_size}pt;")
        self.plugins_label.setStyleSheet(f"padding: 5px; font-weight: bold; font-size: {scaled_label_size}pt;")
        self.log_label.setStyleSheet(f"padding: 5px; font-weight: bold; font-size: {scaled_label_size}pt;")
        self.log_output.setStyleSheet(f"padding: 5px; font-size: {scaled_label_size}pt;")
        self.statusBar().showMessage(f"UI Scale: {int(self._scale_factor * 100)}%", SHOW_MSG_TIME)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.handle_file_drop(event)
        else:
            event.ignore()

    def handle_file_drop(self, event):
        valid_extensions = {'.7z', '.zip', '.rar'}
        installed_count = 0
        failed_files = []
        
        valid_files = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if Path(url.toLocalFile()).suffix.lower() in valid_extensions and Path(url.toLocalFile()).is_file()
        ]
        
        valid_files.sort(key=lambda p: p.stat().st_mtime)
        
        for file_path in valid_files:
            try:
                # Use GUI FOMOD installer, passing self as parent window
                name = install_mod(str(file_path), gui=True, parent=self)
                if name:
                    self.add_mod(name, enabled=True)
                    installed_count += 1
            except Exception as e:
                failed_files.append((file_path.name, str(e)))
        
        self.setStyleSheet("")
        self._show_installation_results(installed_count, failed_files)
        event.acceptProposedAction()



if __name__ == "__main__":
    read_cfg()
    app = QApplication(sys.argv)
    window = ModLoaderUserInterface()
    window.show()
    sys.exit(app.exec())
