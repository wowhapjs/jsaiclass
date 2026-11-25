#!/usr/bin/env python3
"""Untrusted student ZIP hosting core. No production activation or host code execution."""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

MAX_ZIP = 50 * 1024**2
MAX_EXPANDED = 250 * 1024**2
MAX_FILES = 5000
MAX_FILE = 50 * 1024**2
FOLDER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}$")
SAFE_IMAGE = re.compile(r"^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$")
DB_MARKERS = {"@supabase/supabase-js":"supabase","firebase":"firebase",
              "pg":"postgres","postgres":"postgres","@prisma/client":"postgres",
              "mongoose":"mongodb","mysql2":"mysql","better-sqlite3":"sqlite"}
PUBLIC_ENV = re.compile(r"^VITE_(?:SUPABASE_(?:URL|ANON_KEY|PUBLISHABLE_KEY)|FIREBASE_[A-Z0-9_]+|PUBLIC_[A-Z0-9_]+)$")
DENIED = {".git",".svn","node_modules",".npmrc",".yarnrc",".yarnrc.yml",
          ".pnpmfile.cjs",".netrc","id_rsa","id_ed25519"}
ASSET_TYPES = {".html",".htm",".js",".mjs",".css",".json",".webmanifest",".png",
 ".jpg",".jpeg",".webp",".gif",".svg",".ico",".avif",".woff",".woff2",".ttf",
 ".otf",".mp3",".wav",".ogg",".mp4",".webm",".wasm",".txt",".pdf",".xml",".csv"}
class HostingError(Exception):
    pass

def fail(code):
    raise HostingError(code)

def slug(value):
    if not FOLDER.fullmatch(value) or value.lower() in {"api","assets","versions","login","logout","admin"}:
        fail("INVALID_FOLDER_NAME")
    return value

def checked_parts(name):
    if not name or "\\" in name or ":" in name or any(ord(c)<32 for c in name):
        fail("UNSAFE_ZIP_PATH")
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in {"","..","."} for x in name.rstrip("/").split("/")):
        fail("UNSAFE_ZIP_PATH")
    for part in p.parts:
        low=part.lower()
        if low in DENIED or (low.startswith(".env") and low != ".env.example") or low.endswith((".pem",".key",".p12",".pfx")):
            fail("PRIVATE_OR_UNSUPPORTED_FILE")
    return p.parts

def extract(source, target):
    if source.stat().st_size > MAX_ZIP: fail("ZIP_TOO_LARGE")
    with zipfile.ZipFile(source) as archive:
        entries=archive.infolist()
        if len(entries)>MAX_FILES: fail("TOO_MANY_FILES")
        if sum(x.file_size for x in entries)>MAX_EXPANDED: fail("EXPANDED_LIMIT")
        seen=set()
        for item in entries:
            parts=checked_parts(item.filename)
            canonical="/".join(parts).casefold()
            if canonical in seen: fail("DUPLICATE_ZIP_PATH")
            seen.add(canonical)
            if item.flag_bits & 1: fail("ENCRYPTED_ZIP")
            mode=(item.external_attr>>16)&0o170000
            if mode not in (0,stat.S_IFREG,stat.S_IFDIR): fail("UNSAFE_ZIP_FILE_TYPE")
            if item.file_size>MAX_FILE or (item.file_size>1024**2 and item.file_size>max(item.compress_size,1)*250):
                fail("ZIP_EXPANSION_LIMIT")
            dest=target.joinpath(*parts)
            if item.is_dir():
                dest.mkdir(parents=True,exist_ok=True)
            else:
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(item) as src, dest.open("xb") as out:
                    remaining=item.file_size
                    while remaining:
                        data=src.read(min(remaining,65536))
                        if not data: fail("TRUNCATED_ZIP")
                        out.write(data); remaining-=len(data)
                    if src.read(1): fail("ZIP_SIZE_MISMATCH")
    roots=[target,*[x for x in target.iterdir() if x.is_dir() and not x.name.startswith(".")]]
    if (target/"package.json").is_file() or (target/"index.html").is_file() or (target/"dist/index.html").is_file():
        return target
    candidates=[p for p in roots[1:] if (p/"package.json").is_file() or (p/"index.html").is_file() or (p/"dist/index.html").is_file()]
    if len(candidates)!=1: fail("ENTRY_OR_PROJECT_NOT_FOUND")
    return candidates[0]

