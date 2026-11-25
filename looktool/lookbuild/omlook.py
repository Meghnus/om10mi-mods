"""omlook.py - read a `NAME.omlook.zip` (made by the web panel's "Export pack"): the pack JSON + the exact LUT files the looks were made from + a README.

Layout: `NAME.pack.json` (one, at the root), `luts/<file>` (the source tables, matched by name and sha256 against the pack), `README.txt` (ignored).
Entries are read by their base name only (no path of the zip is ever used on disk); sizes are capped; the zip's CRCs are verified.
"""
import hashlib
import json
import os
import zipfile

MAX_PACK = 1 << 20
MAX_LUT = 64 << 20
MAX_LUTS = 64


class OmlookError(Exception):
    """the zip is not a usable look pack (message says what to do)"""


def is_omlook(path):
    return str(path).lower().endswith(".zip")


def extract(zip_path, dest):
    """-> (pack_path, lut_dir) inside dest (created). Raises OmlookError."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as e:
        raise OmlookError("%s is not a readable zip file (%s). Export it again from the panel." % (os.path.basename(zip_path), e))
    with zf:
        packs = [i for i in zf.infolist() if not i.is_dir() and "/" not in i.filename.replace("\\", "/") and i.filename.lower().endswith(".pack.json")]
        if len(packs) != 1:
            raise OmlookError("the zip must hold exactly one *.pack.json (found %d). Export it again from the panel." % len(packs))
        luts = [i for i in zf.infolist() if not i.is_dir() and i.filename.replace("\\", "/").startswith("luts/")]
        if len(luts) > MAX_LUTS:
            raise OmlookError("the zip holds too many LUT files (%d)." % len(luts))
        if packs[0].file_size > MAX_PACK or any(i.file_size > MAX_LUT for i in luts):
            raise OmlookError("a file in the zip is far larger than a look pack or a LUT: refusing it.")
        lut_dir = os.path.join(dest, "luts")
        os.makedirs(lut_dir, exist_ok=True)
        try:
            pack_path = os.path.join(dest, "pack.json")
            with open(pack_path, "wb") as fh:
                fh.write(zf.read(packs[0]))
            for i in luts:
                name = os.path.basename(i.filename.replace("\\", "/"))
                if name:
                    with open(os.path.join(lut_dir, name), "wb") as fh:
                        fh.write(zf.read(i))
        except (zipfile.BadZipFile, OSError) as e:
            raise OmlookError("the zip is damaged (%s). Export it again from the panel." % e)
    return pack_path, lut_dir


def lut_files_needed(pack_path):
    """[(look name, slot, source name, sha256)] of the looks that name a source table"""
    with open(pack_path, "rb") as fh:
        data = json.loads(fh.read().decode("utf-8"))
    out = []
    for look in data.get("looks") or []:
        src = look.get("source") or {}
        if src.get("name"):
            out.append((look.get("name"), look.get("slot"), src["name"], (src.get("sha256") or "").lower()))
    return out


def check_luts(pack_path, lut_dir):
    """-> (missing, wrong): [(look, slot, file)] not present in lut_dir, [(look, slot, file)] present with another sha256"""
    missing, wrong = [], []
    for look, slot, name, sha in lut_files_needed(pack_path):
        p = os.path.join(lut_dir, os.path.basename(name))
        if not os.path.isfile(p):
            missing.append((look, slot, name))
            continue
        with open(p, "rb") as fh:
            got = hashlib.sha256(fh.read()).hexdigest()
        if sha and got != sha:
            wrong.append((look, slot, name))
    return missing, wrong


def prepare(zip_path, extra_lut_dir, dest):
    """extract the zip into dest; LUT files named by the pack but absent from the zip are taken from extra_lut_dir when given. -> (pack_path, lut_dir)"""
    pack_path, lut_dir = extract(zip_path, dest)
    if extra_lut_dir:
        for _look, _slot, name, _sha in lut_files_needed(pack_path):
            src, dst = os.path.join(extra_lut_dir, os.path.basename(name)), os.path.join(lut_dir, os.path.basename(name))
            if not os.path.isfile(dst) and os.path.isfile(src):
                with open(src, "rb") as fi, open(dst, "wb") as fo:
                    fo.write(fi.read())
    return pack_path, lut_dir
