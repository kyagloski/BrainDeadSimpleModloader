#!/usr/bin/python3

# NEXUS MODS INTEGRATION
# api key management, nxm:// link handling, downloads, meta.ini tracking,
# mod info for the mod table, version picking, updates, collections,
# and protocol handler registration (windows + linux)

import os
import re
import sys
import json
import time
import shutil
import difflib
import getpass
import platform
import subprocess
import configparser
import urllib.parse
import urllib.request
import urllib.error
import yaml
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox, QFrame,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QInputDialog, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices, QShortcut, QKeySequence, QFont, QCursor
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

try:
    from utils.utils import *
    import utils.game_specific as game_specific
except:
    from utils import *
    import game_specific
# bdsm is imported lazily (like game_specific), gui -> bdsm -> gui import cycle

API_URL           = "https://api.nexusmods.com/v1"
GRAPHQL_URL       = "https://api.nexusmods.com/v2/graphql"
SITE_URL          = "https://www.nexusmods.com"
API_KEY_URL       = "https://www.nexusmods.com/settings/api-keys"
APP_NAME          = "BrainDeadSimpleModloader"
DESKTOP_FILE      = "bdsm-nxm.desktop"
CHUNK_SIZE        = 1024*1024 # 1MB
REQUEST_TIMEOUT   = 20
try:    SERVER_NAME = f"bdsm-nxm-{getpass.getuser()}"
except: SERVER_NAME = "bdsm-nxm"
RATE_LIMITS       = {"HOURLY": None, "DAILY": None}
CATEGORY_CACHE    = dict()
MAX_BROWSER_TABS  = 5 # non-premium updates open a browser tab per file

# nexus game domains accepted per game (keys match game_specific.GAME_COMPAT values)
NEXUS_DOMAINS     = { "Fallout3"               : ["fallout3"],
                      "FalloutNV"              : ["newvegas", "fallout3"], # ttw uses fo3 mods
                      "Fallout4"               : ["fallout4"],
                      "Fallout4VR"             : ["fallout4"],
                      "Oblivion"               : ["oblivion"],
                      "Skyrim"                 : ["skyrim"],
                      "Skyrim Special Edition" : ["skyrimspecialedition"],
                      "Skyrim VR"              : ["skyrimspecialedition", "skyrimvr"],
                      "Default"                : [] }
# nexus file categories in display order
FILE_CATEGORIES   = ["MAIN", "UPDATE", "OPTIONAL", "MISCELLANEOUS", "OLD_VERSION", "ARCHIVED"]
# metadata kept in the mod list (loadorder) files
LO_META_KEYS      = ["game", "modid", "fileid", "version"]

COLLECTION_QUERY  = """query ($slug: String!, $domain: String, $revision: Int) {
  collectionRevision(slug: $slug, domainName: $domain, revision: $revision, viewAdultContent: true) {
    revisionNumber
    collection { name slug summary game { domainName } user { name } }
    modFiles { fileId optional
      file { fileId name version sizeInBytes category uri modId
        mod { modId name author category version game { domainName } } } }
  }
}"""


class NexusError(Exception): pass


# CONFIG

def _local_dir():
    from bdsm import LOCAL_DIR
    return Path(LOCAL_DIR)


def _version():
    from bdsm import VERSION
    return VERSION.lstrip('v')


def nexus_cfg_path():
    return _local_dir()/"nexus.yaml"


def read_nexus_cfg():
    cfg={"API_KEY": "", "USER": "", "PREMIUM": False}
    if not os.path.exists(nexus_cfg_path()): return cfg
    try:
        with open(nexus_cfg_path(), "r") as f: cfg.update(yaml.safe_load(f) or {})
    except Exception as e: print(f"warning: could not read nexus config ({e})")
    return cfg


def write_nexus_cfg(cfg):
    with open(nexus_cfg_path(), "w") as f: yaml.dump(dict(cfg),f,sort_keys=False,default_flow_style=False)
    if os.name=="posix": os.chmod(nexus_cfg_path(), 0o600) # api key is a secret


def get_api_key():
    return str(read_nexus_cfg()["API_KEY"] or "").strip()


def is_premium():
    return bool(read_nexus_cfg()["PREMIUM"])


def set_api_key(key):
    key=key.strip()
    user=validate_key(key)
    cfg=read_nexus_cfg()
    cfg["API_KEY"]=key
    cfg["USER"]=user.get("name","")
    cfg["PREMIUM"]=bool(user.get("is_premium",False))
    write_nexus_cfg(cfg)
    print(f"nexus api key saved for user {cfg['USER']} (premium: {cfg['PREMIUM']})")
    return user


def clear_api_key():
    cfg=read_nexus_cfg()
    cfg["API_KEY"]=""; cfg["USER"]=""; cfg["PREMIUM"]=False
    write_nexus_cfg(cfg)
    print("removed nexus api key")


def get_download_dir():
    from bdsm import get_instance_path
    return ensure_dir(Path(get_instance_path())/"downloads")


def get_instance_domains(cfg):
    game=game_specific.determine_game(cfg["COMPAT_DIR"])
    if not isinstance(game,str): game="Default" # determine_game returns a list on failure
    return NEXUS_DOMAINS.get(game, [])


# API

def _headers(key=None):
    h = { "Application-Name"    : APP_NAME,
          "Application-Version" : _version(),
          "User-Agent"          : f"{APP_NAME}/{_version()} ({platform.system()} {platform.release()}; Python {platform.python_version()})",
          "Accept"              : "application/json" }
    if key: h["apikey"]=key
    return h


def _request(req):
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
            _update_rate_limits(r.headers)
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _update_rate_limits(e.headers)
        try:    msg=json.loads(e.read().decode("utf-8")).get("message","")
        except: msg=""
        if e.code==401: msg=msg or "invalid api key"
        if e.code==403: msg=msg or "not allowed, free accounts must download from the website"
        if e.code==429: msg=msg or "rate limit reached, try again later"
        raise NexusError(f"nexus api error {e.code}: {msg or e.reason}")
    except urllib.error.URLError as e:
        raise NexusError(f"could not reach nexus api: {e.reason}")


def api_get(endpoint, key=None, params=None):
    if key is None: key=get_api_key()
    if not key: raise NexusError("no nexus api key set")
    url=API_URL+endpoint
    if params: url+="?"+urllib.parse.urlencode({k:v for k,v in params.items() if v is not None})
    return _request(urllib.request.Request(url, headers=_headers(key)))


def graphql(query, variables=None, key=None):
    if key is None: key=get_api_key()
    headers=_headers(key)
    headers["Content-Type"]="application/json"
    data=json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    result=_request(urllib.request.Request(GRAPHQL_URL, data=data, headers=headers, method="POST"))
    if result.get("errors"): raise NexusError("nexus api error: "+"; ".join(e.get("message","") for e in result["errors"]))
    return result.get("data") or {}


def _update_rate_limits(headers):
    if not headers: return
    try:
        if headers.get("x-rl-hourly-remaining"): RATE_LIMITS["HOURLY"]=int(headers["x-rl-hourly-remaining"])
        if headers.get("x-rl-daily-remaining"):  RATE_LIMITS["DAILY"]=int(headers["x-rl-daily-remaining"])
    except ValueError: pass


def validate_key(key):
    return api_get("/users/validate.json", key=key)


def get_mod_info(domain, mod_id, key=None):
    return api_get(f"/games/{domain}/mods/{mod_id}.json", key=key)


def get_mod_files(domain, mod_id, key=None):
    return api_get(f"/games/{domain}/mods/{mod_id}/files.json", key=key)


def get_file_info(domain, mod_id, file_id, key=None):
    return api_get(f"/games/{domain}/mods/{mod_id}/files/{file_id}.json", key=key)


