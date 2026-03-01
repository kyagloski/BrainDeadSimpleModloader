#!/usr/bin/python3

import os
import re
import sys
import stat
import shutil
import yaml
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

try:    from utils.utils import *
except: from utils import * 

#LOCAL_DIR         = Path(os.path.dirname(os.path.realpath(__file__)))

# preloaded plugins required in plugins.txt file
GAME_PLUGINS      = { "Fallout3"               : "Anchorage.esm\nBrokenSteel.esm\nFallout3.esm\nPointLookout.esm\nThePitt.esm\nZeta.esm\n",
                      "FalloutNV"              : "FalloutNV.esm\nDeadMoney.esm\nHonestHearts.esm\nOldWorldBlues.esm\nLonesomeRoad.esm\nGunRunnersArsenal.esm\nTribalPack.esm\nClassicPack.esm\nMercenaryPack.esm\nCaravanPack.esm\n",
                      "Fallout4"               : "",
                      "Fallout4VR"             : "",
                      "Oblivion"               : "DLCHorseArmor.esp\nDLCMehrunesRazor.esp\nKnights.esp\nDLCShiveringIsles.esp\nDLCVileLair.esp\nDLCFrostcrag.esp\nDLCBattlehornCastle.esp\nDLCSpellTomes.esp\nDLCThievesDen.esp\n",
                      "Skyrim"                 : "Dawnguard.esm\nDragonborn.esm\nHearthFires.esm\nHighResTexturePack01.esp\nHighResTexturePack02.esp\nHighResTexturePack03.esp\n",
                      "Skyrim Special Edition" : "",
                      "Skyrim VR"              : "",
                      "Default"                : "" }
# file names for plugins.txt (experiences issues with this file capitalization)
PLUGINS_FILE      = { "Fallout3"               : "plugins.txt",
                      "FalloutNV"              : "plugins.txt",
                      "Fallout4"               : "Plugins.txt",
                      "Fallout4VR"             : "Plugins.txt",
                      "Oblivion"               : "Plugins.txt",
                      "Skyrim"                 : "plugins.txt",
                      "Skyrim Special Edition" : "Plugins.txt",
                      "Skyrim VR"              : "Plugins.txt",
                      "Default"                : "Plugins.txt" }
# vanilla game launcher executables
VANILLA_LAUNCHERS = { "Fallout3"               : "Fallout3Launcher.exe",
                      "FalloutNV"              : "FalloutNVLauncher.exe",
                      "Fallout4"               : "Fallout4Launcher.exe",
                      "Fallout4VR"             : "",
                      "Oblivion"               : "OblivionLauncher.exe",
                      "Skyrim"                 : "SkyrimLauncher.exe",
                      "Skyrim Special Edition" : "SkyrimSELauncher.exe",
                      "Skyrim VR"              : "",
                      "Default"                : "" }
# vanilla game executables
VANILLA_GAMES     = { "Fallout3"               : "Fallout3.exe",
                      "FalloutNV"              : "FalloutNV.exe",
                      "Fallout4"               : "Fallout4.exe",
                      "Fallout4VR"             : "Fallout4VR.exe",
                      "Oblivion"               : "Oblivion.exe",
                      "Skyrim"                 : "TESV.exe",
                      "Skyrim Special Edition" : "SkyrimSE.exe",
                      "Skyrim VR"              : "SkyrimVR.exe",
                      "Default"                : "" }
# script extender executables
SCRIPT_EXTENDERS  = { "Fallout3"               : "fose_loader.exe",
                      "FalloutNV"              : "nvse_loader.exe",
                      "Fallout4"               : "f4se_loader.exe",
                      "Fallout4VR"             : "f4sevr_loader.exe",
                      "Oblivion"               : "obse_loader.exe",
                      "Skyrim"                 : "skse_loader.exe",
                      "Skyrim Special Edition" : "skse64_loader.exe",
                      "Skyrim VR"              : "sksevr_loader.exe",
                      "Default"                : "" }
