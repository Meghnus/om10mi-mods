"""webbuild.py - entry of the in-browser build (Pyodide, see docs/lut/buildworker.js): your official firmware (or the unmodified version 94 image) + the pack + its LUT files -> the card-ready image.

    run(stock_bytes, pack_text, luts, name, progress, label) -> dict(ok, message, image, sha1, stock_sha1, howto)

luts = {file name: bytes}. All work is the same code as `om10mi_look.py --pack ... --base <om10mi.py build>`, so the image is byte-identical to the command line's.
Nothing leaves the browser: no network is used here.
"""
import os
import tempfile

from lookbuild import guide as G


def run(stock, pack_text, luts, name, progress, label="This file"):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lut_dir = os.path.join(tmp, "luts")
            os.makedirs(lut_dir)
            for n, b in dict(luts).items():
                with open(os.path.join(lut_dir, os.path.basename(n)), "wb") as fh:
                    fh.write(bytes(b))
            pack_path = os.path.join(tmp, "pack.json")
            with open(pack_path, "w", encoding="utf-8") as fh:
                fh.write(pack_text)
            res = G.build_all(bytes(stock), pack_path, lut_dir, progress, label)
        res["ok"] = True
        res["howto"] = G.HOWTO % dict(name=name, sha1=res["sha1"], stock=res["origin"], changes="\n".join("  " + c for c in res["changes"]))
        res["message"] = "done"
        return res
    except G.Stop as e:
        return dict(ok=False, message=str(e))
    except MemoryError:
        return dict(ok=False, message="The browser ran out of memory. Close other tabs and try again (a desktop browser with 4 GB free is needed).")
    except Exception as e:                                                  # anything unforeseen: short text, no traceback
        return dict(ok=False, message="Unexpected problem (%s: %s). Nothing was built." % (type(e).__name__, e))
