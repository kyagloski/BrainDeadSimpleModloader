
# UTILITY FUNCTIONS

import os
import sys
import traceback
import subprocess
from pathlib import Path

def force_symlink(target, link_name):
    try:
        if os.path.islink(link_name) or os.path.exists(link_name):
            os.unlink(link_name)
    except FileNotFoundError: pass
    if os.name=="posix": os.symlink(target, link_name)
    else: os.link(target, link_name)#; print(f"linked {target} -> {link_name}")

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

def fix_dirname_used(output_dir):
    name=output_dir.name
    output_dir = next(
        p for i in range(10**9)
        if not (p := Path(output_dir).parent / f"{name}{'' if i == 0 else f'_{i}'}").exists())
    name = str(Path(output_dir).name)
    return output_dir, name

def print_traceback():
    for line in traceback.format_stack()[:-1]: print(line.strip())

def is_steam_running():
    if os.name=="posix":
        cmd=["pgrep","-x","steam"]
        result = subprocess.run(cmd,capture_output=True)
        return result.returncode == 0
    else:
        cmd=['tasklist', '/FI', 'IMAGENAME eq steam.exe']
        result = subprocess.run(cmd, capture_output=True,text=True)
        return 'steam.exe' in result.stdout.lower()

def launch_game(cfg,game_exe):
    if os.name=="posix":
        c=cfg["COMPAT_DIR"].split("pfx")[0]
        with open(Path(c)/"config_info",'r') as f: # read steam config for proton path
            proton=(f.readlines()[1].split("files")[0]+"proton").replace(' ','\\ ')
        exe=cfg["EXECUTABLES"][game_exe]["PATH"]
        exe_dir=str(Path(exe).parent).replace(' ','\\ ')
        params=cfg["EXECUTABLES"][game_exe]["PARAMS"]
        appid="SteamAppId="+str(Path(c).name)
        gameid="SteamGameId="+str(Path(c).name)
        cpath="STEAM_COMPAT_DATA_PATH="+c
        spath="STEAM_COMPAT_CLIENT_INSTALL_PATH="+os.path.expanduser("~/.steam/steam")
        cmd=f"cd {exe_dir}; {cpath} {spath} {appid} {gameid} {proton} run \"{exe}\" {params} &"
    else:
        exe=cfg["EXECUTABLES"][game_exe]["PATH"]
        exe_dir=str(Path(exe).parent)
        params=cfg["EXECUTABLES"][game_exe]["PARAMS"]
        cmd=f"cd \"{exe_dir}\" & \"{exe}\" {params}"
    print("Launching using: "+cmd)
    os.system(cmd)