def get_download_links(domain, mod_id, file_id, key=None, nxm_key=None, expires=None):
    # non-premium users need the key/expires from an nxm link, premium can omit them
    return api_get(f"/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json",
                   key=key, params={"key": nxm_key, "expires": expires})


def get_category_name(domain, category_id):
    # one request per game per session
    if domain not in CATEGORY_CACHE:
        try:    CATEGORY_CACHE[domain]={c["category_id"]: c["name"] for c in api_get(f"/games/{domain}.json").get("categories",[])}
        except: CATEGORY_CACHE[domain]=dict()
    return CATEGORY_CACHE[domain].get(category_id, "")


def mod_url(domain, mod_id):
    return f"{SITE_URL}/{domain}/mods/{mod_id}"


def file_url(domain, mod_id, file_id):
    # nmm=1 jumps straight to the mod manager download page
    return f"{SITE_URL}/{domain}/mods/{mod_id}?tab=files&file_id={file_id}&nmm=1"


# NXM LINKS

def parse_nxm(url):
    # nxm://<domain>/mods/<mod_id>/files/<file_id>?key=..&expires=..&user_id=..
    # nxm://<domain>/collections/<slug>/revisions/<revision>
    u=urllib.parse.urlparse(url.strip())
    if u.scheme.lower()!="nxm": raise NexusError(f"not an nxm link: {url}")
    parts=[p for p in u.path.split('/') if p]
    if len(parts)>=2 and parts[0]=="collections":
        rev=parts[3] if len(parts)>=4 and parts[2]=="revisions" and parts[3].isdigit() else None
        return {"type": "collection", "domain": u.netloc.lower(), "slug": parts[1], "revision": int(rev) if rev else None}
    if len(parts)<4 or parts[0]!="mods" or parts[2]!="files": raise NexusError(f"malformed nxm link: {url}")
    q=urllib.parse.parse_qs(u.query)
    info = { "type"    : "file",
             "domain"  : u.netloc.lower(),
             "mod_id"  : int(parts[1]),
             "file_id" : int(parts[3]),
             "key"     : q.get("key",[None])[0],
             "expires" : q.get("expires",[None])[0],
             "user_id" : q.get("user_id",[None])[0] }
    if info["expires"] and int(info["expires"])<time.time():
        raise NexusError("nxm link has expired, click the download button on nexus again")
    return info


def parse_collection_ref(text, default_domain=None):
    # accepts nxm links, collection page urls, or a bare slug
    text=text.strip()
    if text.lower().startswith("nxm://"):
        info=parse_nxm(text)
        if info["type"]!="collection": raise NexusError("this nxm link is a mod file, not a collection")
        return info["domain"], info["slug"], info["revision"]
    m=re.search(r'nexusmods\.com/(?:games/)?([\w-]+)/collections/([\w-]+)(?:/revisions/(\d+))?', text)
    if m: return m.group(1).lower(), m.group(2), int(m.group(3)) if m.group(3) else None
    if re.fullmatch(r'[\w-]+', text): return default_domain, text, None
    raise NexusError(f"not a collection link: {text}")


def parse_mod_ref(text, default_domain=None):
    # accepts mod page urls or a bare mod id
    text=text.strip()
    m=re.search(r'nexusmods\.com/(?:games/)?([\w-]+)/mods/(\d+)', text)
    if m: return m.group(1).lower(), int(m.group(2))
    if text.isdigit() and default_domain: return default_domain, int(text)
    raise NexusError(f"not a nexus mod link or id: {text}")


def _safe_filename(name):
    name=Path(name.replace('\\','/')).name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(" .") or "download"


# DOWNLOADS

def download_file(uri, dest, progress=None, total=0):
    # stream to .part file so a broken download never looks complete
    uri=urllib.parse.quote(uri, safe=":/?&=%#+@,;~")
    req=urllib.request.Request(uri, headers={"User-Agent": _headers()["User-Agent"]})
    part=Path(str(dest)+".part")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r, open(part, "wb") as f:
            total=int(r.headers.get("Content-Length") or total or 0)
            done=0
            while True:
                chunk=r.read(CHUNK_SIZE)
                if not chunk: break
                f.write(chunk)
                done+=len(chunk)
                if progress: progress(done,total)
    except (urllib.error.URLError, OSError) as e:
        try: part.unlink()
        except: pass
        raise NexusError(f"download failed: {e}")
    os.replace(part, dest)
    return Path(dest)


def download_nexus_file(domain, mod_id, file_id, nxm_key=None, expires=None,
                        file_info=None, mod_info=None, dest_dir=None, progress=None):
    key=get_api_key()
    if not key: raise NexusError("no nexus api key set")
    if not dest_dir: dest_dir=get_download_dir()
    if file_info is None: file_info=get_file_info(domain, mod_id, file_id, key)
    if mod_info is None:
        try:    mod_info=get_mod_info(domain, mod_id, key)
        except: mod_info={} # not required, only used for nicer metadata
    fname=file_info.get("file_name")
    size=int(file_info.get("size_in_bytes") or 0)

    dest=Path(dest_dir)/_safe_filename(fname) if fname else None
    if dest and dest.exists() and size and dest.stat().st_size==size:
        print(f"already downloaded {dest.name}, skipping download")
    else:
        links=get_download_links(domain, mod_id, file_id, key, nxm_key, expires)
        if not links: raise NexusError("nexus returned no download links")
        if not dest: # name the file like the cdn does
            fname=urllib.parse.unquote(Path(urllib.parse.urlparse(links[0]["URI"]).path).name)
            dest=Path(dest_dir)/_safe_filename(fname or f"{mod_id}-{file_id}")
        print(f"downloading {dest.name} from {links[0].get('name','nexus cdn')}...")
        download_file(links[0]["URI"], dest, progress=progress, total=size)
        print(f"downloaded {dest.name}")

    write_download_meta(dest, domain, mod_id, file_id, file_info, mod_info)
    return dest


def download_nxm(url, dest_dir=None, progress=None):
    info=parse_nxm(url)
    if info["type"]!="file": raise NexusError("collection links must be opened in the collection installer")
    return download_nexus_file(info["domain"], info["mod_id"], info["file_id"], info["key"], info["expires"],
                               dest_dir=dest_dir, progress=progress)


# META FILES (mo2 compatible meta.ini format)

def _new_ini():
    ini=configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform=str # keep key case
    return ini


def _read_ini(path):
    if not os.path.exists(path): return dict()
    ini=_new_ini()
    try: ini.read(path, encoding="utf-8")
    except Exception: return dict()
    return dict(ini["General"]) if ini.has_section("General") else dict()


def _write_ini(path, general):
    ini=_new_ini()
    ini["General"]={k:str(v) for k,v in general.items() if v is not None}
    with open(path, "w", encoding="utf-8") as f: ini.write(f)


def _now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def write_download_meta(archive, domain, mod_id, file_id, file_info, mod_info):
    category=mod_info.get("category") or (get_category_name(domain, mod_info["category_id"]) if mod_info.get("category_id") else "")
    _write_ini(str(archive)+".meta", { "gameName"     : domain,
                                       "modID"        : mod_id,
                                       "fileID"       : file_id,
                                       "url"          : mod_url(domain, mod_id),
                                       "name"         : file_info.get("name",""),
                                       "modName"      : mod_info.get("name",""),
                                       "author"       : mod_info.get("author",""),
                                       "category"     : category,
                                       "version"      : file_info.get("version") or file_info.get("mod_version") or "",
                                       "newestVersion": mod_info.get("version",""),
                                       "fileCategory" : file_info.get("category_name",""),
                                       "installed"    : "false" })


def read_download_meta(archive):
    return _read_ini(str(archive)+".meta") or None


