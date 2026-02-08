#!/usr/bin/python3

import os
import sys
import zipfile
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import argparse
import subprocess

from PyQt6.QtWidgets import QApplication, QMessageBox

import patoolib

try:
    from fomod_gui import FomodInstallerDialog
    from utils import * 
except:
    from utils.fomod_gui import FomodInstallerDialog
    from utils.utils import * 


DEBUG=False

def extract_archive(archive_path, extract_path):
    archive_path=Path(archive_path)
    if os.path.isdir(archive_path): shutil.copytree(archive_path, extract_to); return
    try:
        patoolib.extract_archive(archive_path, outdir=extract_path, verbosity=-1)
        return True
    except Exception as e:
        print(f"encountered exception during extract: {str(e)}")
        return False


def find_fomod_config(extract_dir):
    """Find ModuleConfig.xml case-insensitively."""
    # Common locations
    common_paths = [
        'fomod/ModuleConfig.xml',
        'ModuleConfig.xml',
        #'fomod/info.xml',
        #'info.xml'
    ]
    extract_path = Path(extract_dir)
    for path in common_paths:
        if os.name=="posix": full_path = Path(fix_path_case(extract_path / path))
        else: full_path=extract_path/path
        if full_path.exists():
            return full_path
    
    return None


def find_mod_base_dir(mod_path):
    mod_path = Path(mod_path)
    data_indicators = [
        '.esp', '.esm', '.esl', '.bsa', '.ba2',
        'meshes', 'textures', 'scripts', 'sounds',
        'interface', 'music', 'video', 'strings',
        'skse', 'fose', 'f4se', 'nvse', 'seq',
        'fomod'
    ]
    def is_data_directory(path):
        try:
            items = list(path.iterdir())
        except (PermissionError, OSError):
            return False
        for item in items:
            item_lower = item.name.lower()
            for indicator in data_indicators:
                if (indicator.startswith('.') and item_lower.endswith(indicator)) or \
                   (not indicator.startswith('.') and item_lower == indicator and item.is_dir()):
                    return True
        return False
    for root in mod_path.rglob('*'):
        if root.is_dir() and root.name.lower() == 'data' and is_data_directory(root):
            return root
    for root in mod_path.rglob('*'):
        if root.is_dir() and 'fomod' in [d.name.lower() for d in root.iterdir() if d.is_dir()] and is_data_directory(root):
            return root
    for root in [mod_path] + [p for p in mod_path.rglob('*') if p.is_dir()]:
        if is_data_directory(root):
            return root
    return mod_path


