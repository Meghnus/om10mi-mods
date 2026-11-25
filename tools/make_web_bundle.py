#!/usr/bin/env python3
"""make_web_bundle.py - pack the builder's own Python sources into docs/lut/pyodide/om10mi_py.zip, the code the in-browser build runs (Pyodide).

    python tools/make_web_bundle.py

The zip holds om10mi.py, patch/looks94.json and the looktool modules that the build needs, in the repository layout (so paths resolve exactly as in a checkout).
Deterministic (fixed timestamps). No firmware is involved. Run it again whenever one of these sources changes.
"""
import os
import sys
import zipfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "docs", "lut", "pyodide", "om10mi_py.zip")
FILES = ["om10mi.py", "patch/looks94.json", "looktool/webbuild.py", "looktool/lutfit_check.py", "looktool/lookfile/lookfile_check.py",
         "looktool/web/model-cm-v2-web1.json"]
DIRS = [("looktool/lookbuild", ".py"), ("looktool/lutimport", ".py")]


def main():
    names = list(FILES)
    for d, ext in DIRS:
        names += ["%s/%s" % (d, f) for f in sorted(os.listdir(os.path.join(ROOT, d))) if f.endswith(ext)]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(names):
            zi = zipfile.ZipInfo(n, (2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(os.path.join(ROOT, n), "rb") as fh:
                z.writestr(zi, fh.read())
    print("wrote %s (%d files, %d bytes)" % (OUT, len(names), os.path.getsize(OUT)))


if __name__ == "__main__":
    sys.exit(main())