def write_mod_meta(archive, mod_dir):
    # called after every install, links installed mod dir back to its source
    if not os.path.isdir(mod_dir): return False
    meta=read_download_meta(archive)
    general = { "installationFile" : Path(archive).name,
                "installDate"      : _now() }
    if meta:
        general.update({ "gameName"      : meta.get("gameName",""),
                         "modid"         : meta.get("modID",""),
                         "fileid"        : meta.get("fileID",""),
                         "version"       : meta.get("version",""),
                         "newestVersion" : meta.get("newestVersion") or meta.get("version",""),
                         "modName"       : meta.get("modName",""),
                         "author"        : meta.get("author",""),
                         "category"      : meta.get("category",""),
                         "fileCategory"  : meta.get("fileCategory",""),
                         "url"           : meta.get("url","") })
        meta["installed"]="true"
        _write_ini(str(archive)+".meta", meta)
        print(f"linked {Path(mod_dir).name} to nexus mod {meta.get('modID','')}")
    _write_ini(Path(mod_dir)/"meta.ini", general)
    return bool(meta)


def update_mod_meta(mod_dir, **fields):
    path=Path(mod_dir)/"meta.ini"
    general=_read_ini(path)
    general.update({k:v for k,v in fields.items() if v is not None})
    _write_ini(path, general)


def read_mod_meta(mod_dir):
    meta=_read_ini(Path(mod_dir)/"meta.ini")
    if not str(meta.get("modid","")).strip().isdigit() or int(meta["modid"])<=0: return None
    return meta


def guess_from_name(name):
    # nexus archive names look like "SkyUI_5_2_SE-12604-5-2SE-1573416040"
    name=re.sub(r'_\d+$', '', name) if not re.search(r'-\d{9,11}$', name) else name # strip "_1" dupe suffix
    m=re.match(r'^(.+?)-(\d+)(?:-(.+?))?-(\d{9,11})$', name)
    if not m: return None
    return { "name"    : m.group(1).replace('_',' ').strip(),
             "modid"   : m.group(2),
             "version" : (m.group(3) or "").replace('-','.') }


def _norm_version(v):
    return str(v or "").strip().lstrip("vV").strip()


def get_local_info(mod_dir, lo_meta=None, default_domain=""):
    # merged mod info for the mod table: meta.ini > mod list metadata > archive name guess
    mod_dir=Path(mod_dir)
    meta=_read_ini(mod_dir/"meta.ini")
    lo_meta=lo_meta or {}
    info = { "game"      : meta.get("gameName") or lo_meta.get("game",""),
             "modid"     : meta.get("modid") or lo_meta.get("modid",""),
             "fileid"    : meta.get("fileid") or lo_meta.get("fileid",""),
             "version"   : meta.get("version") or lo_meta.get("version",""),
             "latest"    : meta.get("newestVersion",""),
             "author"    : meta.get("author",""),
             "category"  : meta.get("category",""),
             "modname"   : meta.get("modName",""),
             "file"      : meta.get("installationFile",""),
             "installed" : 0,
             "tracked"   : False,
             "guessed"   : False,
             "outdated"  : False }
    if str(info["modid"]).isdigit() and int(info["modid"])>0: info["tracked"]=True
    else:
        guess=guess_from_name(mod_dir.name)
        if guess:
            info.update({"modid": guess["modid"], "game": default_domain, "guessed": True})
            if not info["version"]: info["version"]=guess["version"]
            if not info["modname"]: info["modname"]=guess["name"]
        else: info["modid"]=""
    # install time, old installs fall back to folder time
    try:    info["installed"]=datetime.fromisoformat(meta["installDate"].replace("Z","")).timestamp()
    except:
        try: info["installed"]=os.path.getmtime(mod_dir)
        except OSError: pass
    if info["tracked"] and info["latest"] and info["version"]:
        info["outdated"]=_norm_version(info["latest"])!=_norm_version(info["version"])
    return info


def build_mod_info(source_dir, lo_meta=None, default_domain=""):
    source_dir=Path(source_dir)
    lo_meta=lo_meta or {}
    if not source_dir.is_dir(): return dict()
    return { m: get_local_info(source_dir/m, lo_meta.get(m), default_domain)
             for m in os.listdir(source_dir) if (source_dir/m).is_dir() }


def loadorder_meta(mod_info):
    # metadata written to mod list files, only for confirmed nexus mods
    return { name: {k: str(info.get(k,"")) for k in LO_META_KEYS}
             for name,info in mod_info.items() if info.get("tracked") }


def link_mod(mod_dir, domain, mod_id, mod_info=None, version=None):
    mod_info=mod_info or {}
    category=mod_info.get("category") or (get_category_name(domain, mod_info["category_id"]) if mod_info.get("category_id") else None)
    update_mod_meta(mod_dir, gameName=domain, modid=mod_id, url=mod_url(domain, mod_id), version=version,
                    modName=mod_info.get("name"), author=mod_info.get("author"), category=category,
                    newestVersion=mod_info.get("version"))
    print(f"linked {Path(mod_dir).name} to nexus mod {mod_id}")


def unlink_mod(mod_dir):
    general=_read_ini(Path(mod_dir)/"meta.ini")
    for k in ["gameName","modid","fileid","newestVersion","url"]: general.pop(k, None)
    _write_ini(Path(mod_dir)/"meta.ini", general)
    print(f"unlinked {Path(mod_dir).name} from nexus")


def auto_link_guessed(source_dir, mod_info, domains, progress=None):
    # link mods installed before tracking existed, verified by comparing names
    guessed=[(n,i) for n,i in mod_info.items() if i.get("guessed")]
    linked,failed=[],[]
    for idx,(name,info) in enumerate(guessed):
        if progress: progress(idx+1,len(guessed))
        best=None
        for domain in domains:
            try: remote=get_mod_info(domain, info["modid"])
            except NexusError: continue
            a=re.sub(r'[\W_]+',' ',info["modname"]).lower().strip()
            b=re.sub(r'[\W_]+',' ',remote.get("name","")).lower().strip()
            ratio=difflib.SequenceMatcher(None,a,b).ratio()
            if a and b and (a in b or b in a): ratio=1.0
            if ratio>=0.6 and (not best or ratio>best[0]): best=(ratio,domain,remote)
        if best:
            link_mod(Path(source_dir)/name, best[1], int(info["modid"]), best[2], version=info["version"])
            linked.append(name)
        else: failed.append(name)
    return linked,failed


def check_updates(source_dir, mod_info, progress=None):
    # updates newestVersion in meta.ini for every tracked mod
    tracked=[(n,i) for n,i in sorted(mod_info.items()) if i.get("tracked") and i.get("game")]
    cache=dict() # dont request the same mod twice
    results=[]
    for idx,(mod,info) in enumerate(tracked):
        if progress: progress(idx+1,len(tracked))
        domain,mod_id=info["game"],int(info["modid"])
        if (domain,mod_id) not in cache:
            try: cache[(domain,mod_id)]=get_mod_info(domain, mod_id)
            except NexusError as e:
                print(f"warning: could not check {mod} ({e})")
                cache[(domain,mod_id)]=None
        remote=cache[(domain,mod_id)]
        if remote is None: continue
        latest=str(remote.get("version") or "")
        outdated=bool(latest) and bool(info.get("version")) and _norm_version(latest)!=_norm_version(info["version"])
        results.append({ "mod"      : mod,
                         "domain"   : domain,
                         "mod_id"   : mod_id,
                         "version"  : info.get("version",""),
                         "latest"   : latest,
                         "status"   : remote.get("status","published"),
                         "outdated" : outdated,
                         "url"      : mod_url(domain, mod_id) })
        # store so it survives restarts, also migrates mod list only metadata into meta.ini
        try: update_mod_meta(Path(source_dir)/mod, gameName=domain, modid=mod_id, fileid=info.get("fileid") or None,
                             version=info.get("version") or None, newestVersion=latest,
                             modName=remote.get("name"), author=remote.get("author"))
        except OSError: pass
    return results


