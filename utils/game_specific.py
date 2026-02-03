#!/usr/bin/python3

import os
import sys
import stat
import shutil
import yaml
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

try:    from utils.utils import *
except: from utils import * 

# preloaded plugins required in plugins.txt file
GAME_PLUGINS      = { "Fallout3" : "Anchorage.esm\nBrokenSteel.esm\nFallout3.esm\nPointLookout.esm\nThePitt.esm\nZeta.esm\n",
                      "FalloutNV": "FalloutNV.esm\nCaravanPack.esm\nClassicPack.esm\nDeadMoney.esm\nGunRunnersArsenal.esm\nHonestHearts.esm\nLonesomeRoad.esm\nMercenaryPack.esm\nOldWorldBlues.esm\nTribalPack.esm\n",
                      "Fallout4" : "",
                      "Skyrim Special Edition" : "",
                      "Default"  : ""}
# file names for plugins.txt
PLUGINS_FILE      = { "Fallout3" : "plugins.txt",
                      "FalloutNV": "plugins.txt",
                      "Fallout4" : "Plugins.txt",
                      "Skyrim Special Edition"   : "Plugins.txt",
                      "Default"  : "Plugins.txt"}
# vanilla game launcher executables
VANILLA_LAUNCHERS = { "Fallout3" : "Fallout3Launcher.exe",
                      "FalloutNV": "FalloutNVLauncher.exe",
                      "Fallout4" : "Fallout4Launcher.exe",
                      "Skyrim Special Edition" : "SkyrimSELauncher.exe",
                      "Default"  : ""}
# vanilla game executables
VANILLA_GAMES     = { "Fallout3" : "Fallout3.exe",
                      "FalloutNV": "FalloutNV.exe",
                      "Fallout4" : "Fallout4.exe",
                      "Skyrim Special Edition" : "SkyrimSE.exe",
                      "Default"  : ""}
# script extender executables
SCRIPT_EXTENDERS  = { "Fallout3" : "fose_loader.exe",
                      "FalloutNV": "nvse_loader.exe",
                      "Fallout4" : "f4se_loader.exe",
                      "Skyrim Special Edition" : "skse64_loader.exe",
                      "Default"  : ""}
# file names for ini configs
INIS              = { "Fallout3"  : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
                      "FalloutNV" : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
                      "Fallout4"  : ["Fallout4Custom.ini", "Fallout4.ini", "Fallout4Prefs.ini"],
                      "Skyrim Special Edition" : ["SkyrimCustom.ini", "Skyrim.ini", "SkyrimPrefs.ini"],
                      "Default"   : ["Fallout.ini", "FalloutPrefs.ini"] } # testing
# steam game ids
GAME_IDS          = { "Fallout 3 goty"         : 22370,
                      "Fallout 3"              : 22300,
                      "Fallout New Vegas"      : 22380,
                      "Fallout 4"              : 377160,
                      "Skyrim Special Edition" : 489830,
                      "Skyrim VR"              : "", # TODO: add support for ALL beth game 
                      "Default"                : "" }
# AppData directory names
GAME_COMPAT       = { "Fallout 3 goty"    : "Fallout3",
                      "Fallout 3"         : "Fallout3",
                      "Fallout New Vegas" : "FalloutNV",
                      "Fallout 4"         : "Fallout4",
                      "Skyrim VR"         : "", # TODO: add support for ALL beth game 
                      "Skyrim Special Edition" : "Skyrim Special Edition",
                      "Default"           : ""}


def determine_game(compat_dir):
    game=""
    if   "Fallout3"  in str(compat_dir): game="Fallout3"
    elif "FalloutNV" in str(compat_dir): game="FalloutNV"
    elif "Fallout4"  in str(compat_dir): game="Fallout4"
    elif "Skyrim" in str(compat_dir): game="Skyrim Special Edition"
    else: 
        print("error: cannot detect game name from compat dir: "+compat_dir)
        game="Default"
    return game

def determine_game_id(target_dir):
    id=0
    if   "Fallout 3 goty"    in str(target_dir): id=GAME_IDS["Fallout 3 goty"]
    elif "Fallout 3"         in str(target_dir): id=GAME_IDS["Fallout 3"]
    elif "Fallout New Vegas" in str(target_dir): id=GAME_IDS["Fallout New Vegas"]
    elif "Fallout 4"         in str(target_dir): id=GAME_IDS["Fallout 4"]
    elif "Skyrim" in str(target_dir): id = GAME_IDS["Skyrim Special Edition"]
    else: print("error: cannot detect game id")
    return str(id)


def get_ini_path(compat_dir):
    game=determine_game(compat_dir)
    return Path(*compat_dir.parts[:compat_dir.parts.index("AppData")])/"Documents"/"My Games"/game
    

def infer_compat_path(target_dir, verbose=False):
    if os.name == "posix":
        game_id = determine_game_id(target_dir)
        game=GAME_COMPAT[Path(target_dir).parent.name]
        u_compat=target_dir.parent.parent.parent/"compatdata"/game_id/"pfx"/"drive_c"/"users"/"steamuser"/"AppData"/"Local"
        compat_dir = u_compat/game
    elif os.name == "nt":
        game=GAME_COMPAT[Path(target_dir).parent.name]
        compat_dir=Path("C:\\Users\\"+os.getlogin()+"\\AppData\\Local\\")/game
    return compat_dir
        
    
