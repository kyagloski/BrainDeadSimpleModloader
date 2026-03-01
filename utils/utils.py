
# UTILITY FUNCTIONS

import os
import sys
import stat
import urllib.request
import traceback
import subprocess
from collections import defaultdict, OrderedDict
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
    return path

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

def set_readonly_file(f):
    f = Path(f)
    mode = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    try: f.chmod(mode)
    except Exception as e: print(f"{str(e)} when setting permissions on {str(f)}")
    return f

def scan_mod_overrides(src_dir, loadorder, prev_overriders=None, prev_overriddens=None, prev_overriddens_full=None, prev_mod_files=None, change_idxs=None):
    overriders=dict()
    overriddens=dict()
    overriddens_full=dict()
    ignore_files = {b"meta.ini", b"readme.txt"}

    # slim down search
    if change_idxs: loadorder=loadorder[min(change_idxs):max(change_idxs)+1]

    mod_files = OrderedDict()
    file_set  = set()
    # build file table
    for mod in loadorder[::-1]:
        path = src_dir + os.sep + mod
        if not os.path.isdir(path): continue
        mod_files[mod]=set()
        path_name_len = len(path) + 1
        for root, _, files in os.walk(path): # fast
            if not files: continue
            path_name = root[len(path)+1:]
            for file in files:
                if file.encode().lower() in ignore_files: continue # TODO: maybe could avoid this
                mod_data = path_name + os.sep + file if path_name else file
                mod_files[mod].add(mod_data)
    # iterating bottom up, check overrides
    for mod1,files1 in mod_files.items():
        # get keys after key were currently looking at
        tmp_mod_files=after = OrderedDict(list(mod_files.items())[list(mod_files.keys()).index(mod1) + 1:])
        for mod2,files2 in tmp_mod_files.items():
            # overriders and overriddens
            if len(files1 & files2)>0: # file set intersection
                overriders.setdefault(mod1,[]).append(mod2) # overrider: overriddens
                overriddens.setdefault(mod2,[]).append(mod1) # overriden: overridders
            # full overrides
            if files1==files2: # file set equivalent
                overriddens_full.setdefault(mod2,[]).append(mod1) # overridden: overriders
    # update previous dicts with new entries
    if prev_overriders: 
        [prev_overriders.pop(k, None) for k in loadorder] # del for update
        prev_overriders.update(overriders)
        overriders=prev_overriders
    if prev_overriddens: 
        [prev_overriddens.pop(k, None) for k in loadorder]
        prev_overriddens.update(overriddens) 
        overriddens=prev_overriddens
    if prev_overriddens_full: 
        [prev_overriddens_full.pop(k, None) for k in loadorder]
        prev_overriddens.update(overriddens_full) 
        overriddens_full=prev_overriddens_full
    if prev_mod_files: 
        [prev_mod_files.pop(k, None) for k in loadorder]
        prev_mod_files.update(mod_files) 
        mod_files=prev_mod_files
          
    return overriders, overriddens, overriddens_full, mod_files

def count_files(directory):
    count = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    count += 1
                elif entry.is_dir(follow_symlinks=False):
                    count += count_files(entry.path)
    except PermissionError:
        pass  # Skip directories we can't access
    return count

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

def get_steam_resources(name,app_id,save_dir,icon=False,bg=False):
    if (not icon) and (not bg): return
    urls=[]
    save_dirs=[]
    if icon: 
        save_dirs.append(Path(save_dir)/f"{name.lower().replace(' ','_')}_icon.jpg")
        urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg")
    if bg:
        save_dirs.append(Path(save_dir)/f"{name.lower().replace(' ','_')}_bg1.jpg")
        save_dirs.append(Path(save_dir)/f"{name.lower().replace(' ','_')}_bg2.jpg")
        save_dirs.append(Path(save_dir)/f"{name.lower().replace(' ','_')}_bg3.jpg")
        urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/capsule_616x353.jpg")
        urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/library_hero.jpg")
        urls.append(f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/page_bg_raw.jpg")
    for i in range(len(save_dirs)):
        if os.path.exists(save_dirs[i]): continue
        try: 
            response = urllib.request.urlopen(urls[i])
            with open(save_dirs[i], 'wb') as f:
                f.write(response.read())
        except Exception as e: 
            print(f"request for {urls[i]} failed..."); 
            save_dirs[i]=None; 
            continue
    if icon: return str(save_dirs[0])
    else: return save_dirs

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