def find_latest_file(files_json, current_file_id=None):
    # returns (file, ambiguous), follows the author's update chain first
    files={f["file_id"]: f for f in files_json.get("files",[])}
    updates={u["old_file_id"]: u["new_file_id"] for u in files_json.get("file_updates",[])}
    cur=int(current_file_id) if str(current_file_id or "").isdigit() else None
    fid,seen=cur,set()
    while fid in updates and fid not in seen: seen.add(fid); fid=updates[fid]
    if fid and fid!=cur and fid in files: return files[fid],False
    if cur in files and files[cur].get("category_name") in ("MAIN","OPTIONAL","MISCELLANEOUS"): return files[cur],False # still current
    mains=sorted([f for f in files.values() if f.get("category_name")=="MAIN"], key=lambda f: f.get("uploaded_timestamp",0))
    if not mains: return None,True
    return mains[-1],len(mains)>1


def replace_mod(source_dir, new_name, old_name):
    # swap freshly installed dir into the old mod's place, keeps load order position
    source_dir=Path(source_dir)
    old,new,bak=source_dir/old_name,source_dir/new_name,source_dir/(old_name+".bdsm_old")
    if old==new: return old_name
    if old.exists(): os.rename(old, bak)
    try: os.rename(new, old)
    except Exception:
        if bak.exists(): os.rename(bak, old)
        raise
    if bak.exists():
        set_full_perms_dir(bak)
        shutil.rmtree(bak, ignore_errors=True)
    print(f"replaced mod {old_name} with new version")
    return old_name


# COLLECTIONS

def get_collection(slug, domain=None, revision=None):
    data=graphql(COLLECTION_QUERY, {"slug": slug, "domain": domain, "revision": revision})
    rev=data.get("collectionRevision")
    if not rev: raise NexusError(f"collection {slug} not found")
    col=rev.get("collection") or {}
    mods=[]
    for mf in rev.get("modFiles") or []:
        f=mf.get("file") or {}
        m=f.get("mod") or {}
        mods.append({ "domain"   : (m.get("game") or {}).get("domainName") or domain,
                      "mod_id"   : int(f.get("modId") or m.get("modId") or 0),
                      "file_id"  : int(mf.get("fileId") or f.get("fileId") or 0),
                      "name"     : f.get("name",""),
                      "mod_name" : m.get("name",""),
                      "author"   : m.get("author",""),
                      "category" : m.get("category",""),
                      "version"  : f.get("version") or mf.get("version") or "",
                      "latest"   : m.get("version",""),
                      "size"     : int(f.get("sizeInBytes") or 0),
                      "file_name": f.get("uri") or "",
                      "fcategory": f.get("category",""),
                      "optional" : bool(mf.get("optional")) })
    return { "name"     : col.get("name", slug),
             "slug"     : col.get("slug", slug),
             "summary"  : col.get("summary",""),
             "author"   : (col.get("user") or {}).get("name",""),
             "domain"   : (col.get("game") or {}).get("domainName") or domain,
             "revision" : rev.get("revisionNumber"),
             "mods"     : [m for m in mods if m["mod_id"] and m["file_id"]] }


def download_collection_mod(item, progress=None):
    file_info = { "file_name"     : item["file_name"],
                  "name"          : item["name"],
                  "version"       : item["version"],
                  "size_in_bytes" : item["size"],
                  "category_name" : item["fcategory"] }
    mod_info  = { "name": item["mod_name"], "author": item["author"], "category": item["category"], "version": item["latest"] }
    return download_nexus_file(item["domain"], item["mod_id"], item["file_id"],
                               file_info=file_info, mod_info=mod_info, progress=progress)


# PROTOCOL HANDLER REGISTRATION

def get_handler_cmd():
    # frozen build entry point is gui.py itself
    if getattr(sys, "frozen", False): return [sys.executable]
    exe=Path(sys.executable)
    if os.name=="nt" and exe.with_name("pythonw.exe").exists(): exe=exe.with_name("pythonw.exe") # no console
    return [str(exe), str(Path(__file__).resolve().parent/"gui.py")]


def _desktop_quote(arg):
    # desktop entry spec quoting
    if not re.search(r'[\s"\'\\><~|&;$*?#()`]', arg): return arg
    return '"'+re.sub(r'(["`$\\])', r'\\\1', arg)+'"'


def _applications_dir():
    data_home=os.environ.get("XDG_DATA_HOME") or str(Path.home()/".local"/"share")
    return ensure_dir(Path(data_home)/"applications")


def get_current_handler():
    if os.name=="nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\nxm\shell\open\command") as k:
                return winreg.QueryValueEx(k, "")[0]
        except OSError: return ""
    try:
        r=subprocess.run(["xdg-mime","query","default","x-scheme-handler/nxm"], capture_output=True, text=True)
        return r.stdout.strip()
    except FileNotFoundError: return ""


def is_handler_registered():
    cur=get_current_handler()
    if os.name=="nt": return get_handler_cmd()[-1].lower() in cur.lower()
    return cur==DESKTOP_FILE


def register_nxm_handler():
    cmd=get_handler_cmd()
    if os.name=="nt": _register_windows(cmd)
    else: _register_linux(cmd)
    print("registered bdsm as the nxm:// link handler!")
    return True


def _register_windows(cmd):
    import winreg
    command=" ".join(f'"{c}"' for c in cmd)+' --nxm "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\nxm") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:NXM Protocol")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\nxm\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{cmd[0]}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\nxm\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)


def _register_linux(cmd):
    app_dir=_applications_dir()
    icon=_local_dir()/"utils"/"resources"/"icon.png"
    exec_line=" ".join(_desktop_quote(c) for c in cmd)+" --nxm %u"
    with open(app_dir/DESKTOP_FILE, "w") as f:
        f.write("[Desktop Entry]\n")
        f.write("Type=Application\n")
        f.write("Name=BrainDead Simple Modloader (NXM Handler)\n")
        f.write(f"Exec={exec_line}\n")
        if icon.exists(): f.write(f"Icon={icon}\n")
        f.write("Terminal=false\n")
        f.write("NoDisplay=true\n")
        f.write("MimeType=x-scheme-handler/nxm;\n")
    try: subprocess.run(["update-desktop-database", str(app_dir)], capture_output=True)
    except FileNotFoundError: pass
    try:
        r=subprocess.run(["xdg-mime","default",DESKTOP_FILE,"x-scheme-handler/nxm"], capture_output=True, text=True)
        if r.returncode!=0: raise FileNotFoundError(r.stderr)
    except FileNotFoundError: # no xdg-utils, write mimeapps.list directly
        cfg_home=Path(os.environ.get("XDG_CONFIG_HOME") or Path.home()/".config")
        mimeapps=ensure_dir(cfg_home)/"mimeapps.list"
        ini=_new_ini()
        if mimeapps.exists(): ini.read(mimeapps, encoding="utf-8")
        if not ini.has_section("Default Applications"): ini.add_section("Default Applications")
        ini["Default Applications"]["x-scheme-handler/nxm"]=DESKTOP_FILE
        with open(mimeapps, "w", encoding="utf-8") as f: ini.write(f, space_around_delimiters=False)


# SINGLE INSTANCE IPC (unix socket on linux, named pipe on windows)

def send_to_running(url, timeout=1000):
    sock=QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(timeout): return False
    sock.write((url.strip()+"\n").encode("utf-8"))
    sock.waitForBytesWritten(timeout)
    sock.disconnectFromServer()
    print("sent nxm link to running instance")
    return True


