"""guide.py - the whole "stock firmware + pack + LUT files -> card-ready image" run in plain language, for the in-browser build (webbuild.py, Pyodide).

Same code path as the command line (om10mi.build_image, pack.build_pack): the same pack and the same stock give the same bytes. Every refusal is turned into
what to do next. Nothing is written here; the caller gets the bytes. om10mi.py (the public builder) must be importable.
"""
import hashlib
import json
import os

from . import build as B
from . import container as C
from . import names88 as N
from . import omlook as Z
from . import pack as PK

STOCK_NAME = "OLY_E_113_1400_0000_0000.BIN"
CARD_NAME = "E1139999.BIN"

HOWTO = """HOW TO FLASH  (E-M10 Mark I, your look pack: %(name)s)

Read this once, then do it step by step. You flash at your own risk; nothing here has been tried on your camera.

1. Full battery. Back up the card, then format the card IN THE CAMERA.
2. Unzip this file and copy the folder DCOLYMP to the root of the card, so that DCOLYMP\\E1139999.BIN exists on the card.
3. Camera off. Insert the card.
4. HOLD the OK button while you switch the camera on. The screen stays black.
5. The AF lamp on the front lights orange. Do NOT switch the camera off while this runs. Wait until the lamp blinks rapidly: that means it is finished.
6. Switch off, take the battery out for a moment, put it back, switch on.
7. Delete the DCOLYMP folder from the card.

Go back to the official firmware: make a folder DCOLYMP on the card, copy your own official OLY_E_113_1400_0000_0000.BIN into it, rename it to
E1139999.BIN, and repeat steps 3 to 7.

What changed in this image (compared with the standard version 94 image):
%(changes)s

To change or add looks later: open the panel, Open pack, pick %(name)s.omlook.zip (in this zip, next to DCOLYMP), edit, and Build firmware again from the
official firmware. Never build on top of this E1139999.BIN: it already holds your looks and the panel refuses it.

Image         : DCOLYMP\\E1139999.BIN   (sha1 %(sha1)s)
Made from     : %(stock)s + the looks of %(name)s
Never copy a firmware of another camera model to the card.
"""


class Stop(Exception):
    """a plain-language reason to stop; nothing was produced"""


def explain(e):
    """plain-language text for a refusal of the builder (what to do next)"""
    look = getattr(e, "look_name", None)
    quoted = '"%s"' % look if look else "A look"
    if isinstance(e, B.LutNotFound):
        return ('The LUT file %s is missing, so look "%s" cannot be checked.\n'
                "Import that LUT again in the panel (Choose file) and build once more." % (e.lut_name, e.look_name))
    if isinstance(e, B.GateRefused):
        if e.kind == "lut":
            return ('%s is too far from what the camera can do in %s: the camera version scores %.2f dE against your LUT, the panel predicted %.2f.\n'
                    "Pick another base mode for this look (the panel ranks them), or another LUT, add it to the pack again and build once more." % (quoted, e.mode, e.de, e.ref))
        return ('%s cannot be matched safely in %s (our two models of the camera disagree by %.2f dE).\n'
                "Pick another base mode for this look, add it to the pack again and build once more." % (quoted, e.mode, e.de))
    m = str(e)
    if "composed ORF coefficient" in m or "slot writer refused" in m:
        return "%s makes colour numbers the camera cannot hold in its slot.\nPick another base mode or a milder LUT and build once more.\n(%s)" % (quoted, m)
    if "has sha256" in m:
        return "A LUT file is not the one the look was made from.\nImport the original LUT again and build once more.\n(%s)" % m
    if "is not the image the pack was made for" in m:
        return "This pack was made for a different release than this page builds.\nRe-create the pack with the current panel.\n(%s)" % m
    if "hide is experimental" in m:
        return "Hiding looks is not available. Show the hidden looks again and build once more."
    if "pack refused by the checker" in m or "no `pack` block" in m or "cannot read the pack" in m:
        return "The pack is not valid.\nRe-create it with the panel.\n(%s)" % m
    if "order / hide" in m or "rename of slot" in m:
        return "The menu order or a name in your pack cannot be written.\nCheck the names and the order and build once more.\n(%s)" % m
    if "acceptance battery" in m or "pack audit failed" in m:
        return "The safety checks refused this combination, so nothing was built.\nTry fewer looks or other base modes and build once more.\n(%s)" % m
    return "The builder refused this pack, nothing was built.\n(%s)" % m


def accepted_files(patch):
    """the ONLY files a build may start from, by sha1 (one table; a new release adds its sha1 to its patch file, nothing here): {sha1: ("stock" | "release", size)}"""
    return {patch["stock_sha1"]: ("stock", patch["stock_size"]), patch["result_sha1"]: ("release", patch["result_size"])}


