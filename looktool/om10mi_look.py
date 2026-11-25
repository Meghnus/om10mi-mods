#!/usr/bin/env python3
"""om10mi_look.py - write a look made in the web page (look file v2) into one look slot of your own E-M10 Mark I release image.

    python om10mi_look.py --look my.look.json --slot 9 --base E1139999.BIN --out out_dir [--lut source.cube]
    python om10mi_look.py --pack NAME.omlook.zip --base E1139999.BIN --out out_dir          (zip from the web panel: carries its LUT files)
    python om10mi_look.py --selftest --base E1139999.BIN

--base   the version 94 image built from YOUR OWN official firmware by om10mi.py (sha1 is checked). Or give --stock OLY_E_113_1400_0000_0000.BIN
         and --om10mi path/to/om10mi.py: the release image is built first (a minute or so).
--slot   1..18 except 2; the slot's base mode must be the look's base mode (the tool lists the compatible slots).
--lut    the source .cube / .xmp (its sha256 must equal source.sha256): the builder then re-scores the exact model against the target and
         refuses when it differs from the file's predicted dE by more than --gate (0.5). Without it the gate compares the browser model and
         the exact model on the synthetic reference set (target-free).
The slot's menu name is rewritten too (--name / --keep-name) and its two icon images (unselected / selected) get the universal film roll without text
         (--keep-icon leaves the old look's icon, with its old label).
Output   out_dir/E113_LOOK_SLOT<N>_TEST.BIN (or DCOLYMP/E1139999.BIN with --card), audit.json / audit.txt (confinement audit), report.json,
         slot_tables.json. The tool never talks to a camera or a card; copying anything to a card is your own decision.
Needs Python 3.10+ and numpy (tone lift and re-score). Standard library otherwise. No firmware is stored in this tool.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lookbuild import audit as A          # noqa: E402
from lookbuild import build as B          # noqa: E402
from lookbuild import container as C      # noqa: E402
from lookbuild import names88 as N       # noqa: E402
from lookbuild import omlook as OM        # noqa: E402
from lookbuild import slots88 as S        # noqa: E402


def selftest(base_bin, allow_other):
    """write the base image's own slot data into every slot: the image must not change (and the container must round-trip)"""
    parts = B.check_base(base_bin, allow_other)
    if C.join_image(parts) != base_bin:
        print("FAIL container round trip")
        return 1
    p0 = bytearray(parts[0].plain())
    S.check_layout(p0)
    p1 = bytearray(parts[1].plain())
    book = N.NameBook(p1)
    bad = 0
    for s in S.WRITABLE:
        r = S.read_slot(p0, s)
        q = bytearray(p0)
        S.write_slot(q, s, r["L16"], r["t3"], r["t2"])
        r1 = bytearray(p1)
        nm = book.current_name(s)
        N.write_name(r1, book, s, nm)
        same = q == p0 and r1 == p1
        img = C.join_image([C.with_plain(parts[0], bytes(q)), C.with_plain(parts[1], bytes(r1))] + parts[2:]) if not same else base_bin
        if not same or hashlib.sha1(img).hexdigest() != hashlib.sha1(base_bin).hexdigest():
            bad += 1
        print("slot %2d  %-9s  %-15s rewrite own matrix / T3 / T2 / name: %s" % (s, S.base_mode(p0, s), repr(nm), "image unchanged" if same else "CHANGED"))
    print("selftest: %s (%d slots)" % ("PASS" if not bad else "FAIL", len(S.WRITABLE)))
    return 1 if bad else 0


def run_pack(a, base):
    from lookbuild import pack as PK
    try:
        res = PK.build_pack(base, a.pack, lut_dir=a.lut_dir, gate=a.gate, allow_other_base=a.allow_other_base, battery=not a.no_battery)
    except B.BuildError as e:
        print("REFUSED: %s\nNothing was written." % e)
        return 1
    os.makedirs(a.out, exist_ok=True)
    if a.card:
        folder = os.path.join(a.out, "DCOLYMP")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "E1139999.BIN")
    else:
        target = os.path.join(a.out, "E113_PACK_TEST.BIN")
    with open(target + ".part", "wb") as fh:
        fh.write(res["image"])
    os.replace(target + ".part", target)
    with open(os.path.join(a.out, "pack_report.json"), "w") as fh:
        json.dump(res["report"], fh, indent=1)
    with open(os.path.join(a.out, "audit.txt"), "w") as fh:
        fh.write(A.format_report(dict(res["audit"], slot="pack")) + "\n")
    print(A.format_report(dict(res["audit"], slot="pack")))
    if res["battery"] is not None:
        from lookbuild import accept88 as AC
        print(AC.format_report(res["battery"]))
    print("wrote %s (sha1 %s)" % (target, res["report"]["sha1"]))
    print("This file has NOT been checked on a camera. Keep your official firmware ready to restore it (you flash at your own risk).")
    return 0