class NxmServer(QLocalServer):
    received = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buffers=dict()
        self.newConnection.connect(self._on_connection)
        if not self.listen(SERVER_NAME):
            # stale socket from a crash, only remove if nothing answers
            probe=QLocalSocket()
            probe.connectToServer(SERVER_NAME)
            if probe.waitForConnected(300):
                probe.disconnectFromServer()
                print("warning: another bdsm instance is handling nxm links")
                return
            QLocalServer.removeServer(SERVER_NAME)
            if not self.listen(SERVER_NAME): print(f"warning: could not start nxm server ({self.errorString()})")

    def _on_connection(self):
        while self.hasPendingConnections():
            sock=self.nextPendingConnection()
            self.buffers[id(sock)]=b""
            sock.readyRead.connect(lambda s=sock: self._on_ready(s))
            sock.disconnected.connect(lambda s=sock: self._on_disconnect(s))

    def _on_disconnect(self, sock):
        self.buffers.pop(id(sock), None)
        sock.deleteLater()

    def _on_ready(self, sock):
        buf=self.buffers.get(id(sock),b"")+bytes(sock.readAll())
        *lines,rest=buf.split(b"\n")
        self.buffers[id(sock)]=rest
        for line in lines:
            url=line.decode("utf-8","ignore").strip()
            if url: self.received.emit(url)


# GUI

def _require_key(window):
    if get_api_key(): return True
    QMessageBox.information(window, "Nexus", "No Nexus API key set\nPlease add your API key in the Nexus Manager")
    open_nexus_manager(window)
    return False


def _confirm_domain(window, domain):
    domains=get_instance_domains(window.cfg)
    if not domains or domain in domains: return True
    reply=QMessageBox.warning(window,
                "Nexus Warning",
                f"This is for '{domain}' but the current instance expects '{domains[0]}'\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return reply==QMessageBox.StandardButton.Yes


def handle_nxm_link(window, url):
    window.showNormal(); window.raise_(); window.activateWindow()
    try: info=parse_nxm(url)
    except (NexusError, ValueError) as e:
        QMessageBox.warning(window, "Nexus Error", str(e))
        return
    if not _require_key(window): return
    if not _confirm_domain(window, info["domain"]): return
    if info["type"]=="collection":
        open_collection(window, info["slug"], info["domain"], info["revision"])
        return
    replace=window.nexus_pending.pop((info["domain"], info["mod_id"]), None) # requested update
    thread=NexusDownloadThread(window, url=url, replace=replace)
    window.nexus_threads.append(thread)
    thread.start()


def start_download(window, domain, mod_id, file_id, replace=None):
    # premium downloads directly, free accounts go through the website and come back as nxm links
    if is_premium():
        thread=NexusDownloadThread(window, domain=domain, mod_id=mod_id, file_id=file_id, replace=replace)
        window.nexus_threads.append(thread)
        thread.start()
        return
    if replace: window.nexus_pending[(domain, int(mod_id))]=replace
    QDesktopServices.openUrl(QUrl(file_url(domain, mod_id, file_id)))
    window.status_label.setText("Click 'Slow download' in your browser to continue")
    print(f"opened nexus download page for mod {mod_id}, waiting for nxm link...")


def open_nexus_manager(window):
    window.nexus_manager=NexusManager(parent=window)
    window.nexus_manager.setWindowModality(Qt.WindowModality.ApplicationModal)
    window.nexus_manager.show()


def open_collection(window, slug, domain=None, revision=None):
    window.collection_dialog=CollectionDialog(window, slug, domain, revision)
    window.collection_dialog.show()


def run_task(window, fn, done, status=None):
    # run blocking api calls off the ui thread, done(result, error) runs on the ui thread
    task=NexusTask(fn)
    task.complete.connect(lambda result,error: (window.nexus_threads.remove(task) if task in window.nexus_threads else None, done(result,error)))
    window.nexus_threads.append(task)
    if status: window.status_label.setText(status)
    task.start()
    return task


def add_mod_menu(window, menu, names):
    # nexus submenu for the mod table context menu
    infos=[(n, window.mod_info.get(n, {})) for n in names]
    tracked=[(n,i) for n,i in infos if i.get("tracked")]
    one=infos[0] if len(infos)==1 else (None,{})
    sub=menu.addMenu("Nexus")
    has_key=bool(get_api_key())

    a=sub.addAction("Open on Nexus")
    a.setEnabled(bool(one[1].get("modid") and one[1].get("game")))
    a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(mod_url(one[1]["game"], one[1]["modid"]))))
    sub.addSeparator()
    a=sub.addAction("Check for Updates")
    a.setEnabled(bool(tracked) and has_key)
    a.triggered.connect(lambda: check_updates_gui(window, [n for n,_ in tracked]))
    a=sub.addAction("Update to Latest")
    a.setEnabled(bool(tracked) and has_key)
    a.triggered.connect(lambda: update_mods(window, [n for n,_ in tracked]))
    a=sub.addAction("Change Version...")
    a.setEnabled(bool(one[0] and one[1].get("tracked")) and has_key)
    a.triggered.connect(lambda: NexusFileDialog(window, one[0]).show())
    sub.addSeparator()
    a=sub.addAction("Link to Nexus Mod...")
    a.setEnabled(bool(one[0]) and has_key)
    a.triggered.connect(lambda: link_mod_dialog(window, one[0]))
    a=sub.addAction("Unlink")
    a.setEnabled(bool(one[0] and one[1].get("tracked")))
    a.triggered.connect(lambda: _unlink(window, one[0]))
    return sub


def _unlink(window, name):
    unlink_mod(Path(window.cfg["SOURCE_DIR"])/name)
    window.refresh_mod_info([name])
    window.auto_save_load_order()


