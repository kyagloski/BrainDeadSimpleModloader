
# UTILITY FUNCTIONS

import os


def force_symlink(target, link_name):
    try:
        if os.path.islink(link_name) or os.path.exists(link_name):
            os.unlink(link_name)
    except FileNotFoundError: pass
    os.symlink(target, link_name)

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

