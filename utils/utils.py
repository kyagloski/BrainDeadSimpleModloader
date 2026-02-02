
# UTILITY FUNCTIONS

import os
import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog

def force_symlink(target, link_name):
    try:
        if os.path.islink(link_name) or os.path.exists(link_name):
            os.unlink(link_name)
    except FileNotFoundError: pass
    os.symlink(target, link_name)

def remove_symlink_rec(target):
    [os.unlink(os.path.join(r,f)) for r,d,fs in os.walk(target) for f in fs+d if os.path.islink(os.path.join(r,f))]

def fix_path_case(path):
    path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(path)
    cur = drive + os.sep if drive else os.sep
    fixed = []
    for part in rest.strip(os.sep).split(os.sep):
        try:
            entries = os.listdir(cur)
            part = next((e for e in entries if e.lower() == part.lower()), part)
        except FileNotFoundError:
            pass  # keep part as-is if the directory doesn't exist
        fixed.append(part)
        cur = os.path.join(cur, part)
    return os.path.join(drive, *fixed) if drive else os.sep + os.path.join(*fixed)

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def print_traceback():
    for line in traceback.format_stack()[:-1]: print(line.strip())

def select_directory():
    """Show detailed prompt then directory picker with confirmation"""
    app = QApplication(sys.argv)
    
    # Create custom message box
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle("Target Directory Required")
    msg.setText("Select the root of your game directory:")
    msg.setInformativeText(
        "• Choose the directory containing the \"Data\" folder.\n\n"
        "Click OK to choose a directory."
    )
    msg.setStandardButtons(
        QMessageBox.StandardButton.Ok | 
        QMessageBox.StandardButton.Cancel
    )
    msg.setDefaultButton(QMessageBox.StandardButton.Ok)
    
    # Show message and wait for response
    result = msg.exec()
    
    if result == QMessageBox.StandardButton.Ok:
        # Loop until user confirms or cancels
        while True:
            # Show directory picker
            directory = QFileDialog.getExistingDirectory(
                None,
                "Select Target Directory",
                "/home",
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
            )
            
            if directory:
                # Show confirmation dialog
                confirm = QMessageBox.question(
                    None,
                    "Confirm Directory",
                    f"Are you sure you want to use this directory?\n\n{directory}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                if confirm == QMessageBox.StandardButton.Yes:
                    # User confirmed, return the directory
                    print(f"Selected directory: {directory}")
                    return directory
                else:
                    # User said no, loop continues to show directory picker again
                    print("User rejected directory, showing picker again...")
                    continue
            else:
                # No directory selected (user cancelled the file dialog)
                QMessageBox.warning(
                    None,
                    "Warning",
                    "No directory was selected!"
                )
                return None
    else:
        print("User cancelled")
        return None