def read_fomod(xml_path):
    try:
        # Read raw bytes to detect encoding
        with open(xml_path, 'rb') as f: raw_content = f.read()
        if raw_content.startswith(b'\xff\xfe'):   encoding = 'utf-16-le'
        elif raw_content.startswith(b'\xfe\xff'): encoding = 'utf-16-be'
        elif raw_content.startswith(b'\xef\xbb\xbf'): encoding = 'utf-8-sig'
        else: encoding = 'utf-8'
        # Try detected encoding first, then fallbacks
        encodings = [encoding, 'utf-16', 'utf-16-le', 'utf-16-be', 'utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        last_error = None
        for enc in encodings:
            try:
                content = raw_content.decode(enc)
                root = ET.fromstring(content)
                namespace = ''
                if root.tag.startswith('{'): namespace = root.tag.split('}')[0] + '}'
                return root, namespace
            except (UnicodeDecodeError, ET.ParseError, LookupError) as e:
                last_error = e
                continue
        # if all encodings fail, show the error
        print(f"Failed to parse XML. Last error: {last_error}")
        print(f"\nFirst 200 chars of file (raw):")
        print(raw_content[:200])
        raise Exception("Could not parse XML with any supported encoding")
    except ET.ParseError as e:
        print(f"error parsing XML: {e}")
        return #sys.exit(1)
    except Exception as e:
        print(f"Unexpected error reading XML: {e}")
        return #sys.exit(1)

def get_text(element, default=''):
    """Safely get text from element."""
    return element.text.strip() if element is not None and element.text else default

def parse_fomod_structure(fomod_path, extract_dir):
    """Parse FOMOD structure and return data for GUI or CLI processing"""
    root, namespace = read_fomod(fomod_path)
    ns = {'': namespace.strip('{}')} if namespace else {}
    
    # Get module name
    mod_name_elem = root.find('.//moduleName', ns) if ns else root.find('.//moduleName')
    mod_name = get_text(mod_name_elem, 'Unknown Mod')
    
    # Process required install files first
    required_files = []
    required_elem = root.find('.//requiredInstallFiles', ns) if ns else root.find('.//requiredInstallFiles')
    if required_elem is not None:
        required_files = extract_files_info(required_elem, ns)
    
    # Find install steps (modern format)
    install_steps = root.find('.//installSteps', ns) if ns else root.find('.//installSteps')
   
    # Parse conditional file installs
    conditional_installs = parse_conditional_installs(root, ns)
    
    # Check for legacy format (optionalFileGroups directly under config)
    if install_steps is None:
        optional_groups = root.find('.//optionalFileGroups', ns) if ns else root.find('.//optionalFileGroups')
        if optional_groups is not None:
            # Legacy format: create a single step with all groups
            steps_data = [{ 'name': 'Installation Options',
                            'groups': parse_groups(optional_groups, ns),
                            'visible_elem': None }]
            return { 'mod_name': mod_name,
                     'required_files': required_files,
                     'steps': steps_data,
                     'conditional_installs': conditional_installs,
                     'namespace': ns }
        else:
            # No steps or groups found
            return { 'mod_name': mod_name,
                     'required_files': required_files,
                     'steps': [],
                     'conditional_installs': conditional_installs,
                     'namespace': ns }
    
    steps_data = []
    
    # Process each install step (modern format)
    for step in install_steps.findall('.//installStep', ns) if ns else install_steps.findall('.//installStep'):
        step_name = step.get('name', 'Installation Step')
        # Store visibility conditions for later evaluation
        visible_elem = step.find('.//visible', ns) if ns else step.find('.//visible')
        # Process optional file groups
        groups = step.find('.//optionalFileGroups', ns) if ns else step.find('.//optionalFileGroups')
        groups_data = parse_groups(groups, ns) if groups is not None else []
        
        steps_data.append({'name': step_name,
                           'groups': groups_data,
                           'visible_elem': visible_elem })
    
    return { 'mod_name': mod_name,
             'required_files': required_files,
             'steps': steps_data,
             'conditional_installs': conditional_installs,
             'namespace': ns }

def parse_conditional_installs(root, ns):
    """Parse conditionalFileInstalls section for pattern-based file installation."""
    conditional_installs = []
    
    conditional_elem = root.find('.//conditionalFileInstalls', ns) if ns else root.find('.//conditionalFileInstalls')
    if conditional_elem is None:
        return conditional_installs
    
    patterns_elem = conditional_elem.find('.//patterns', ns) if ns else conditional_elem.find('.//patterns')
    if patterns_elem is None:
        return conditional_installs
    
    for pattern in patterns_elem.findall('.//pattern', ns) if ns else patterns_elem.findall('.//pattern'):
        deps_elem = pattern.find('.//dependencies', ns) if ns else pattern.find('.//dependencies')
        files_elem = pattern.find('.//files', ns) if ns else pattern.find('.//files')
        
        if deps_elem is not None and files_elem is not None:
            files = extract_files_info(files_elem, ns)
            conditional_installs.append({'dependencies_elem': deps_elem, 'files': files})
    
    return conditional_installs

def parse_groups(groups_elem, ns):
    """Parse group elements and return group data"""
    groups_data = []
    
    for group in groups_elem.findall('.//group', ns) if ns else groups_elem.findall('.//group'):
        group_name = group.get('name', 'Options')
        group_type = group.get('type', 'SelectAny')
        
        plugins_elem = group.find('.//plugins', ns) if ns else group.find('.//plugins')
        if plugins_elem is None:
            continue
        
        plugin_list = plugins_elem.findall('.//plugin', ns) if ns else plugins_elem.findall('.//plugin')
        
        plugins_data = []
        for plugin in plugin_list:
            plugin_name = plugin.get('name', 'Option')
            
            # Get description (handle CDATA)
            desc_elem = plugin.find('.//description', ns) if ns else plugin.find('.//description')
            description = get_text(desc_elem, '')
            
            # Get image
            image_elem = plugin.find('.//image', ns) if ns else plugin.find('.//image')
            image_path = image_elem.get('path', '') if image_elem is not None else ''
            
            # Get condition flags
            flags = {}
            flags_elem = plugin.find('.//conditionFlags', ns) if ns else plugin.find('.//conditionFlags')
            if flags_elem is not None:
                for flag in flags_elem.findall('.//flag', ns) if ns else flags_elem.findall('.//flag'):
                    flag_name = flag.get('name', '')
                    flag_value = get_text(flag, 'On')
                    if flag_name:
                        flags[flag_name] = flag_value
            
            # Get files
            files_elem = plugin.find('.//files', ns) if ns else plugin.find('.//files')
            files = extract_files_info(files_elem, ns) if files_elem is not None else []
            
            # Get visibility conditions
            visible_elem = plugin.find('.//visible', ns) if ns else plugin.find('.//visible')
            
            # Get typeDescriptor for dependency checking
            type_desc_elem = plugin.find('.//typeDescriptor', ns) if ns else plugin.find('.//typeDescriptor')
            
            plugins_data.append({'name': plugin_name,
                                 'description': description,
                                 'image': image_path,
                                 'flags': flags,
                                 'files': files,
                                 'visible_elem': visible_elem,
                                 'type_desc_elem': type_desc_elem})
        
        groups_data.append({'name': group_name,
                            'type': group_type,
                            'plugins': plugins_data})
    
    return groups_data


def evaluate_conditional_installs(conditional_installs, condition_flags, ns):
    """Evaluate conditional file installs and return matching files."""
    files = []
    for pattern in conditional_installs:
        deps_elem = pattern['dependencies_elem']
        if evaluate_dependencies_element(deps_elem, condition_flags, ns):
            files.extend(pattern['files'])
            # Only first matching pattern applies (FOMOD spec)
            #break
    return files


def evaluate_dependencies_element(deps_elem, condition_flags, ns):
    """Evaluate a dependencies element directly."""
    if deps_elem is None: return True
    operator = deps_elem.get('operator', 'And')
    # Find all flag dependencies
    flag_deps = deps_elem.findall('.//flagDependency', ns) if ns else deps_elem.findall('.//flagDependency')
    
    if not flag_deps: return True
    
    results = [] # user choice combo active/off
    options = []   # available choice combo names
    choice = condition_flags.keys() # user choice names
    for flag_dep in flag_deps:
        flag_name = flag_dep.get('flag', '')
        options.append(flag_name)
        expected_value = flag_dep.get('value', 'On')
        actual_value = condition_flags.get(flag_name, 'Off')
        if expected_value=="": expected_value="Off"
        results.append(actual_value == expected_value)
    if operator == 'And':  return all(results)
    elif operator == 'Or': return any(results)
    else: return all(results)

def evaluate_conditions(visible_elem, condition_flags, ns):
    """Evaluate visibility conditions based on current flags."""
    # Get dependencies element
    deps_elem = visible_elem.find('.//dependencies', ns) if ns else visible_elem.find('.//dependencies')
    if deps_elem is None: return True
    return evaluate_dependencies_element(deps_elem, condition_flags, ns)

def extract_files_info(files_elem, ns):
    """Extract file and folder information from XML."""
    file_list = []
    
    # Handle individual files
    for file_elem in files_elem.findall('.//file', ns) if ns else files_elem.findall('.//file'):
        source = file_elem.get('source', '')
        destination = file_elem.get('destination', '')
        if sys.platform=='linux': destination=destination.replace('\\','/')
        if source and destination:
            file_list.append(('file', source, destination))
    
    # Handle folders
    for folder_elem in files_elem.findall('.//folder', ns) if ns else files_elem.findall('.//folder'):
        source = folder_elem.get('source', '')
        destination = folder_elem.get('destination', '')
        if sys.platform=='linux': destination=destination.replace('\\','/')
        if destination=="": destination="."
        if source and destination:
            file_list.append(('folder', source, destination))
    return file_list

def process_fomod(archive_path, extract_dir, output_dir, parent=None):
    """Process FOMOD configuration using GUI with dynamic step evaluation"""
    fomod_path=find_fomod_config(extract_dir)
    print(f"found FOMOD config at: {fomod_path}")
    # Parse FOMOD structure
    fomod_data = parse_fomod_structure(fomod_path, extract_dir)
    
    # Check if there are any steps/options
    if not fomod_data['steps'] and not fomod_data['required_files']:
        QMessageBox.information(
            parent,
            "No Options",
            f"Mod '{fomod_data['mod_name']}' has no installation options.\nAll files will be copied."
        )
        return None
    
    # Create GUI dialog with full fomod_data for dynamic evaluation
    if parent:
        app = None
        dialog = FomodInstallerDialog(fomod_data['mod_name'], parent)
    else:
        app = QApplication.instance()
        if app is None: app = QApplication(sys.argv)
        dialog = FomodInstallerDialog(fomod_data['mod_name'])
    
    # Store fomod_data in dialog for dynamic step building
    dialog.fomod_data = fomod_data
    dialog.extract_dir = extract_dir
    dialog.condition_flags = {}
    
    # If no steps, just show required files and install
    if not fomod_data['steps']:
        if fomod_data['required_files']:
            result = dialog.exec()
            if result and not dialog.user_cancelled:
                mod_name = install_fomod_files(fomod_data['required_files'], extract_dir, output_dir)
                #return fomod_data['required_files']
                return mod_name
        return None
    
    # Build initial visible steps dynamically
    dialog.rebuild_steps_dynamically()
    
    # Show first step
    if dialog.steps_data: dialog.show_step(0)
    else:
        # No visible steps, just install required files if any
        if fomod_data['required_files']:
            result = dialog.exec()
            if result and not dialog.user_cancelled:
                mod_name = install_fomod_files(fomod_data['required_files'], extract_dir, output_dir)
                #return fomod_data['required_files']
                return mod_name
        return None
    
    # run dialog 
    result = dialog.exec()
    if result and (not dialog.user_cancelled):
        # Get results of user choice
        results = dialog.get_results()
        # Evaluate conditional file installs based on final flags
        conditional_files = evaluate_conditional_installs(
            fomod_data.get('conditional_installs', []),
            dialog.condition_flags,
            fomod_data['namespace'])
        # Install files
        all_files = fomod_data['required_files'] + results['selected_files'] + conditional_files
        if all_files:
            mod_name = install_fomod_files(archive_path, all_files, extract_dir, output_dir)
        #return results['selected_files']+conditional_files # idk about this one
        return mod_name
    return None  # User cancelled

def install_fomod_files(archive_path, file_list, extract_dir, output_dir):
    """Copy selected files to output directory."""
    extract_dir = Path(extract_dir)
    if os.path.isdir(archive_path): mod_name=Path(archive_path).name
    else: mod_name = Path(archive_path).stem
    output_dir = Path(output_dir)/mod_name
    if os.path.isdir(output_dir): output_dir, mod_name=fix_dirname_used(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*80)
    print("Installing files...")
    print("="*80 + "\n")
    
    for file_type, source, destination in file_list:
        # Try to find source case-insensitively
        source_parts = source.replace('\\', '/').split('/')
        current_path = extract_dir
        
        for part in source_parts:
            found = False
            if not current_path.is_dir(): continue
            for item in current_path.iterdir():
                if item.name.lower() == part.lower():
                    current_path = item
                    found = True
                    break
            if not found:
                print(f"warning: Could not find {source}")
                break
        else:
            dest_path = output_dir / destination
            if file_type == 'file' and current_path.is_file():
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current_path, dest_path)
                print(f"installed: {current_path} to {destination}")
            elif file_type == 'folder' and current_path.is_dir():
                shutil.copytree(current_path, dest_path, dirs_exist_ok=True)
                #print(f"installed folder: {current_path} to {destination}")
    print(f"\ninstallation complete! files installed to: {output_dir}")
    return mod_name

