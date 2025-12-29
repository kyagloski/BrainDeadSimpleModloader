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

from utils import * 

try:
    import rarfile
    HAS_RAR = True
except ImportError:
    HAS_RAR = False


def extract_archive(archive_path, extract_to):
    """Extract zip, 7z, or rar archive."""
    archive_path = Path(archive_path)
    ext = archive_path.suffix.lower()
    print(f"Extracting {archive_path.name}...")
    if ext == '.zip':
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
    elif ext == '.7z':
        try:
            result = subprocess.run(['7z', 'x', str(archive_path), f'-o{extract_to}', '-y'], capture_output=True, text=True)
            if result.returncode == 0: print("Extraction complete!"); return
            else: print(f"7z command failed: {result.stderr}")
        except FileNotFounderror: pass
        print("error: Could not extract 7z file. Install py7zr (pip install py7zr) or 7z command line tool")
        return
    elif ext == '.rar':
        # Try rarfile first
        if HAS_RAR:
            try:
                with rarfile.RarFile(archive_path, 'r') as rar_ref:
                    rar_ref.extractall(extract_to)
                print("Extraction complete!")
                return
            except Exception as e:
                print(f"rarfile failed ({e}), trying system unrar command...")
        # Try system unrar command as fallback
        try:
            result = subprocess.run(['unrar', 'x', '-y', str(archive_path), str(extract_to)],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                print("Extraction complete!")
                return
            else: print(f"unrar command failed: {result.stderr}")
        except FileNotFoundError: pass
        print("error: Could not extract rar file. Install rarfile (pip install rarfile) or unrar command line tool")
        return
    else:
        print("error: Unsupported archive format for "+str(archive_path))
        return
    print("Extraction complete!")


def find_fomod_config(extract_dir):
    """Find ModuleConfig.xml case-insensitively."""
    # Common locations
    common_paths = [
        'fomod/ModuleConfig.xml',
        'ModuleConfig.xml',
        'fomod/info.xml',
        'info.xml'
    ]
    extract_path = Path(extract_dir)
    for path in common_paths:
        full_path = Path(fix_path_case(extract_path / path))
        if full_path.exists():
            print(f"found FOMOD config at: {full_path}")
            return full_path
    
    return None


def find_mod_base_dir(mod_path):
    mod_path = Path(mod_path)
    data_indicators = [
        '.esp', '.esm', '.esl', '.bsa', '.ba2',
        'meshes', 'textures', 'scripts', 'sounds',
        'interface', 'music', 'video', 'strings',
        'skse', 'fose', 'f4se', 'nvse', 'seq',
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


def parse_fomod(xml_path):
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
            except (UnicodeDecodeerror, ET.Parseerror, Lookuperror) as e:
                last_error = e
                continue
        # if all encodings fail, show the error
        print(f"Failed to parse XML. Last error: {last_error}")
        print(f"\nFirst 200 chars of file (raw):")
        print(raw_content[:200])
        raise Exception("Could not parse XML with any supported encoding")
    except ET.Parseerror as e:
        print(f"error parsing XML: {e}")
        return #sys.exit(1)
    except Exception as e:
        print(f"Unexpected error reading XML: {e}")
        return #sys.exit(1)


def get_text(element, default=''):
    """Safely get text from element."""
    return element.text.strip() if element is not None and element.text else default


def process_fomod(fomod_path, extract_dir, output_dir):
    """Process FOMOD configuration and guide user through installation."""
    root, namespace = parse_fomod(fomod_path)
    ns = {'': namespace.strip('{}')} if namespace else {}
    
    # Get module name
    mod_name_elem = root.find('.//moduleName', ns) if ns else root.find('.//moduleName')
    mod_name = get_text(mod_name_elem, 'Unknown Mod')
    
    print(f"\n{'='*60}")
    print(f"Installing: {mod_name}")
    print(f"{'='*60}\n")
    
    # Track conditional flags
    condition_flags = {}
   
    # Process required install files first
    required_files = []
    required_elem = root.find('.//requiredInstallFiles', ns) if ns else root.find('.//requiredInstallFiles')
    if required_elem is not None:
        print("\n--- Required Files ---")
        print("The following files will be installed automatically:\n")
        required_files = extract_files_info(required_elem, ns)
        for file_info in required_files:
            # Handle both tuple (source, dest, priority) and dict formats
            if isinstance(file_info, tuple):
                source, dest = file_info[0], file_info[1]
            else:
                source = file_info.get('source', '')
                dest = file_info.get('destination', '')
            print(f"  • {source} → {dest}")
        print() 
 
    # Find install steps
    install_steps = root.find('.//installSteps', ns) if ns else root.find('.//installSteps')
    if install_steps is None:
        print("No installation steps found in FOMOD.")
        return []
    
    selected_files = []
    
    # Process each install step
    for step in install_steps.findall('.//installStep', ns) if ns else install_steps.findall('.//installStep'):
        step_name = step.get('name', 'Installation Step')
        
        # Check if step has visibility conditions
        visible_elem = step.find('.//visible', ns) if ns else step.find('.//visible')
        if visible_elem is not None and not evaluate_conditions(visible_elem, condition_flags, ns):
            continue
        
        print(f"\n--- {step_name} ---\n")
        
        # Process optional file groups
        groups = step.find('.//optionalFileGroups', ns) if ns else step.find('.//optionalFileGroups')
        if groups is None:
            continue
        
        for group in groups.findall('.//group', ns) if ns else groups.findall('.//group'):
            group_name = group.get('name', 'Options')
            group_type = group.get('type', 'SelectAny')
            
            print('\n'*8+f"\n\033[92m{group_name}\033[0m")
            print(f"Selection Type: {group_type}")
            print("-" * 60)
            
            plugins_elem = group.find('.//plugins', ns) if ns else group.find('.//plugins')
            if plugins_elem is None:
                continue
            
            plugin_list = plugins_elem.findall('.//plugin', ns) if ns else plugins_elem.findall('.//plugin')
            
            # Filter plugins by visibility conditions
            visible_plugins = []
            for plugin in plugin_list:
                visible_elem = plugin.find('.//visible', ns) if ns else plugin.find('.//visible')
                if visible_elem is None or evaluate_conditions(visible_elem, condition_flags, ns):
                    visible_plugins.append(plugin)
            
            if not visible_plugins:
                print("No available options for this group.")
                continue
            
            # Display options
            for idx, plugin in enumerate(visible_plugins, 1):
                plugin_name = plugin.get('name', f'Option {idx}')
                desc_elem = plugin.find('.//description', ns) if ns else plugin.find('.//description')
                description = get_text(desc_elem, 'No description')
                
                print(f"\n\033[96m{idx}. {plugin_name}\033[0m")
                print(f"   {description}")
            
            # Get user selection
            print()
            selected = get_user_selection(len(visible_plugins), group_type)
            
            # Add selected files and update flags
            for selection in selected:
                plugin = visible_plugins[selection - 1]
                
                # Update condition flags
                flags_elem = plugin.find('.//conditionFlags', ns) if ns else plugin.find('.//conditionFlags')
                if flags_elem is not None:
                    for flag in flags_elem.findall('.//flag', ns) if ns else flags_elem.findall('.//flag'):
                        flag_name = flag.get('name', '')
                        flag_value = get_text(flag, 'On')
                        if flag_name:
                            condition_flags[flag_name] = flag_value
                            print(f"  [Set flag: {flag_name} = {flag_value}]")
                
                # Add files
                files_elem = plugin.find('.//files', ns) if ns else plugin.find('.//files')
                if files_elem is not None:
                    selected_files.extend(extract_files_info(files_elem, ns))
   
    # Combine required and selected files
    all_files = required_files + selected_files
    # Install selected files
    install_fomod_files(all_files, extract_dir, output_dir)
    return selected_files


def evaluate_conditions(visible_elem, condition_flags, ns):
    """Evaluate visibility conditions based on current flags."""
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
        actual_value = condition_flags.get(flag_name, 'Off')
        results.append(actual_value == expected_value)
    # Apply operator
    if operator == 'And':  return all(results)
    elif operator == 'Or': return any(results)
    else: return all(results)  # Default to And


def get_user_selection(num_options, selection_type):
    """Get user selection based on group type."""
    while True:
        if selection_type == 'SelectExactlyOne':
            prompt = f"Select one option (1-{num_options}): "
            try:
                choice = int(input('\033[1m'+prompt+'\033[0m'))
                if 1 <= choice <= num_options:
                    return [choice]
                print(f"Please enter a number between 1 and {num_options}")
            except Valueerror:
                print("Please enter a valid number")
        elif selection_type == 'SelectAtMostOne':
            prompt = f"Select one option (1-{num_options}) or 0 to skip: "
            try:
                choice = int(input('\033[1m'+prompt+'\033[0m'))
                if choice == 0:
                    return []
                if 1 <= choice <= num_options:
                    return [choice]
                print(f"Please enter a number between 0 and {num_options}")
            except Valueerror:
                print("Please enter a valid number")
        
        elif selection_type == 'SelectAtLeastOne':
            prompt = f"Select options (comma-separated, 1-{num_options}): "
            try:
                choices = [int(x.strip()) for x in input('\033[1m'+prompt+'\033[0m').split(',')]
                if all(1 <= c <= num_options for c in choices) and len(choices) > 0:
                    return choices
                print(f"Please enter valid numbers between 1 and {num_options}")
            except Valueerror:
                print("Please enter valid numbers separated by commas")
        
        else:  # SelectAny or other
            prompt = f"Select options (comma-separated, 1-{num_options}) or 0 to skip: "
            try:
                user_input = input('\033[1m'+prompt+'\033[0m').strip()
                if user_input == '0':
                    return []
                choices = [int(x.strip()) for x in user_input.split(',')]
                if all(1 <= c <= num_options for c in choices):
                    return choices
                print(f"Please enter valid numbers between 1 and {num_options}")
            except Valueerror:
                print("Please enter valid numbers separated by commas")


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
        if source and destination:
            file_list.append(('folder', source, destination))
    
    return file_list


def install_fomod_files(file_list, extract_dir, output_dir):
    """Copy selected files to output directory."""
    extract_path = Path(extract_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("\n" + "="*80)
    print("Installing files...")
    print("="*80 + "\n")
    
    for file_type, source, destination in file_list:
        # Try to find source case-insensitively
        source_parts = source.replace('\\', '/').split('/')
        current_path = extract_path
        
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
            dest_path = output_path / destination
            if file_type == 'file' and current_path.is_file():
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current_path, dest_path)
                print(f"installed: {current_path} to {destination}")
            elif file_type == 'folder' and current_path.is_dir():
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.copytree(current_path, dest_path)
                print(f"installed folder: {current_path} to {destination}")
    print(f"\ninstallation complete! files installed to: {output_path}")


def install_mod_files(temp_dir, output_dir):
    print("copying files from non-FOMOD archive...")
    # Copy everything from temp to output
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


def run(archive_path=None, output_dir=None):
    archive_name = Path(archive_path).stem
    output_dir = Path(output_dir) / f"{archive_name}"
    
    # handle dups
    output_dir = next(
        p for i in range(10**9)
        if not (p := Path(output_dir).parent / f"{archive_name}{'' if i == 0 else f'_{i}'}").exists())
    archive_name = Path(output_dir).stem # reassign in case of change

    # Create temporary directory for extraction
    try:
        temp_dir = Path(tempfile.mkdtemp())
        extract_archive(archive_path, temp_dir)
        temp_dir = find_mod_base_dir(Path(temp_dir))
        config_path = find_fomod_config(temp_dir)
        if config_path: res=process_fomod(config_path, temp_dir, output_dir)
        if not config_path or not res: install_mod_files(temp_dir, output_dir)
    except Exception as e:
        print("error: encoutered exception: "+str(e)+" when installing mod, giving up")
        return None
    return archive_name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='install Bethesda mods with FOMOD support',
        formatter_class=argparse.RawDescriptionHelpFormatter,)
    parser.add_argument('archive', 
                        help='Path to the mod archive (zip, 7z, or rar)')
    parser.add_argument('-o', '--output', 
                        help='Output directory (default: <archive_name>_installed in current directory)',
                        default=None)
    args = parser.parse_args()
    if not os.path.exists(args.archive):
        print(f"error: Archive not found: {args.archive}")
    archive_path=args.archive

    # Get output directory
    archive_name = Path(args.archive)
    if args.output: output_dir = Path(args.output)
    else: output_dir = Path.cwd()

    run(archive_path, output_dir)
