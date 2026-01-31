#!/usr/bin/python3
import os
import sys
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QSplitter,
    QMessageBox, QFileDialog, QLabel, QDialog, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QDir, QEvent
from PyQt6.QtGui import QFont, QColor, QSyntaxHighlighter, QTextCharFormat, QFileSystemModel, QShortcut, QKeySequence, QTextCursor, QTextDocument  # Add QTextCursor, QTextDocument

from game_specific import *

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
        self.restore_btn.clicked.connect(self.restore_on_click)
        self.restore_btn.setEnabled(False)
        button_layout.addWidget(self.restore_btn)
        
        self.delete_btn = QPushButton("Delete Backup")
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
        self.save_btn.clicked.connect(self.save_current_file)
        self.save_btn.setEnabled(False)
        button_layout.addWidget(self.save_btn)
        
        self.backup_btn = QPushButton("Backup")
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
        root_index = self.right_model.index(str(self.current_dir))
        self.right_tree.setRootIndex(root_index)
        
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
            with open(self.selected_current_file, 'w', encoding='utf-8') as f:
                f.write(self.right_editor.toPlainText())
            self.save_btn.setEnabled(False)
            self.right_editor_modified = False
            QMessageBox.information(self, "Success", "File saved successfully!")
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
            backup_ini(self.compat_dir, self.backup_dir)
        
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

        if res: QMessageBox.information(self, "Success", f"{self.selected_backup_file} restored to:\n{self.current_dir}")
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

    
def main():
    app = QApplication(sys.argv)
    window = INIManager()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
