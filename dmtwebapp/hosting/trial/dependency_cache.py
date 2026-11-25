"""Dependency cache identity and verified lock handling for DMT Vite workers.
Only the trusted worker may write cache entries. Student builds mount node_modules
read-only and offline. Do not use this module in a publicly exposed Docker API.
"""
import hashlib
import json
import re
from pathlib import Path

SCHEMA = 1
SEMVER = re.compile(r"^[~^]?\d+\.\d+\.\d+$")
PKG = re.compile(r"^(?:@[-a-z0-9_]+/)?[-a-z0-9_.]+$")
IMAGE = re.compile(r"^[\w./:-]+@sha256:[0-9a-f]{64}$")
# Explicitly reviewed profile for the supplied FindOne example. Do not silently
# prune unrelated student projects based on an incomplete source import scan.
FINDONE_FULL = {
    "@google/genai":"^2.4.0","@tailwindcss/vite":"^4.3.3",
    "@vitejs/plugin-react":"^6.1.1","lucide-react":"^0.546.0",
    "react":"^19.0.1","react-dom":"^19.0.1","vite":"^8.3.0",
    "express":"^4.21.2","dotenv":"^17.2.3","motion":"^12.23.24",
    "@types/node":"^22.14.0","@types/react":"^19.3.0",
    "@types/react-dom":"^19.3.0","autoprefixer":"^10.4.21",
    "esbuild":"^0.25.0","tailwindcss":"^4.3.3","tsx":"^4.21.0",
    "typescript":"^7.0.2","@types/express":"^4.17.21",
}
FINDONE_KEYS = {"react","react-dom","lucide-react","vite","@vitejs/plugin-react","@tailwindcss/vite","tailwindcss"}

def checked_dependencies(deps):
    if not isinstance(deps,dict) or not 1<=len(deps)<=150:
        raise ValueError("INVALID_DEPENDENCIES")
    if any(not isinstance(k,str) or not isinstance(v,str) or not PKG.fullmatch(k)
           or not SEMVER.fullmatch(v) for k,v in deps.items()):
        raise ValueError("DEPENDENCY_SPEC_REVIEW_REQUIRED")
    return dict(sorted(deps.items()))

def cache_key(deps,image,platform="linux/amd64"):
    deps=checked_dependencies(deps)
    if not IMAGE.fullmatch(image): raise ValueError("UNPINNED_IMAGE")
    obj={"schema":SCHEMA,"deps":deps,"image":image,"platform":platform,
         "lifecycle_scripts":False,"registry":"https://registry.npmjs.org/"}
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def verified_lock(path,expected):
    lock=json.loads(Path(path).read_text())
    packages=lock.get("packages")
    if not isinstance(packages,dict) or packages.get("",{}).get("dependencies")!=expected:
        raise ValueError("LOCK_MANIFEST_MISMATCH")
    for name,entry in packages.items():
        if name=="":
            continue
        if (entry.get("link") or not entry.get("resolved","").startswith("https://registry.npmjs.org/")
            or not re.fullmatch(r"sha(?:256|384|512)-[A-Za-z0-9+/=]+",entry.get("integrity",""))):
            raise ValueError("LOCK_REGISTRY_OR_INTEGRITY_INVALID")
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dependency_profile(deps,reviewed_findone=False):
    deps=checked_dependencies(deps)
    if reviewed_findone:
        if deps!=FINDONE_FULL: raise ValueError("PROFILE_MANIFEST_MISMATCH")
        return {k:deps[k] for k in sorted(FINDONE_KEYS)}
    return deps

def cache_hit(cache_dir,deps,image,platform="linux/amd64"):
    path=Path(cache_dir)/cache_key(deps,image,platform)
    try:
        marker=json.loads((path/"READY.json").read_text())
        lock_sha=verified_lock(path/"package-lock.json",deps)
        if marker!={"key":path.name,"lock_sha256":lock_sha}: return None
        if not (path/"node_modules"/".bin"/"vite").is_file(): return None
        return path
    except (OSError,ValueError,KeyError,TypeError):
        return None
