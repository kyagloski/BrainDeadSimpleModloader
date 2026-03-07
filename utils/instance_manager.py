
import os
import yaml
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QInputDialog, QMessageBox
)
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from utils import *
from game_specific import *

class InstanceManager(QDialog):
    closed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instances=dict()
        self.selected_instance=None

        self.setWindowTitle("Instance Manager")
        self.setMinimumSize(360, 500)
        self.resize(380, 540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()

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
        root.addWidget(self.list_widget)

        # Bottom row
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedSize(35, 35)
        self.btn_add.clicked.connect(self._on_add)

        self.btn_remove = QPushButton("-")
        self.btn_remove.setFixedSize(35, 35)
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self._on_remove)

        bottom.addWidget(self.btn_add)
        bottom.addWidget(self.btn_remove)
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
        from bdsm import read_parent_cfg, read_child_cfg
        local_dir = Path(os.path.dirname(os.path.realpath(__file__))).parent
        cfg_dict = read_parent_cfg()
        self.list_widget.clear()
        for instance in sorted(cfg_dict["INSTANCES"]):
            item = QListWidgetItem(instance)
            item.setData(Qt.ItemDataRole.UserRole, instance)
            
            instance_path=Path(cfg_dict["INSTANCES"][instance]["PATH"])/"config.yaml"

            instance_cfg=read_child_cfg(gui=True, path=instance_path ,update=False)
            target_dir=instance_cfg["TARGET_DIR"]
            game=str(target_dir).split("common"+os.sep)[-1].split(os.sep)[0]
            steam_id=determine_game_id(target_dir)
            save_dir=ensure_dir(local_dir/"resources"/"requested")
            icon_path = get_steam_resources(game,steam_id,save_dir,icon=True)

            if icon_path and os.path.exists(icon_path):
                item.setIcon(QIcon(QPixmap(icon_path)))
                item.setSizeHint(QSize(0,48))
            self.list_widget.addItem(item)

    def _on_selection_changed(self):
        has_sel = bool(self.list_widget.selectedItems())
        self.btn_select.setEnabled(has_sel)
        self.btn_remove.setEnabled(has_sel)

    def _on_add(self):
        from bdsm import read_parent_cfg, write_cfg, create_cfg
        path = QFileDialog.getExistingDirectory(
            None,
            "Select Game Target Directory",
            "/home",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        path=Path(os.path.realpath(path)) # resolve symlinks

        name=str(path).split("common"+os.sep)[-1].split(os.sep)[0].strip()

        # check for native supported games
        if not path.name=="Data" \
        and path.name in GAME_IDS.keys(): 
            path=path/"Data"
        if Path(path).parent.name in GAME_IDS.keys():
            instance_path=Path(path).parent/"bdsm_instance"
        else:
            instance_path=Path(path)/"bdsm_instance"

        compat_dir=infer_compat_path(path)

        # write to parent config
        cfg_dict=read_parent_cfg()
        cfg_dict["INSTANCES"][name]=dict()
        cfg_dict["INSTANCES"][name]["PATH"]=str(instance_path)
        cfg_dict["INSTANCES"][name]["SELECTED"]=False
        write_cfg(cfg_dict, is_global=True)
  
        ensure_dir(instance_path)
        create_cfg(gui=True, path=instance_path/"config.yaml") 
        #write_cfg(instance_cfg,path=instance_path/"config.yaml")

        self._refresh_list()
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def _on_remove(self):
        from bdsm import read_parent_cfg, write_cfg 

        item = self.list_widget.currentItem()
        if not item: return
        name = item.data(Qt.ItemDataRole.UserRole)

        msg = QMessageBox(self)
        msg.setWindowTitle("Remove Instance")
        msg.setText(f"Remove '{name}'?"+' '*60)
        msg.setInformativeText("This only removes it from the list — no files will be deleted.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes: return

        cfg_dict=read_parent_cfg()
        del cfg_dict["INSTANCES"][name]
        write_cfg(cfg_dict, is_global=True)

        self._refresh_list()

    def _on_select(self):
        from bdsm import read_parent_cfg, write_cfg
        item = self.list_widget.currentItem()
        if not item:
            return
        self.selected_instance = item.data(Qt.ItemDataRole.UserRole)
        cfg_dict=read_parent_cfg(gui=True)
        instance_path=""
        for i in cfg_dict["INSTANCES"]:
            if i==self.selected_instance: 
                cfg_dict["INSTANCES"][i]["SELECTED"]=True
            else: cfg_dict["INSTANCES"][i]["SELECTED"]=False
        write_cfg(cfg_dict, is_global=True)
        self.closed.emit(self.selected_instance)
        self.accept()
        self.close()


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dlg = InstanceManager()
    if dlg.exec() == QDialog.DialogCode.Accepted:
        print("Selected:", dlg.get_selected_game())
    else:
        print("Cancelled")