def write_plugins(compat_dir, backup_dir, plugins):
    game=determine_game(compat_dir)
    pfile=Path(PLUGINS_FILE[game])
    defps=GAME_PLUGINS[game]
    with open(compat_dir/pfile, "w", encoding="utf-8") as f:
        f.write("# This file is used by "+game+" to keep track of your downloaded content.\n")
        f.write("# Please do not modify this file.\n")
        f.write(defps)
        for name in plugins:
            if game in ["Fallout4","Skyrim"]: name='*'+name
            f.write(name + "\n")
    #os.chmod(compat_dir / pfile, stat.S_IREAD)
    force_symlink(compat_dir/pfile, backup_dir/pfile)


def switch_launcher(compat_dir, target_dir):
    game=determine_game(compat_dir)
    lbin=VANILLA_LAUNCHERS[game]
    sbin=SCRIPT_EXTENDERS[game]
    tback=target_dir.parent
    if sbin not in os.listdir(tback): print("error: could not find script extender binary"); return
    if not lbin+"_original" in os.listdir(tback): # fresh setup
        os.rename(tback/lbin, tback/(lbin+"_original"))
        try: # utility symlinks for plugin and ini dirs
            force_symlink(compat_dir, tback/"compatdata_plugins")
            force_symlink(get_ini_path(compat_dir), tback/"compatdata_ini")
        except: pass
    try: lpath=os.readlink(tback/lbin)
    except: lpath=tback/(lbin+"_original")
    if str(sbin) in str(lpath): force_symlink(tback/(lbin+"_original"),tback/lbin); print("switched to vanilla launcher!")
    elif lbin+"_original" in str(lpath): force_symlink(tback/sbin,tback/lbin); print("switched to script extender!")
    else: print("error: could not switch launchers")


def set_launcher(compat_dir, target_dir, launcher):
    game=determine_game(compat_dir)
    van_bin=VANILLA_LAUNCHERS[game]
    bin_dir=Path(target_dir).parent
    first=False
    # backup original binary
    if not van_bin+"_original" in os.listdir(bin_dir): # fresh setup
        first=True
        os.rename(bin_dir/van_bin, bin_dir/(van_bin+"_original"))
        LOCAL_DIR=Path(os.path.dirname(os.path.realpath(__file__))).parent
        CONFIG_FILE=LOCAL_DIR/"config.yaml"
        with open(CONFIG_FILE, "r") as f: cfg = OrderedDict(yaml.safe_load(f))
        #cfg=read_cfg(sync=False)
        cfg["EXECUTABLES"][van_bin.rstrip(".exe")]["PATH"]=cfg["EXECUTABLES"][van_bin.rstrip(".exe")]["PATH"]+"_original"
        #write_cfg(cfg)
        with open(CONFIG_FILE, "w") as f: yaml.dump(dict(cfg),f,sort_keys=False,default_flow_style=False)
        try: # utility symlinks for plugin and ini dirs
            force_symlink(compat_dir, bin_dir/"compatdata_plugins")
            force_symlink(get_ini_path(compat_dir), bin_dir/"compatdata_ini")
        except: pass
    # link binary
    force_symlink(launcher,bin_dir/van_bin)
    return first,van_bin


def backup_ini(compat_dir, back_dir):
    game=determine_game(compat_dir)
    time=timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try: ini_dir=get_ini_path(compat_dir)
    except: ini_dir=back_dir/os.listdir(back_dir)[0] # testing
    back_dir=back_dir/time
    ensure_dir(back_dir)
    for i in INIS[game]:
        try:
            if os.name=="posix": f=Path(fix_path_case(str(ini_dir/i)))
            else: f=Path(str(ini_dir/i))
            shutil.copy(f, back_dir)
        except:
            print("error: could find file "+i)
    if not os.listdir(back_dir):
        os.rmdir(back_dir)
        print("error: ini backup failed")
        return False
    else:
        print("successfully backed up inis to "+str(back_dir))
        return True


def restore_ini(compat_dir, back_dir, ui=False):
    game=determine_game(compat_dir)
    try: ini_dir=get_ini_path(compat_dir)
    except: ini_dir=back_dir.parent/os.listdir(back_dir.parent)[0] # testing
    if not ui:
        backs=os.listdir(back_dir)
        prompt="please enter a backup version you want to restore from\n"+('\n'.join(f"{i+1}. {item}" for i, item in enumerate(backs)))+"\nversion number: "
        num=input(prompt)
        if not input("are you sure you want to restore from backup "+num+"? [y/N] ").lower().startswith('y'): return
        back_dir=back_dir/(backs[int(num)-1])
    files=[back_dir/i for i in os.listdir(back_dir)]
    try: [shutil.copy2(f, ini_dir) for f in files] 
    except Exception as e: 
        print("error: could not restore ini files, "+str(e)); 
        return False,str(e)
    print("successfully restored inis from backup!")
    return True,None

def get_launchers(target_dir,compat_dir):
    game=determine_game(compat_dir)
    game_dir=Path(target_dir).parent
    launcher_exe=game_dir/VANILLA_LAUNCHERS[game]
    game_exe=game_dir/VANILLA_GAMES[game]
    se_exe=game_dir/SCRIPT_EXTENDERS[game]
    exes=[launcher_exe,game_exe,se_exe]
    launchers=dict()
    if game=="Default": return {"Default":{"PATH":"\"\"","PARAMS":""}}
    for exe in exes:
        if os.path.exists(exe):
            title=str(exe.name).replace(".exe",'')
            launchers[title]=dict()
            launchers[title]["PATH"]=str(exe)
            launchers[title]["PARAMS"]=""
    return launchers