def link_mod_dialog(window, name):
    info=window.mod_info.get(name, {})
    domains=get_instance_domains(window.cfg)
    default=mod_url(info["game"], info["modid"]) if info.get("modid") and info.get("game") else ""
    text, ok = QInputDialog.getText(window, "Link to Nexus Mod", f"Nexus mod page URL or mod ID for '{name}':"+' '*40,
                                    QLineEdit.EchoMode.Normal, default)
    if not ok or not text.strip(): return
    try: domain,mod_id=parse_mod_ref(text, domains[0] if domains else None)
    except NexusError as e: QMessageBox.warning(window, "Nexus Error", str(e)); return

    def done(remote, error):
        window.status_label.setText("")
        if error: QMessageBox.warning(window, "Nexus Error", f"Could not find mod:\n{error}"); return
        reply=QMessageBox.question(window, "Link to Nexus Mod",
                    f"Link '{name}' to '{remote.get('name','')}' by {remote.get('author','')}?\n\n"
                    f"Installed version: {info.get('version') or 'unknown'}\nLatest version: {remote.get('version','')}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply!=QMessageBox.StandardButton.Yes: return
        link_mod(Path(window.cfg["SOURCE_DIR"])/name, domain, mod_id, remote, version=info.get("version") or None)
        window.refresh_mod_info([name])
        window.auto_save_load_order()
    run_task(window, lambda: get_mod_info(domain, mod_id), done, status="Looking up nexus mod...")


def check_updates_gui(window, names=None, done_cb=None):
    infos={n:i for n,i in window.mod_info.items() if names is None or n in names}
    def done(results, error):
        window.refresh_mod_info(list(infos))
        if error: window.status_label.setText("Update check failed!"); print(f"error: update check failed: {error}")
        else:
            outdated=[r for r in results if r["outdated"]]
            window.status_label.setText(f"{len(outdated)} of {len(results)} mods have updates")
            for r in outdated: print(f"update available: {r['mod']} {r['version']} -> {r['latest']}")
        if done_cb: done_cb(results or [], error)
    return run_task(window, lambda: check_updates(window.cfg["SOURCE_DIR"], infos), done, status="Checking for updates...")


def update_mods(window, names):
    infos=[(n, window.mod_info[n]) for n in names if window.mod_info.get(n,{}).get("tracked")]
    def work():
        plan,skipped=[],[]
        for name,info in infos:
            try: files=get_mod_files(info["game"], info["modid"])
            except NexusError as e: skipped.append((name, str(e))); continue
            latest,ambiguous=find_latest_file(files, info.get("fileid"))
            if not latest: skipped.append((name, "no main file found")); continue
            if ambiguous: skipped.append((name, "several main files, use Change Version")); continue
            if str(latest["file_id"])==str(info.get("fileid")) \
            and _norm_version(latest.get("version"))==_norm_version(info.get("version")): continue # up to date
            plan.append((name, info["game"], int(info["modid"]), latest["file_id"], latest.get("version","")))
        return plan,skipped
    def done(result, error):
        window.status_label.setText("")
        if error: QMessageBox.warning(window, "Nexus Error", f"Update failed:\n{error}"); return
        plan,skipped=result
        if skipped: print("skipped updates:\n  "+"\n  ".join(f"{n}: {r}" for n,r in skipped))
        if not plan:
            msg="Selected mods are up to date"+(f"\n\nSkipped:\n"+"\n".join(f"{n}: {r}" for n,r in skipped) if skipped else "")
            QMessageBox.information(window, "Nexus", msg); return
        if not is_premium() and len(plan)>MAX_BROWSER_TABS:
            reply=QMessageBox.question(window, "Nexus", f"Free accounts download through the website\nThis will open {len(plan)} browser tabs, continue?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply!=QMessageBox.StandardButton.Yes: return
        for name,domain,mod_id,file_id,version in plan:
            print(f"updating {name} to {version}...")
            start_download(window, domain, mod_id, file_id, replace=name)
    run_task(window, work, done, status="Finding latest files...")


class NexusTask(QThread):
    complete = pyqtSignal(object, str)

    def __init__(self, fn):
        super().__init__()
        self.fn=fn

    def run(self):
        try: self.complete.emit(self.fn(), "")
        except Exception as e: self.complete.emit(None, str(e) or type(e).__name__)


class NexusDownloadThread(QThread):
    progress = pyqtSignal(int, int)
    complete = pyqtSignal(str, str) # path, error

    def __init__(self, window, url=None, domain=None, mod_id=None, file_id=None, replace=None):
        super().__init__()
        self.window=window
        self.url=url
        self.target=(domain, mod_id, file_id)
        self.replace=replace
        self.mod_name=replace or f"mod {parse_nxm(url)['mod_id'] if url else mod_id}"
        self.last_pct=-1
        # slots belong to this object (main thread) so ui updates are queued safely
        self.progress.connect(self._on_progress)
        self.complete.connect(self._on_complete)

    def run(self):
        try:
            report=lambda d,t: self.progress.emit(d,t)
            if self.url: path=download_nxm(self.url, progress=report)
            else:        path=download_nexus_file(*self.target, progress=report)
            self.complete.emit(str(path), "")
        except Exception as e:
            self.complete.emit("", str(e))

    def _on_progress(self, done, total):
        pct=int(done*100/total) if total else -1
        if pct==self.last_pct and pct!=-1: return
        self.last_pct=pct
        mb=f"{done/1048576:.1f}"+(f"/{total/1048576:.1f}" if total else "")+" MB"
        self.window.status_label.setText(f"Downloading {self.mod_name} {str(pct)+'% ' if pct>=0 else ''}({mb})")

    def _on_complete(self, path, error):
        try: self.window.nexus_threads.remove(self)
        except ValueError: pass
        if error:
            self.window.status_label.setText("Download failed!")
            print(f"error: nexus download failed: {error}")
            QMessageBox.warning(self.window, "Nexus Download Error", f"Failed to download {self.mod_name}:\n{error}")
            return
        self.window.status_label.setText("Download complete!")
        if self.replace: self.window.nexus_replacements[path]=self.replace
        self.window.install_archives([path])


class NexusCollectionThread(QThread):
    progress = pyqtSignal(int, int, str, int, int)  # index, count, name, done, total
    complete = pyqtSignal(list, list)               # paths, errors

    def __init__(self, items):
        super().__init__()
        self.items=items
        self.cancelled=False

    def run(self):
        paths,errors=[],[]
        for i,item in enumerate(self.items):
            if self.cancelled: break
            label=item["mod_name"] or item["name"]
            try: paths.append(str(download_collection_mod(item, progress=lambda d,t: self.progress.emit(i+1,len(self.items),label,d,t))))
            except Exception as e:
                print(f"error: could not download {label}: {e}")
                errors.append(f"{label}: {e}")
        self.complete.emit(paths, errors)


class NexusFileDialog(QDialog):
    # pick any file/version of a tracked mod
    def __init__(self, window, mod_name):
        super().__init__(window)
        self.window=window
        self.mod_name=mod_name
        self.info=window.mod_info.get(mod_name, {})
        self.files=[]

        self.setWindowTitle(f"Versions - {mod_name}")
        self.setMinimumSize(640, 420)
        self.resize(760, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        self.title_label = QLabel(f"Installed: {self.info.get('version') or 'unknown'}   Loading files...")
        root.addWidget(self.title_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Version", "Uploaded", "Size"])
        self.tree.setRootIsDecorated(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self._on_install())
        root.addWidget(self.tree)

        self.replace_check = QCheckBox("Replace installed mod (keeps load order position)")
        self.replace_check.setChecked(True)
        root.addWidget(self.replace_check)

        bottom = QHBoxLayout()
        self.btn_page = QPushButton("Open Page")
        self.btn_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(mod_url(self.info["game"], self.info["modid"]))))
        bottom.addWidget(self.btn_page)
        bottom.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        self.btn_install = QPushButton("Install")
        self.btn_install.setFixedWidth(80)
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._on_install)
        bottom.addWidget(self.btn_install)
        root.addLayout(bottom)

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)
        run_task(window, lambda: get_mod_files(self.info["game"], self.info["modid"]), self._on_loaded)

    def _on_loaded(self, result, error):
        if error: self.title_label.setText(f"Could not load files: {error}"); return
        self.files=result.get("files",[])
        cur=str(self.info.get("fileid",""))
        self.title_label.setText(f"Installed: {self.info.get('version') or 'unknown'}   ({len(self.files)} files)")
        groups=dict()
        for cat in FILE_CATEGORIES+["OTHER"]:
            group=QTreeWidgetItem(self.tree, [cat.replace('_',' ').title()])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            groups[cat]=group
        for f in sorted(self.files, key=lambda f: f.get("uploaded_timestamp",0), reverse=True):
            cat=f.get("category_name") or "OTHER"
            uploaded=datetime.fromtimestamp(f.get("uploaded_timestamp",0)).strftime("%Y-%m-%d") if f.get("uploaded_timestamp") else ""
            size=f"{(f.get('size_kb') or 0)/1024:.1f} MB"
            item=QTreeWidgetItem(groups.get(cat, groups["OTHER"]), [f.get("name",""), str(f.get("version","")), uploaded, size])
            item.setData(0, Qt.ItemDataRole.UserRole, f)
            item.setToolTip(0, re.sub(r'<[^>]+>', '', f.get("description") or "")[:500])
            if str(f.get("file_id"))==cur:
                font=item.font(0); font.setBold(True)
                for c in range(4): item.setFont(c, font)
                item.setText(0, f.get("name","")+"  (installed)")
        for cat,group in groups.items():
            if group.childCount()==0: group.setHidden(True)
            group.setExpanded(cat not in ("OLD_VERSION","ARCHIVED"))
        self.tree.resizeColumnToContents(1)

    def _selected_file(self):
        items=self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _on_selection(self):
        f=self._selected_file()
        self.btn_install.setEnabled(bool(f))
        # add-on files usually install next to the main file
        if f: self.replace_check.setChecked(f.get("category_name") not in ("OPTIONAL","UPDATE","MISCELLANEOUS"))

    def _on_install(self):
        f=self._selected_file()
        if not f: return
        replace=self.mod_name if self.replace_check.isChecked() else None
        print(f"installing {self.mod_name} file {f.get('name','')} ({f.get('version','')})...")
        start_download(self.window, self.info["game"], int(self.info["modid"]), f["file_id"], replace=replace)
        self.accept()


