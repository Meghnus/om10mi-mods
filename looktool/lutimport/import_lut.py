#!/usr/bin/env python3
"""import_lut.py - import a look from .cube / Adobe Creative Profile .xmp (with an RGB table).

    python import_lut.py FILE [--out look.json] [--cube table33.cube] [--name NAME] [--slot N] [--label TXT]
                              [--licence TEXT]

Prints an import report. --out writes a look-file v2 (looks[0].source carries the provenance and the sha256 of the
file, NEVER the table; the parameters of slider presets are written out as look fields). --cube writes the common
33^3 table (a local debugging / fitting aid, not a public artefact when the source licence forbids redistribution).
Nothing is written to any device. Standard library only.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lutcore import LutError, write_cube          # noqa: E402
import imp_cube, imp_xmp   # noqa: E402

LUT_TYPES = ("cube", "xmp-profile")


def detect(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cube":
        return "cube"
    if ext == ".xmp":
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read()
        if imp_xmp.has_rgb_table(head):
            return "xmp-profile"
        raise LutError("this .xmp has no RGB table (slider presets are not supported; use a Creative Profile or a .cube)")
    raise LutError("unknown file type %r (this build reads .cube and Adobe Creative Profile .xmp)" % ext)


def import_any(path, **kw):
    """-> list of ImportResult (one)."""
    kind = detect(path)
    lic = kw.get("licence", "")
    if kind == "cube":
        return [imp_cube.import_cube(path, licence=lic)]
    return [imp_xmp.import_xmp_profile(path, licence=lic)]


def _clean_name(s, limit=17):
    s = re.sub(r"[^\x20-\x7e]", "", s).replace("@", "").strip()
    return (s or "Imported")[:limit]


def make_look(res, name=None, slot=None, label=None, base=None):
    """ImportResult -> look object of a version-2 look file."""
    if res.refused:
        raise LutError(res.refused)
    look = {}
    nm = name or res.source.get("preset_name") or res.source.get("title") or os.path.splitext(res.name)[0]
    look["name"] = _clean_name(nm)
    if slot is not None:
        look["slot"] = int(slot)
    if label:
        look["label"] = label
    src = {k: v for k, v in res.source.items() if v not in (None, "")}
    src["approximate"] = bool(res.approximate)
    if res.kind in LUT_TYPES:
        src["requires_file"] = True
    look["source"] = src
    if base:
        look["base"] = base
    else:
        look["base"] = {"mode": "auto"}
    if res.look:
        for k, v in res.look.items():
            look[k] = v
    notes = "; ".join(res.notes + ["dropped: " + d for d in res.dropped])
    if notes:
        look["notes"] = notes[:200]
    if res.dropped:
        look["extras"] = {"import_dropped": res.dropped}
    return look


def make_lookfile(looks, generator_model=None):
    gen = {"name": "om10mi-lut-import", "version": "0.1"}
    if generator_model:
        gen["model"] = generator_model
    return {"format": "om10mi-look", "version": 2, "target": "E113", "generator": gen, "looks": looks}


def print_report(res, out=sys.stdout):
    out.write("== %s  [%s]%s\n" % (res.name, res.kind, "  APPROXIMATE" if res.approximate else ""))
    if res.native is not None:
        out.write("   native table %d^3%s\n" % (res.native.n, "" if res.native.n == 33 else " (resampled to 33^3)"))
    if res.lut33 is not None:
        st = res.lut33.stats()
        out.write("   33^3: max deviation from identity %.3f, mean %.3f\n" % (st["max_dev_from_identity"], st["mean_dev_from_identity"]))
    for n in res.notes:
        out.write("   note: %s\n" % n)
    for d in res.dropped:
        out.write("   dropped: %s\n" % d)
    if res.refused:
        out.write("   REFUSED: %s\n" % res.refused)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out")
    ap.add_argument("--cube")
    ap.add_argument("--name")
    ap.add_argument("--slot", type=int)
    ap.add_argument("--label")
    ap.add_argument("--licence", default="")
    a = ap.parse_args(argv)
    try:
        results = import_any(a.file, licence=a.licence)
    except (LutError, OSError, ValueError) as e:
        print("import failed: %s" % e)
        return 1
    for r in results:
        print_report(r)
    ok = [r for r in results if not r.refused]
    if not ok:
        return 1
    if a.cube:
        if len(ok) > 1:
            print("--cube needs a single preset: pass --preset")
            return 1
        write_cube(a.cube, ok[0].lut33, title=ok[0].source.get("title") or ok[0].name,
                   comment="om10mi LUT import, common 33^3 lattice (local use; check the source licence before sharing)")
        print("wrote %s" % a.cube)
    if a.out:
        looks = [make_look(r, a.name if len(ok) == 1 else None, a.slot if len(ok) == 1 else None, a.label) for r in ok]
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(make_lookfile(looks), fh, indent=1)
            fh.write("\n")
        print("wrote %s (%d look(s))" % (a.out, len(looks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