def read_json(path):
    if not path.exists(): return {}
    if path.stat().st_size>256*1024: fail("MANIFEST_TOO_LARGE")
    result=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result,dict): fail("INVALID_MANIFEST")
    return result

def inspect(root):
    pkg=read_json(root/"package.json")
    manifest=read_json(root/"dmt-host.json")
    deps={**pkg.get("dependencies",{}),**pkg.get("devDependencies",{})}
    dbs={v for k,v in DB_MARKERS.items() if k in deps}
    env=set()
    local=False
    server=False
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size>512*1024: continue
        if path.name==".env.example":
            env.update(re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]*)\s*=",path.read_text(errors="replace")))
        if path.suffix.lower() not in {".js",".mjs",".cjs",".ts",".tsx",".jsx",".py",".sql",".html"}: continue
        content=path.read_text(errors="replace")
        local |= "localStorage" in content or "indexedDB" in content
        if re.search(r"from\s+['\"](?:@supabase/supabase-js|firebase[/\w-]*|pg|postgres|mongoose|mysql2|better-sqlite3)['\"]",content):
            for k,v in DB_MARKERS.items():
                if k in content: dbs.add(v)
        if re.search(r"\b(?:express\s*\(|app\.listen\s*\(|createServer\s*\(|psycopg|sqlite3\.connect)\b",content):
            server=True
    vite="vite" in deps
    mode="vite" if vite else "static" if (root/"index.html").is_file() or (root/"dist/index.html").is_file() else "unsupported"
    if pkg and not vite and not (root/"dist/index.html").is_file():
        mode="unsupported"
    db=manifest.get("database",{})
    if not isinstance(db,dict): fail("INVALID_DB_MANIFEST")
    dbmode=db.get("mode","review" if dbs or server else "browser" if local else "none")
    if dbmode not in {"none","browser","external","managed-postgres","review"}: fail("INVALID_DB_MODE")
    if dbmode=="external" and db.get("provider") not in {"supabase","firebase","https-api"}: fail("UNSUPPORTED_EXTERNAL_PROVIDER")
    if dbmode=="managed-postgres" or server: state="runtime_review_required"
    elif mode=="unsupported": state="unsupported_framework"
    elif dbmode=="review" or (dbs and dbmode in {"browser","none"}): state="db_review_required"
    elif dbmode=="external": state="public_config_required"
    else: state="buildable"
    return {"framework":mode,"database_mode":dbmode,"database_candidates":sorted(dbs),
            "browser_storage":bool(local),"backend_detected":bool(server),"env_names":sorted(env),
            "lockfile":(root/"package-lock.json").is_file(),"status":state,
            "external_provider":db.get("provider") if dbmode=="external" else None}

def verify_dist(root):
    if not (root/"index.html").is_file() or (root/"index.html").is_symlink(): fail("INDEX_NOT_FOUND")
    size=count=0
    for p in root.rglob("*"):
        if p.is_symlink() or not (p.is_dir() or p.is_file()): fail("UNSAFE_BUILD_OUTPUT")
        if p.is_dir(): continue
        parts=p.relative_to(root).parts
        if any(x.startswith(".") or x.lower() in DENIED for x in parts): fail("PRIVATE_BUILD_OUTPUT")
        if p.suffix.lower() not in ASSET_TYPES: fail("UNSUPPORTED_BUILD_ASSET")
        count+=1; size+=p.stat().st_size
        if count>MAX_FILES or size>MAX_EXPANDED or p.stat().st_size>MAX_FILE: fail("BUILD_OUTPUT_LIMIT")
    return {"entry":"index.html","files":count,"bytes":size}