class CollectionDialog(QDialog):
    def __init__(self, window, slug, domain=None, revision=None):
        super().__init__(window)
        self.window=window
        self.collection=None
        self.thread=None
        self.queue=[]      # free account browser queue
        self.queue_pos=0

        self.setWindowTitle("Nexus Collection")
        self.setMinimumSize(640, 480)
        self.resize(760, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        self.title_label = QLabel(f"Loading collection {slug}...")
        font=self.title_label.font(); font.setBold(True); self.title_label.setFont(font)
        root.addWidget(self.title_label)
        self.info_label = QLabel("")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Mod", "File", "Version", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.tree)

        opts = QHBoxLayout()
        self.optional_check = QCheckBox("Include optional mods")
        self.optional_check.toggled.connect(self._on_optional_toggled)
        opts.addWidget(self.optional_check)
        self.sep_check = QCheckBox("Add separator")
        self.sep_check.setChecked(True)
        opts.addWidget(self.sep_check)
        opts.addStretch()
        root.addLayout(opts)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        bottom.addWidget(self.status, 1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.close)
        bottom.addWidget(self.btn_cancel)
        self.btn_install = QPushButton("Install")
        self.btn_install.setMinimumWidth(80)
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._on_install)
        bottom.addWidget(self.btn_install)
        root.addLayout(bottom)

        run_task(window, lambda: get_collection(slug, domain, revision), self._on_loaded)

    def _installed_ids(self):
        return {(str(i.get("modid")), str(i.get("fileid"))) for i in self.window.mod_info.values() if i.get("tracked")}

    def _on_loaded(self, col, error):
        if error: self.title_label.setText(f"Could not load collection: {error}"); return
        self.collection=col
        total=sum(m["size"] for m in col["mods"])
        self.title_label.setText(f"{col['name']}  (revision {col['revision']})")
        self.info_label.setText(f"by {col['author']}  |  {len(col['mods'])} mods  |  {total/1073741824:.2f} GB\n{col['summary']}")
        installed=self._installed_ids()
        for m in col["mods"]:
            done=(str(m["mod_id"]), str(m["file_id"])) in installed
            item=QTreeWidgetItem(self.tree, [m["mod_name"]+(" (installed)" if done else "")+(" [optional]" if m["optional"] else ""),
                                             m["name"], m["version"], f"{m['size']/1048576:.1f} MB"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked if done or m["optional"] else Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, m)
        self.btn_install.setEnabled(True)

    def _on_optional_toggled(self, checked):
        installed=self._installed_ids()
        for i in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(i)
            m=item.data(0, Qt.ItemDataRole.UserRole)
            if m["optional"] and (str(m["mod_id"]), str(m["file_id"])) not in installed:
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _selected(self):
        items=[self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        return [i.data(0, Qt.ItemDataRole.UserRole) for i in items if i.checkState(0)==Qt.CheckState.Checked]

    def _add_separator(self):
        if not self.sep_check.isChecked(): return
        self.window.add_separator(f"v#{self.collection['name']}")
        self.window.auto_save_load_order(instant=True) # installs append after it
        self.sep_check.setChecked(False) # only once

    def _on_install(self):
        if self.queue: self._open_next(); return
        items=self._selected()
        if not items: return
        if is_premium():
            self._add_separator()
            self.btn_install.setEnabled(False)
            self.tree.setEnabled(False)
            self.thread=NexusCollectionThread(items)
            self.thread.progress.connect(self._on_progress)
            self.thread.complete.connect(self._on_complete)
            self.thread.start()
            return
        # free accounts must click download on the website for every file
        QMessageBox.information(self, "Nexus Collection",
                    "Free Nexus accounts can't download automatically\n\n"
                    "Each mod's download page will open in your browser, click 'Slow download' "
                    "and the mod will install automatically. Use 'Open Next' to continue through the list.")
        self._add_separator()
        self.queue=items
        self.queue_pos=0
        self.tree.setEnabled(False)
        self._open_next()

    def _open_next(self):
        if self.queue_pos>=len(self.queue): self.close(); return
        m=self.queue[self.queue_pos]
        QDesktopServices.openUrl(QUrl(file_url(m["domain"], m["mod_id"], m["file_id"])))
        self.queue_pos+=1
        self.status.setText(f"Opened {self.queue_pos}/{len(self.queue)}: {m['mod_name']}")
        self.btn_install.setText("Done" if self.queue_pos>=len(self.queue) else f"Open Next ({self.queue_pos+1}/{len(self.queue)})")

    def _on_progress(self, i, n, name, done, total):
        pct=f" {int(done*100/total)}%" if total else ""
        self.status.setText(f"Downloading {i}/{n}: {name}{pct}")
        self.window.status_label.setText(f"Collection {i}/{n}: {name}{pct}")

    def _on_complete(self, paths, errors):
        self.thread=None
        self.status.setText(f"Downloaded {len(paths)} mods, installing...")
        if errors: QMessageBox.warning(self, "Nexus Collection", "Some mods failed to download:\n\n"+"\n".join(errors[:20]))
        if paths: self.window.install_archives(paths)
        self.close()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            reply=QMessageBox.question(self, "Nexus Collection", "Stop downloading the collection?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply!=QMessageBox.StandardButton.Yes: event.ignore(); return
            self.thread.cancelled=True # finishes current file, then installs what it has
        event.accept()


class NexusManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent=parent

        self.setWindowTitle("Nexus Manager")
        self.setMinimumSize(420, 560)
        self.resize(500, 620)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._build_ui()
        self._refresh()

        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(10)

        # api key
        root.addWidget(QLabel("Nexus API key"))
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste personal API key...")
        self.key_edit.returnPressed.connect(self._on_save_key)
        key_row.addWidget(self.key_edit)

        self.btn_get_key = QPushButton("?")
        self.btn_get_key.setFixedSize(35, 35)
        self.btn_get_key.setToolTip("Get an API key from nexusmods.com")
        self.btn_get_key.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(API_KEY_URL)))
        key_row.addWidget(self.btn_get_key)

        self.btn_save_key = QPushButton("Save")
        self.btn_save_key.setFixedWidth(80)
        self.btn_save_key.setToolTip("Validate and save API key")
        self.btn_save_key.clicked.connect(self._on_save_key)
        key_row.addWidget(self.btn_save_key)

        self.btn_clear_key = QPushButton("-")
        self.btn_clear_key.setFixedSize(35, 35)
        self.btn_clear_key.setToolTip("Remove API key")
        self.btn_clear_key.clicked.connect(self._on_clear_key)
        key_row.addWidget(self.btn_clear_key)
        root.addLayout(key_row)

        self.user_label = QLabel("")
        root.addWidget(self.user_label)

        root.addWidget(self._hline())

        # nxm handler
        handler_row = QHBoxLayout()
        self.handler_label = QLabel("")
        self.handler_label.setWordWrap(True)
        handler_row.addWidget(self.handler_label, 1)
        self.btn_register = QPushButton("Register")
        self.btn_register.setFixedWidth(80)
        self.btn_register.setToolTip("Handle 'Mod Manager Download' buttons on nexusmods.com")
        self.btn_register.clicked.connect(self._on_register)
        handler_row.addWidget(self.btn_register)
        root.addLayout(handler_row)

        # manual nxm link
        nxm_row = QHBoxLayout()
        self.nxm_edit = QLineEdit()
        self.nxm_edit.setPlaceholderText("nxm://...")
        self.nxm_edit.returnPressed.connect(self._on_download)
        nxm_row.addWidget(self.nxm_edit)
        self.btn_download = QPushButton("Download")
        self.btn_download.setFixedWidth(80)
        self.btn_download.setToolTip("Download and install an nxm link")
        self.btn_download.clicked.connect(self._on_download)
        nxm_row.addWidget(self.btn_download)
        root.addLayout(nxm_row)

        # collections
        col_row = QHBoxLayout()
        self.col_edit = QLineEdit()
        self.col_edit.setPlaceholderText("Collection URL or slug...")
        self.col_edit.returnPressed.connect(self._on_collection)
        col_row.addWidget(self.col_edit)
        self.btn_collection = QPushButton("Open")
        self.btn_collection.setFixedWidth(80)
        self.btn_collection.setToolTip("Install a Nexus collection (mod list)")
        self.btn_collection.clicked.connect(self._on_collection)
        col_row.addWidget(self.btn_collection)
        root.addLayout(col_row)

        root.addWidget(self._hline())

        # updates
        update_row = QHBoxLayout()
        self.update_label = QLabel("Nexus tracked mods")
        update_row.addWidget(self.update_label, 1)
        self.btn_link = QPushButton("Link Untracked")
        self.btn_link.setToolTip("Match mods installed from Nexus archives before tracking existed")
        self.btn_link.clicked.connect(self._on_link_untracked)
        update_row.addWidget(self.btn_link)
        self.btn_updates = QPushButton("Check Updates")
        self.btn_updates.clicked.connect(self._on_check_updates)
        update_row.addWidget(self.btn_updates)
        root.addLayout(update_row)

        self.update_list = QListWidget()
        self.update_list.setToolTip("Double click to open mod page")
        self.update_list.itemDoubleClicked.connect(self._on_open_mod)
        root.addWidget(self.update_list)

        # bottom row
        bottom = QHBoxLayout()
        self.rate_label = QLabel("")
        bottom.addWidget(self.rate_label, 1)
        self.btn_update_all = QPushButton("Update All")
        self.btn_update_all.setEnabled(False)
        self.btn_update_all.clicked.connect(self._on_update_all)
        bottom.addWidget(self.btn_update_all)
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(80)
        self.btn_close.clicked.connect(self.close)
        bottom.addWidget(self.btn_close)
        root.addLayout(bottom)

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _refresh(self):
        cfg=read_nexus_cfg()
        if cfg["API_KEY"]:
            self.key_edit.setText(cfg["API_KEY"])
            self.user_label.setText(f"Logged in as {cfg['USER']}"+(" (premium)" if cfg["PREMIUM"] else " (free account, downloads go through the website)"))
        else: self.user_label.setText("Not logged in")
        has_key=bool(cfg["API_KEY"])
        for btn in [self.btn_clear_key, self.btn_download, self.btn_collection, self.btn_updates, self.btn_link]: btn.setEnabled(has_key)

        tracked=sum(1 for i in self.parent.mod_info.values() if i.get("tracked"))
        guessed=sum(1 for i in self.parent.mod_info.values() if i.get("guessed"))
        self.update_label.setText(f"{tracked} tracked mods"+(f", {guessed} untracked" if guessed else ""))
        self.btn_link.setVisible(guessed>0)

        if is_handler_registered(): self.handler_label.setText("nxm:// links open in BDSM")
        else:
            cur=get_current_handler()
            self.handler_label.setText("nxm:// links not handled by BDSM"+(f"\n(current: {cur})" if cur else ""))

        hourly,daily=RATE_LIMITS["HOURLY"],RATE_LIMITS["DAILY"]
        if hourly is not None or daily is not None: self.rate_label.setText(f"API requests left: {hourly} hourly / {daily} daily")

    def _on_save_key(self):
        key=self.key_edit.text().strip()
        if not key: return
        self.user_label.setText("Validating...")
        self.user_label.repaint()
        try: set_api_key(key)
        except NexusError as e:
            QMessageBox.warning(self, "Nexus Error", f"Could not validate API key:\n{e}")
        self._refresh()

    def _on_clear_key(self):
        reply=QMessageBox.question(self, "Nexus", "Remove saved API key?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply!=QMessageBox.StandardButton.Yes: return
        clear_api_key()
        self.key_edit.clear()
        self._refresh()

    def _on_register(self):
        try: register_nxm_handler()
        except Exception as e:
            QMessageBox.warning(self, "Nexus Error", f"Could not register nxm handler:\n{e}")
        self._refresh()

    def _on_download(self):
        url=self.nxm_edit.text().strip()
        if not url: return
        self.nxm_edit.clear()
        handle_nxm_link(self.parent, url)

    def _on_collection(self):
        text=self.col_edit.text().strip()
        if not text: return
        domains=get_instance_domains(self.parent.cfg)
        try: domain,slug,revision=parse_collection_ref(text, domains[0] if domains else None)
        except NexusError as e: QMessageBox.warning(self, "Nexus Error", str(e)); return
        if domain and not _confirm_domain(self.parent, domain): return
        self.col_edit.clear()
        self.close()
        open_collection(self.parent, slug, domain, revision)

    def _on_link_untracked(self):
        domains=get_instance_domains(self.parent.cfg)
        if not domains: QMessageBox.warning(self, "Nexus", "Unknown game for this instance"); return
        self.btn_link.setEnabled(False)
        def done(result, error):
            self.btn_link.setEnabled(True)
            self.parent.refresh_mod_info()
            self.parent.auto_save_load_order()
            if error: QMessageBox.warning(self, "Nexus Error", str(error)); return
            linked,failed=result
            msg=f"Linked {len(linked)} mods"
            if failed: msg+=f"\n\nCould not verify (use Nexus > Link to Nexus Mod):\n"+"\n".join(failed[:20])
            QMessageBox.information(self, "Nexus", msg)
            self._refresh()
        run_task(self.parent, lambda: auto_link_guessed(self.parent.cfg["SOURCE_DIR"], self.parent.mod_info, domains),
                 done, status="Linking untracked mods...")

    def _on_check_updates(self):
        self.update_list.clear()
        self.btn_updates.setEnabled(False)
        self.update_label.setText("Checking...")
        check_updates_gui(self.parent, done_cb=self._on_updates_complete)

    def _on_updates_complete(self, results, error):
        self.btn_updates.setEnabled(True)
        if error:
            self.update_label.setText("Update check failed")
            QMessageBox.warning(self, "Nexus Error", f"Update check failed:\n{error}")
            return
        outdated=[r for r in results if r["outdated"]]
        self.update_label.setText(f"{len(outdated)} of {len(results)} tracked mods have updates")
        self.btn_update_all.setEnabled(bool(outdated))
        self.outdated=[r["mod"] for r in outdated]
        for r in sorted(results, key=lambda r: (not r["outdated"], r["mod"].lower())):
            if r["status"]!="published": text=f"✕  {r['mod']}  ({r['status']})"
            elif r["outdated"]: text=f"⬆  {r['mod']}  {r['version']} → {r['latest']}"
            else: text=f"✓  {r['mod']}  {r['version']}"
            item=QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, r["url"])
            item.setToolTip(r["url"])
            self.update_list.addItem(item)
        hourly,daily=RATE_LIMITS["HOURLY"],RATE_LIMITS["DAILY"]
        if hourly is not None or daily is not None: self.rate_label.setText(f"API requests left: {hourly} hourly / {daily} daily")

    def _on_update_all(self):
        self.btn_update_all.setEnabled(False)
        update_mods(self.parent, self.outdated)

    def _on_open_mod(self, item):
        QDesktopServices.openUrl(QUrl(item.data(Qt.ItemDataRole.UserRole)))


# CLI

def cli_check_updates(cfg):
    from bdsm import load_list_meta
    domains=get_instance_domains(cfg)
    infos=build_mod_info(cfg["SOURCE_DIR"], load_list_meta(), domains[0] if domains else "")
    results=check_updates(cfg["SOURCE_DIR"], infos)
    if not results: print("no nexus tracked mods found"); return
    for r in results:
        if r["outdated"]: print(f"update available: {r['mod']} {r['version']} -> {r['latest']} ({r['url']})")
    print(f"{len([r for r in results if r['outdated']])} of {len(results)} tracked mods have updates")
