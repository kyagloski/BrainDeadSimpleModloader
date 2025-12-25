#!/usr/bin/python3

import os
import sys
import stat
import shutil
from datetime import datetime
from pathlib import Path

from utils import *

COMPACT_GAME_LIST = ["Fallout4",
                     "Skyrim",
                     "Skyrim Special Edition",
                     "Fallout3", 
                     "FalloutNV"]

GAME_PLUGINS = { "Fallout3" : "Anchorage.esm\nBrokenSteel.esm\nFallout3.esm\nPointLookout.esm\nThePitt.esm\nZeta.esm\n",
                 "FalloutNV": "FalloutNV.esm\nCaravanPack.esm\nClassicPack.esm\nDeadMoney.esm\nGunRunnersArsenal.esm\nHonestHearts.esm\nLonesomeRoad.esm\nMercenaryPack.esm\nOldWorldBlues.esm\nTribalPack.esm\n",
                 "Fallout4" : "",
                 "Skyrim"   : "",
                 "Default"  : ""}

PLUGINS_FILE = { "Fallout3" : "plugins.txt",
                 "FalloutNV": "plugins.txt",
                 "Fallout4" : "Plugins.txt",
                 "Skyrim"   : "Plugins.txt",
                 "Default"  : "Plugins.txt"}

VANILLA_LAUNCHERS = { "Fallout3" : "Fallout3Launcher.exe",
                      "FalloutNV": "FalloutNVLauncher.exe",
                      "Fallout4" : "Fallout4Launcher.exe",
                      "Skyrim"   : "SkyrimLauncher.exe",
                      "Default"  : ""}

SCRIPT_EXTENDERS  = { "Fallout3" : "fose_loader.exe",
                      "FalloutNV": "nvse_loader.exe",
                      "Fallout4" : "f4se_loader.exe",
                      "Skyrim"   : "skse_loader.exe",
                      "Default"  : ""}

INIS = { "Fallout3"  : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
         "FalloutNV" : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
         "Fallout4"  : ["Fallout4Custom.ini", "Fallout4.ini", "Fallout4Prefs.ini"],
         "Skyrim"    : ["SkyrimCustom.ini", "Skyrim.ini", "SkyrimPrefs.ini"],
         "Default"   : [] }

GAME_IDS = { "Fallout 3 goty"         : 22370,
             "Fallout 3"              : 22300,
             "Fallout New Vegas"      : 22380,
             "Fallout 4"              : 377160,
             "Skyrim Special Edition" : 489830,
             "Default"                : "" }


def determine_game(compat_dir):
    game=""
    if   "Fallout3"  in str(compat_dir): game="Fallout3"
    elif "FalloutNV" in str(compat_dir): game="FalloutNV"
    elif "Fallout4"  in str(compat_dir): game="Fallout4"
    elif "Skyrim"    in str(compat_dir): game="Skyrim"
    else: 
        print("error: cannot detect game name")
        game="Default"
    return game

def determine_game_id(target_dir):
    id=0
    print(target_dir)
    if   "Fallout 3 goty"    in str(target_dir): id=GAME_IDS["Fallout 3 goty"]
    elif "Fallout 3"         in str(target_dir): id=GAME_IDS["Fallout 3"]
    elif "Fallout New Vegas" in str(target_dir): id=GAME_IDS["Fallout New Vegas"]
    elif "Fallout 4"         in str(target_dir): id=GAME_IDS["Fallout 4"]
    elif "Skyrim Special Edition" in str(target_dir): id = GAME_IDS["Skyrim Special Edition"]
    else: print("error: cannot detect game id")
    return str(id)


def get_ini_path(compat_dir):
    game=determine_game(compat_dir)
    return Path(*compat_dir.parts[:compat_dir.parts.index("AppData")])/"Documents"/"My Games"/game
    

def infer_compat_path(target_dir):
    if os.name == "posix":
        game_id = determine_game_id(target_dir)  
        u_compat=target_dir.parent.parent.parent/"compatdata"/game_id/"pfx"/"drive_c"/"users"/"steamuser"/"AppData"/"Local"
        try: match = next((s for s in COMPACT_GAME_LIST if os.path.isdir(os.path.join(str(u_compat), s))), None).rstrip("/") + "/"
        except: print("error: cannot determine game"); return ""
        compat_dir = u_compat/match
    elif os.name == "nt":
        match = next((s for s in COMPACT_GAME_LIST if os.path.isdir(os.path.join(compat, s))), None).rstrip("/") + "/"
        compat_dir=Path("C:\\Users\\"+os.getlogin()+"\\AppData\\Local\\"+match)
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
    if sbin in lpath: force_symlink(tback/(lbin+"_original"),tback/lbin); print("switched to vanilla launcher!")
    elif lbin+"_original" in str(lpath): force_symlink(tback/sbin,tback/lbin); print("switched to script extender!")
    else: print("error: could not switch launchers")


def backup_ini(compat_dir, source_dir):
    game=determine_game(compat_dir)
    time=timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    back_dir=source_dir.parent/"inis"/time
    ini_dir=get_ini_path(compat_dir)
    os.makedirs(back_dir)
    for i in INIS[game]:
        try:
            f=Path(fix_path_case(str(ini_dir/i)))
            print(f)
            shutil.copy(f, back_dir)
        except:
            print("error: could find file "+i)
    if not os.listdir(back_dir):
        os.rmdir(back_dir)
        print("error: ini backup failed")
    else:
        print("successfully backed up inis to "+str(back_dir))


def restore_ini(compat_dir, source_dir):
    game=determine_game(compat_dir)
    ini_dir=get_ini_path(compat_dir)
    back_dir=source_dir.parent/"inis"
    backs=os.listdir(back_dir)
    prompt="please enter a backup version you want to restore from\n"+('\n'.join(f"{i+1}. {item}" for i, item in enumerate(backs)))+"\nversion number: "
    num=input(prompt)
    if not input("are you sure you want to restore from backup "+num+"? [y/N] ").lower().startswith('y'): return
    back_dir=back_dir/(backs[int(num)-1])
    files=[back_dir/i for i in os.listdir(back_dir)]
    try: [shutil.copy2(f, ini_dir) for f in files] 
    except: print("error: could not restore ini files"); return
    print("successfully restored inis from backup!")
