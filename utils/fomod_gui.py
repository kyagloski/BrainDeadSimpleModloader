#!/usr/bin/python

from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QCheckBox, QScrollArea, QWidget, QButtonGroup,
    QTextEdit, QFrame, QSizePolicy, QSpacerItem, QSplitter,
    QListWidget, QListWidgetItem, QStackedWidget, QGroupBox,
    QMessageBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont

DEBUG=False

class OptionListItem(QListWidgetItem):
    """Custom list item that stores plugin data"""
    def __init__(self, plugin_data, index):
        super().__init__(plugin_data['name'])
        self.plugin_data = plugin_data
        self.plugin_index = index


class SelectableListWidget(QListWidget):
    """List widget that emits signals on hover and selection"""
    item_hovered = pyqtSignal(object)
    item_selected = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.itemEntered.connect(self._on_item_entered)
        self.currentItemChanged.connect(self._on_current_changed)
    
    def _on_item_entered(self, item):
        if isinstance(item, OptionListItem):
            self.item_hovered.emit(item.plugin_data)
    
    def _on_current_changed(self, current, previous):
        if isinstance(current, OptionListItem):
            self.item_selected.emit(current.plugin_data)


class FomodInstallerDialog(QDialog):
    """GUI dialog for FOMOD installation process with dynamic step support"""
    
    def __init__(self, mod_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"FOMOD Installer - {mod_name}")
        self.resize(900, 550)
        self.setModal(True)
        
        self.mod_name = mod_name
        self.condition_flags = {}
        self.selected_files = []
        self.user_cancelled = False
        self.extract_dir = None
        self.step_index=0
        
        # For dynamic step rebuilding
        self.fomod_data = None  # Will be set by process_fomod_gui
        self.all_steps_raw = []  # Store raw step data before filtering
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI layout"""
        if DEBUG: print("FomodInstallerDialog._init_ui")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Main content area with splitter
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left side: options list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        
        self.step_title = QLabel()
        self.step_title.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(self.step_title)
        
        # Scroll area for groups
        self.groups_scroll = QScrollArea()
        self.groups_scroll.setWidgetResizable(True)
        self.groups_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(8)
        self.groups_scroll.setWidget(self.groups_container)
        
        left_layout.addWidget(self.groups_scroll)
        
        # Right side: details panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        
        details_label = QLabel("Details")
        details_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(details_label)
        
        # Scrollable details area
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # Details content
        self.details_frame = QFrame()
        self.details_frame.setFrameShape(QFrame.Shape.StyledPanel)
        details_frame_layout = QVBoxLayout(self.details_frame)
        details_frame_layout.setContentsMargins(8, 8, 8, 8)
        details_frame_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.detail_name = QLabel()
        self.detail_name.setStyleSheet("font-weight: bold;")
        self.detail_name.setWordWrap(True)
        details_frame_layout.addWidget(self.detail_name)
        
        self.detail_image = QLabel()
        self.detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_image.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        details_frame_layout.addWidget(self.detail_image)
        
        self.detail_description = QLabel()
        self.detail_description.setWordWrap(True)
        self.detail_description.setAlignment(Qt.AlignmentFlag.AlignTop)
        details_frame_layout.addWidget(self.detail_description)
        
        self.details_scroll.setWidget(self.details_frame)
        right_layout.addWidget(self.details_scroll)
        
        # Add to splitter
        self.main_splitter.addWidget(left_widget)
        self.main_splitter.addWidget(right_widget)
        self.main_splitter.setSizes([450, 450])
        
        layout.addWidget(self.main_splitter, 1)
        
        # Bottom button bar
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 4, 0, 0)
        
        self.step_indicator = QLabel()
        button_layout.addWidget(self.step_indicator)
        
        button_layout.addStretch()
        
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
        self.back_button.setEnabled(False)
        button_layout.addWidget(self.back_button)
        
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.go_next)
        self.next_button.setDefault(True)
        button_layout.addWidget(self.next_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_installation)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        # State tracking
        self.current_step = 0
        self.steps_data = []
        self.step_selections = []
        self.button_groups = {}
        self.checkbox_groups = {}
        
        self._clear_details()
    
    def _clear_details(self):
        """Clear the details panel"""
        if DEBUG: print("_clear_details")
        self.detail_name.setText("Select an option to see details")
        self.detail_image.clear()
        self.detail_description.clear()
    
    def _show_details(self, plugin_data):
        """Show details for a plugin"""
        #if DEBUG: print("_show_details")
        if not plugin_data:
            self._clear_details()
            return
        
        self.detail_name.setText(plugin_data.get('name', ''))
        
        description = plugin_data.get('description', '')
        self.detail_description.setText(description if description else "No description available.")
        
        # Load image
        image_path_str = plugin_data.get('image')
        if image_path_str and self.extract_dir:
            image_path = self._find_image_path(image_path_str, self.extract_dir)
            if image_path and image_path.exists():
                pixmap = QPixmap(str(image_path))
                # Scale to fit
                scaled = pixmap.scaled(
                    380, 280,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.detail_image.setPixmap(scaled)
            else:
                self.detail_image.clear()
        else:
            self.detail_image.clear()
    
    def show_required_files(self, required_files):
        """Display required files that will be installed automatically"""
        if DEBUG: print("show_required_files")
        self._clear_groups()
        
        self.step_title.setText("Required Files")
        self.step_indicator.setText("Required files will be installed automatically")
        
        info_group = QGroupBox("Files to install")
        info_layout = QVBoxLayout(info_group)
        
        files_list = QListWidget()
        files_list.setAlternatingRowColors(True)
        
        for file_info in required_files:
            if isinstance(file_info, tuple):
                file_type, source, dest = file_info
                files_list.addItem(f"{source} → {dest}")
            else:
                source = file_info.get('source', '')
                dest = file_info.get('destination', '')
                files_list.addItem(f"{source} → {dest}")
        
        info_layout.addWidget(files_list)
        self.groups_layout.addWidget(info_group)
        self.groups_layout.addStretch()
        
        self._clear_details()
        self.detail_name.setText("Required Files")
        self.detail_description.setText(
            "These files are required by the mod and will be installed automatically."
        )
    
    def add_step(self, step_name, groups_data, extract_dir):
        """Add an installation step with its groups (legacy method)"""
        if DEBUG: print("add_step")
        self.steps_data.append({
            'name': step_name,
            'groups': groups_data,
            'extract_dir': extract_dir
        })
        self.extract_dir = extract_dir
    
    def rebuild_steps_dynamically(self):
        """
        Rebuild the list of visible steps based on current condition_flags.
        This is called before showing each step to handle conditional steps.
        """
        if DEBUG: print("rebuild_steps_dynamically")
        if not self.fomod_data:
            return
        
        ns = self.fomod_data.get('namespace', {})
        
        # Clear current steps but preserve selections
        old_steps_data = self.steps_data.copy()
        self.steps_data = []
       
        for step in self.fomod_data['steps']:
            # Check step visibility
            if step.get('visible_elem') is not None:
                if not self._evaluate_visibility(step['visible_elem'], ns):
                    continue
            
            # Filter visible groups and plugins
            visible_groups = []
            for group in step['groups']:
                visible_plugins = []
                for plugin in group['plugins']:
                    if plugin.get('visible_elem') is None or self._evaluate_visibility(plugin['visible_elem'], ns):
                        visible_plugins.append(plugin)
                
                if visible_plugins:
                    visible_groups.append({
                        'name': group['name'],
                        'type': group['type'],
                        'plugins': visible_plugins
                    })
            
            if visible_groups:
                self.steps_data.append({
                    'name': step['name'],
                    'groups': visible_groups,
                    'extract_dir': self.extract_dir
                })
    
    def _evaluate_visibility(self, visible_elem, ns):
        """Evaluate visibility conditions based on current flags."""
        #if DEBUG: print("_evaluate_visibility")
        if visible_elem is None: return True
        
        # Get dependencies element
        deps_elem = visible_elem.find('.//dependencies', ns) if ns else visible_elem.find('.//dependencies')
        if deps_elem is None: return True
        
        operator = deps_elem.get('operator', 'And')
        
        # Find all flag dependencies
        flag_deps = deps_elem.findall('.//flagDependency', ns) if ns else deps_elem.findall('.//flagDependency')
        if not flag_deps: return True
        
        results = []
        for flag_dep in flag_deps:
            flag_name = flag_dep.get('flag', '')
            expected_value = flag_dep.get('value', 'On')
            actual_value = self.condition_flags.get(flag_name, 'Off')
            if DEBUG and actual_value=="Active": print(flag_name,'->',actual_value)
            if expected_value=="": expected_value="Off"
            results.append(actual_value == expected_value)
        
        if operator == 'And': return all(results)
        elif operator == 'Or':return any(results)
        else: return all(results)
    
    def show_step(self, step_index):
        """Display a specific installation step"""
        if DEBUG: print("show_step")
        if step_index < 0 or step_index >= len(self.steps_data):
            return
        self.step_index=step_index 
        self._clear_groups()
        self.button_groups.clear()
        self.checkbox_groups.clear()
        
        step_data = self.steps_data[step_index]
        self.extract_dir = step_data['extract_dir']
        
        self.step_title.setText(step_data['name'])
        self.step_indicator.setText(f"Step {step_index + 1} of {len(self.steps_data)}")
        
        # Initialize selections storage
        while len(self.step_selections) <= step_index:
            self.step_selections.append([])
        
        # Create groups
        for group_idx, group_data in enumerate(step_data['groups']):
            self._add_group_widget(group_data, step_index, group_idx)
        
        self.groups_layout.addStretch()
        
        # Update navigation
        self.back_button.setEnabled(step_index > 0)
        self.next_button.setText("Install" if step_index == len(self.steps_data) - 1 else "Next")
        
        self._clear_details()
    
    def _clear_groups(self):
        """Clear all group widgets"""
        if DEBUG: print("_clear_groups")
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _add_group_widget(self, group_data, step_index, group_idx):
        """Add a compact group widget"""
        #if DEBUG: print("_add_group_widget")
        group_type = group_data['type']
        
        # Type hints
        type_hints = {
            'SelectExactlyOne': 'Select one',
            'SelectAtMostOne': 'Select one or none',
            'SelectAtLeastOne': 'Select at least one',
            'SelectAny': 'Select any',
            'SelectAll': 'All required'
        }
        hint = type_hints.get(group_type, '')
        
        group_box = QGroupBox(f"{group_data['name']} ({hint})")
        group_layout = QVBoxLayout(group_box)
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(2)
        
        if group_type in ['SelectExactlyOne', 'SelectAtMostOne']:
            self._add_radio_options(group_layout, group_data, step_index, group_idx)
        else:
            self._add_checkbox_options(group_layout, group_data, step_index, group_idx)
        
        self.groups_layout.addWidget(group_box)
    
    def _add_radio_options(self, layout, group_data, step_index, group_idx):
        """Add radio button options"""
        #if DEBUG: print("_add_radio_options")
        button_group = QButtonGroup(self)
        button_group.setExclusive(True)
        
        # None option for SelectAtMostOne
        if group_data['type'] == 'SelectAtMostOne':
            none_radio = QRadioButton("None")
            none_radio.setChecked(True)
            none_radio.toggled.connect(lambda checked: self._clear_details() if checked else None)
            none_radio.setProperty('plugin_data', None)
            none_radio.installEventFilter(self)
            none_radio.setMouseTracking(True)
            button_group.addButton(none_radio, -1)
            layout.addWidget(none_radio)
        
        for idx, plugin in enumerate(group_data['plugins']):
            radio = QRadioButton(plugin['name'])
            radio.toggled.connect(
                lambda checked, p=plugin: self._on_plugin_toggled(p, checked)
            )
            # update selection table
            self._on_plugin_toggled(plugin,False)
            # Store plugin data and install event filter for hover
            radio.setProperty('plugin_data', plugin)
            radio.installEventFilter(self)
            radio.setMouseTracking(True)
            button_group.addButton(radio, idx)
            
            # Auto-select first for SelectExactlyOne
            if group_data['type'] == 'SelectExactlyOne' and idx == 0:
                radio.setChecked(True)
                #self._on_pluggin_toggled(radio.plugin,True)
            
            layout.addWidget(radio)
        
        self.button_groups[(step_index, group_idx)] = button_group
    
    def _add_checkbox_options(self, layout, group_data, step_index, group_idx):
        """Add checkbox options"""
        #if DEBUG: print("_add_checkbox_options")
        checkboxes = []
        
        for idx, plugin in enumerate(group_data['plugins']):
            checkbox = QCheckBox(plugin['name'])
            checkbox.toggled.connect(
                lambda checked, p=plugin: self._on_plugin_toggled(p, checked)
            )
            # reupdate selection table
            self._on_plugin_toggled(plugin,False)
            # Show details on hover
            checkbox.setProperty('plugin_data', plugin)
            checkbox.installEventFilter(self)
            checkbox.setMouseTracking(True)
            checkboxes.append(checkbox)
            layout.addWidget(checkbox)
        
        self.checkbox_groups[(step_index, group_idx)] = checkboxes
    
    def _on_plugin_toggled(self, plugin, checked):
        """Handle plugin selection toggle - update flags immediately"""
        if DEBUG: print("_on_plugin_toggled", plugin["flags"])
        #if checked:
        self._show_details(plugin)
        # Update condition flags when a plugin is selected
        for flag_name, flag_value in plugin.get('flags', {}).items():
            if checked: self.condition_flags[flag_name] = "Active"
            else: self.condition_flags[flag_name] = "Off"
        self.rebuild_steps_dynamically()
        self.next_button.setText("Install" if self.step_index == len(self.steps_data) - 1 else "Next")
        self.step_indicator.setText(f"Step {self.step_index + 1} of {len(self.steps_data)}")
    
    def eventFilter(self, obj, event):
        """Handle hover events for radio buttons and checkboxes"""
        #if DEBUG: print("eventFilter")
        from PyQt6.QtCore import QEvent
        if event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.MouseMove):
            plugin_data = obj.property('plugin_data')
            if plugin_data:
                self._show_details(plugin_data)
            elif plugin_data is None and isinstance(obj, QRadioButton):
                # "None" option
                self._clear_details()
        return super().eventFilter(obj, event)
    
    def _find_image_path(self, image_path, extract_dir):
        """Find image path case-insensitively"""
        if DEBUG: print("_find_image_path")
        extract_path = Path(extract_dir)
        image_parts = image_path.replace('\\', '/').split('/')
        
        current_path = extract_path
        for part in image_parts:
            if not current_path.is_dir():
                return None
            
            found = False
            try:
                for item in current_path.iterdir():
                    if item.name.lower() == part.lower():
                        current_path = item
                        found = True
                        break
            except (PermissionError, OSError):
                return None
            
            if not found:
                return None
        
        return current_path if current_path.is_file() else None
    
    def go_back(self):
        """Go to previous step"""
        if DEBUG: print("go_back")
        if self.current_step > 0:
            # Rebuild steps in case conditions changed
            new_step = min(self.current_step - 1, len(self.steps_data) - 1)
            if new_step >= 0:
                self.current_step = new_step
                self.show_step(self.current_step)
            #self.rebuild_steps_dynamically()
            #self.next_button.setText("Install" if self.step_index == len(self.steps_data) - 1 else "Next")
            #self.step_indicator.setText(f"Step {self.step_index + 1} of {len(self.steps_data)}")
 
    def go_next(self):
        """Go to next step or finish installation"""
        if DEBUG: print("go_next")
        if self.current_step < len(self.steps_data):
            selections = self._collect_step_selections()
            if selections is None: return
            if len(self.step_selections) <= self.current_step:
                self.step_selections.append(selections)
            else:
                self.step_selections[self.current_step] = selections
            # Collect flags from current selections
            self._collect_flags_from_current_step()
        
        # Rebuild steps to check for new conditional steps
        self.rebuild_steps_dynamically()
        
        if self.current_step < len(self.steps_data) - 1:
            self.current_step += 1
            self.show_step(self.current_step)
        else:
            self._process_all_selections()
            self.accept()
    
    def _collect_flags_from_current_step(self):
        """Collect all flags from selections in the current step"""
        if DEBUG: print("_collect_flags_from_current_step")
        if self.current_step >= len(self.steps_data): return
        
        step_data = self.steps_data[self.current_step]
        
        for group_idx, group_data in enumerate(step_data['groups']):
            group_type = group_data['type']
            
            if group_type in ['SelectExactlyOne', 'SelectAtMostOne']:
                button_group = self.button_groups.get((self.current_step, group_idx))
                if button_group:
                    checked_id = button_group.checkedId()
                    if checked_id >= 0 and checked_id < len(group_data['plugins']):
                        plugin = group_data['plugins'][checked_id]
                        for flag_name, flag_value in plugin.get('flags', {}).items():
                            self.condition_flags[flag_name] = flag_value
            else:
                checkboxes = self.checkbox_groups.get((self.current_step, group_idx))
                if checkboxes:
                    for idx, cb in enumerate(checkboxes):
                        if cb.isChecked() and idx < len(group_data['plugins']):
                            plugin = group_data['plugins'][idx]
                            for flag_name, flag_value in plugin.get('flags', {}).items():
                                self.condition_flags[flag_name] = flag_value
    
    def _collect_step_selections(self):
        """Collect user selections for the current step"""
        if DEBUG: print("_collect_step_selections")
        step_data = self.steps_data[self.current_step]
        selections = []
        
        for group_idx, group_data in enumerate(step_data['groups']):
            group_type = group_data['type']
            
            if group_type in ['SelectExactlyOne', 'SelectAtMostOne']:
                button_group = self.button_groups.get((self.current_step, group_idx))
                if button_group:
                    checked_id = button_group.checkedId()
                    if checked_id >= 0:
                        selections.append({
                            'group_idx': group_idx,
                            'plugin_indices': [checked_id]
                        })
                    elif group_type == 'SelectExactlyOne':
                        return None
            else:
                checkboxes = self.checkbox_groups.get((self.current_step, group_idx))
                if checkboxes:
                    selected_indices = [
                        idx for idx, cb in enumerate(checkboxes)
                        if cb.isChecked()
                    ]
                    
                    if group_type == 'SelectAtLeastOne' and not selected_indices:
                        QMessageBox.warning(
                            self,
                            "Selection Required",
                            f"Please select at least one option for:\n{group_data['name']}"
                        )
                        return None
                    
                    if selected_indices:
                        selections.append({
                            'group_idx': group_idx,
                            'plugin_indices': selected_indices
                        })
        
        return selections
    
    def _process_all_selections(self):
        """Process all user selections"""
        if DEBUG: print("_process_all_selections")
        for step_idx, step_selections in enumerate(self.step_selections):
            if step_idx >= len(self.steps_data): continue
            step_data = self.steps_data[step_idx]
            
            for selection in step_selections:
                group_idx = selection['group_idx']
                if group_idx >= len(step_data['groups']): continue
                group_data = step_data['groups'][group_idx]
                
                for plugin_idx in selection['plugin_indices']:
                    if plugin_idx >= len(group_data['plugins']): continue
                    plugin = group_data['plugins'][plugin_idx]
                    
                    for flag_name, flag_value in plugin.get('flags', {}).items():
                        self.condition_flags[flag_name] = flag_value
                    
                    self.selected_files.extend(plugin.get('files', []))
    
    def cancel_installation(self):
        self.user_cancelled = True
        self.reject()

    def get_results(self):
        """Get installation results"""
        if DEBUG: print("get_results")
        return { 'cancelled': self.user_cancelled,
                 'condition_flags': self.condition_flags,
                 'selected_files': self.selected_files }


# Demo/test code
if __name__ == '__main__':
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    dialog = FomodInstallerDialog("Test Mod")
    
    # Add test data
    test_groups = [
        {
            'name': 'Texture Quality',
            'type': 'SelectExactlyOne',
            'plugins': [
                {'name': '1K Textures', 'description': 'Lower quality textures for better performance.', 'image': '', 'flags': {}, 'files': []},
                {'name': '2K Textures', 'description': 'Medium quality textures. Recommended for most systems.', 'image': '', 'flags': {}, 'files': []},
                {'name': '4K Textures', 'description': 'High quality textures. Requires a powerful GPU.', 'image': '', 'flags': {}, 'files': []},
            ]
        },
        {
            'name': 'Optional Features',
            'type': 'SelectAny',
            'plugins': [
                {'name': 'ENB Compatibility', 'description': 'Adds compatibility patches for ENB presets.', 'image': '', 'flags': {}, 'files': []},
                {'name': 'Performance Mode', 'description': 'Optimizes assets for lower-end hardware.', 'image': '', 'flags': {}, 'files': []},
            ]
        }
    ]
    
    dialog.add_step("Configuration", test_groups, "/tmp")
    dialog.show_step(0)
    
    dialog.show()
    sys.exit(app.exec())
