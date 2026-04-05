
import sys
import platform
import yaml
import tempfile
import random
from pathlib import Path
from copy import deepcopy
from time import sleep

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, 
    QPushButton, QSplitter, QLabel, QLineEdit, QMenu, QMessageBox, 
    QComboBox, QFileDialog, QInputDialog, QTextEdit, QToolButton, 
    QSplashScreen, QToolTip, QStyledItemDelegate, QHeaderView,
    QGraphicsOpacityEffect, QStyle, QScrollArea, QFrame, QCheckBox,
    QDialog, QListWidget, QListWidgetItem, QFormLayout, QTreeView,
    QDialogButtonBox
)
from PyQt6.QtCore import ( Qt, QItemSelectionModel, QObject, QThread, 
    QWaitCondition, pyqtSignal, QMutex, QMutexLocker, QTimer, QPoint, 
    QSize, QFile, QTextStream, QMetaObject, pyqtSlot, QItemSelection,
    QPointF, Qt, QPropertyAnimation, QDir, QEvent, QUrl
)
from PyQt6.QtGui import ( QIcon, QFont, QTextCursor, QCursor, QPixmap, 
    QTextDocument, QPainter, QRadialGradient, QColor, QSyntaxHighlighter,
    QTextCharFormat, QFileSystemModel, QShortcut, QKeySequence,
    QDesktopServices
)

from game_specific import *
from installer import *

OPERATION_TIMEOUT = 500
 
OVERRIDING_COLOR = "#053005"
OVERRIDDEN_COLOR = "#300505"
ALPHA   = 20
OPACITY = ALPHA/255
DIALOGUE_WIDTH   = 60

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
    
    def __init__(self, parent):
        super().__init__()
        self.parent=parent
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
        #self.parent._loading=True
        command_id(*command_data) 
        #self.parent._loading=False
        return f"Executed: {command_id} with data: {command_data}"
        
    def run(self):
        self.exec()
        
    def stop(self):
        self.is_running = False
        if self.timer: self.timer.stop()
        self.quit()
        self.wait()


class ExtractorThread(QThread):
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
            if result: self.call_handle_mod_install.emit(str(temp_dir), str(archive_path))
            else: self.call_handle_mod_install.emit(None, str(archive_path))
               
        self.parent._extracting=False 
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
                QThread.msleep(200)
                continue
            if i>len(a)-1:i=0
            name=Path(self.file).name
            if os.path.isdir(self.file): self.status.setText(f"Copying {name}  {a[i]}")
            else: self.status.setText(f"Extracting {name}  {a[i]}")
            QThread.msleep(500)
            i+=1
        if os.path.isdir(self.file): self.status.setText("Copying complete!")
        else: self.status.setText("Extraction complete!")
        QThread.msleep(200)
        self.status.setText("")

    def set_temp_complete(self):
        self.temp_complete=True 

    def done(self):
        self.stopped=True


class ConflictThread(QThread):
    conflict_update=pyqtSignal(int,str,str)
    
    def __init__(self, parent):
        super().__init__()
        self.parent=parent
        self.mod_table=parent.mod_table
        self.load_order=[]
   
    def run(self):
        while 1:
            # this is retarded but i am at my wits end
            if (not self.parent._is_sorted_alphabetically) \
            and (not self.parent._loading) \
            and (not self.parent._extracting):
                try: updated_mods=self.parent._collect_load_order()
                except: continue
                if self.load_order!=updated_mods:
                    self.load_order=updated_mods
                    try: self.update_conflict_data(self.load_order)
                    except Exception as e: print(e); self.load_order=[]
            elif self.parent._is_sorted_alphabetically: self.load_order=[]
            QThread.msleep(80)
        
    def set_mod_conflict_flags(self, name, row):
        over_text=""
        tooltip_text_er=""
        tooltip_text_en=""
        tooltip_text_fu=""
        if name in self.mod_table.overriders.keys(): 
            if tooltip_text_er=="": tooltip_text_er+="<span style=\"color: #99ff99; font-weight: bold;\">Overriding:</span><br>  "
            over_text+=" <span style=\"color: #99ff99; font-size: 14px;\">▲</span>"
            tooltip_text_er+="\n  ".join(self.mod_table.overriders[name])
        if name in self.mod_table.overriddens.keys(): 
            if tooltip_text_en=="": tooltip_text_en+="<span style=\"color: #ff9999; font-weight: bold;\">Overridden By:</span><br>  "
            over_text+=" <span style=\"color: #ff9999; font-size: 14px;\">▼</span>"
            tooltip_text_en+="\n  ".join(self.mod_table.overriddens[name])
        if name in self.mod_table.overriddens_full.keys(): 
            if tooltip_text_fu=="": tooltip_text_fu+="<span style=\"color: #ff9999; font-weight: bold;\">Fully Overridden By:</span><br>  "
            over_text+=" <span style=\"color: #ff9999; font-size: 14px;\">▽</span>"
            tooltip_text_fu+="\n  ".join(self.mod_table.overriddens_full[name])
    
        if tooltip_text_fu and tooltip_text_fu.replace("Fully ",'')==tooltip_text_en: 
            tooltip_text_en=""
            over_text=over_text.replace("<span style=\"color: #ff9999; font-size: 14px;\">▼</span>",'')

        over_text=f'<div style="text-align: center;">{over_text}</div>'

        if tooltip_text_er and tooltip_text_en and tooltip_text_fu: 
            tooltip_text=tooltip_text_fu+'<br><br>'+tooltip_text_en+'<br><br>'+tooltip_text_er
        elif tooltip_text_er and tooltip_text_en: tooltip_text=tooltip_text_er+'<br><br>'+tooltip_text_en
        elif tooltip_text_fu and tooltip_text_en: tooltip_text=tooltip_text_fu+'<br><br>'+tooltip_text_en
        elif tooltip_text_fu and tooltip_text_er: tooltip_text=tooltip_text_fu+'<br><br>'+tooltip_text_er
        elif tooltip_text_er: tooltip_text=tooltip_text_er
        elif tooltip_text_en: tooltip_text=tooltip_text_en
        elif tooltip_text_fu: tooltip_text=tooltip_text_fu
        else: tooltip_text=""
    
        self.conflict_update.emit(row,over_text,tooltip_text)
        
    def update_conflict_data(self, mods=[]):
        er,en,fu,mf=scan_mod_overrides(self.parent.cfg["SOURCE_DIR"],mods)
        self.mod_table.overriders=er
        self.mod_table.overriddens=en
        self.mod_table.overriddens_full=fu
        self.mod_table.mod_files=mf

        for i in range(len(mods)):
            if mods[i].startswith(">#") or mods[i].startswith("v#"): continue # skip seps
            self.set_mod_conflict_flags(mods[i],i)


class EditableComboBox(QComboBox):
    def __init__(self, action_dict, parent=None):
        super().__init__(None)
        self.action_dict = action_dict
        self.parent=parent
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
    
    def show_context_menu(self, pos):
        menu=QMenu(self)
        actions=[]
        for action in self.action_dict: actions.append(menu.addAction(action))
        action=menu.exec(self.mapToGlobal(pos))
        for check_action in actions:
            if action==check_action: exec(self.action_dict[action.text()])
            
    def open_in_editor(self):
        file_path = str(self.parent.cfg["LOAD_ORDER"])
        print("Opening loadorder file with system text editor...")
        if not os.path.isfile(file_path):
            print("error: could not open "+file_path)
            return
        if sys.platform == 'win32':    os.startfile(file_path)
        elif sys.platform == 'darwin': subprocess.run(['open', file_path])
        else: subprocess.run(['xdg-open', file_path]) # linux


class RichTextDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg: option.backgroundBrush = bg
        style = option.widget.style()
        style.drawControl(style.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            if option.state & QStyle.StateFlag.State_Selected:
                color = option.palette.highlightedText().color().name()
            else:
                color = option.palette.text().color().name()
            if not Qt.mightBeRichText(text):
                text = f"<span style='font-weight: 600;'>{text}</span>"
            text = f"<span style='color: {color};'>{text}</span>"
            doc = QTextDocument()
            doc.setHtml(text)
            painter.save()
            painter.translate(option.rect.topLeft())
            doc.setTextWidth(option.rect.width())
            doc.drawContents(painter)
            painter.restore()
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            doc = QTextDocument()
            doc.setHtml(text)
            return QSize(int(doc.idealWidth()), int(doc.size().height()))
        return super().sizeHint(option, index)


class FadingBg:
    def __init__(self, table, paths, interval_ms=20000): # 20000 - 20s
        global OVERRIDING_COLOR, OVERRIDDEN_COLOR
        OVERRIDING_COLOR = "#00ff00"
        OVERRIDDEN_COLOR = "#ff0000"
        self.table = table
        self.table.horizontalHeader().setAutoFillBackground(False)
        self.table.horizontalHeader().setAutoFillBackground(False)
        self.viewport = table.viewport()
        self.paths = [str(p) for p in paths]
        self.index = 0
        self.full_opacity=0.25
        # two layered labels
        self.label1 = QLabel(self.table)
        self.label2 = QLabel(self.table)
        for lbl in (self.label1, self.label2):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setScaledContents(False)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lbl.lower()
        self.update_geometry()
        # opacity effects
        self.fx1 = QGraphicsOpacityEffect(self.label1)
        self.fx2 = QGraphicsOpacityEffect(self.label2)
        self.label1.setGraphicsEffect(self.fx1)
        self.label2.setGraphicsEffect(self.fx2)
        self.fx1.setOpacity(self.full_opacity)
        self.fx2.setOpacity(0.0)
        self.timer = QTimer()
        self.timer.timeout.connect(self.fade_next)
        self.timer.start(interval_ms)
        #self.timer.start(10000)
        self.set_pixmap(self.label1, self.paths[self.index])
        # keep resized
        table.resizeEvent = self._wrap_resize(table.resizeEvent)
        
    def _wrap_resize(self, orig):
        def new_resize(e):
            if orig: orig(e)
            self.update_geometry()
        return new_resize

    def update_geometry(self):
        header_h = self.table.horizontalHeader().height()
        geo = deepcopy(self.viewport.geometry())

        # Move label up and increase height so it covers header + viewport
        geo.setTop(geo.top() - header_h)
        geo.setHeight(geo.height() + header_h)

        for lbl in (self.label1, self.label2):
            lbl.setGeometry(geo)
            path = lbl.property("path")
            if path: self.set_pixmap(lbl, path)
            lbl.lower()

    def apply_vignette(self, pix):
        result = QPixmap(pix.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pix)
        
        center = QPointF(pix.width() / 2, (pix.height() / 2)-400)
        
        # Cap the radius at a maximum value
        max_dimension = max(pix.width(), pix.height())
        radius = min(max_dimension / 1.4, 2000)  # Cap at 1200px
        
        grad = QRadialGradient(center, radius)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.7, QColor(0, 0, 0, 180))
        grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        
        painter.fillRect(result.rect(), grad)
        painter.end()
        return result   

    def set_pixmap(self, label, path):
        pm = QPixmap(path)
        try: label.setProperty("path", path)
        except: return
        if pm.isNull(): return
        scaled = pm.scaled(
            label.size(),  # ← was self.viewport.size()
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        scaled = self.apply_vignette(scaled)
        label.setPixmap(scaled)

    def fade_next(self):
        self.index = (self.index + 1) % len(self.paths)
        next_path = self.paths[self.index]

        # prepare second label with next image
        self.set_pixmap(self.label2, next_path)
        try: self.label2.raise_()
        except: return

        # animations
        self.anim_out = QPropertyAnimation(self.fx1, b"opacity")
        self.anim_out.setDuration(2500)
        self.anim_out.setStartValue(self.full_opacity)
        self.anim_out.setEndValue(0.0)

        self.anim_in = QPropertyAnimation(self.fx2, b"opacity")
        self.anim_in.setDuration(2500)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(self.full_opacity)

        self.anim_out.start()
        self.anim_in.start()

        # swap labels after fade
        self.anim_in.finished.connect(self._swap)
        self.update_geometry()

    def _swap(self):
        self.label1, self.label2 = self.label2, self.label1
        self.fx1, self.fx2 = self.fx2, self.fx1


class ModTable(QTableWidget):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(*args, **kwargs)
        global OVERRIDING_COLOR, OVERRIDDEN_COLOR
        OVERRIDING_COLOR = "#053005"
        OVERRIDDEN_COLOR = "#300505"
        self.parent=parent
        self.alpha=255
        self.opacity=1
        if self.parent.cfg["DO_REQUESTS"]:
            bg_paths=get_game_bgs(self.parent.cfg)
            if bg_paths:
                self.alpha=ALPHA
                self.opacity=OPACITY
                self.background=FadingBg(self,bg_paths)

    def is_separator_row(self, row):
        name_item = self.item(row, 2)
        return name_item and name_item.data(Qt.ItemDataRole.UserRole) == "separator"

    def is_separator_collapsed(self, row):
        if not self.is_separator_row(row): return None
        if self.item(row, 0).text()=="▶": return True
        else: return False

    def get_row_from_name(self,name):
        for row in range(self.rowCount()):
            item = self.item(row, 2)
            if item and item.text() == name: return row
        return None

    def get_row_from_priority(self,priority):
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and item.text() == str(priority): return row
        return None

    def get_all_separators(self):
        seps=[]
        for row in range(self.rowCount()):
            name_item=self.item(row,2)
            if name_item and name_item.data(Qt.ItemDataRole.UserRole) == "separator":
                seps.append(name_item.text())
        return seps

    def get_priorities(self):
        priorities=[]
        for row in range(self.rowCount()):
            if self.is_separator_row(row): continue
            priorities.append(int(self.item(row,0).text()))
        return priorities

    def update_priority_numbers(self):
        priority = 1
        for row in range(self.rowCount()):
            if self.is_separator_row(row): continue
            priority_item = self.item(row, 0)
            if priority_item:
                priority_item.setText(str(priority))
                priority += 1
    
    def get_separator_children(self, separator_row):
        children = []
        for r in range(separator_row + 1, self.rowCount()):
            if self.is_separator_row(r): break
            children.append(r)
        return children

    def get_item_separator_row(self, row):
        if self.is_separator_row(row): return None
        for i in range(row,-1,-1):
            if self.is_separator_row(i): return i
        return None
       
    def collect_row_data(self, row):
        is_sep = self.is_separator_row(row)
        if is_sep:
            return { 'priority_num': "",
                     'is_separator': True,
                     'name': self.item(row, 2).data(Qt.ItemDataRole.UserRole + 1),
                     'collapse_state': self.item(row, 0).text(),
                     'hidden': self.isRowHidden(row),
                     'conflicts': "",
                     'conflict_tooltip':"" }

        return { 'priority_num': self.item(row,0).text(),
                 'is_separator': False,
                 'name': self.item(row, 2).text(),
                 'checkbox': self.item(row, 1).checkState(),
                 'hidden': self.isRowHidden(row),
                 'conflicts': self.item(row,3).text(),
                 'conflict_tooltip': self.item(row,3).toolTip() }

    def create_row_from_data(self, row, data, hidden=False):
        if data['is_separator']:
            self._create_separator_items(row, data['name'], collapse_state=data["collapse_state"])
        else:
            self._create_mod_items(row, data['name'], data['checkbox'], data['conflicts'], hidden=hidden)
        
        if data['hidden']:
            self.setRowHidden(row, True)
    
    def _create_separator_items(self, row, name, collapse_state=False, conflicts="", tooltip=""):
        self.parent._loading=True
        if collapse_state or name[0]==">": collapse_state="▶"
        else: collapse_state="▼"
        priority_item = QTableWidgetItem(collapse_state)
        priority_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        priority_item.setToolTip("Collapse/expand separator")
        self.setItem(row, 0, priority_item)
        
        checkbox_item = QTableWidgetItem("")
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        self.setItem(row, 1, checkbox_item)
        
        if name.startswith("v#") \
        or name.startswith(">#"): clean_name=name[2:]
        else: clean_name=name
        if not Qt.mightBeRichText(name): clean_name=f"<b><u>{clean_name}</u></b>"
        name_item = QTableWidgetItem(clean_name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        font = name_item.font()
        font.setBold(True)
        font.setUnderline(True)
        name_item.setFont(font)
        name_item.setData(Qt.ItemDataRole.UserRole, "separator")
        name_item.setData(Qt.ItemDataRole.UserRole + 1, name)
        self.setItem(row, 2, name_item)

        conflict_item = QTableWidgetItem("")
        conflict_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        conflict_item.setFlags(conflict_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row,3, conflict_item)
        self.parent._loading=False

    def _create_mod_items(self, row, name, checkbox_state=None, conflicts="", tooltip="", hidden=False):
        self.parent._loading=True
        priority_item = QTableWidgetItem("")
        priority_item.setFlags(priority_item.flags() | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsDragEnabled)
        priority_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setItem(row, 0, priority_item)
        
        checkbox_item = QTableWidgetItem()
        checkbox_item.setFlags(checkbox_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        if checkbox_state is not None:
            checkbox_item.setCheckState(checkbox_state)
        self.setItem(row, 1, checkbox_item)
        
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(row, 2, name_item)
        
        conflict_item = QTableWidgetItem(conflicts)
        conflict_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        conflict_item.setToolTip(tooltip)
        self.setItem(row, 3, conflict_item)
        conflict_item.setFlags(conflict_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        if hidden: self.setRowHidden(row,True)
        self.parent._loading=False

    def highlight_row(self, row, overriding=False, overridden=False):
        for col in range(self.columnCount()):
            if self.item(row, col):
                if   overriding: color=QColor(OVERRIDING_COLOR)
                elif overridden: color=QColor(OVERRIDDEN_COLOR)
                else: color=QColor(0,0,0) # TODO: will need to be theme adaptive
                color.setAlpha(self.alpha)
                self.item(row, col).setBackground(color)
 
    def dropEvent(self, event):
        # this is the worst
        drop_pos = event.position().toPoint()
        index = self.indexAt(drop_pos)
        selected = self.selectedItems()
        if not selected:
            event.ignore()
            return
      
        # selected separator, get all child items 
        selected_rows = sorted(set(item.row() for item in selected))
        more_selected_rows=[]
        for row in selected_rows:
            if self.is_separator_row(row) and self.is_separator_collapsed(row):
                more_selected_rows+=self.get_separator_children(row)
        selected_rows+=more_selected_rows
        
        if not index.isValid(): target_row = self.rowCount()
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
                if min_sel <= target_row <= max_sel + 1: return
        rows_data = [self.collect_row_data(row) for row in selected_rows]

        for row in reversed(selected_rows):
            self.removeRow(row)
        
        rows_removed_before_target = sum(1 for r in selected_rows if r < target_row)
        adjusted_target = target_row - rows_removed_before_target

        # determine if we dragged into collapsed separator
        hidden=False
        if self.is_separator_row(adjusted_target-1) \
        and self.is_separator_collapsed(adjusted_target-1):
            children=self.get_separator_children(adjusted_target-1)
            if children: adjusted_target=max(children)+1
            hidden=True

        new_selection_rows = []
        for i, data in enumerate(rows_data):
            insert_row = adjusted_target + i
            self.insertRow(insert_row)
            self.create_row_from_data(insert_row, data, hidden=hidden)
            new_selection_rows.append(insert_row)
        
        self.clearSelection()
        selection = QItemSelection()
        for row in new_selection_rows:
            left = self.model().index(row, 0)
            right = self.model().index(row, self.columnCount() - 1)
            selection.select(left, right)
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.Select)
        
        self.update_priority_numbers()
        
        QTimer.singleShot(100,lambda: self.parent.highlight_conflicts(new_selection_rows))
        if self.selectedItems():
            self.itemChanged.emit(self.selectedItems()[0])


class ConfigManager(QMainWindow):
    applied = pyqtSignal()

    def __init__(self, cfg_dict):
        super().__init__()
        from bdsm import read_cfg
        #self.config = cfg_dict
        self.config = read_cfg()
        self.widgets = {}
        self.setWindowTitle("Settings")
        self.setMinimumWidth(800)
        self.build_ui()

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.apply)

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        form = QVBoxLayout(container)
        form.setSpacing(8)
        form.setContentsMargins(4, 4, 4, 4)

        longest = max((len(k) for k in self.config.keys()), default=10)
        label_width = longest * 8 + 8  # rough char width
        
        BOOL_KEYS         = {"RELOAD_ON_INSTALL", "UPDATE_ON_CLOSE", "LINK_ON_LAUNCH", "DO_REQUESTS"}
        PATH_KEYS         = {"SOURCE_DIR", "TARGET_DIR", "COMPAT_DIR", "PRESET_DIR", "LOAD_ORDER", "INI_DIR"}
        STYLESHEET_KEY    = "STYLESHEET"
        
        tooltips = {"RELOAD_ON_INSTALL":"Reload all mods upon change to loadorder (priority changes, mod install, mod deletion, etc.)",
                    "UPDATE_ON_CLOSE"  :"Save loadorder on close of application",
                    "LINK_ON_LAUNCH"   :"Link all mods upon launching executable",
                    "DO_REQUESTS"      :"Request assets (background and icon images) from Steam API\n(Disabling will not render default background and icons)",
                    "SOURCE_DIR"       :"Mod install directory (location mods are linked from)",
                    "TARGET_DIR"       :"Mod load target directory (location mods are linked to)",
                    "COMPAT_DIR"       :"Steam game compatability data directory (necessarily the 'AppData/Local' directory)",
                    "PRESET_DIR"       :"Preset directory location (location loadorder files are stored)",
                    "LOAD_ORDER"       :"Currently selected loadorder preset file",
                    "INI_DIR"          :"INI backup directory location",
                    "STYLESHEET"       :"Application theme stylesheet (located in <BDSM_INSTALL_DIR>/utils/resources/stylesheets)",
                    "EXECUTABLES"      :"",
                    "INSTANCES"        :""}

        import bdsm
        STYLESHEET_OPTIONS = sorted([Path(i).name for i in os.listdir(bdsm.LOCAL_DIR/"utils"/"resources"/"stylesheets") if i.endswith(".qss")])

        for key, value in self.config.items():
            if key not in tooltips: continue
            row = QHBoxLayout()
            label = QLabel(f"<b>{key.replace("_",' ')}</b>")
            label.setToolTip(tooltips[key])
            label.setFixedWidth(label_width)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(label)

            if key in BOOL_KEYS:
                cb = QCheckBox()
                cb.setChecked(value)
                cb.setToolTip(tooltips[key])
                self.widgets[key] = cb
                row.addWidget(cb)
                row.addStretch()

            elif key == STYLESHEET_KEY:
                combo = QComboBox()
                combo.setMinimumWidth(250)
                options = list(STYLESHEET_OPTIONS)
                if value not in options:
                    options.insert(0, value)
                combo.addItems(options)
                idx = combo.findText(value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                self.widgets[key] = combo
                row.addWidget(combo)
                row.addStretch()
                combo.setToolTip(tooltips[key])

            elif key in PATH_KEYS:
                edit = QLineEdit(value)
                self.widgets[key] = edit
                edit.setToolTip(tooltips[key])
                row.addWidget(edit)
                btn = QPushButton("...")
                btn.setToolTip("Browse files")
                btn.setFixedWidth(28)
                # Determine if it's a file or directory picker
                is_file = key == "LOAD_ORDER"
                btn.clicked.connect(lambda checked, e=edit, f=is_file: file_select(e, f))
                row.addWidget(btn)

            else:
                continue

            form.addLayout(row)

        form.addStretch()

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.addStretch()
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedWidth(90)
        apply_btn.clicked.connect(self.apply)
        bottom.addWidget(apply_btn)

        info_btn = QPushButton("ⓘ")
        info_btn.setToolTip("About")
        info_btn.setFixedSize(30, 35)
        info_btn.clicked.connect(lambda: self.show_info(self))
        bottom.addWidget(info_btn)

        outer.addLayout(bottom)

    def apply(self):
        from bdsm import write_cfg
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):   self.config[key] = widget.isChecked()
            elif isinstance(widget, QComboBox): self.config[key] = widget.currentText()
            else:                               self.config[key] = widget.text()
        write_cfg(self.config)
        self.applied.emit()
        #QMessageBox.information(self, "Saved", "Settings saved!"+' '*20)

    def show_info(self, parent=None):
        dialog = QDialog(parent)
        dialog.setWindowTitle("About")
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        from bdsm import VERSION, LOCAL_DIR

        title = QLabel("BrainDead Simple Modloader")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        image = QLabel()
        pixmap = QPixmap(str(Path(LOCAL_DIR)/"utils"/"resources"/"icon.png")).scaled(200, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        image.setPixmap(pixmap)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)

        version = QLabel(f"Version {VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)

        author = QLabel("Author: Kyle Yagloski (kyleyagloski@gmail.com)")
        author.setAlignment(Qt.AlignmentFlag.AlignCenter)

        github = QLabel('<a href="https://github.com/kyagloski/BrainDeadSimpleModloader">Github</a>')
        github.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github.setOpenExternalLinks(True)

        check_update = QPushButton("Check for Updates")
        check_update.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/kyagloski/BrainDeadSimpleModloader/releases")))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)

        layout2=QHBoxLayout()
        donate = QPushButton("❤ Donate")
        donate.setFixedWidth(80)
        donate.setStyleSheet("""
            QPushButton { color: white; background-color: #003087; font-weight: bold; }
            QPushButton:hover { background-color: #ff99ff; }
            QPushButton:pressed { background-color: #ff1493; }""")
        donate.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://www.paypal.com/donate/?business=V8SHLGV7N7WSN&no_recurring=0&item_name=If+you+are+super+generous%2C+enjoy+my+software%2C+and+would+like+to+support+its+development%2C+donations+are+greatly+appreciated%21&currency_code=USD")))

        layout.addWidget(title)
        layout.addWidget(image)
        layout.addWidget(author)
        layout.addWidget(version)
        layout.addWidget(github)
        layout.addWidget(check_update)
        layout2.addWidget(donate)
        layout2.addStretch()
        layout2.addWidget(buttons)
        layout.addLayout(layout2)

        dialog.exec() 


class InstanceManager(QDialog):
    closed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent=parent
        self.instances=dict()
        self.selected_instance=None

        self.setWindowTitle("Instance Manager")
        self.setMinimumSize(360, 500)
        self.resize(380, 540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        # Header labels
        title = QLabel("Select a game instance")
        root.addWidget(title)

        # Game list
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(83, 55))
        self.list_widget.setSpacing(1)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_select)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        root.addWidget(self.list_widget)

        # Bottom row
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedSize(35, 35)
        self.btn_add.setToolTip("Add instance")
        self.btn_add.clicked.connect(self._on_add)

        self.btn_remove = QPushButton("-")
        self.btn_remove.setFixedSize(35, 35)
        self.btn_remove.setToolTip("Remove instance")
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self._on_remove)

        self.btn_edit = QPushButton("☰")
        self.btn_edit.setFixedSize(35, 35)
        self.btn_edit.setToolTip("Edit instance configuration")
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self.open_instance_editor)

        bottom.addWidget(self.btn_add)
        bottom.addWidget(self.btn_remove)
        bottom.addWidget(self.btn_edit)
        bottom.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_select = QPushButton("Select")
        self.btn_select.setFixedWidth(80)
        self.btn_select.setEnabled(False)
        self.btn_select.clicked.connect(self._on_select)

        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_select)

        root.addLayout(bottom)

        self._refresh_list()

    def _refresh_list(self):
        from bdsm import read_parent_cfg, read_child_cfg, LOCAL_DIR
        #local_dir = Path(os.path.dirname(os.path.realpath(__file__))).parent
        cfg = read_parent_cfg()
        self.list_widget.clear()
        for instance in sorted(cfg["INSTANCES"]):
            item = QListWidgetItem(instance)
            item.setData(Qt.ItemDataRole.UserRole, instance)
            
            instance_path=Path(cfg["INSTANCES"][instance]["PATH"])/"config.yaml"
            instance_cfg=read_child_cfg(gui=True, path=instance_path ,update=False)
            if instance_cfg==None: continue
            target_dir=instance_cfg["TARGET_DIR"]
            game=str(target_dir).split("common"+os.sep)[-1].split(os.sep)[0]
            steam_id=determine_game_id(target_dir)
            save_dir=ensure_dir(LOCAL_DIR/"utils"/"resources"/"requested")
            if "ICON" in cfg["INSTANCES"][instance].keys() and \
            cfg["INSTANCES"][instance]["ICON"]: icon_path=cfg["INSTANCES"][instance]["ICON"]
            else: icon_path = get_steam_resources(game,steam_id,save_dir,icon=True)

            item.setToolTip(f"Instance at {instance_path.parent}")

            if icon_path and os.path.exists(icon_path):
                item.setIcon(QIcon(QPixmap(icon_path)))
                item.setSizeHint(QSize(0,48))

            self.list_widget.addItem(item)
    
    def show_context_menu(self, pos):
        menu = QMenu(self)
        add_action = menu.addAction("Add Instance")
        open_action = menu.addAction("Open Instance Folder")
        edit_action = menu.addAction("Edit")
        duplicate_action = menu.addAction("Duplicate")
        delete_action = menu.addAction("Delete")
        action = menu.exec(QCursor.pos())
       
        if action == add_action:       self._on_add() 
        if action == open_action:      self.open_instance_dir()
        if action == edit_action:      self.open_instance_editor()
        if action == duplicate_action: self.dup_instance()
        if action == delete_action:    self._on_remove()

    def open_instance_dir(self):
        """Open a path with system's default application"""
        from bdsm import read_parent_cfg
        item = self.list_widget.currentItem().text()
        cfg=read_parent_cfg()
        path=cfg["INSTANCES"][item]["PATH"]
        try:
            if platform.system() == 'Windows':
                if path.is_dir(): subprocess.run(['explorer', str(path)])
                else: subprocess.run(['start', '', str(path)], shell=True)
            elif platform.system() == 'Darwin': subprocess.run(['open', str(path)])
            else: subprocess.run(['xdg-open', str(path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open:\n{str(e)}")

    def dup_instance(self, prev_name=None, prev_path=None):
        from bdsm import read_parent_cfg, read_child_cfg, write_cfg
        dialog = QDialog(self)
        dialog.setWindowTitle("New Instance Setup")
        layout = QVBoxLayout(dialog)
        dialog.setMinimumWidth(480)

        item = self.list_widget.currentItem().text()
        cfg = read_parent_cfg()
        old_name = item
        old_path = cfg["INSTANCES"][item]["PATH"]

        layout.addWidget(QLabel("<b>New Name:</b>"))
        h = QHBoxLayout()
        name_input = QLineEdit()
        h.addWidget(name_input)
        layout.addLayout(h)

        layout.addWidget(QLabel("<b>New Path:</b>"))
        h = QHBoxLayout()
        path_input = QLineEdit()
        browse = QPushButton("...")
        browse.clicked.connect(lambda: path_input.setText(QFileDialog.getExistingDirectory(dialog, "Select Directory") or path_input.text()))
        h.addWidget(path_input)
        h.addWidget(browse)
        layout.addLayout(h)

        if prev_name: name_input.setText(prev_name)
        else: name_input.setText(old_name)
        if prev_path: path_input.setText(old_path)
        else: path_input.setText(old_path)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def check():
            if name_input.text()!=old_name and path_input.text()!=old_path: ok.setEnabled(True)
            else: ok.setEnabled(False)

        name_input.textChanged.connect(check)
        path_input.textChanged.connect(check)

        if dialog.exec() != QDialog.DialogCode.Accepted: return

        name=name_input.text()
        path=path_input.text()
        # check valid dir
        if os.path.exists(path) and os.listdir(path)!=[]: QMessageBox.warning(self, 'Move Error',
                      'Target path is non-empty (choose an empty directory)'); self.dup_instance(name,path); return

        def copy_dirs():
            for item in os.listdir(old_path):
                s = os.path.join(old_path, item)
                d = os.path.join(path, item)
                if os.path.isdir(s): print(f"copying file: {d}"); shutil.copytree(s, d);
                else: print(f"copying file: {d}"); shutil.copy2(s, d);

            child_cfg=read_child_cfg(path=Path(path)/"config.yaml") 
            for i in ["SOURCE_DIR","PRESET_DIR","LOAD_ORDER","INI_DIR"]: child_cfg[i]=child_cfg[i].replace(old_path,path)
            write_cfg(child_cfg, path=Path(path)/"config.yaml")
            # update global config
            if "ICON" in cfg["INSTANCES"][old_name].keys(): icon=cfg["INSTANCES"][old_name]["ICON"]
            else: icon=""
            cfg["INSTANCES"][name]=dict()
            cfg["INSTANCES"][name]["ICON"]=icon
            cfg["INSTANCES"][name]["PATH"]=path
            cfg["INSTANCES"][name]["SELECTED"]=False
            write_cfg(cfg, is_global=True)
    
            self._refresh_list() 
            
        self.info = QDialog(self)
        self.info.setWindowTitle("Processing")
        layout = QVBoxLayout(self.info)
        layout.addWidget(QLabel("   Copying files (this may take a while)...   "))
        self.info.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.info.show()

        ensure_dir(path)
        thread = QThread()
        thread.run = lambda: copy_dirs()
        thread.finished.connect(self.info.close)
        thread.start()
        self.thread = thread  # keep reference

    def _on_selection_changed(self):
        has_sel = bool(self.list_widget.selectedItems())
        self.btn_select.setEnabled(has_sel)
        self.btn_remove.setEnabled(has_sel)
        self.btn_edit.setEnabled(has_sel)

    def _on_add(self):
        from bdsm import read_parent_cfg, write_cfg, create_cfg
        path = QFileDialog.getExistingDirectory(
            None,
            "Select Game Target Directory",
            "/home",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        path=Path(os.path.realpath(path)) # resolve symlinks
        if not path: return

        name=str(path).split("common"+os.sep)[-1].split(os.sep)[0].strip()

        # check for native supported games
        if not path.name=="Data" \
        and path.name in GAME_IDS.keys(): 
            path=path/"Data"
        if Path(path).parent.name in GAME_IDS.keys():
            instance_path=Path(path).parent/"bdsm_instance"
        else:
            instance_path=Path(path)/"bdsm_instance"
        
        if os.path.exists(instance_path): 
            instance_path, dirname = fix_dirname_used(instance_path)
            print(f"prexisting instance found, creating instance at {instance_path}")
            name+=str(instance_path)[-1]

        # TODO: actually fix this lol
        try: compat_dir=infer_compat_path(path)
        except: return

        # write to parent config
        cfg_dict=read_parent_cfg()
        cfg_dict["INSTANCES"][name]=dict()
        cfg_dict["INSTANCES"][name]["PATH"]=str(instance_path)
        cfg_dict["INSTANCES"][name]["SELECTED"]=False
        write_cfg(cfg_dict, is_global=True)
  
        ensure_dir(instance_path)
        create_cfg(gui=True, path=instance_path/"config.yaml", instance_path=instance_path) 
        #write_cfg(instance_cfg,path=instance_path/"config.yaml")

        self._refresh_list()
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def _on_remove(self):
        from bdsm import read_parent_cfg, write_cfg, get_instance_name

        item = self.list_widget.currentItem()
        if not item: return
        name = item.data(Qt.ItemDataRole.UserRole)

        cfg_dict=read_parent_cfg()
        path=cfg_dict["INSTANCES"][name]["PATH"]

        msg = QMessageBox(self)
        msg.setWindowTitle("Remove Instance")
        msg.setText(f"Remove '{name}' instance at '{path}'?")
        msg.setInformativeText("(Leaving box unchecked will only remove instance from config)")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        checkbox = QCheckBox("Remove instance files")
        checkbox.setChecked(False)
        msg.setCheckBox(checkbox)
        if msg.exec() != QMessageBox.StandardButton.Yes: return

        # check if deleting selected instance
        sel_name = get_instance_name()
        if name==sel_name: self._on_select(item=self.list_widget.item(0), close=False)
        
        cfg_dict=read_parent_cfg()
        path=cfg_dict["INSTANCES"][name]["PATH"]
        del cfg_dict["INSTANCES"][name]
        if checkbox.isChecked(): shutil.rmtree(path)
        write_cfg(cfg_dict, is_global=True)

        # last instance was deleted
        if cfg_dict["INSTANCES"]=={}:
            from bdsm import create_cfg
            reply = QMessageBox.warning(None,"No Remaining Instances", "There are no remaining instances.\nRerunning initial instance setup..."+' '*20, QMessageBox.StandardButton.Ok)
            os.execv(sys.executable, [sys.executable]+sys.argv) # restart application
            return

        self._refresh_list()

    def _on_select(self, item=None, close=True):
        from bdsm import read_parent_cfg, write_cfg
        if not item:
            item = self.list_widget.currentItem()
            if not item: item=self.list_widget.item(0)
        
        self.selected_instance = item.data(Qt.ItemDataRole.UserRole)
        cfg_dict=read_parent_cfg(gui=True)
        instance_path=""
        for i in cfg_dict["INSTANCES"]:
            if i==self.selected_instance: 
                cfg_dict["INSTANCES"][i]["SELECTED"]=True
            else: cfg_dict["INSTANCES"][i]["SELECTED"]=False
        write_cfg(cfg_dict, is_global=True)
        self.closed.emit(self.selected_instance)
        if not close: return
        self.accept()
        self.close()

    def open_instance_editor(self):
        item = self.list_widget.currentItem().text()
        if not item: return
        self.instance_editor = InstanceEditor(item, self)
        self.instance_editor.setWindowModality(Qt.WindowModality.ApplicationModal)
        #self.instance_editor.closed.connect(self.on_instance_manager_close)
        self.instance_editor.show()


class InstanceEditor(QMainWindow):
    closed = pyqtSignal(str)

    def __init__(self, instance_name, parent=None):
        super().__init__(parent)
        self.parent=parent
        self.instance_name = instance_name 

        self.setWindowTitle("Edit Instance")
        self.setMinimumSize(480, 200)
        self.resize(480, 200)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.has_pending_changes = False

        self._build_ui()
        self._add_data()

        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.apply_changes)

    def _build_ui(self):
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)

        form_layout = QFormLayout()
        
        # Name field
        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.mark_pending_changes)
        self.name_edit.setToolTip("Instance name")
        form_layout.addRow(QLabel("Name:"), self.name_edit)

        # Path field
        self.icon_edit = QLineEdit()
        self.icon_edit.textChanged.connect(self.mark_pending_changes)
        self.icon_edit.setToolTip("Instance icon path")
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.icon_edit)
        icon_btn = QPushButton("...")
        icon_btn.setToolTip("Browse files")
        icon_btn.setFixedWidth(28)
        icon_btn.clicked.connect(lambda checked, e=self.icon_edit, f=True: file_select(e, f))
        icon_row.addWidget(icon_btn)
        form_layout.addRow(QLabel("Icon:"), icon_row)

        # Path field
        self.path_edit = QLineEdit()
        self.path_edit.textChanged.connect(self.mark_pending_changes)
        self.path_edit.setToolTip("Instance path")
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_btn = QPushButton("...")
        path_btn.setToolTip("Browse files")
        path_btn.setFixedWidth(28)
        path_btn.clicked.connect(lambda checked, e=self.path_edit, f=True: file_select(e, f))
        path_row.addWidget(path_btn)
        form_layout.addRow(QLabel("Path:"), path_row)
        
        layout.addLayout(form_layout)
        main_layout.addLayout(layout, 1)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
       
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self.close)
        bottom_layout.addWidget(self.cancel_button)
 
        # Apply button
        self.apply_button = QPushButton("Apply")
        self.apply_button.setFixedWidth(100)
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setEnabled(False)
        bottom_layout.addWidget(self.apply_button)
        
        layout.addLayout(bottom_layout)

    def _add_data(self):
        from bdsm import read_parent_cfg
        cfg=read_parent_cfg(gui=True) 
        instance_data=cfg["INSTANCES"][self.instance_name]
        self.name_edit.blockSignals(True)
        self.path_edit.blockSignals(True)
        self.icon_edit.blockSignals(True)
        self.name_edit.setText(self.instance_name)
        self.path_edit.setText(instance_data["PATH"])
        if "ICON" in instance_data.keys(): self.icon_edit.setText(instance_data["ICON"])
        self.name_edit.blockSignals(False)
        self.path_edit.blockSignals(False)
        self.icon_edit.blockSignals(False)
   
    def mark_pending_changes(self):
        self.has_pending_changes = True
        # Only enable apply button if both title and path are not empty
        name_filled = self.name_edit.text().strip() != ""
        path_filled = self.path_edit.text().strip() != ""
        
        if name_filled and path_filled:
            self.apply_button.setEnabled(True)
            self.apply_button.setToolTip("")
        else:
            self.apply_button.setEnabled(False)
            missing = []
            if not name_filled:
                missing.append("Name")
            if not path_filled:
                missing.append("Path")
            self.apply_button.setToolTip(f"Required field(s) missing: {', '.join(missing)}")

    def apply_changes(self):
        if not self.has_pending_changes: return
        from bdsm import read_parent_cfg, read_child_cfg, write_cfg
        cfg=read_parent_cfg(gui=True) 

        name=self.name_edit.text().strip()
        path=self.path_edit.text().strip()
        icon=self.icon_edit.text().strip()
        
        if name: cfg["INSTANCES"][name] = cfg["INSTANCES"].pop(self.instance_name); self.instance_name=name
        if icon is not None: cfg["INSTANCES"][self.instance_name]["ICON"]=icon if os.path.exists(icon) else ""
        if path and path!=cfg["INSTANCES"][self.instance_name]["PATH"]:
            msg = QMessageBox()
            msg.setWindowTitle("Confirm Instance Path Change")
            msg.setText("Are you sure you want to change instance path?"+' '*DIALOGUE_WIDTH)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            checkbox = QCheckBox("Move instance files\n(A new instance will be created if not moved)")
            checkbox.setChecked(True)
            msg.setCheckBox(checkbox)
            result = msg.exec()
    
            if result==QMessageBox.StandardButton.Yes:
                old_path=cfg["INSTANCES"][self.instance_name]["PATH"]
                child_cfg=read_child_cfg(gui=True, path=Path(old_path)/"config.yaml")
                if checkbox.isChecked(): 
                    if os.path.exists(path) and os.listdir(path)!=[]: QMessageBox.warning(self, 'Move Error',
                                  'Target path is non-empty (choose an empty directory)\nAlternatively, uncheck the move files box (creates a new instance)'); return
                    for i in ["SOURCE_DIR","PRESET_DIR","LOAD_ORDER","INI_DIR"]: child_cfg[i]=child_cfg[i].replace(old_path,path)
                    write_cfg(child_cfg, path=Path(old_path)/"config.yaml")
                    ensure_dir(path)
                    for item in os.listdir(old_path): shutil.move(os.path.join(old_path, item), os.path.join(path, item))
                    #shutil.move(old_path, path)
                else: 
                    #if not os.path.exists(Path(path)/"config.yaml"):
                    for i in ["SOURCE_DIR","PRESET_DIR","LOAD_ORDER","INI_DIR"]: child_cfg[i]=child_cfg[i].replace(old_path,path)
                    write_cfg(child_cfg, path=Path(old_path)/"config.yaml")
                    ensure_dir(path); shutil.copy(Path(old_path)/"config.yaml",Path(path)/"config.yaml") # im too lazy to figure this one out
                cfg["INSTANCES"][self.instance_name]["PATH"]=path
            else: return
        write_cfg(cfg, is_global=True)
        self.parent._refresh_list()
        # update current instance with change if edited
        if cfg["INSTANCES"][self.instance_name]["SELECTED"]: self.parent.parent.on_instance_manager_close(self.instance_name)
        self.close()


