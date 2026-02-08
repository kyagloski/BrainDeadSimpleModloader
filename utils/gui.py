#!/usr/bin/python

import sys
import subprocess
import platform
import yaml
import tempfile
import random
from pathlib import Path
from collections import OrderedDict
from time import sleep
from copy import deepcopy
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, 
    QPushButton, QSplitter, QLabel, QLineEdit, QMenu, QMessageBox, 
    QComboBox, QFileDialog, QInputDialog, QTextEdit, QToolButton, 
    QSplashScreen
)
from PyQt6.QtCore import ( Qt, QItemSelectionModel, QObject, QThread, 
    QWaitCondition, pyqtSignal, QMutex, QMutexLocker, QTimer, QPoint, 
    QSize, QFile, QTextStream, QMetaObject
)
from PyQt6.QtGui import QIcon, QFont, QTextCursor, QCursor, QPixmap

try:
    sys.path.append(str(Path(__file__).parent.parent))
    from ..bdsm import *
except:
    from bdsm import *
from game_specific import *
from ini_manager import *
from exe_manager import *
from installer import *

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
        self.commands = {}  # dict to store latest version of each unique command
        self.mutex = QMutex()
        self.timer = None
        self.is_running = True
        
    def add_command(self, command_id, command_data):
        with QMutexLocker(self.mutex):
            # store/update the latest version of this command
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

class ExtractorThread(QThread):
    #archive_extracted = pyqtSignal(str,str)  # mod name
    call_handle_mod_install = pyqtSignal(str, str)
    progress = pyqtSignal(str)
    complete = pyqtSignal()
    temp_complete = pyqtSignal()
    
    def __init__(self, file_paths, output_dir, parent):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.parent = parent
        self.call_handle_mod_install.connect(
            parent.handle_mod_install,
            Qt.ConnectionType.BlockingQueuedConnection
        )

    def run(self): # this is dumb
        for archive_path in self.file_paths:
            self.progress.emit(str(Path(archive_path)))
            archive_name = Path(archive_path).stem
            output_dir = Path(self.output_dir) / f"{archive_name}"
            output_dir = next(
                p for i in range(10**9)
                if not (p := Path(output_dir).parent / f"{archive_name}{'' if i == 0 else f'_{i}'}").exists())
                
            temp_dir = Path(tempfile.mkdtemp())
            if os.path.isdir(archive_path):  # handle dir install
                shutil.copytree(archive_path,temp_dir,dirs_exist_ok=True)
                result=True
            else: result=extract_archive(archive_path, temp_dir)
            self.temp_complete.emit()
            #if result: self.archive_extracted.emit(str(temp_dir),str(archive_path))
            #else: self.archive_extracted.emit(None,str(archive_path))
            if result: self.call_handle_mod_install.emit(str(temp_dir), str(archive_path))
            else: self.call_handle_mod_install.emit(None, str(archive_path))
                
        self.complete.emit()

class StatusThread(QThread):
    def __init__(self, status_widget, file):
        super().__init__()
        self.status=status_widget
        self.file=file
        self.temp_complete=False
        self.stopped=False
       
    def set_file(self,file):
        self.file=file
        self.temp_complete=False
 
    def run(self):
        i=0
        a=["|","/","-","\\"]
        while not self.stopped:
            if self.temp_complete:
                if os.path.isdir(self.file): self.status.setText("Copying complete!")
                else: self.status.setText("Extraction complete!")
                sleep(0.2)
                continue
            if i>len(a)-1:i=0
            name=Path(self.file).name
            if os.path.isdir(self.file): self.status.setText(f"Copying {name}  {a[i]}")
            else: self.status.setText(f"Extracting {name}  {a[i]}")
            sleep(0.5)
            i+=1
        if os.path.isdir(self.file): self.status.setText("Copying complete!")
        else: self.status.setText("Extraction complete!")
        sleep(2)
        self.status.setText("")

    def set_temp_complete(self):
        self.temp_complete=True 

    def done(self):
        self.stopped=True


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


