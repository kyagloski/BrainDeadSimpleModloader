
# UTILITY FUNCTIONS

import os
import sys
import stat
import traceback
import subprocess
from collections import defaultdict
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

def set_full_perms_dir(d):
    d = Path(d)
    mode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
    try: d.chmod(mode)
    except Exception as e: print(f"{str(e)} when setting permissions on {str(d)}")
    for item in d.rglob('*'):
        try: item.chmod(mode)
        except Exception as e: print(f"{str(e)} when setting permissions on {str(item)}")
    return d

def set_full_perms_file(f):
    f = Path(f)
    mode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
    try: f.chmod(mode)
    except Exception as e: print(f"{str(e)} when setting permissions on {str(f)}")
    return f


def scan_mod_overrides(top_dir, load_order, prev_files=None, prev_ow=None, prev_owt=None, changed_mods=None):
    # ugly but optimized
    idx = {m: i for i, m in enumerate(load_order)}
    ign = {b"meta.ini", b"readme.txt"}
    
    if prev_files is None or changed_mods is None:
        files = {}
        for m in load_order:
            p = top_dir + os.sep + m
            try: 
                if not os.path.isdir(p): continue
            except: continue
            pl = len(p) + 1
            for r, _, fs in os.walk(p):
                if not fs: continue
                rr = r[pl:]
                for f in fs:
                    if f.encode().lower() in ign: continue
                    k = rr + os.sep + f if rr else f
                    files.setdefault(k, []).append(idx[m])
    else:
        files = prev_files
    
    if changed_mods:
        changed_set = set(changed_mods) if not isinstance(changed_mods, set) else changed_mods
        affected = {k: v for k, v in files.items() if len(v) > 1 and any(load_order[i] in changed_set for i in v)}
    else:
        affected = {k: v for k, v in files.items() if len(v) > 1}
    
    ow = prev_ow.copy() if prev_ow else {}
    owt = prev_owt.copy() if prev_owt else {}
    
    if changed_mods:
        for k in affected:
            for i in files[k]:
                m = load_order[i]
                if m in ow:
                    for vic in list(ow[m].keys()):
                        if k not in ow[m][vic]: continue
                        ow[m][vic].remove(k)
                        if not ow[m][vic]: del ow[m][vic]
                    if not ow[m]: del ow[m]
                if m not in owt: continue
                for att in list(owt[m].keys()):
                    if k not in owt[m][att]: continue
                    owt[m][att].remove(k)
                    if not owt[m][att]: del owt[m][att]
                if not owt[m]: del owt[m]
    
    for k, v in affected.items():
        w = min(v)
        wn = load_order[w]
        ow.setdefault(wn, {})
        for l in v:
            if l == w: continue
            ln = load_order[l]
            ow[wn].setdefault(ln, []).append(k)
            owt.setdefault(ln, {}).setdefault(wn, []).append(k)
    
    return ow, owt #, files


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
