#!/usr/bin/python3
import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QSplitter,
    QMessageBox, QFileDialog, QLabel
)
from PyQt6.QtCore import Qt, QDir, QEvent
from PyQt6.QtGui import QFont, QColor, QSyntaxHighlighter, QTextCharFormat, QFileSystemModel, QShortcut, QKeySequence


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
    def __init__(self, backup_dir, compat_dir):
        super().__init__()
        self.setWindowTitle("BrainDead Simple Modloader - INI Manager")
        self.setGeometry(100, 100, 1400, 800)
        
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

        self.set_backup_directory(backup_dir)
        self.set_current_directory(compat_dir)
        
        # Initialize paths
        self.backup_dir = None
        self.current_dir = None
        self.selected_backup_file = None
        self.selected_current_file = None
    
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
        
        # Set Directory button
        #self.left_set_dir_btn = QPushButton("Set Backup Directory")
        #self.left_set_dir_btn.clicked.connect(self.set_backup_directory)
        #button_layout.addWidget(self.left_set_dir_btn)
        
        self.restore_btn = QPushButton("Restore")
        #self.restore_btn.clicked.connect(self.restore_file)
        self.restore_btn.setEnabled(False)
        button_layout.addWidget(self.restore_btn)
        
        self.delete_btn = QPushButton("Delete Backup")
        #self.delete_btn.clicked.connect(self.delete_backup)
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
        
        # Set Directory button
        #self.right_set_dir_btn = QPushButton("Set Current Directory")
        #self.right_set_dir_btn.clicked.connect(self.set_current_directory)
        #button_layout.addWidget(self.right_set_dir_btn)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_current_file)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.backup_btn = QPushButton("Backup")
        #self.backup_btn.clicked.connect(self.backup_file)
        self.backup_btn.setEnabled(False)
        button_layout.addWidget(self.backup_btn)
        
        layout.addLayout(button_layout)
        
        return column_widget
    
    def set_backup_directory(self, directory):
        """Set the backup directory for left column"""
        #directory = QFileDialog.getExistingDirectory(self, "Select Backup Directory")
        #if directory:
        self.backup_dir = Path(directory)
        self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))
        self.left_tree.expandAll()
        self.left_dir_label.setText(self.backup_dir.name)
    
    def set_current_directory(self, directory):
        """Set the current directory for right column (INI files only)"""
        #directory = QFileDialog.getExistingDirectory(self, "Select Current Directory")
        #if directory:
        #self.current_dir = Path(directory)
        #self.right_tree.setRootIndex(self.right_model.index(str(self.current_dir)))
        #self.backup_btn.setEnabled(True)
        #self.right_dir_label.setText(self.current_dir.name)
        self.current_dir = Path(directory)
        root_index = self.right_model.index(str(self.current_dir))
        self.right_tree.setRootIndex(root_index)
        
        # Hide all subdirectories
        for i in range(self.right_model.rowCount(root_index)):
            index = self.right_model.index(i, 0, root_index)
            if self.right_model.isDir(index):
                self.right_tree.setRowHidden(i, root_index, True)
        
        self.backup_btn.setEnabled(True)
        self.right_dir_label.setText(self.current_dir.name)
    
    def on_left_file_clicked(self, index):
        """Handle file selection in left tree"""
        file_path = Path(self.left_model.filePath(index))
        
        # Update label with current directory or file's parent directory
        if file_path.is_dir():
            self.left_dir_label.setText(file_path.name)
        else:
            self.left_dir_label.setText(file_path.parent.name)
        
        if file_path.is_file() and file_path.suffix.lower() == '.ini':
            self.selected_backup_file = file_path
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.left_editor.setPlainText(content)
                self.restore_btn.setEnabled(True)
                self.delete_btn.setEnabled(True)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read file:\n{str(e)}")
        else:
            self.restore_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
    
    def on_right_file_clicked(self, index):
        """Handle file selection in right tree"""
        file_path = Path(self.right_model.fileInfo(index).absoluteFilePath())

        if file_path.is_dir():
            self.right_dir_label.setText(file_path.name)
        else:
            self.right_dir_label.setText(file_path.parent.name)
        
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
            with open(self.selected_current_file, 'w', encoding='utf-8') as f:
                f.write(self.right_editor.toPlainText())
            self.save_btn.setEnabled(False)
            self.right_editor_modified = False
            QMessageBox.information(self, "Success", "File saved successfully!")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save file:\n{str(e)}")
    
    #def backup_file(self):
    #    """Backup current file to backup directory"""
    #    if not self.selected_current_file:
    #        QMessageBox.warning(self, "Warning", "Please select a file to backup.")
    #        return
    #    
    #    if not self.backup_dir:
    #        QMessageBox.warning(self, "Warning", "Please set a backup directory first.")
    #        return
    #    
    #    # Check if there are unsaved changes
    #    if hasattr(self, 'right_editor_modified') and self.right_editor_modified:
    #        reply = QMessageBox.question(
    #            self, 
    #            "Unsaved Changes",
    #            "You have unsaved changes. Do you want to save before backing up?",
    #            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
    #        )
    #        
    #        if reply == QMessageBox.StandardButton.Cancel:
    #            return
    #        elif reply == QMessageBox.StandardButton.Yes:
    #            self.save_current_file()
    #    
    #    try:
    #        import shutil
    #        from datetime import datetime
    #        
    #        # Create backup with timestamp
    #        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    #        backup_name = f"{self.selected_current_file.stem}_{timestamp}.ini"
    #        backup_path = self.backup_dir / backup_name
    #        
    #        shutil.copy2(self.selected_current_file, backup_path)
    #        
    #        QMessageBox.information(self, "Success", f"File backed up to:\n{backup_path}")
    #        
    #        # Refresh left tree
    #        self.left_model.setRootPath("")
    #        self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))
    #        
    #    except Exception as e:
    #        QMessageBox.warning(self, "Error", f"Could not backup file:\n{str(e)}")
    #
    #def restore_file(self):
    #    """Restore backup file to current directory"""
    #    if not self.selected_backup_file:
    #        QMessageBox.warning(self, "Warning", "Please select a backup file to restore.")
    #        return
    #    
    #    if not self.current_dir:
    #        QMessageBox.warning(self, "Warning", "Please set a current directory first.")
    #        return
    #    
    #    # Ask for confirmation
    #    reply = QMessageBox.question(
    #        self,
    #        "Confirm Restore",
    #        f"Restore {self.selected_backup_file.name} to current directory?\nThis will overwrite any existing file with the same name.",
    #        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    #    )
    #    
    #    if reply == QMessageBox.StandardButton.No:
    #        return
    #    
    #    try:
    #        import shutil
    #        
    #        # Extract original filename (remove timestamp)
    #        original_name = self.selected_backup_file.stem.rsplit('_', 1)[0] + '.ini'
    #        restore_path = self.current_dir / original_name
    #        
    #        shutil.copy2(self.selected_backup_file, restore_path)
    #        
    #        QMessageBox.information(self, "Success", f"File restored to:\n{restore_path}")
    #        
    #        # Refresh right tree
    #        self.right_model.setRootPath("")
    #        self.right_tree.setRootIndex(self.right_model.index(str(self.current_dir)))
    #        
    #    except Exception as e:
    #        QMessageBox.warning(self, "Error", f"Could not restore file:\n{str(e)}")
    
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
    
    #def delete_backup(self):
    #    """Delete selected backup file"""
    #    if not self.selected_backup_file:
    #        QMessageBox.warning(self, "Warning", "Please select a backup file to delete.")
    #        return
    #    
    #    # Ask for confirmation
    #    reply = QMessageBox.question(
    #        self,
    #        "Confirm Delete",
    #        f"Delete backup file:\n{self.selected_backup_file.name}?",
    #        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    #    )
    #    
    #    if reply == QMessageBox.StandardButton.No:
    #        return
    #    
    #    try:
    #        self.selected_backup_file.unlink()
    #        self.left_editor.clear()
    #        self.restore_btn.setEnabled(False)
    #        self.delete_btn.setEnabled(False)
    #        
    #        QMessageBox.information(self, "Success", "Backup file deleted.")
    #        
    #        # Refresh left tree
    #        self.left_model.setRootPath("")
    #        self.left_tree.setRootIndex(self.left_model.index(str(self.backup_dir)))
    #        
    #    except Exception as e:
    #        QMessageBox.warning(self, "Error", f"Could not delete file:\n{str(e)}")


def main():
    app = QApplication(sys.argv)
    window = INIManager()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
