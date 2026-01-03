#!/usr/bin/python3

import os
import sys
import shutil
import argparse
import stat
import yaml
from pathlib import Path

from utils import * 
import installer
import game_specific

VERSION="v0.1"
LOCAL_DIR=Path(os.path.dirname(os.path.realpath(__file__)))
CONFIG_FILE=LOCAL_DIR/"config.yaml"
LOAD_ORDER=LOCAL_DIR/"load_order.txt"
BACKUP_DIR=LOCAL_DIR/"manifest"
COPY_MANIFEST=BACKUP_DIR/"copy_manifest.txt"
BACKUP_MANIFEST=BACKUP_DIR/"backup_manifest.txt"

SOURCE_DIR=LOCAL_DIR/"mods"
TARGET_DIR=LOCAL_DIR/"target"
COMPAT_DIR=TARGET_DIR/"compat"

RELOAD_ON_INSTALL=False

VERBOSITY=False


def create_cfg(gui=False, target=None):
    # prompt user choice
    if not gui:
        choice = input("currently no config file exists or is not configured\nwould you like to create one? [Y/n] ").strip().lower()
        if (not choice.startswith("y")) and (choice!=""): return
        target = input("enter absolute path to target dir: ").rstrip("/")+"/Data/"
        if not os.path.exists(target): print("error: invalid target dir: "+target); sys.exit()
    else: target=Path(target)
    compat = str(game_specific.infer_compat_path(Path(target)))
    if not os.path.exists(compat): print("error: could not infer comapt dir: "+compat); sys.exit()
    # write data
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write("# config file for braindead modloader\n")
        f.write("# mods directory\n")
        f.write("SOURCE_DIR: "+str(SOURCE_DIR)+"\n")
        f.write("# data directory (usually)\n")
        f.write("TARGET_DIR: "+str(target)+"\n")
        f.write("# ini/plugins.txt directory\n")
        f.write("COMPAT_DIR: "+str(compat)+"\n")
        f.write("# load order txt file\n")
        f.write("LOAD_ORDER: "+str(LOAD_ORDER)+"\n")
        f.write("# reload mods after installing new mod (or deleting) (boolean)\n")
        f.write("RELOAD_ON_INSTALL: True\n")
    print("created new config!")
    read_cfg()

    
def read_cfg():
    global SOURCE_DIR, TARGET_DIR, COMPAT_DIR, LOAD_ORDER, RELOAD_ON_INSTALL
    if not os.path.exists(CONFIG_FILE): create_cfg(); return
    with open("config.yaml", "r") as f: cfg_dict = yaml.safe_load(f)
    SOURCE_DIR=Path(cfg_dict["SOURCE_DIR"])
    TARGET_DIR=Path(cfg_dict["TARGET_DIR"])
    COMPAT_DIR=Path(cfg_dict["COMPAT_DIR"])
    LOAD_ORDER=Path(cfg_dict["LOAD_ORDER"])
    RELOAD_ON_INSTALL=bool(cfg_dict["RELOAD_ON_INSTALL"])
    sync_loadorder() # just in case


