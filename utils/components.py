
import sys
import platform
import yaml
import tempfile
import random
from pathlib import Path
from copy import deepcopy

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, 
    QPushButton, QSplitter, QLabel, QLineEdit, QMenu, QMessageBox, 
    QComboBox, QFileDialog, QInputDialog, QTextEdit, QToolButton, 
    QSplashScreen, QToolTip, QStyledItemDelegate, QHeaderView,
    QGraphicsOpacityEffect
)
from PyQt6.QtCore import ( Qt, QItemSelectionModel, QObject, QThread, 
    QWaitCondition, pyqtSignal, QMutex, QMutexLocker, QTimer, QPoint, 
    QSize, QFile, QTextStream, QMetaObject, pyqtSlot, QItemSelection,
    QPointF, Qt, QPropertyAnimation
)
from PyQt6.QtGui import ( QIcon, QFont, QTextCursor, QCursor, QPixmap, 
    QTextDocument, QPainter, QRadialGradient, QColor
)

from game_specific import *
from installer import *

OPERATION_TIMEOUT = 500
 
OVERRIDING_COLOR = "#053005"
OVERRIDDEN_COLOR = "#300505"
ALPHA   = 20
OPACITY = ALPHA/255

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


class RichTextDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg: option.backgroundBrush = bg
        style = option.widget.style()
        style.drawControl(style.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            if not Qt.mightBeRichText(text): text=f"<span style='font-weight: 600;'>{text}</span>"
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
    def __init__(self, table, paths, interval_ms=30000):
        global OVERRIDING_COLOR, OVERRIDDEN_COLOR
        OVERRIDING_COLOR = "#00ff00"
        OVERRIDDEN_COLOR = "#ff0000"
        self.table = table
        self.table.horizontalHeader().setAutoFillBackground(False)
        self.table.horizontalHeader().setAutoFillBackground(False)
        self.table.horizontalHeader().setStyleSheet("background: transparent; \
                                                     background-color: rgba(10, 10, 10, 140); \
                                                     gridline-color: rgba(0, 0, 0, 0); \
                                                     outline: none; \
                                                     border: none;")
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
            if orig:
                orig(e)
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
            if path:
                self.set_pixmap(lbl, path)
            lbl.lower()

    def apply_vignette(self, pix):
        result = QPixmap(pix.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, pix)
        
        center = QPointF(pix.width() / 2, (pix.height() / 2)-400)
        
        # Cap the radius at a maximum value
        max_dimension = max(pix.width(), pix.height())
        radius = min(max_dimension / 1.1, 1200)  # Cap at 1200px
        
        grad = QRadialGradient(center, radius)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.7, QColor(0, 0, 0, 200))
        grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        
        painter.fillRect(result.rect(), grad)
        painter.end()
        return result   

 
    def set_pixmap(self, label, path):
        pm = QPixmap(path)
        try: label.setProperty("path", path)
        except: return
        if pm.isNull():
            return
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
            self.alpha=ALPHA
            self.opacity=OPACITY
            bg_paths=get_game_bgs(self.parent.cfg)
            self.background=FadingBg(self,bg_paths)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

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

    def get_item_separator_row(self, row):
        if self.is_separator_row(row): return None
        for i in range(row,-1,-1):
            if self.is_separator_row(i): return i
        return None
       
    def collect_row_data(self, row):
        is_sep = self.is_separator_row(row)
        if is_sep:
            return {
                'priority_num': "",
                'is_separator': True,
                'name': self.item(row, 2).data(Qt.ItemDataRole.UserRole + 1),
                'collapse_state': self.item(row, 0).text(),
                'hidden': self.isRowHidden(row),
                'conflicts': "",
                'conflict_tooltip':""
            }
        return {
            'priority_num': self.item(row,0).text(),
            'is_separator': False,
            'name': self.item(row, 2).text(),
            'checkbox': self.item(row, 1).checkState(),
            'hidden': self.isRowHidden(row),
            'conflicts': self.item(row,3).text(),
            'conflict_tooltip': self.item(row,3).toolTip()
        }

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
        self.setItem(row, 0, priority_item)
        
        checkbox_item = QTableWidgetItem("")
        checkbox_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        self.setItem(row, 1, checkbox_item)
        
        clean_name=name[2:]
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
                if min_sel <= target_row <= max_sel + 1:
                    return
       
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

    def highlight_row(self, row, overriding=False, overridden=False):
        for col in range(self.columnCount()):
            if self.item(row, col):
                if   overriding: color=QColor(OVERRIDING_COLOR)
                elif overridden: color=QColor(OVERRIDDEN_COLOR)
                else: color=QColor(0,0,0)
                color.setAlpha(self.alpha)
                self.item(row, col).setBackground(color)