def build_base_from_stock(stock_path, om10mi_path):
    spec = importlib.util.spec_from_file_location("om10mi_public", om10mi_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(stock_path, "rb") as fh:
        stock = fh.read()
    patch = mod.load_patch()
    print("building the release image from your firmware (a minute or so) ...")
    image = mod.build_image(stock, patch)
    if hashlib.sha1(image).hexdigest() != patch["result_sha1"]:
        raise B.BuildError("the release image does not match the published hash")
    return image


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--look", help="look file v2 (JSON)")
    ap.add_argument("--pack", help="look pack (look file v2 + `pack` block, PACK_SPEC_v2.md): replace / rename / reorder in one build (hide is not available). "
                    "Also a NAME.omlook.zip from the web panel (pack + the LUT files it needs; --lut-dir then only fills in files the zip lacks)")
    ap.add_argument("--lut-dir", help="folder holding the source tables of the pack's looks (found by source.name, sha256 checked)")
    ap.add_argument("--no-battery", action="store_true", help="(not recommended) skip the acceptance battery: the report says UNCHECKED")
    ap.add_argument("--index", type=int, default=0, help="which look of the file (default 0)")
    ap.add_argument("--slot", type=int, help="look slot 1..18 (not 2); default = `slot` of the look")
    ap.add_argument("--base", help="version 94 image")
    ap.add_argument("--stock", help="your official firmware (builds the release image first; needs --om10mi)")
    ap.add_argument("--om10mi", help="path to om10mi.py of the public builder")
    ap.add_argument("--lut", help="source LUT of the look (sha256 must equal source.sha256)")
    ap.add_argument("--gate", type=float, default=B.GATE, help="refusal gate in dE (default %.1f)" % B.GATE)
    ap.add_argument("--name", help="menu name of the slot (default: the look's name; at most the slot's capacity, printable ASCII, no '@')")
    ap.add_argument("--keep-name", action="store_true", help="do not rename the slot (the menu keeps the old name and icon label)")
    ap.add_argument("--keep-icon", action="store_true", help="do not write the universal film-roll icon into the slot (the old look's icon stays, with its old label)")
    ap.add_argument("--out", help="output directory")
    ap.add_argument("--card", action="store_true", help="write out/DCOLYMP/E1139999.BIN (the card update name) instead of a TEST name")
    ap.add_argument("--selftest", action="store_true", help="rewrite every slot with its own data and check the image is unchanged")
    ap.add_argument("--allow-other-base", action="store_true", help="skip the release sha1 pin (layout is still checked); for tests")
    a = ap.parse_args(argv)
    try:
        if a.stock:
            if not a.om10mi:
                ap.error("--stock needs --om10mi")
            base = build_base_from_stock(a.stock, a.om10mi)
        elif a.base:
            with open(a.base, "rb") as fh:
                base = fh.read()
        else:
            ap.error("give --base (or --stock and --om10mi)")
        if a.selftest:
            return selftest(base, a.allow_other_base)
        if a.pack:
            if not a.out:
                ap.error("--out is required")
            if OM.is_omlook(a.pack):
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        a.pack, a.lut_dir = OM.prepare(a.pack, a.lut_dir, tmp)
                    except OM.OmlookError as e:
                        print("REFUSED: %s\nNothing was written." % e)
                        return 1
                    return run_pack(a, base)
            return run_pack(a, base)
        if not a.look or not a.out:
            ap.error("--look (or --pack) and --out are required")
        res = B.build(base, a.look, slot=a.slot, lut_path=a.lut, index=a.index, gate=a.gate, allow_other_base=a.allow_other_base, name=a.name, keep_name=a.keep_name, keep_icon=a.keep_icon)
    except B.BuildError as e:
        print("REFUSED: %s\nNothing was written." % e)
        return 1
    except (OSError, S.SlotError) as e:
        print("ERROR: %s" % e)
        return 2
    os.makedirs(a.out, exist_ok=True)
    if a.card:
        folder = os.path.join(a.out, "DCOLYMP")
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, "E1139999.BIN")
    else:
        target = os.path.join(a.out, "E113_LOOK_SLOT%d_TEST.BIN" % res["slot"])
    with open(target + ".part", "wb") as fh:
        fh.write(res["image"])
    os.replace(target + ".part", target)
    with open(os.path.join(a.out, "audit.json"), "w") as fh:
        json.dump(res["audit"], fh, indent=1)
    with open(os.path.join(a.out, "audit.txt"), "w") as fh:
        fh.write(A.format_report(res["audit"]) + "\n")
    with open(os.path.join(a.out, "report.json"), "w") as fh:
        json.dump(res["report"], fh, indent=1)
    with open(os.path.join(a.out, "slot_tables.json"), "w") as fh:
        json.dump(res["tables"], fh)
    print(A.format_report(res["audit"]))
    print("wrote %s (sha1 %s)" % (target, res["report"]["sha1"]))
    print("This file has NOT been checked on a camera. Keep your official firmware ready to restore it (Rule: you flash at your own risk).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