class ListItem:
    """Class to represent a list item with title, path, and params"""
    def __init__(self, title="", path="", params=""):
        self.title = title
        self.path = path
        self.params = params
    
    def __str__(self):
        return self.title if self.title else "New Item"

class ExeManager(QMainWindow):
    # Signal emitted when the window is closed, sends the list of items
    closed = pyqtSignal(list)
   
    def __init__(self, parent=None):
        super().__init__(parent)
        import bdsm
        self.cfg = bdsm.read_cfg(sync=False)
        self.items = []
        self.current_item_index = -1
        self.has_pending_changes = False
        # Make this window modal if it has a parent
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.init_ui()

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)
        
    def init_ui(self):
        self.setWindowTitle("Executable Manager")
        self.resize(650, 250)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Left side - List and buttons
        left_layout = QVBoxLayout()
        
        # List widget
        self.list_widget = QListWidget()
        exes=self.cfg["EXECUTABLES"]
        if exes:
            for exe in exes:
                if "ICON" not in exes[exe]: exes[exe]["ICON"]="" # for prev installs
                self.add_item(title=exe, icon=exes[exe]["ICON"], path=exes[exe]["PATH"], params=exes[exe]["PARAMS"])
        self.list_widget.currentRowChanged.connect(self.on_item_selected)
        left_layout.addWidget(self.list_widget)
        
        # Button layout for list controls
        button_layout = QHBoxLayout()
        
        # Plus button
        self.plus_button = QPushButton("+")
        self.plus_button.setFixedSize(35, 35)
        self.plus_button.setToolTip("Add executable")
        self.plus_button.clicked.connect(self.add_item)
        button_layout.addWidget(self.plus_button)
        
        # Minus button
        self.minus_button = QPushButton("-")
        self.minus_button.setFixedSize(35, 35)
        self.minus_button.setToolTip("Remove executable")
        self.minus_button.clicked.connect(self.remove_item)
        button_layout.addWidget(self.minus_button)
        
        # Up arrow button
        #self.up_button = QPushButton("↑")
        #self.up_button.setFixedSize(35, 35)
        #self.up_button.clicked.connect(self.move_item_up)
        #button_layout.addWidget(self.up_button)
        #
        ## Down arrow button
        #self.down_button = QPushButton("↓")
        #self.down_button.setFixedSize(35, 35)
        #self.down_button.clicked.connect(self.move_item_down)
        #button_layout.addWidget(self.down_button)
        
        button_layout.addStretch()
        
        left_layout.addLayout(button_layout)
        
        main_layout.addLayout(left_layout, 1)
        
        # Right side - Form
        right_layout = QVBoxLayout()
        
        # Form layout for labels and text boxes
        form_layout = QFormLayout()
        
        # Title field
        self.title_edit = QLineEdit()
        self.title_edit.textChanged.connect(self.mark_pending_changes)
        self.title_edit.setToolTip("Executable configuration name")
        form_layout.addRow(QLabel("Title:"), self.title_edit)
       
        # Icon field
        self.icon_edit = QLineEdit()
        self.icon_edit.textChanged.connect(self.mark_pending_changes)
        self.icon_edit.setToolTip("Icon path")
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.icon_edit)
        icon_btn = QPushButton("...")
        icon_btn.setToolTip("Browse files")
        icon_btn.setFixedWidth(28)
        icon_btn.clicked.connect(lambda checked, e=self.icon_edit, f=True: file_select(e, f))
        icon_row.addWidget(icon_btn)
        form_layout.addRow(QLabel("Icon:"), icon_row)
 
        # Path field
        self.path_edit = QLineEdit()
        self.path_edit.textChanged.connect(self.mark_pending_changes)
        self.path_edit.setToolTip("Executable path")
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_btn = QPushButton("...")
        path_btn.setToolTip("Browse files")
        path_btn.setFixedWidth(28)
        path_btn.clicked.connect(lambda checked, e=self.path_edit, f=True: file_select(e, f))
        path_row.addWidget(path_btn)
        form_layout.addRow(QLabel("Path:"), path_row)
        
        # Params field
        self.params_edit = QLineEdit("%command%")
        self.params_edit.setToolTip("Add parameters before/after launch command\nEquivalent to Steam launch options")
        self.params_edit.textChanged.connect(self.mark_pending_changes)
        form_layout.addRow(QLabel("Params:"), self.params_edit)
        
        right_layout.addLayout(form_layout)
        
        # Use as Steam executable button
        #steam_layout = QHBoxLayout()
        #self.steam_button = QPushButton("Use as Steam executable")
        #self.steam_button.setFixedWidth(180)
        #self.steam_button.setToolTip("Swap this executable with the original Steam launcher so this is launched in its stead")
        #self.steam_button.clicked.connect(self.use_as_steam_executable)
        #self.steam_button.setEnabled(False)
        #steam_layout.addWidget(self.steam_button)
        #right_layout.addLayout(steam_layout)
        #
        #right_layout.addStretch()
        
        # Apply button layout
        apply_layout = QHBoxLayout()
        apply_layout.addStretch()
        
        # Apply button
        self.apply_button = QPushButton("Apply")
        self.apply_button.setFixedWidth(100)
        self.apply_button.clicked.connect(self.apply_changes)
        self.apply_button.setEnabled(False)
        apply_layout.addWidget(self.apply_button)
        
        right_layout.addLayout(apply_layout)
        
        main_layout.addLayout(right_layout, 2)
        
        # Initialize with empty fields disabled
        self.set_fields_enabled(False)

        # start selection
        if len(self.items)>0: self.on_item_selected(0)
        self.list_widget.setCurrentRow(0)

        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.apply_changes)
        
    def set_fields_enabled(self, enabled):
        """Enable or disable the text fields and apply button"""
        self.title_edit.setEnabled(enabled)
        self.path_edit.setEnabled(enabled)
        self.params_edit.setEnabled(enabled)
        #self.steam_button.setEnabled(enabled)
        
    def mark_pending_changes(self):
        """Mark that there are pending changes"""
        if self.current_item_index >= 0:
            self.has_pending_changes = True
            # Only enable apply button if both title and path are not empty
            title_filled = self.title_edit.text().strip() != ""
            path_filled = self.path_edit.text().strip() != ""
            
            if title_filled and path_filled:
                self.apply_button.setEnabled(True)
                self.apply_button.setToolTip("")
            else:
                self.apply_button.setEnabled(False)
                missing = []
                if not title_filled:
                    missing.append("Title")
                if not path_filled:
                    missing.append("Path")
                self.apply_button.setToolTip(f"Required field(s) missing: {', '.join(missing)}")
            
    def add_item(self, title=None, icon=None, path=None, params=None):
        """Add a new item to the list"""
        # Check if there's already an item with empty title or path
        for item in self.items:
            if item.title.strip() == "" or item.path.strip() == "":
                QMessageBox.warning(self, 'Incomplete Item',
                                  'Please complete the current item (title and path required) before adding a new one.')
                return
        
        # Check for pending changes
        if self.has_pending_changes:
            if not self.prompt_save_changes():
                return
        
        # Create new item
        new_item = ListItem()
        if title: new_item.title=title
        if icon is not None: new_item.icon=icon
        else: new_item.icon=None
        if path: new_item.path=path
        if params: new_item.params=params if params.strip() else "%command%"

        self.items.append(new_item)
        self.list_widget.addItem(str(new_item))
        
        # Select the new item
        self.list_widget.setCurrentRow(len(self.items) - 1)
        
    def remove_item(self):
        """Remove the selected item from the list"""
        import bdsm
        current_row = self.list_widget.currentRow()
        name = self.list_widget.item(current_row).text()
        if current_row >= 0:
            # Confirm deletion
            reply = QMessageBox.question(self, 'Remove Item', 
                                        'Are you sure you want to remove this item?',
                                        QMessageBox.StandardButton.Yes | 
                                        QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                self.items.pop(current_row)
                self.list_widget.takeItem(current_row)
                self.has_pending_changes = False
                self.apply_button.setEnabled(False)
                
                # Clear fields if no items left
                if len(self.items) == 0:
                    self.clear_fields()
                    self.set_fields_enabled(False)
                    self.current_item_index = -1

                try: del self.cfg["EXECUTABLES"][name]
                except: pass
                bdsm.write_cfg(self.cfg)
                    
    def move_item_up(self):
        """Move the selected item up in the list"""
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            # Check for pending changes
            if self.has_pending_changes:
                if not self.prompt_save_changes():
                    return
            
            # Swap items
            self.items[current_row], self.items[current_row - 1] = \
                self.items[current_row - 1], self.items[current_row]
            
            # Update list widget
            self.refresh_list()
            self.list_widget.setCurrentRow(current_row - 1)
            
    def move_item_down(self):
        """Move the selected item down in the list"""
        current_row = self.list_widget.currentRow()
        if current_row >= 0 and current_row < len(self.items) - 1:
            # Check for pending changes
            if self.has_pending_changes:
                if not self.prompt_save_changes():
                    return
            
            # Swap items
            self.items[current_row], self.items[current_row + 1] = \
                self.items[current_row + 1], self.items[current_row]
            
            # Update list widget
            self.refresh_list()
            self.list_widget.setCurrentRow(current_row + 1)
            
    def refresh_list(self):
        """Refresh the list widget to show current items"""
        self.list_widget.clear()
        for item in self.items:
            self.list_widget.addItem(str(item))
            
    def on_item_selected(self, index):
        """Handle item selection in the list"""
        if index < 0: return
            
        # Check for pending changes
        if self.has_pending_changes and index != self.current_item_index:
            if not self.prompt_save_changes():
                # Revert selection
                self.list_widget.setCurrentRow(self.current_item_index)
                return
        
        # Update current index
        self.current_item_index = index
        
        # Enable fields
        self.set_fields_enabled(True)
 
        # Load item data into fields
        if 0 <= index < len(self.items):
            item = self.items[index]
            self.current_item = item
            self.title_edit.setText(item.title)
            self.icon_edit.setText(item.icon)
            self.path_edit.setText(item.path)
            item.params = item.params if item.params.strip() else "%command%"
            self.params_edit.setText(item.params)
            
        # Reset pending changes flag
        self.has_pending_changes = False
        self.apply_button.setEnabled(False)
        
    def prompt_save_changes(self):
        """Prompt user to save or discard pending changes"""
        reply = QMessageBox.question(self, 'Pending Changes',
                                    'You have unsaved changes. Do you want to apply them?',
                                    QMessageBox.StandardButton.Yes | 
                                    QMessageBox.StandardButton.No |
                                    QMessageBox.StandardButton.Cancel)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.apply_changes()
            return True
        elif reply == QMessageBox.StandardButton.No:
            self.has_pending_changes = False
            self.apply_button.setEnabled(False)
            return True
        else:  # Cancel
            return False
            
    def apply_changes(self):
        """Apply changes to the current item"""
        import bdsm
        if self.current_item_index >= 0 and self.current_item_index < len(self.items):
            new_title = self.title_edit.text().strip()
            
            # Check if the title is unique (excluding the current item)
            for i, item in enumerate(self.items):
                if i != self.current_item_index and item.title == new_title:
                    QMessageBox.warning(self, 'Duplicate Title',
                                      'An item with this title already exists. Please use a unique title.')
                    return
            
            item = self.items[self.current_item_index]
            if not self.cfg["EXECUTABLES"]: self.cfg["EXECUTABLES"]=dict()
            if item.title!=new_title and item.title in self.cfg["EXECUTABLES"]:
                del self.cfg["EXECUTABLES"][item.title] # rename occured
                self.cfg["EXECUTABLES"][new_title]=dict()
                self.cfg["EXECUTABLES"][new_title]["SELECTED"]=False
            elif item.title not in self.cfg["EXECUTABLES"]:
                self.cfg["EXECUTABLES"][new_title]=dict()
                self.cfg["EXECUTABLES"][new_title]["PATH"]=""
                self.cfg["EXECUTABLES"][new_title]["ICON"]=""
                self.cfg["EXECUTABLES"][new_title]["PARAMS"]=""
                self.cfg["EXECUTABLES"][new_title]["SELECTED"]=False
            item.title = new_title
            item.icon = self.icon_edit.text()
            item.path = self.path_edit.text()
            item.params = self.params_edit.text()
            if not item.params: item.params="%command%"
            self.cfg["EXECUTABLES"][item.title]["PATH"]=item.path
            self.cfg["EXECUTABLES"][item.title]["ICON"]=item.icon if os.path.exists(item.icon) else ""
            if not os.path.exists(item.icon): self.icon_edit.setText("")
            self.cfg["EXECUTABLES"][item.title]["PARAMS"]=item.params
            bdsm.write_cfg(self.cfg)

            # Update list widget item text
            self.list_widget.item(self.current_item_index).setText(str(item))
            
            # Clear pending changes
            self.has_pending_changes = False
            self.apply_button.setEnabled(False)
            
    def clear_fields(self):
        """Clear all text fields"""
        self.title_edit.clear()
        self.path_edit.clear()
        self.params_edit.clear()
    
    def use_as_steam_executable(self):
        """Swap this executable with Steam launcher"""
        reply = QMessageBox.question(self, 'Steam Executable',
                            'This will swap the selected executable with what Steam uses as its launcher.\nWarning, this is kinda broken\nContinue?',
                             QMessageBox.StandardButton.Yes | 
                             QMessageBox.StandardButton.No)
        # this is deplorable
        if reply == QMessageBox.StandardButton.Yes:
            exe=self.current_item.path
            first,van_bin=set_launcher(self.cfg["COMPAT_DIR"],self.cfg["TARGET_DIR"],exe)
            if first:
                item=None
                for i in range(len(self.items)):
                    if self.items[i].path.strip().endswith(van_bin): item=self.items[i]
                if item and (not item.path.endswith("_original")): item.path=item.path+"_original"
            # Placeholder for Steam executable swap functionality
            QMessageBox.information(self, 'Steam Executable',
                                  f'Set {exe} as Steam game launcher.')
    
    def closeEvent(self, event):
        """Handle window close event and emit signal with items"""
        # Emit the closed signal with the current items list
        self.closed.emit(self.items)
        event.accept()


class IniSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for INI files"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Define formats
        self.section_format = QTextCharFormat()
        self.section_format.setForeground(QColor("#0066CC"))
        self.section_format.setFontWeight(QFont.Weight.Bold)
        
        self.key_format = QTextCharFormat()
        self.key_format.setForeground(QColor("#008800"))
        
        self.value_format = QTextCharFormat()
        self.value_format.setForeground(QColor("#CC6600"))
        
        self.comment_format = QTextCharFormat()
        self.comment_format.setForeground(QColor("#808080"))
        self.comment_format.setFontItalic(True)

    def highlightBlock(self, text):
        # Highlight comments (lines starting with ; or #)
        if text.strip().startswith(';') or text.strip().startswith('#'):
            self.setFormat(0, len(text), self.comment_format)
            return
        
        # Highlight sections [section_name]
        if text.strip().startswith('[') and text.strip().endswith(']'):
            self.setFormat(0, len(text), self.section_format)
            return
        
        # Highlight key=value pairs
        if '=' in text:
            eq_pos = text.index('=')
            # Key
            self.setFormat(0, eq_pos, self.key_format)
            # Value
            self.setFormat(eq_pos + 1, len(text) - eq_pos - 1, self.value_format)


class INIManager(QMainWindow):
    def __init__(self, compat_dir, backup_dir, ini_dir):
        super().__init__()

        self.setWindowTitle("BrainDead Simple Modloader - INI Manager")
        #self.setGeometry(100, 100, 1400, 800)
        self.resize(1400,800)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        # Create left column (backup directory browser)
        left_column = self.create_left_column()
        
        # Create right column (current INI files)
        right_column = self.create_right_column()
        
        # Add columns to a splitter for resizable columns
        column_splitter = QSplitter(Qt.Orientation.Horizontal)
        column_splitter.addWidget(left_column)
        column_splitter.addWidget(right_column)
        column_splitter.setStretchFactor(0, 1)
        column_splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(column_splitter)
        
        # Add Ctrl+S keyboard shortcut
        self.save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.save_shortcut.activated.connect(self.save_current_file)
        
        # Add zoom shortcuts (Ctrl++ and Ctrl+-)
        self.zoom_in_shortcut = QShortcut(QKeySequence("Ctrl++"), self)
        self.zoom_in_shortcut.activated.connect(self.zoom_in)
        
        self.zoom_out_shortcut = QShortcut(QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)
        
        # Also support Ctrl+= for zoom in (since + requires shift)
        self.zoom_in_shortcut2 = QShortcut(QKeySequence("Ctrl+="), self)
        self.zoom_in_shortcut2.activated.connect(self.zoom_in)
        
        # Track font size
        self.editor_font_size = 10
        
        # Install event filters for zoom on scroll (after both editors exist)
        # Install on both the editors and their viewports to catch all events
        self.left_editor.installEventFilter(self)
        self.left_editor.viewport().installEventFilter(self)
        self.right_editor.installEventFilter(self)
        self.right_editor.viewport().installEventFilter(self)

        # Initialize paths
        self.compat_dir  = compat_dir
        self.current_dir = ini_dir
        self.backup_dir  = backup_dir
        if "Documents" not in str(ini_dir):
            print("reading inis from: "+str(ini_dir)) # testing
        self.game = determine_game(ini_dir)
        self.set_current_directory(self.current_dir)
        self.set_backup_directory(self.backup_dir)

        # Add Ctrl+F for find
        self.find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.find_shortcut.activated.connect(self.show_find_dialog)
        
        # Track font size
        self.editor_font_size = 10
        
        # Track find state
        self.find_dialog = None
        self.current_matches = []
        self.current_match_index = -1

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    def create_left_column(self):
        """Create left column with directory tree and read-only editor"""
        column_widget = QWidget()
        layout = QVBoxLayout(column_widget)
        
        # Directory name label at top
        self.left_dir_label = QLabel("No directory selected")
        self.left_dir_label.setMaximumHeight(25)
        self.left_dir_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.left_dir_label)
        
        # File tree for backup directories
        self.left_tree = QTreeView()
        self.left_model = QFileSystemModel()
        self.left_model.setRootPath("")
        self.left_tree.setModel(self.left_model)
        self.left_tree.setHeaderHidden(True)
        
        # Hide all columns except name
        for i in range(1, 4):
            self.left_tree.hideColumn(i)
        
        self.left_tree.clicked.connect(self.on_left_file_clicked)
        
        # Text editor (read-only)
        self.left_editor = QTextEdit()
        self.left_editor.setReadOnly(True)
        self.left_editor.setFont(QFont("Courier New", 10))
        self.left_highlighter = IniSyntaxHighlighter(self.left_editor.document())
        
        # Splitter for tree and editor (horizontal)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_tree)
        splitter.addWidget(self.left_editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.setToolTip("Restore INIs from selected backup")
        self.restore_btn.clicked.connect(self.restore_on_click)
        self.restore_btn.setEnabled(False)
        button_layout.addWidget(self.restore_btn)
        
        self.delete_btn = QPushButton("Delete Backup")
        self.delete_btn.setToolTip("Delete INI backup")
        self.delete_btn.clicked.connect(self.delete_on_click)
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)
        
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        return column_widget
    
    def create_right_column(self):
        """Create right column with INI file tree and editable editor"""
        column_widget = QWidget()
        layout = QVBoxLayout(column_widget)
        
        # Directory name label at top
        self.right_dir_label = QLabel("No directory selected")
        self.right_dir_label.setMaximumHeight(25)
        self.right_dir_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.right_dir_label)
        
        # File tree for current INI files
        self.right_tree = QTreeView()
        self.right_model = QFileSystemModel()
        self.right_model.setRootPath("")
        self.right_model.setNameFilters(["*.ini"])
        self.right_model.setFilter(QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.right_model.setNameFilterDisables(False)
        self.right_tree.setModel(self.right_model)
        self.right_tree.setHeaderHidden(True)
 
        # Hide all columns except name
        for i in range(1, 4):
            self.right_tree.hideColumn(i)
        
        self.right_tree.clicked.connect(self.on_right_file_clicked)
        
        # Text editor (editable)
        self.right_editor = QTextEdit()
        self.right_editor.setFont(QFont("Courier New", 10))
        self.right_highlighter = IniSyntaxHighlighter(self.right_editor.document())
        self.right_editor.textChanged.connect(self.on_right_editor_changed)
        
        # Splitter for tree and editor (horizontal)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.right_tree)
        splitter.addWidget(self.right_editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        layout.addWidget(splitter)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_btn = QPushButton("Save")
        self.save_btn.setToolTip("Save edits to compat INI")
        self.save_btn.clicked.connect(self.save_current_file)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.backup_btn = QPushButton("Backup")
        self.backup_btn.setToolTip("Backup compat INIs")
        self.backup_btn.clicked.connect(self.backup_on_click)
        self.backup_btn.setEnabled(False)
        button_layout.addWidget(self.backup_btn)
        
        layout.addLayout(button_layout)
        
        return column_widget
    
    def set_backup_directory(self, directory):
        """Set the backup directory for left column"""
        #directory = QFileDialog.getExistingDirectory(self, "Select Backup Directory")
        self.backup_dir = Path(directory)
        self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))
        self.left_tree.expandAll()
        self.left_dir_label.setText("Backups - "+self.backup_dir.name)
    
    def set_current_directory(self, directory):
        """Set the current directory for right column (INI files only)"""
        self.current_dir = Path(directory)
        self.right_tree.setSortingEnabled(True)
        self.right_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        root_index = self.right_model.index(str(self.current_dir)+os.sep)
        self.right_tree.setRootIndex(root_index)
        self.right_model.setRootPath(str(self.current_dir))
        
        # Hide all subdirectories
        for i in range(self.right_model.rowCount(root_index)):
            index = self.right_model.index(i, 0, root_index)
            if self.right_model.isDir(index):
                self.right_tree.setRowHidden(i, root_index, True)
        
        self.backup_btn.setEnabled(True)
        self.right_dir_label.setText(self.game)
    
    def on_left_file_clicked(self, index):
        """Handle file selection in left tree"""
        file_path = Path(self.left_model.filePath(index))
        
        # Update label with current directory or file's parent directory
        if file_path.is_dir():
            self.left_dir_label.setText(file_path.name)
            self.restore_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
            self.selected_backup_file = file_path
        else:
            self.left_dir_label.setText(file_path.parent.name+" - "+file_path.name)
            self.restore_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

        if file_path.is_file() and file_path.suffix.lower() == '.ini':
            self.selected_backup_file = file_path
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.left_editor.setPlainText(content)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read file:\n{str(e)}")
    
    def on_right_file_clicked(self, index):
        """Handle file selection in right tree"""
        file_path = Path(self.right_model.fileInfo(index).absoluteFilePath())

        if file_path.is_dir():
            self.right_dir_label.setText(self.game+" - "+file_path.name)
        else:
            self.right_dir_label.setText(self.game+" - "+file_path.name)
        
        if file_path.is_file() and file_path.suffix.lower() == '.ini':
            self.selected_current_file = file_path
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.right_editor.setPlainText(content)
                self.save_btn.setEnabled(False)
                self.right_editor_modified = False
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read file:\n{str(e)}")
    
    def on_right_editor_changed(self):
        """Track changes to right editor"""
        if hasattr(self, 'selected_current_file') and self.selected_current_file:
            self.save_btn.setEnabled(True)
            self.right_editor_modified = True
    
    def save_current_file(self):
        """Save the current file being edited"""
        if not self.selected_current_file:
            return
        
        try:
            set_full_perms_file(self.selected_current_file) 
            with open(self.selected_current_file, 'w', encoding='utf-8') as f:
                f.write(self.right_editor.toPlainText())
            rscroll=self.right_editor.verticalScrollBar().value()
            lscroll=self.left_editor.verticalScrollBar().value()
            self.save_btn.setEnabled(False)
            self.right_editor_modified = False
            self.right_model.setRootPath(str(self.current_dir))
            self.right_tree.setRootIndex(self.right_model.index(str(self.current_dir)))
            self.on_right_file_clicked(self.right_tree.currentIndex())
            #self.right_editor.setPlainText("")
            self.right_editor.verticalScrollBar().setValue(rscroll)
            self.left_editor.verticalScrollBar().setValue(lscroll)
            #QMessageBox.information(self, "Success", "File saved successfully!")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save file:\n{str(e)}")

    def backup_on_click(self):
        # Check if there are unsaved changes
        if hasattr(self, 'right_editor_modified') and self.right_editor_modified:
            reply = QMessageBox.question(
                self, 
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before backing up?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Cancel:
                return
            elif reply == QMessageBox.StandardButton.Yes:
                self.save_current_file()

        reply = QMessageBox.question(
            self, "Confirm Backup Creation",
            "Create Backup?\n",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # backup files
            res=backup_ini(self.compat_dir, self.backup_dir)
            if res: QMessageBox.information(self, "Success", f"Backed up to dir:\n{self.backup_dir}")
            else: QMessageBox.information(self, "Failure", f"Failed to backup ini files")

            # Refresh left tree
            self.left_model.setRootPath("")
            self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))

    def delete_on_click(self):
        """Delete selected backup file"""
        if not self.selected_backup_file:
            QMessageBox.warning(self, "Warning", "Please select a backup file to delete.")
            return
        
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete backup file:\n{self.selected_backup_file.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No:
            return
        try:
            #self.selected_backup_file.unlink()
            shutil.rmtree(self.selected_backup_file)
            self.left_editor.clear()
            self.restore_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            
            QMessageBox.information(self, "Success", "Backup file deleted.")
            
            # Refresh left tree
            self.left_model.setRootPath("")
            self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not delete file:\n{str(e)}")

    def restore_on_click(self):
        if not self.selected_backup_file:
            QMessageBox.warning(self, "Warning", "Please select a backup directory to restore from.")
            return
        # Ask for confirmation
        reply = QMessageBox.question(
            self,
            "Confirm Restore",
            f"Restore {self.selected_backup_file.name} to current directory?\nThis will overwrite any existing file with the same name.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No:
            return
        # restore
        res,exc=restore_ini(self.compat_dir, self.selected_backup_file, ui=True)

        if res: QMessageBox.information(self, "Success", f"Successfully restored INIs to:\n{Path(self.selected_backup_file).name}")
        else: QMessageBox.information(self, "Failure", f"Failed to restore ini files\nEncountered exception: {exc}")
        # Refresh right tree
        self.right_model.setRootPath(str(self.current_dir))
        self.right_tree.setRootIndex(self.right_model.index(str(self.current_dir)))
        self.right_editor.setPlainText("")
    
    def zoom_in(self):
        """Increase font size in both editors"""
        self.editor_font_size = min(self.editor_font_size + 1, 72)  # Max 72pt
        self.update_editor_fonts()
    
    def zoom_out(self):
        """Decrease font size in both editors"""
        self.editor_font_size = max(self.editor_font_size - 1, 6)  # Min 6pt
        self.update_editor_fonts()
    
    def update_editor_fonts(self):
        """Update font size for both editors"""
        font = QFont("Courier New", self.editor_font_size)
        if hasattr(self, 'left_editor'):
            self.left_editor.setFont(font)
        if hasattr(self, 'right_editor'):
            self.right_editor.setFont(font)
    
    def eventFilter(self, obj, event):
        """Handle Ctrl+Scroll zoom for editors"""
        from PyQt6.QtGui import QWheelEvent
        
        # Check if both editors exist yet
        if not (hasattr(self, 'left_editor') and hasattr(self, 'right_editor')):
            return super().eventFilter(obj, event)
        
        # Check if this is one of our editors or their viewports
        is_left = obj in (self.left_editor, self.left_editor.viewport())
        is_right = obj in (self.right_editor, self.right_editor.viewport())
        
        if not (is_left or is_right):
            return super().eventFilter(obj, event)
        
        # Check if this is a wheel event with Ctrl held
        if event.type() == QEvent.Type.Wheel:
            wheel_event = event
            if wheel_event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                if wheel_event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True  # Block the scroll event completely
        
        return super().eventFilter(obj, event)


    def show_find_dialog(self):
        """Show or focus the find dialog"""
        if self.find_dialog is None:
            self.find_dialog = QDialog(self)
            self.find_dialog.setWindowTitle("Find")
            self.find_dialog.setModal(False)
            
            layout = QVBoxLayout(self.find_dialog)
            
            # Search input
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("Find:"))
            self.find_input = QLineEdit()
            self.find_input.textChanged.connect(self.on_find_text_changed)
            self.find_input.returnPressed.connect(self.find_next)
            search_layout.addWidget(self.find_input)
            layout.addLayout(search_layout)
            
            # Match count label
            self.match_count_label = QLabel("0 matches")
            layout.addWidget(self.match_count_label)
            
            # Checkboxes
            self.case_insensitive_check = QCheckBox("Case insensitive")
            self.case_insensitive_check.setChecked(True)
            self.case_insensitive_check.stateChanged.connect(self.on_find_text_changed)
            layout.addWidget(self.case_insensitive_check)
            
            self.search_both_check = QCheckBox("Search both editors")
            self.search_both_check.stateChanged.connect(self.on_find_text_changed)
            layout.addWidget(self.search_both_check)
            
            # Navigation buttons
            button_layout = QHBoxLayout()
            prev_btn = QPushButton("Previous")
            prev_btn.clicked.connect(self.find_previous)
            button_layout.addWidget(prev_btn)
            
            next_btn = QPushButton("Next")
            next_btn.clicked.connect(self.find_next)
            button_layout.addWidget(next_btn)
            
            layout.addLayout(button_layout)
            
            self.find_dialog.setLayout(layout)
        
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()
        self.find_input.setFocus()
        self.find_input.selectAll()
    
    def on_find_text_changed(self):
        """Update search results when text or options change"""
        search_text = self.find_input.text()
        
        if not search_text:
            self.current_matches = []
            self.current_match_index = -1
            self.match_count_label.setText("0 matches")
            self.clear_highlights()
            return
        
        # Get search flags
        case_sensitive = not self.case_insensitive_check.isChecked()
        search_both = self.search_both_check.isChecked()
        
        # Find all matches
        self.current_matches = []
        
        if search_both:
            # Search in both editors
            self.find_in_editor(self.left_editor, search_text, case_sensitive, 'left')
            self.find_in_editor(self.right_editor, search_text, case_sensitive, 'right')
        else:
            # Determine which editor has focus or was last used
            if self.right_editor.hasFocus() or (hasattr(self, 'selected_current_file') and self.selected_current_file):
                self.find_in_editor(self.right_editor, search_text, case_sensitive, 'right')
            else:
                self.find_in_editor(self.left_editor, search_text, case_sensitive, 'left')
        
        # Update match count
        self.match_count_label.setText(f"{len(self.current_matches)} matches")
        
        # Reset match index
        self.current_match_index = -1
        
        # Highlight all matches
        self.highlight_all_matches()
    
    def find_in_editor(self, editor, search_text, case_sensitive, editor_id):
        """Find all occurrences in a specific editor"""
        document = editor.document()
        cursor = QTextCursor(document)
        
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        
        while True:
            cursor = document.find(search_text, cursor, flags)
            if cursor.isNull():
                break
            self.current_matches.append({
                'editor': editor,
                'editor_id': editor_id,
                'position': cursor.position(),
                'start': cursor.selectionStart(),
                'end': cursor.selectionEnd()
            })
    
    def highlight_all_matches(self):
        """Highlight all matches in the editors"""
        self.clear_highlights()
        
        # Create highlight format
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#FFFF00"))  # Yellow background
        
        for match in self.current_matches:
            editor = match['editor']
            cursor = QTextCursor(editor.document())
            cursor.setPosition(match['start'])
            cursor.setPosition(match['end'], QTextCursor.MoveMode.KeepAnchor)
            
            # Apply highlight using extra selections
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = highlight_format
            
            current_selections = editor.extraSelections()
            current_selections.append(selection)
            editor.setExtraSelections(current_selections)
    
    def clear_highlights(self):
        """Clear all highlights from both editors"""
        self.left_editor.setExtraSelections([])
        self.right_editor.setExtraSelections([])
    
    def find_next(self):
        """Go to next match"""
        if not self.current_matches:
            return
        
        # Move to next match (wrap around)
        self.current_match_index = (self.current_match_index + 1) % len(self.current_matches)
        self.select_current_match()
    
    def find_previous(self):
        """Go to previous match"""
        if not self.current_matches:
            return
        
        # Move to previous match (wrap around)
        self.current_match_index = (self.current_match_index - 1) % len(self.current_matches)
        self.select_current_match()
    
    def select_current_match(self):
        """Select and scroll to the current match"""
        if not self.current_matches or self.current_match_index < 0:
            return
        
        match = self.current_matches[self.current_match_index]
        editor = match['editor']
        
        # Create cursor and select the match
        cursor = QTextCursor(editor.document())
        cursor.setPosition(match['start'])
        cursor.setPosition(match['end'], QTextCursor.MoveMode.KeepAnchor)
        
        # Set the cursor (this also scrolls to it)
        editor.setTextCursor(cursor)
        
        # Give focus to the editor
        editor.setFocus()
        
        # Re-highlight with current selection emphasized
        self.highlight_all_matches()
        
        # Add a different color for current match
        current_format = QTextCharFormat()
        current_format.setBackground(QColor("#FFA500"))  # Orange background
        
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = current_format
        
        current_selections = editor.extraSelections()
        current_selections.append(selection)
        editor.setExtraSelections(current_selections)


def load_stylesheet(filename):
    file = QFile(str(filename))
    if file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        stream = QTextStream(file)
        stylesheet = stream.readAll()
        file.close()
        return stylesheet
    return ""


def file_select(edit, is_file=False):
    current = edit.text()
    start = current if os.path.exists(current) else os.path.expanduser("~")
    if is_file:
        path, _ = QFileDialog.getOpenFileName(None, "Select File", start)
    else:
        path = QFileDialog.getExistingDirectory(None, "Select Directory", start)
    if path:
        edit.setText(path)


def select_directory():
    app = QApplication(sys.argv)
    global_msg = QMessageBox(None)
    global_msg.setWindowTitle("Select Game Location")
    global_msg.setText("Setup a game instance?"+' '*(DIALOGUE_WIDTH+20))
    global_msg.setInformativeText("This will create a 'bdsm_instance' folder in the game folder,\nit will be where mods and configs will be stored")
    global_msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if global_msg.exec() == QMessageBox.StandardButton.Yes: is_global=True
    else: sys.exit()

    while True:
        directory = QFileDialog.getExistingDirectory(
            None,
            "Select Target Directory",
            "/home",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        if directory:
            directory=Path(os.path.realpath(directory))
            if not directory.name=="Data" \
            and directory.name in GAME_IDS.keys(): 
                directory=os.path.join(directory,"Data")

            confirm = QMessageBox.question(
                None,
                "Confirm Directory",
                f"Are you sure you want to use this directory?\n\n{directory}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            
            if confirm == QMessageBox.StandardButton.Yes: return directory
            else: continue
        else: return None
    else: return None