def load_list():
    if not os.path.exists(LOAD_ORDER):
        print("load order file not found, creating new load_order.txt")
        Path(LOAD_ORDER).touch()
    with open(LOAD_ORDER, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def copy_with_backup(src, dst, backup_dir, copied_manifest, backedup_manifest, target_root):
    filename = os.path.basename(src)
    rel_dir = os.path.relpath(dst, target_root)
    rel_path = os.path.join(rel_dir, filename) if rel_dir != "." else filename
    dst_path = os.path.join(dst, filename)
    # backup ONLY if:
    # 1. the file exists
    # 2. the file was NOT already copied from a source directory earlier
    if os.path.exists(dst_path) and (rel_path not in copied_manifest):
        backup_path = os.path.join(backup_dir, rel_path)
        if VERBOSITY: print("backing up: "+rel_path) # status
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if not os.path.exists(backup_path):
            shutil.move(dst_path, backup_path)
            backedup_manifest.append(rel_path)
    # copy incoming file
    #shutil.copy2(src, dst_path) # TODO: provide option for hardlink/copying
    force_symlink(src, dst_path)
    # record that this file is now sourced
    copied_manifest.append(rel_path)


def perform_copy():
    ensure_dir(SOURCE_DIR)
    ensure_dir(TARGET_DIR)
    ensure_dir(BACKUP_DIR)

    load_order = load_list()

    if (os.path.exists(COPY_MANIFEST) \
    or os.path.exists(BACKUP_MANIFEST)) \
    and RELOAD_ON_INSTALL: restore()

    copied_manifest = []
    backedup_manifest = []
    plugins = []
    # read manifests
    if os.path.exists(COPY_MANIFEST):
        with open(COPY_MANIFEST, "r", encoding="utf-8") as f:
            copied_manifest = [line.strip() for line in f if line.strip()]
    if os.path.exists(BACKUP_MANIFEST):
        with open(BACKUP_MANIFEST, "r", encoding="utf-8") as f:
            backedup_manifest = [line.strip() for line in f if line.strip()]

    # clean all symlinks (if install broke) (maybe risky idk)
    remove_symlink_rec(TARGET_DIR)

    for dirname in load_order:
        if dirname.startswith('*') \
        or dirname.startswith('#') \
        or dirname.startswith('~'): # skip mods
            continue
        source_path = os.path.join(SOURCE_DIR, dirname)
        if not os.path.isdir(source_path):
            print("warning, source directory does not exist: "+source_path)
            continue

        # copy files AND subdirectories recursively
        for root, dirs, files in os.walk(source_path):
            # calculate relative path within the source directory
            rel = os.path.relpath(root, source_path)
            #if rel.startswith("Data"): rel = rel.replace("Data/","",1) # might be broken
            dest_root = os.path.join(TARGET_DIR, rel) if rel != "." else TARGET_DIR

            # ensure destination subdirectory exists
            if (dest_root != TARGET_DIR) \
            and (not os.path.isdir(dest_root)): 
                dest_dir=dest_root.replace(str(TARGET_DIR),'')
                copied_manifest.append(dest_dir) # add empty dirs
            dest_root=fix_path_case(dest_root)
            os.makedirs(dest_root, exist_ok=True)

            # copy all files
            for file in files:
                if VERBOSITY: print("linking: "+file) # status
                if file.endswith('.esm') \
                or file.endswith('.esl') \
                or file.endswith('.esp'):
                    plugins.append(file)
                src_file = os.path.join(root, file)
                copy_with_backup(
                    src_file, dest_root, BACKUP_DIR,
                    copied_manifest, backedup_manifest,
                    TARGET_DIR
                )
    # only get latest copies
    copied_manifest = list(dict.fromkeys(copied_manifest))
    # save manifests
    with open(COPY_MANIFEST, "w", encoding="utf-8") as f:
        for name in copied_manifest:
            f.write(name + "\n")
    with open(BACKUP_MANIFEST, "w", encoding="utf-8") as f:
        for name in backedup_manifest:
            f.write(name + "\n")
    # write plugins
    game_specific.write_plugins(COMPAT_DIR, BACKUP_DIR, plugins)
     
    print('-'*40)
    print("load complete!")
    print("backed up files: "+str(len(backedup_manifest)))
    print("linked new files: "+str(len(copied_manifest)))


def restore():
    if not os.path.exists(COPY_MANIFEST) \
    or not os.path.exists(BACKUP_MANIFEST):
        print("no manifests found, nothing to restore.")
        return
    # load manifests
    with open(COPY_MANIFEST, "r", encoding="utf-8") as f:
        copied_files = [line.strip() for line in f if line.strip()]
    with open(BACKUP_MANIFEST, "r", encoding="utf-8") as f:
        backedup_files = [line.strip() for line in f if line.strip()]
    # remove copied files
    for filename in copied_files:
        path = os.path.join(TARGET_DIR, filename)
        if not os.path.exists(path): continue
        if VERBOSITY: print("unlinking: "+path) # status
        if os.path.isdir(path): shutil.rmtree(path)
        else: os.remove(path)
    # restore originals
    for filename in backedup_files:
        backup_path = os.path.join(BACKUP_DIR, filename)
        target_path = os.path.join(TARGET_DIR, filename)
        if os.path.exists(BACKUP_DIR):
            if VERBOSITY: print("restoring: "+target_path) # status
            shutil.move(backup_path, target_path)
    # remove manifests
    os.remove(COPY_MANIFEST)
    os.remove(BACKUP_MANIFEST)
    # clean all symlinks (if install broke) (maybe risky idk)
    remove_symlink_rec(TARGET_DIR)
    if os.path.exists(BACKUP_DIR / Path("plugins.txt")): os.unlink(BACKUP_DIR / Path("plugins.txt"))
    if os.path.exists(BACKUP_DIR / Path("Plugins.txt")): os.unlink(BACKUP_DIR / Path("Plugins.txt"))
    
    print('-'*40)
    print("unload complete!")


def save_to_loadorder(mods):
    # save list of mods to load order
    with open(LOAD_ORDER, "w") as f:
        for mod in mods: f.write(mod+'\n')
    print("wrote to "+str(LOAD_ORDER))


def sync_loadorder():
    # this is in case user does something shifty with their files
    # in between sessions (hehehe)
    loadorder=load_list()
    clean_loadorder=[s.lstrip('~*') for s in loadorder]
    additions  = []
    exclusions = []
    for mod in os.listdir(SOURCE_DIR):
        if mod not in clean_loadorder: additions.append('~'+mod)
    for mod in loadorder:
        if any(mod.startswith(sub) for sub in ['~','*','#']): continue
        if mod not in os.listdir(SOURCE_DIR): exclusions.append(mod)
    loadorder = [x for x in loadorder if x not in exclusions] # remove exclusions
    loadorder = [item for i, item in enumerate(loadorder) if item.startswith('#') or item not in loadorder[:i]]
    save_to_loadorder(loadorder+additions)


def install_mod(mod_path, gui=False, parent=None):  
    name = installer.run(mod_path, SOURCE_DIR, gui, parent)
    if not name: return None
    with open(LOAD_ORDER, "a", encoding="utf-8") as f:
        f.write(name+'\n')
    if RELOAD_ON_INSTALL: perform_copy() #restore(); perform_copy()
    print("wrote mod: "+name+" to load order!")
    return name


def delete_mod(mod_name, gui=False):
    # TODO: apply this to all load order presets (when that is supported)
    matches = [mod for mod in load_list() if mod_name.lower() in mod.lower()]
    if matches==[]: print("error: could not find mod "+mod_name); return
    mod = matches[0].lstrip('*~#')
    if not gui: 
        prompt="are you sure you want to remove mod "+mod+" [y/N] "
        if 'y' not in input(prompt): return
    # remove from load order 
    with open(LOAD_ORDER, "r") as f: lines = f.readlines()
    with open(LOAD_ORDER, "w") as f:
        for line in lines:
            if line.strip() != mod: f.write(line)
    # delete dir
    try: shutil.rmtree(SOURCE_DIR/mod)
    except: print("error: could not delete mod or mod does not exist in "+str(SOURCE_DIR))
    if RELOAD_ON_INSTALL: perform_copy() #restore(); perform_copy()
    print("deleted mod "+mod+"!")


def rename_mod(old_name, new_name):
    # TODO: apply this to all load order presets (when that is supported)
    odir = Path(old_name)
    ndir = Path(new_name)
    if os.path.exists(Path(SOURCE_DIR) / old_name): 
        os.rename(Path(SOURCE_DIR) / old_name, Path(SOURCE_DIR) / new_name)
    else: print("error: cannot find mod dir "+str(Path(SOURCE_DIR) / old_name)); return
    loadorder = Path(LOAD_ORDER)
    llist = [line.strip().lstrip('*~#') for line in loadorder.read_text(encoding="utf-8").splitlines()]
    llist[llist.index(old_name)] = new_name
    loadorder.write_text("\n".join(llist), encoding="utf-8")
    print("successfully renamed mod "+old_name+" to "+new_name)


def main():
    parser = argparse.ArgumentParser(description="mod your bethesda games with ease")
    parser.add_argument("-l", "--load", action="store_true", help="perform load/copy operation")
    parser.add_argument("-u", "--unload", action="store_true", help="restore original state")
    parser.add_argument("-r", "--reload", action="store_true", help="reload mods from load order")
    parser.add_argument("--rename", nargs=2, metavar=("CUR_NAME", "NEW_NAME"), help="rename mod [CUR_NAME NEW_NAME]")
    parser.add_argument("--switch-launcher", action="store_true", help="switch between script extender and vanilla launcher")
    parser.add_argument("--backup-ini", action="store_true", help="create a backup of ini files")
    parser.add_argument("--restore-ini", action="store_true", help="restore ini files from backup")
    parser.add_argument("-i", "--install", help="install a mod") 
    parser.add_argument("-d", "--delete", help="delete a mod")
    args = parser.parse_args()

    if len(sys.argv)>1: read_cfg() 

    if args.load: perform_copy()
    elif args.unload: restore()
    elif args.reload: restore(); perform_copy()
    elif args.install: install_mod(args.install) # TODO: handle mutliple
    elif args.delete: delete_mod(args.delete) # TODO: handle multiple
    elif args.rename: rename_mod(*tuple(args.rename))
    elif args.switch_launcher: game_specific.switch_launcher(COMPAT_DIR, TARGET_DIR) 
    elif args.backup_ini: game_specific.backup_ini(COMPAT_DIR, SOURCE_DIR)
    elif args.restore_ini: game_specific.restore_ini(COMPAT_DIR, SOURCE_DIR)
    else: 
        os.system("python '"+str(LOCAL_DIR / Path("gui.py"))+"'")

if __name__ == "__main__":
    main()