# file names for ini configs
INIS              = { "Fallout3"               : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
                      "FalloutNV"              : ["FalloutCustom.ini", "Fallout.ini", "FalloutPrefs.ini"],
                      "Fallout4"               : ["Fallout4Custom.ini", "Fallout4.ini", "Fallout4Prefs.ini"],
                      "Fallout4VR"             : ["Fallout4Custom.ini", "Fallout4.ini", "Fallout4Prefs.ini"],
                      "Oblivion"               : ["OblivionCustom.ini", "Oblivion.ini", "OblivionPrefs.ini"],
                      "Skyrim"                 : ["SkyrimCustom.ini", "Skyrim.ini", "SkyrimPrefs.ini"],
                      "Skyrim Special Edition" : ["SkyrimCustom.ini", "Skyrim.ini", "SkyrimPrefs.ini"],
                      "Skyrim VR"              : ["SkyrimCustom.ini", "Skyrim.ini", "SkyrimPrefs.ini"],
                      "Default"                : ["Fallout.ini", "FalloutPrefs.ini"] }
# steam game ids
GAME_IDS          = { "Fallout 3"              : 22300,
                      "Fallout 3 goty"         : 22370,
                      "Fallout New Vegas"      : 22380,
                      "Fallout 4"              : 377160,
                      "Fallout 4 VR"           : 611660,
                      "Oblivion"               : 22330,
                      "Skyrim"                 : 72850,
                      "Skyrim Special Edition" : 489830,
                      "SkyrimVR"               : 611670,  
                      "Default"                : -1 }
# AppData directory names
GAME_COMPAT       = { "Fallout 3"              : "Fallout3",
                      "Fallout 3 goty"         : "Fallout3",
                      "Fallout New Vegas"      : "FalloutNV",
                      "Fallout 4"              : "Fallout4",
                      "Fallout 4 VR"           : "Fallout4VR",
                      "Oblivion"               : "Oblivion",
                      "Skyrim"                 : "Skyrim",
                      "Skyrim Special Edition" : "Skyrim Special Edition",
                      "SkyrimVR"               : "Skyrim VR", # ass backards
                      "Default"                : "" } # testing


def determine_game(compat_dir):
    game=""
    compats=sorted(GAME_COMPAT.values())[::-1] # reverse so we get largest name first
    game=[game for game in compats if game in str(compat_dir)]
    if game!=['']: game=game[0]
    else: game=determine_game_acf(compat_dir)
    if game==-1:
        print("error: cannot detect game name from compat dir: "+compat_dir)
        game=["Default"]
    return game
  

def determine_game_acf(compat_dir):
    if "steamapps" not in str(compat_dir): return -1
    app_id=Path(compat_dir).name
    game_dir=str(compat_dir).split("common"+os.sep)[-1].split(os.sep)[0]
    steamapps_dir=Path(str(compat_dir).split("steamapps")[0])/"steamapps"
    game=-1
    try:
        with open(steamapps_dir/f"appmanifest_{app_id}.acf", 'r', encoding='utf-8') as f:
            lines = f.readlines()
            game_line = next((line.strip() for line in lines if line.strip().startswith('"name"')), None)
            game=game_line.split('\t',1)[-1].replace('"','').strip()
    except Exception as e: print(e)
    return game 
            
 
def determine_game_id(target_dir):
    gid=0
    ids=sorted(GAME_IDS.keys())[::-1] # reverse so we get largest name first
    game_dir=str(target_dir).split("common"+os.sep)[-1].split(os.sep)[0]
    gid=[gid for gid in ids if gid in str(target_dir)]
    if gid!=[]: gid=str(GAME_IDS[gid[0]])
    else: gid=determine_game_id_acf(target_dir) 
    if gid==-1: print("error: cannot detect game id")
    return int(gid)


def determine_game_id_acf(target_dir):
    if "steamapps" not in str(target_dir): return -1
    game_dir=str(target_dir).split("common"+os.sep)[-1].split(os.sep)[0]
    steamapps_dir=Path(str(target_dir).split("steamapps")[0])/"steamapps"
    app_id=-1
    for acf in os.listdir(steamapps_dir):
        if not acf.endswith(".acf"): continue
        with open(steamapps_dir/acf, 'r', encoding='utf-8') as f:
            content = f.read()
            if f'"installdir"\t\t"{game_dir}"' in content:
                app_id = acf.replace("appmanifest_", "").replace(".acf", "")
    return int(app_id)
    

def get_ini_path(compat_dir):
    game=determine_game(compat_dir)
    return Path(*compat_dir.parts[:compat_dir.parts.index("AppData")])/"Documents"/"My Games"/game
    