def classify(data, patch, label="This file"):
    """"stock" = the official v1.4 firmware (the version 94 image is built from it first), "release" = the unmodified version 94 image; anything else is refused.
    -> (kind, sha1)"""
    sha = hashlib.sha1(data).hexdigest()
    hit = accepted_files(patch).get(sha)
    if hit is None or hit[1] != len(data):
        raise Stop("%s is not the official v1.4 firmware or the unmodified v94 image (this file: %d bytes, sha1 %s...).\n"
                   "Pick the official OLY_E_113_1400_0000_0000.BIN (always works). A file that already holds a look pack, a test image or a firmware of "
                   "another model or version is never used.%s" % (label, len(data), sha[:8],
                   "\nTo change looks, open the .omlook.zip you saved with it instead (panel: Open pack)." if len(data) == patch["result_size"] else ""))
    return hit[0], sha


def check_pack(pack_path, lut_dir):
    try:
        data, _warns = PK.load_pack(pack_path)
    except B.BuildError as e:
        raise Stop(explain(e))
    missing, wrong = Z.check_luts(pack_path, lut_dir)
    if missing:
        raise Stop("LUT file(s) missing: %s.\nImport them again in the panel (Choose file) and build once more."
                   % ", ".join('%s (look "%s")' % (f, lk) for lk, _s, f in missing))
    if wrong:
        raise Stop("These LUT file(s) are not the ones the looks were made from: %s.\nImport the original files again and build once more."
                   % ", ".join('%s (look "%s")' % (f, lk) for lk, _s, f in wrong))
    return data


NO_CHANGE = "This file is the standard version 94 image (no look changes)."


def describe_changes(base, data):
    """what the pack changes, one line each: replaced looks (old menu name -> new name, LUT file), renames, menu order. [] when nothing changes"""
    pack = data.get("pack") or {}
    book = N.NameBook(bytearray(C.split_image(base)[1].plain()))
    out, now = [], {}
    for look in data.get("looks") or []:
        s = look["slot"]
        now[s] = look.get("name")
        src = (look.get("source") or {}).get("name")
        out.append("slot %d %s -> %s%s" % (s, book.current_name(s), look.get("name"), " (%s)" % src if src else ""))
    for k, nm in sorted((pack.get("renames") or {}).items(), key=lambda kv: int(kv[0])):
        if int(k) not in now:
            now[int(k)] = nm
            out.append("slot %s renamed %s -> %s" % (k, book.current_name(int(k)), nm))
    order = list(pack.get("order") or [])
    if order:
        names = [now.get(x) or book.current_name(x) if isinstance(x, int) else x for x in order]
        out.append("menu order: %s%s go first" % (", ".join(names[:14]), ", ..." if len(names) > 14 else ""))
    return out


def build_all(stock, pack_path, lut_dir, say, label="This file"):
    """-> dict(image, sha1, stock_sha1, battery=(n, failed)). Raises Stop with the plain-language reason; nothing is produced then."""
    import om10mi as OM
    patch = OM.load_patch()
    data = check_pack(pack_path, lut_dir)
    say("[1/3] Checking your file ...")
    kind, in_sha = classify(stock, patch, label)
    if kind == "release":
        say("      OK: this is the unmodified version 94 image; building the version 94 image is skipped.")
        base, stock_sha = stock, None
        say("[2/3] (skipped)")
    else:
        say("      OK: this is the official firmware 1.4.")
        stock_sha = in_sha
        say("[2/3] Building the version 94 image from it ...")
        try:
            base = OM.build_image(stock, patch)
        except OM.BuildError as e:
            raise Stop("The firmware could not be processed: %s" % e)
        sha = hashlib.sha1(base).hexdigest()
        if sha != patch["result_sha1"]:
            raise Stop("The version 94 image does not match the published hash (%s). Nothing was built." % sha[:8])
        say("      OK: version 94 image, sha1 %s..." % sha[:8])
    changes = describe_changes(base, data)
    say("This pack changes:" if changes else NO_CHANGE)
    for c in changes:
        say("      " + c)
    say("[3/3] Building your looks (every look is fitted, the result is checked) ...")

    def log(line):
        if line.startswith("--- look"):
            say("      " + line[4:].split(" (LUT file")[0])
        elif line.startswith("acceptance battery"):
            say("      checking the written image with the acceptance checks ...")
        elif line.startswith("rename slot"):
            say("      " + line)
        elif line.startswith("order:"):
            say("      " + line.split(";")[0])
    try:
        res = PK.build_pack(base, pack_path, lut_dir=lut_dir, log=log)
    except B.BuildError as e:
        raise Stop(explain(e))
    bat = res["battery"] or []
    fails = sum(1 for r in bat if r[1] == "FAIL")
    say("      OK: safety checks passed (%d checks, %d failed), image sha1 %s..." % (len(bat), fails, res["report"]["sha1"][:8]))
    return dict(image=res["image"], sha1=res["report"]["sha1"], stock_sha1=stock_sha, base_kind=kind,
                changes=changes or [NO_CHANGE], origin=("your official firmware (sha1 %s) + version 94" % stock_sha) if stock_sha else ("your unmodified version 94 image (sha1 %s)" % in_sha), battery=(len(bat), fails))