class EditableComboBox(QComboBox):
    def __init__(self, upper=None):
        super().__init__(None)
        self.upper=upper
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
    
    def show_context_menu(self, pos):
        menu = QMenu(self)
        open_action = menu.addAction("Edit")
        rename_action = menu.addAction("Rename")
        duplicate_action = menu.addAction("Duplicate")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self.mapToGlobal(pos))
        
        if action == open_action:      self.open_in_editor()
        if action == rename_action:    self.upper.rename_preset()
        if action == duplicate_action: self.upper.dup_preset()
        if action == delete_action:    self.upper.del_preset()
    
    def open_in_editor(self):
        file_path = str(LOAD_ORDER)
        print("Opening loadorder file with system text editor...")
        if not os.path.isfile(file_path):
            print("error: could not open "+file_path)
            return
        if sys.platform == 'win32':    os.startfile(file_path)
        elif sys.platform == 'darwin': subprocess.run(['open', file_path])
        else: subprocess.run(['xdg-open', file_path]) # linux


class ModLoaderUserInterface(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = read_cfg(sync=False)
        self.command_queue = OrderedDict() # ordered set

        self.setWindowTitle("BrainDead Simple Modloader (BDSM "+VERSION+")")
        icon=QIcon()
        try:icon.addFile(str(LOCAL_DIR/"utils"/"resources"/"icon.png"), QSize(256, 256))
        except:pass
        self.setWindowIcon(QIcon(icon))
        self.resize(1000, 600)
        
        self._loading = True
        self._scale_factor = 1.0
        self._separator_rows = {}
        self._is_sorted_alphabetically = False
        self._sort_ascending = True
        self.showing_fomod = False
        
        self.setAcceptDrops(True)
        self._init_ui()
        self._setup_stdout_redirect()
        self._load_initial_data()
        self._loading = False

        self.status_label=QLabel("")
        self.status_label.setStyleSheet("font-weight: bold;")
        self.status_label.setFont(QFont("Courier"))
        self.statusBar().addPermanentWidget(self.status_label)

        # Create the command executor thread
        self.executor = CommandExecutorThread()
        self.executor.commands_finished.connect(self.load_plugins_list)
        self.executor.start()
        # threads
        self.extract_threads=[]
        self.status_threads=[]

    def _setup_stdout_redirect(self):
        self._stdout_redirector = StdoutRedirector(sys.stdout)
        self._stdout_redirector.text_written.connect(self._append_log)
        sys.stdout = self._stdout_redirector

    def _append_log(self, text):
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        self.log_output.insertPlainText(text + "\n")
        self.log_output.moveCursor(QTextCursor.MoveOperation.End)
        QApplication.processEvents()

    def _init_ui(self, verbose=False):
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
        if verbose: 
            self.log_output.setPlainText(verbose)
            self.log_output.moveCursor(QTextCursor.MoveOperation.End)
            self.log_output.ensureCursorVisible()
        else: self.log_output.setPlaceholderText("Click '+' or drag archive to install mods!")
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
        
        right_layout.addLayout(self._create_top_layout())
        right_layout.addWidget(self._create_mod_table())
        right_layout.addWidget(self._create_search_box())
        right_layout.addLayout(self._create_button_layout())
        
        return right_panel

    def _create_top_layout(self):
        preset_layout = QHBoxLayout()
        
        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(35, 35)
        self.settings_button.clicked.connect(self.open_settings)
        preset_layout.addWidget(self.settings_button)

        self.tools_button = QToolButton()
        self.tools_button.setText("⚒")
        self.tools_button.setFixedSize(35, 35)
        self.tools_button.setToolTip("Tools")
        #self.tools_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        #self.tools_button.clicked.connect(self.open_settings)
        menu = QMenu()
        ini_man = menu.addAction("INI Manager")
        def show_menu(): menu.exec(self.tools_button.mapToGlobal(QPoint(0, self.tools_button.height())))
        self.tools_button.clicked.connect(show_menu)
        self.tools_button.setMenu(menu)
        preset_layout.addWidget(self.tools_button)

        ini_man.triggered.connect(self.open_ini_manager)
        
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = EditableComboBox(upper=self)
        #self.preset_combo.setFixedWidth(150)
        self.preset_combo.setSizePolicy(self.preset_combo.sizePolicy().horizontalPolicy().Expanding,
                                        self.preset_combo.sizePolicy().verticalPolicy().Preferred)
        self.read_presets()
        self.preset_combo.currentTextChanged.connect(self.select_preset)
        preset_layout.addWidget(self.preset_combo,2)

        self.add_preset_button = QPushButton("+")
        self.add_preset_button.setFixedSize(35, 35)
        self.add_preset_button.setToolTip("New Preset")
        self.add_preset_button.clicked.connect(self.add_preset)
        preset_layout.addWidget(self.add_preset_button)
        
        self.del_preset_button = QPushButton("-")
        self.del_preset_button.setFixedSize(35, 35)
        self.del_preset_button.setToolTip("Delete Preset")
        self.del_preset_button.clicked.connect(self.del_preset)
        preset_layout.addWidget(self.del_preset_button)

        separator = QLabel("|")
        separator.setStyleSheet("color: gray; font-size: 20px; padding: 0px; margin: 0px 5px;")
        separator.setFixedWidth(30)
        preset_layout.addWidget(separator)

        preset_layout.addStretch()

        preset_layout.addWidget(QLabel("Binary:"))
        self.bin_combo = QComboBox()
        #self.bin_combo.setFixedWidth(150)
        self.bin_combo.setSizePolicy(self.bin_combo.sizePolicy().horizontalPolicy().Expanding,
                                     self.bin_combo.sizePolicy().verticalPolicy().Preferred)
        exes=self.cfg["EXECUTABLES"]
        self.current_exe=None
        for exe in exes:
            if exes[exe]["SELECTED"]: self.current_exe=deepcopy(exe)
            self.bin_combo.addItem(exe)
        if not self.current_exe: self.current_exe=deepcopy(list(exes.keys())[0])
        self.bin_combo.setCurrentText(self.current_exe)
        self.bin_combo.currentTextChanged.connect(self.select_exe)
        preset_layout.addWidget(self.bin_combo,2)


        self.settings_button = QPushButton("☰")
        self.settings_button.setFixedSize(35, 35)
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self.open_exe_manager)
        preset_layout.addWidget(self.settings_button)


        self.play_button = QPushButton("▶︎")
        self.play_button.setFixedSize(35, 35)
        self.play_button.setToolTip("Settings")
        self.play_button.clicked.connect(self.on_play)
        preset_layout.addWidget(self.play_button)

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
        self.add_button.setFixedSize(35, 35)
        self.add_button.setToolTip("Add Mod")
        self.add_button.clicked.connect(self.add_mod_dialog)
        
        self.move_up_button = QPushButton("↑")
        self.move_up_button.setFixedSize(35, 35)
        self.move_up_button.setToolTip("Move Up")
        self.move_up_button.clicked.connect(self.move_mod_up)
        self.move_up_button.setEnabled(False)
        
        self.move_down_button = QPushButton("↓")
        self.move_down_button.setFixedSize(35, 35)
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

    def _load_initial_data(self, reload=False):
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
        if not reload: self.load_plugins_list()

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

    def read_presets(self):
        global LOAD_ORDER
        LOAD_ORDER=Path(self.cfg["LOAD_ORDER"])
        self.preset_combo.clear()
        for i in os.listdir(PRESET_DIR):
            self.preset_combo.addItem(i)
        self.preset_combo.setCurrentText(LOAD_ORDER.name)

    def load_plugins_list(self):
        self.plugins_list.clear()
        try:
            backup_path = Path(BACKUP_DIR)
            plugins_file = None
            
            for filename in ['Plugins.txt', 'plugins.txt']:
                potential_path = backup_path / filename
                if not potential_path.exists(): continue
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
        if not name_item: return
            
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
            self.populate_file_explorer(Path(self.cfg["SOURCE_DIR"]) / Path(mod_name))
    
    def populate_file_explorer(self, path):
        self.file_explorer.clear()
        if not path.exists() or not path.is_dir(): return
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
        if not self.is_separator_row(row): return
        
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

    def load_mods(self):
        try:
            read_cfg(sync=False) # check for update
            self.executor.add_command(perform_copy, tuple())
            self.update_unload_button_state()
            self.load_plugins_list()
            self.statusBar().showMessage("Mods loaded successfully", SHOW_MSG_TIME)
        except Exception as e:
            QMessageBox.warning(self, "Load Error", f"Failed to load mods:\n{str(e)}")

    def unload_mods(self):
        try:
            read_cfg(sync=False) # check for update
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
        reply = QMessageBox.question(
            self, "Confirm Enable All",
            "Enable all mods?\n",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._set_all_mods_state(Qt.CheckState.Checked)
            
    def disable_all(self):
        reply = QMessageBox.question(
            self, "Confirm Disable All",
            "Disable all mods?\n",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
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

    def move_mod_top(self):
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or min(selected_rows) <= 0:
            return
        nrow=0
        nsrows=[]
        for row in selected_rows:
            self.move_row(row, nrow)
            nrow+=1
            nsrows.append(nrow-1)
        self._reselect_rows(nsrows)
        self.update_priority_numbers()
        self.auto_save_load_order()
    
    def move_mod_bot(self):
        selected_rows = sorted(set(item.row() for item in self.mod_table.selectedItems()))
        if not selected_rows or max(selected_rows) >= self.mod_table.rowCount() - 1:
            return
        nr=self.mod_table.rowCount()-1
        sr=[]
        for row in reversed(selected_rows):
            self.move_row(row, nr)
            sr.append(nr)
            nr-=1
        self._reselect_rows(sr)
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

    def auto_save_load_order(self,instant=False):
        global RELOAD_ON_INSTALL
        if self._loading: return
        try:
            self.cfg=read_cfg(sync=False) # check for update
            if instant: self.save_load_order()
            else: self.executor.add_command(self.save_load_order, tuple())
            if self.cfg["RELOAD_ON_INSTALL"]:
                #self.save_load_order()
                self.load_mods()
                self.statusBar().showMessage("Load order auto-saved", SHOW_MSG_TIME)
        except Exception as e:
            print("error: encountered exception: "+str(e)+" during autosave!")
            self.statusBar().showMessage(f"Auto-save failed: {str(e)}", SHOW_MSG_TIME)

    def save_load_order(self):
        try:
            mods = self._collect_load_order()
            read_cfg(sync=False) # check for update
            save_to_loadorder(mods, verbose=False)
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
            if self.is_separator_row(row): continue
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
            menu.addSeparator()
            collapse_all_action  = menu.addAction("Collapse All")
            expand_all_action    = menu.addAction("Expand All")
            
            action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
            
            if action == rename_sep_action:      self.rename_separator(clicked_row)
            elif action == remove_sep_action:    self.remove_separator(clicked_row)
            elif action == add_sep_above_action: self.add_separator_at(clicked_row)
            elif action == add_sep_below_action: self.add_separator_at(clicked_row + 1)
            elif action == collapse_all_action:  self.collapse_all_seps()
            elif action == expand_all_action:    self.expand_all_seps()
        else:
            if not self.mod_table.selectedItems():
                add_sep_action = menu.addAction("Add Separator Here")
                action = menu.exec(self.mod_table.viewport().mapToGlobal(position))
                if action == add_sep_action:
                    self.add_separator_at(clicked_row if clicked_row >= 0 else self.mod_table.rowCount())
                return
            
            move_up_action = menu.addAction("Move Up")
            move_down_action = menu.addAction("Move Down")
            to_top_action = menu.addAction("Move Top")
            to_bot_action = menu.addAction("Move Bottom")
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
            
            if action == rename_action: self.rename_selected_mod()
            elif action == move_up_action: self.move_mod_up()
            elif action == move_down_action: self.move_mod_down()
            elif action == to_top_action: self.move_mod_top()
            elif action == to_bot_action: self.move_mod_bot()
            elif action == enable_action: self.enable_selected_mods()
            elif action == disable_action: self.disable_selected_mods()
            elif action == add_sep_above_action:
                selected = self.mod_table.selectedItems()
                if selected:
                    self.add_separator_at(selected[0].row())
            elif action == add_sep_below_action:
                selected = self.mod_table.selectedItems()
                if selected:
                    self.add_separator_at(selected[0].row() + 1)
            elif action == remove_action: self.remove_selected_mod()
            elif action == open_folder_action: self.open_mod_folder()


    def select_preset(self, text):
        print("switching to preset "+text)
        load_order=str(PRESET_DIR / Path(text))
        self.cfg["LOAD_ORDER"]=load_order
        write_cfg(self.cfg)
        sync_loadorder()
        self._init_ui(verbose=self.log_output.toPlainText())
        self._load_initial_data()

    def add_preset(self, text=None):
        if text:
            name, ok = QInputDialog.getText(
                self, "New Preset", text+"Preset name",
                QLineEdit.EchoMode.Normal, "New Preset")
        else:
            name, ok = QInputDialog.getText(
                self, "New Preset", "Preset name:",
                QLineEdit.EchoMode.Normal, "New Preset")
        if ok and name:
            name=name.removesuffix(".txt")+".txt"
            if name in os.listdir(PRESET_DIR):
                print("error: preset already exists")
                QMessageBox.warning(self, "Preset Error", f"Preset already exists: {name}")
                return
            Path(str(PRESET_DIR / name)).touch() 
            self.select_preset(name)

    def rename_preset(self):
        name, ok = QInputDialog.getText(
            self, "Rename Preset", "Preset name",
            QLineEdit.EchoMode.Normal, self.preset_combo.currentText())
        if name:
            if name in os.listdir(PRESET_DIR):
                print("error: preset already exists")
                QMessageBox.warning(self, "Preset Error", f"Preset already exists: {name}")
                return
            name=name.removesuffix(".txt")+".txt"
            new_name=PRESET_DIR/name
            os.rename(self.cfg["LOAD_ORDER"], new_name)
            self.cfg["LOAD_ORDER"]=new_name
            self.preset_combo.setItemText(self.preset_combo.currentIndex(),name)

    def dup_preset(self):
        name, ok = QInputDialog.getText(
            self, "Duplicate Preset", "Preset name",
            QLineEdit.EchoMode.Normal, self.preset_combo.currentText())
        if name:
            if name in os.listdir(PRESET_DIR):
                print("error: preset already exists")
                QMessageBox.warning(self, "Preset Error", f"Preset already exists: {name}")
                return
            name=name.removesuffix(".txt")+".txt"
            new_name=PRESET_DIR/name
            shutil.copy(self.cfg["LOAD_ORDER"],new_name)
            self.cfg["LOAD_ORDER"]=new_name
            self.select_preset(name)

    def del_preset(self):
        reply = QMessageBox.question(
            self, "Confirm Removal",
            "Remove this preset?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            print("removing "+str(self.cfg["LOAD_ORDER"]))
            os.unlink(self.cfg["LOAD_ORDER"])
            preset_idx=self.preset_combo.currentIndex()
            if self.preset_combo.count()>1:
                self.preset_combo.removeItem(preset_idx)
            else:
                print("no presets left, creating new preset...")
                self.add_preset(text="No presets left, creating new preset...\n")
        
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
                if not self.is_separator_row(r): continue
                next_separator = r
                break
            for r in range(row + 1, next_separator):
                self.mod_table.setRowHidden(r, False)
            self.mod_table.removeRow(row)
            self.update_priority_numbers()
            self.auto_save_load_order()

    def collapse_all_seps(self):
        for r in range(self.mod_table.rowCount()):
            if not self.is_separator_row(r): continue
            self._collapse_selected_separators(r)

    def expand_all_seps(self):
        for r in range(self.mod_table.rowCount()):
            if not self.is_separator_row(r): continue
            self._expand_selected_separators(r)

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

        names=[self.mod_table.collect_row_data(row)["name"] for row in selected_rows]
        if has_separator and has_mod:
            msg = f"Remove selected mods and separators from load order?\n{'\n'.join(names)}"
        elif has_separator:
            msg = f"Remove selected separator(s) from load order?\n{'\n'.join(names)}"
        else:
            msg = f"Remove selected mod(s) from load order?\n{'\n'.join(names)}"
        
        reply = QMessageBox.question(self, "Confirm Removal", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            for row in selected_rows:
                if self.is_separator_row(row):
                    children = self.get_separator_children_rows(row)
                    for child_row in children:
                        self.mod_table.setRowHidden(child_row, False)
                mod_name = self.mod_table.collect_row_data(row)["name"]
                if not self.is_separator_row(row): delete_mod(mod_name, gui=True)
                else: print(f"deleted seperator {mod_name}!")
                self.mod_table.removeRow(row)
            
            self.update_priority_numbers()
            self.update_status()
            #sync_loadorder()
            self.auto_save_load_order()
            read_cfg() # check for update
            if RELOAD_ON_INSTALL: self.load_mods()

    def toggle_selected_mods(self):
        selected_rows = set(item.row() for item in self.mod_table.selectedItems())
        if not selected_rows: return
        
        enabled_count = sum(1 for row in selected_rows 
                          if self.mod_table.item(row, 1).checkState() == Qt.CheckState.Checked)
        new_state = Qt.CheckState.Unchecked if enabled_count > len(selected_rows) / 2 else Qt.CheckState.Checked
        
        for row in selected_rows:
            row_data = self.mod_table.collect_row_data(row)
            if row_data["is_separator"]: continue
            self.mod_table.item(row, 1).setCheckState(new_state)
        
        self.update_status()
        read_cfg(sync=False) # check for update
        if RELOAD_ON_INSTALL:
            self.load_mods()

    def rename_selected_mod(self):
        selected_items = self.mod_table.selectedItems()
        if not selected_items: return
        
        row = selected_items[0].row()
        old_name = self.mod_table.item(row, 2).text()
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Mod", "Enter new name:",
            QLineEdit.EchoMode.Normal, old_name)
        
        if ok and new_name and new_name != old_name:
            try:
                rename_mod(old_name, new_name)
                self.mod_table.item(row, 2).setText(new_name)
                self.explorer_label.setText(new_name)
                self.populate_file_explorer(Path(self.cfg["SOURCE_DIR"]) / Path(new_name))
                self.auto_save_load_order()
                self.statusBar().showMessage(f"Renamed '{old_name}' to '{new_name}'", SHOW_MSG_TIME)
            except Exception as e:
                QMessageBox.warning(self, "Rename Error", f"Failed to rename mod:\n{str(e)}")

    def remove_selected_mod(self):
        self.delete_selected_items()

    def open_mod_folder(self):
        selected_items = self.mod_table.selectedItems()
        if not selected_items: return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        mod_path = Path(self.cfg["SOURCE_DIR"]) / Path(mod_name)
        
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
        if not selected_items: return
        
        row = selected_items[0].row()
        mod_name = self.mod_table.item(row, 2).text()
        full_path = Path(self.cfg["SOURCE_DIR"]) / mod_name / Path(*path_parts)
        
        if not full_path.exists():
            QMessageBox.warning(self, "Error", f"Path not found:\n{full_path}")
            return
        
        self._open_path(full_path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            valid_extensions = {'.7z', '.zip', '.rar',''}
            for url in event.mimeData().urls():
                if (Path(url.toLocalFile()).suffix.lower() in valid_extensions) \
                or os.path.isdir(Path(url.toLocalFile())):
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
                self._init_ui(verbose=self.log_output.toPlainText())
                self._load_initial_data(reload=True)
            elif event.key() == Qt.Key.Key_Minus:
                self._scale_factor = max(0.5, self._scale_factor - 0.1)
                self.apply_scale()
                self._init_ui(verbose=self.log_output.toPlainText())
                self._load_initial_data(reload=True)
            elif event.key() == Qt.Key.Key_0:
                self._scale_factor = 1.0
                self.apply_scale()
                self._init_ui(verbose=self.log_output.toPlainText())
                self._load_initial_data(reload=True)
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def apply_scale(self):
        # TODO: fix this (broken w/ other stylesheets)
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
        valid_extensions = {'.7z', '.zip', '.rar',''}
        installed_count = 0
        
        file_paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if (Path(url.toLocalFile()).suffix.lower() in valid_extensions and Path(url.toLocalFile()).is_file())
            or os.path.isdir(Path(url.toLocalFile()))
        ] 
        file_paths.sort(key=lambda p: p.stat().st_mtime)
         
        extract_thread=ExtractorThread(file_paths, self.cfg["SOURCE_DIR"], self) 
        status_thread=StatusThread(self.status_label,Path(file_paths[0]))
        self.extract_threads.append(extract_thread)
        self.status_threads.append(status_thread)

        #extract_thread.archive_extracted.connect(lambda path,archive: self.handle_mod_install(path,archive))
        extract_thread.progress.connect(lambda file: status_thread.set_file(file))
        extract_thread.temp_complete.connect(status_thread.set_temp_complete)
        extract_thread.complete.connect(status_thread.done)
        extract_thread.start()
        status_thread.start()
 
        self.setStyleSheet("") # this seems broken with extra stylesheets
        event.acceptProposedAction()

    def add_mod_dialog(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Mod Archive(s)", "",
            "Mod Archives (*.7z *.zip *.rar);;All Files (*)"
        )
        if not file_paths: return
        file_paths.sort(key=lambda p: Path(p).stat().st_mtime)
        
        extract_thread=ExtractorThread(file_paths, self.cfg["SOURCE_DIR"], self) 
        status_thread=StatusThread(self.status_label)
        self.extract_threads.append(extract_thread)
        self.status_threads.append(status_thread)

        #extract_thread.archive_extracted.connect(lambda path,archive: self.handle_mod_install(path,archive))
        extract_thread.progress.connect(lambda file: status_thread.set_file(file))
        extract_thread.temp_complete.connect(status_thread.set_temp_complete)
        extract_thread.complete.connect(status_thread.done)
        extract_thread.start()
        status_thread.start()
 
    def handle_mod_install(self, temp_dir, archive_path):
        if not temp_dir:
            QMessageBox.warning(self,
                        "Installation Error",
                        f"Encountered exception during mod extraction for archive:\n{Path(archive_path).name}")
            return
        
        name=install_mod(archive_path=archive_path, temp_dir=temp_dir, gui=True, parent=self)
        if name: 
            self.add_mod(name, enabled=True)
            self.mod_table.scrollToBottom()
            self.statusBar().showMessage(f"Successfully installed {name}", SHOW_MSG_TIME)

    def select_exe(self, text):
        if text=='': return
        self.current_exe = text
        for exe in self.cfg["EXECUTABLES"]:
            self.cfg["EXECUTABLES"][exe]["SELECTED"]=False
        self.cfg["EXECUTABLES"][self.current_exe]["SELECTED"]=True
        write_cfg(self.cfg) 
    
    def open_ini_manager(self):
        #cfg_dict=read_cfg(sync=False)
        ensure_dir(Path(self.cfg["INI_DIR"]))
        if determine_game(self.cfg["COMPAT_DIR"])!="Default":
            compat_dir=Path(self.cfg["COMPAT_DIR"])
            back_dir=Path(self.cfg["INI_DIR"])
            ini_dir=get_ini_path(Path(self.cfg["COMPAT_DIR"])) 
        else:
            compat_dir=Path(self.cfg["COMPAT_DIR"])
            back_dir=Path(self.cfg["INI_DIR"])
            try: test=Path(self.cfg["INI_DIR"])/os.listdir(back_dir)[0]
            except: test=back_dir
            ini_dir=test
        
        self.ini_manager = INIManager(compat_dir,back_dir,ini_dir)
        self.ini_manager.show() 

    def open_exe_manager(self):
        self.exe_manager = ExeManager(parent=self)
        self.exe_manager.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.exe_manager.closed.connect(self.on_exe_manager_close)
        self.exe_manager.show() 
    
    def on_exe_manager_close(self):
        self.cfg=read_cfg(sync=False)
        exes=self.cfg["EXECUTABLES"]
        self.bin_combo.clear()
        new_select=None
        for exe in exes:
            if exes[exe]["SELECTED"]: new_select=exe
            self.bin_combo.addItem(exe)
        if not new_select: self.current_exe=deepcopy(list(exes.keys())[0])
        self.bin_combo.setCurrentText(self.current_exe)

    def closeEvent(self, event):
        print("saving load order...")
        if self.cfg["UPDATE_ON_CLOSE"]: self.auto_save_load_order(instant=True)
        event.accept()

    def on_play(self):
        if not is_steam_running():
            QMessageBox.warning(None,
                        "Launch Error",
                        f"Steam is required to launch the game\nPlease open steam to launch executable")
            return
        if self.cfg["LINK_ON_LAUNCH"]: 
            self.auto_save_load_order(instant=True)
            perform_copy()
        launch_game(self.cfg, self.current_exe) 


def load_stylesheet(filename):
    file = QFile(str(filename))
    if file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        stream = QTextStream(file)
        stylesheet = stream.readAll()
        file.close()
        return stylesheet
    return ""

def select_directory():
    """Show detailed prompt then directory picker with confirmation"""
    app = QApplication(sys.argv)
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle("Target Directory Required")
    msg.setText("Select the root of your game directory:")
    msg.setInformativeText(
        "Choose the directory containing the \"Data\" folder.\n\n"
        "Click OK to choose a directory."
    )
    msg.setStandardButtons(
        QMessageBox.StandardButton.Ok | 
        QMessageBox.StandardButton.Cancel
    )
    msg.setDefaultButton(QMessageBox.StandardButton.Ok)
    result = msg.exec()
    if result == QMessageBox.StandardButton.Ok:
        while True:
            directory = QFileDialog.getExistingDirectory(
                None,
                "Select Target Directory",
                "/home",
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
            if directory:
                directory=os.path.realpath(directory)
                if not directory.endswith("Data"): directory=os.path.join(directory,"Data")
                try: compat = str(infer_compat_path(Path(directory))) # test path validity
                except Exception as e: 
                    directory=Path(directory).parent
                    QMessageBox.warning(None, "Warning", f"Path is invalid: {directory}\nChoose a game with a Data directory in it")
                    continue
                confirm = QMessageBox.question(
                    None,
                    "Confirm Directory",
                    f"Are you sure you want to use this directory?\n\n{directory}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                
                if confirm == QMessageBox.StandardButton.Yes: return directory
                else: continue
            else:
                QMessageBox.warning(
                    None,
                    "Error",
                    "No directory was selected!")
                return None
    else: return None


if __name__ == "__main__":
    cfg=read_cfg(gui=True)
    app = QApplication(sys.argv)
    window = ModLoaderUserInterface()
    stylesheet = load_stylesheet(Path(LOCAL_DIR)/"utils"/"resources"/"stylesheets"/"dark.qss")
    app.setStyleSheet(stylesheet)
    splash = QSplashScreen(QPixmap(str(LOCAL_DIR/"utils"/"resources"/"splash.png")))
    if os.name!="posix": window.show()
    splash.show()
    QTimer.singleShot(1700, splash.close)
    window.show()
    sys.exit(app.exec())