def public_config(path, plan):
    cfg=read_json(path) if path else {}
    if plan["database_mode"]!="external" and cfg: fail("UNEXPECTED_PUBLIC_CONFIG")
    if plan["database_mode"]=="external" and not cfg: fail("PUBLIC_CONFIG_REQUIRED")
    for k,v in cfg.items():
        if not PUBLIC_ENV.fullmatch(k) or not isinstance(v,str) or len(v)>4096:
            fail("INVALID_PUBLIC_CONFIG")
        # Never pass admin/service-role credentials to a client build.
        if re.search(r"service.role|sb_secret_|sk_live_|private.key|-----BEGIN",v,re.I):
            fail("SECRET_IN_PUBLIC_CONFIG")
        if v.count(".")==2:
            import base64
            try:
                part=v.split(".")[1]
                payload=json.loads(base64.urlsafe_b64decode(part+"="*(-len(part)%4)))
                if payload.get("role") not in (None,"anon"): fail("SECRET_IN_PUBLIC_CONFIG")
            except (ValueError,TypeError,UnicodeError): pass
    return cfg

def build(root, plan, image, cfg):
    if plan["status"] not in {"buildable","public_config_required"}: fail("REVIEW_REQUIRED")
    if plan["framework"]=="static":
        return root/"dist" if (root/"dist/index.html").is_file() else root
    if not image or not SAFE_IMAGE.fullmatch(image): fail("TRUSTED_BUILD_IMAGE_REQUIRED")
    if os.getuid()==0: fail("NON_ROOT_WORKER_REQUIRED")
    # Trusted image contains Node + a pre-populated offline npm cache.
    # Never use npm scripts or mount credentials, Docker socket or host services.
    name="dmt-build-"+uuid.uuid4().hex
    env={**os.environ,**cfg}
    args=["docker","run","--name",name,"--pull=never","--network=none","--read-only",
          "--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=128",
          "--memory=512m","--memory-swap=512m","--cpus=0.75",
          "--user",f"{os.getuid()}:{os.getgid()}","--tmpfs","/tmp:rw,nosuid,nodev,size=192m",
          "--mount",f"type=bind,src={root},dst=/work","-w","/work",
          "-e","HOME=/tmp","-e","npm_config_cache=/tmp/npm-cache"]
    for k in cfg: args+=["-e",k]
    args += ["--entrypoint","/bin/sh",image,"-ec",
             'cp -a /opt/npm-cache /tmp/npm-cache; if [ -f package-lock.json ]; then npm ci --offline --ignore-scripts --no-audit --no-fund; else npm install --offline --ignore-scripts --no-audit --no-fund; fi; ./node_modules/.bin/vite build --base=./']
    try:
        with tempfile.TemporaryFile() as log:
            proc=subprocess.run(args,env=env,stdout=log,stderr=log,timeout=240)
            if proc.returncode: fail("ISOLATED_BUILD_FAILED")
    except subprocess.TimeoutExpired: fail("BUILD_TIMEOUT")
    finally:
        subprocess.run(["docker","rm","-f",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False,timeout=20)
    return root/"dist"

def prepare(source, output=None, image=None, config=None):
    with tempfile.TemporaryDirectory(prefix="dmt-source-") as temp:
        root=extract(source,Path(temp))
        plan=inspect(root)
        if output is None: return plan
        if output.exists(): fail("OUTPUT_ALREADY_EXISTS")
        cfg=public_config(config,plan)
        dist=build(root,plan,image,cfg)
        result=verify_dist(dist)
        output.parent.mkdir(parents=True,exist_ok=True)
        # Only publish to a private staging directory. Activation is a separate DB transaction.
        with tempfile.TemporaryDirectory(prefix=".dmt-publish-",dir=output.parent) as parent:
            candidate=Path(parent)/"artifact"
            shutil.copytree(dist,candidate)
            verify_dist(candidate)
            candidate.rename(output)
        return {**plan,"artifact":result,"status":"artifact_ready"}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("zip",type=Path)
    parser.add_argument("--output",type=Path,help="Private staging artifact directory, not a live web root")
    parser.add_argument("--image",help="Trusted local digest-pinned build image")
    parser.add_argument("--public-config",type=Path)
    args=parser.parse_args()
    try:
        print(json.dumps(prepare(args.zip,args.output,args.image,args.public_config)))
    except (HostingError,zipfile.BadZipFile,ValueError,OSError,TypeError) as err:
        # Do not echo uploaded contents, file paths, package output or credentials.
        print(json.dumps({"status":"failed","code":str(err) if isinstance(err,HostingError) else "INVALID_ARCHIVE_OR_CONFIG"}))
        raise SystemExit(1)
if __name__=="__main__": main()
