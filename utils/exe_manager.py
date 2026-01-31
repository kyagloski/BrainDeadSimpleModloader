#!/usr/bin/python3
import sys
from collections import OrderedDict
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QListWidget, QPushButton, QLineEdit, 
                             QLabel, QMessageBox, QFormLayout)
from PyQt6.QtCore import Qt, pyqtSignal

from bdsm import *
from game_specific import *

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
        self.cfg = read_cfg(sync=False)
        self.items = []
        self.current_item_index = -1
        self.has_pending_changes = False
        # Make this window modal if it has a parent
        if parent is not None:
            self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.init_ui()
        
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
        for exe in exes:
            self.add_item(title=exe, path=exes[exe]["PATH"], params=exes[exe]["PARAMS"])
        self.list_widget.currentRowChanged.connect(self.on_item_selected)
        left_layout.addWidget(self.list_widget)
        
        # Button layout for list controls
        button_layout = QHBoxLayout()
        
        # Plus button
        self.plus_button = QPushButton("+")
        self.plus_button.setFixedSize(35, 30)
        self.plus_button.clicked.connect(self.add_item)
        button_layout.addWidget(self.plus_button)
        
        # Minus button
        self.minus_button = QPushButton("-")
        self.minus_button.setFixedSize(35, 30)
        self.minus_button.clicked.connect(self.remove_item)
        button_layout.addWidget(self.minus_button)
        
        # Up arrow button
        self.up_button = QPushButton("↑")
        self.up_button.setFixedSize(35, 30)
        self.up_button.clicked.connect(self.move_item_up)
        button_layout.addWidget(self.up_button)
        
        # Down arrow button
        self.down_button = QPushButton("↓")
        self.down_button.setFixedSize(35, 30)
        self.down_button.clicked.connect(self.move_item_down)
        button_layout.addWidget(self.down_button)
        
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
        form_layout.addRow(QLabel("Title:"), self.title_edit)
        
        # Path field
        self.path_edit = QLineEdit()
        self.path_edit.textChanged.connect(self.mark_pending_changes)
        form_layout.addRow(QLabel("Path:"), self.path_edit)
        
        # Params field
        self.params_edit = QLineEdit()
        self.params_edit.textChanged.connect(self.mark_pending_changes)
        form_layout.addRow(QLabel("Params:"), self.params_edit)
        
        right_layout.addLayout(form_layout)
        
        # Use as Steam executable button
        steam_layout = QHBoxLayout()
        self.steam_button = QPushButton("Use as Steam executable")
        self.steam_button.setFixedWidth(180)
        self.steam_button.setToolTip("Swap this executable with the original Steam launcher so this is launched in its stead")
        self.steam_button.clicked.connect(self.use_as_steam_executable)
        self.steam_button.setEnabled(False)
        steam_layout.addWidget(self.steam_button)
        right_layout.addLayout(steam_layout)
        
        right_layout.addStretch()
        
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
        self.on_item_selected(0)
        self.list_widget.setCurrentRow(0)
        
    def set_fields_enabled(self, enabled):
        """Enable or disable the text fields and apply button"""
        self.title_edit.setEnabled(enabled)
        self.path_edit.setEnabled(enabled)
        self.params_edit.setEnabled(enabled)
        self.steam_button.setEnabled(enabled)
        
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
            
    def add_item(self, title=None, path=None, params=None):
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
        if path: new_item.path=path
        if params: new_item.params=params

        self.items.append(new_item)
        self.list_widget.addItem(str(new_item))
        
        
        # Select the new item
        self.list_widget.setCurrentRow(len(self.items) - 1)
        
    def remove_item(self):
        """Remove the selected item from the list"""
        current_row = self.list_widget.currentRow()
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
        if index < 0:
            return
            
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
            self.path_edit.setText(item.path)
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
        if self.current_item_index >= 0 and self.current_item_index < len(self.items):
            new_title = self.title_edit.text().strip()
            
            # Check if the title is unique (excluding the current item)
            for i, item in enumerate(self.items):
                if i != self.current_item_index and item.title == new_title:
                    QMessageBox.warning(self, 'Duplicate Title',
                                      'An item with this title already exists. Please use a unique title.')
                    return
            
            item = self.items[self.current_item_index]
            if item.title!=new_title: 
                del self.cfg["EXECUTABLES"][item.title] # rename occured
                self.cfg["EXECUTABLES"][new_title]=dict()
                self.cfg["EXECUTABLES"][new_title]["SELECTED"]=False
            item.title = new_title
            item.path = self.path_edit.text()
            item.params = self.params_edit.text()
            self.cfg["EXECUTABLES"][item.title]["PATH"]=item.path
            self.cfg["EXECUTABLES"][item.title]["PARAMS"]=item.params
            write_cfg(self.cfg)

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


def main():
    app = QApplication(sys.argv)
    editor = ExeManager()
    editor.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