def infer_compat_path(target_dir, verbose=False):
    game_id = determine_game_id(target_dir)
    if int(game_id) not in GAME_IDS.values():
        if "steamapps" not in str(target_dir): return -1
        steamapps_dir=Path(str(target_dir).split("steamapps")[0])/"steamapps"
        compat_dir=steamapps_dir/"compatdata"/str(game_id)
    elif os.name == "posix":
        game=GAME_COMPAT[Path(target_dir).parent.name]
        u_compat=target_dir.parent.parent.parent/"compatdata"/str(game_id)/"pfx"/"drive_c"/"users"/"steamuser"/"AppData"/"Local"
        compat_dir = u_compat/game
    elif os.name == "nt":
        game=GAME_COMPAT[Path(target_dir).parent.name]
        compat_dir=Path("C:\\Users\\"+os.getlogin()+"\\AppData\\Local\\")/game
    return compat_dir
        
    
def write_plugins(compat_dir, backup_dir, plugins):
    game=determine_game(compat_dir)
    pfile=Path(PLUGINS_FILE[game])
    defps=GAME_PLUGINS[game]
    #set_full_perms_file(compat_dir/pfile)
    with open(compat_dir/pfile, "w", encoding="utf-8") as f:
        agame=[k for k, v in GAME_COMPAT.items() if v == game][0]
        f.write("# This file is used by "+agame+" to keep track of your downloaded content.\n")
        f.write("# Please do not modify this file.\n")
        f.write(defps)
        for name in plugins:
            if game in ["Fallout4","Skyrim Special Edition"]: name='*'+name # TODO: determine what other peices of shit do this
            f.write(name + "\n")
    #set_readonly_file(compat_dir/pfile)
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
    ini_files=[set_full_perms_file(Path(ini_dir)/f) for f in os.listdir(ini_dir) if f.endswith(".ini")]
    try: [shutil.copy2(f, ini_dir) for f in files] 
    except Exception as e: 
        print("error: could not restore ini files, "+str(e)); 
        return False,str(e)
    print("successfully restored inis from backup!")
    return True,None


def get_launchers(target_dir,compat_dir):
    game=determine_game(compat_dir)
    game_dir=Path(target_dir).parent
    if game in VANILLA_LAUNCHERS.keys():
        launcher_exe=game_dir/VANILLA_LAUNCHERS[game]
        game_exe=game_dir/VANILLA_GAMES[game]
        se_exe=game_dir/SCRIPT_EXTENDERS[game]
        exes=[launcher_exe,game_exe,se_exe]
    else:
        exes=[target_dir/i for i in os.listdir(target_dir) if i.endswith(".exe")]
    launchers=dict()
    if game=="Default": return {"Default":{"PATH":"\"\"","PARAMS":""}}
    for exe in exes:
        if os.path.exists(exe):
            title=str(exe.name).replace(".exe",'')
            launchers[title]=dict()
            launchers[title]["PATH"]=str(exe)
            launchers[title]["PARAMS"]=""
    return launchers


def get_game_icon(exe, cfg):
    game=determine_game(cfg["COMPAT_DIR"])
    game_dir=Path(cfg["TARGET_DIR"]).parent
    steamid=determine_game_id(cfg["TARGET_DIR"])
    local_dir=Path(os.path.dirname(os.path.realpath(__file__)))
    save_dir=ensure_dir(local_dir/"resources"/"requested")
    if game in VANILLA_LAUNCHERS.keys():
        launcher_exe=VANILLA_LAUNCHERS[game]
        game_exe=VANILLA_GAMES[game]
        se_exe=SCRIPT_EXTENDERS[game]
        exes=[launcher_exe,game_exe,se_exe]
    else: 
        exes=[i for i in os.listdir(cfg["TARGET_DIR"]) if i.endswith(".exe")]
    if Path(exe).name in exes:
        icon_path=get_steam_resources(game,steamid,save_dir,icon=True)
    else:
        icon_path=None
    return icon_path


def get_game_bgs(cfg):
    game=determine_game(cfg["COMPAT_DIR"])
    game_dir=Path(cfg["TARGET_DIR"]).parent
    steamid=determine_game_id(cfg["TARGET_DIR"])
    local_dir=Path(os.path.dirname(os.path.realpath(__file__)))
    save_dir=ensure_dir(local_dir/"resources"/"requested")
    bg_paths=get_steam_resources(game,steamid,save_dir,bg=True)
    bg_paths=[i for i in bg_paths if i!=None]
    return bg_paths
        
    