def install_mod_files(archive_path, temp_dir, output_dir):
    print("copying files from non-FOMOD archive...")
    # Copy everything from temp to output
    mod_name = Path(archive_path).stem
    output_dir=Path(output_dir)/mod_name
    if os.path.isdir(output_dir): output_dir,mod_name=fix_dirname_used(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_path = Path(temp_dir)
    for item in temp_path.iterdir():
        dest = output_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
            print(f"copied: {item.name}")
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
            print(f"copied folder: {item.name}")
    print(f"\nall files copied to: {output_dir}")
    return mod_name

def installer_run(archive_path=None, output_dir=None, temp_dir=None, gui=False, parent=None):
    try:
        temp_dir = find_mod_base_dir(Path(temp_dir))
        is_fomod = find_fomod_config(temp_dir)
        if is_fomod:
            mod_name = process_fomod(archive_path, temp_dir, output_dir, parent)
        else:
            mod_name = install_mod_files(archive_path, temp_dir, output_dir)
    except Exception as e:
        if gui:
            QMessageBox.warning(parent,
                        "Installation Error",
                        f"Encountered exception during mod installation! \n\nException:\n"+str(e))
        print("error: encountered exception: "+str(e)+" when installing mod, giving up")
        return None
    try: shutil.rmtree(temp_dir); print("removed tmp extract dir")
    except: print("warning: could not remove tmp extract dir")
    return mod_name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='install mods with FOMOD support',
        formatter_class=argparse.RawDescriptionHelpFormatter,)
    parser.add_argument('archive', 
                        help='Path to the mod archive (zip, 7z, or rar)')
    parser.add_argument('-o', '--output', 
                        help='Output directory (default: <archive_name>_installed in current directory)',
                        default=None)
    parser.add_argument('--gui', action='store_true',
                        help='Use GUI installer instead of CLI')
    args = parser.parse_args()
    if not os.path.exists(args.archive):
        print(f"error: Archive not found: {args.archive}")
    archive_path=args.archive

    # Get output directory
    archive_name = Path(args.archive)
    if args.output: output_dir = Path(args.output)
    else: output_dir = Path.cwd()

    installer_run(archive_path, output_dir, gui=args.gui)
