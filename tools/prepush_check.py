#!/usr/bin/env python3
"""prepush_check - run before every commit / push of this repository.

This repository must never contain OM Digital Solutions firmware: no .BIN files, no
decoded images, no dumps, no long byte excerpts. The patch file holds only our own bytes
plus addresses and hashes. This script fails (exit 1) when it finds any of:

  * a forbidden file type (.bin .dec .part .dmp .dump .img .rom) or a name containing "dump"
  * a file that starts like an OM firmware container (marker "OE" + a valid block chain)
  * a file larger than 1 MB, except images (.jpg .jpeg .png, up to 5 MB), .json (up to 2 MB) and the Pyodide runtime of the in-browser build
    (docs/lut/pyodide/*.wasm .zip .whl .js, up to 12 MB)
  * a long hex string (200+ hex digits) or base64-looking blob in any text file outside patch/
  * a patch/*.json that is malformed, has an unknown step type, or carries more literal
    bytes than expected for a look pack (sanity cap 128 KB)
  * with --stock FILE (the official v1.4 .BIN, kept outside the repo): any run of 16 or more
    literal bytes in a patch file that also occurs in the official image

    python tools/prepush_check.py
    python tools/prepush_check.py --stock path/to/OLY_E_113_1400_0000_0000.BIN

Only the standard library is used. Nothing is written anywhere.
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BAD_EXT = {".bin", ".dec", ".part", ".dmp", ".dump", ".img", ".rom"}
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
LIMIT_DEFAULT = 1 << 20
LIMIT_IMAGE = 5 << 20
LIMIT_JSON = 2 << 20
LIMIT_RUNTIME = 12 << 20          # the self-hosted Pyodide runtime of the in-browser build (docs/lut/pyodide/: .wasm .zip .whl .js)
RUNTIME_EXT = {".wasm", ".zip", ".whl", ".js"}
LITERAL_CAP = 128 * 1024
HEX_RUN = re.compile(rb"[0-9a-fA-F]{200,}")
B64_RUN = re.compile(rb"[A-Za-z0-9+/]{300,}={0,2}")
TEXT_EXT = {".md", ".py", ".txt", ".bat", ".sh", ".command", ".yml", ".yaml", ".cfg", ".toml", ".html", ""}


def list_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, check=True).stdout
        names = [n for n in out.decode("utf-8", "surrogateescape").split("\0") if n]
        return sorted(set(n for n in names if os.path.isfile(os.path.join(ROOT, n))))
    except (OSError, subprocess.CalledProcessError):
        names = []
        for d, dirs, files in os.walk(ROOT):
            dirs[:] = [x for x in dirs if x != ".git"]
            for f in files:
                names.append(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/"))
        return sorted(names)


def looks_like_container(head, size):
    """True when the file is a chain of OE blocks (the OM firmware container)."""
    if head[:2] != b"OE" or len(head) < 16:
        return False
    n = struct.unpack_from("<I", head, 12)[0]
    return 32 + n + 32 <= size


def check_files(problems):
    names = list_files()
    for name in names:
        path = os.path.join(ROOT, name)
        low = name.lower()
        ext = os.path.splitext(low)[1]
        size = os.path.getsize(path)
        base = os.path.basename(low)
        if ext in BAD_EXT:
            problems.append("%s: forbidden file type" % name)
        if "dump" in base:
            problems.append("%s: name contains 'dump'" % name)
        limit = LIMIT_IMAGE if ext in IMAGE_EXT else LIMIT_JSON if ext == ".json" else LIMIT_DEFAULT
        if name.replace("\\", "/").startswith("docs/lut/pyodide/") and ext in RUNTIME_EXT:
            limit = LIMIT_RUNTIME
        if size > limit:
            problems.append("%s: %d bytes exceeds the %d byte limit for this file type" % (name, size, limit))
        with open(path, "rb") as f:
            head = f.read(64)
            if looks_like_container(head, size):
                problems.append("%s: starts like an OM firmware container" % name)
            if ext in TEXT_EXT and size <= LIMIT_DEFAULT and not name.startswith("patch/"):
                f.seek(0)
                data = f.read()
                if HEX_RUN.search(data):
                    problems.append("%s: contains a hex string of 200+ digits (byte excerpt?)" % name)
                if B64_RUN.search(data):
                    problems.append("%s: contains a long base64-like blob" % name)
    return names


def literals(patch):
    """Yield (partition, zone offset, bytes) for every literal step."""
    for entry in patch["partitions"]:
        for zone in entry["zones"]:
            for op in zone["ops"]:
                if op[0] == "l":
                    yield entry["index"], zone["at"], bytes.fromhex(op[1])


def check_patch(name, problems, stock_plain):
    with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
        try:
            patch = json.load(f)
        except ValueError as e:
            problems.append("%s: not valid JSON (%s)" % (name, e))
            return
    total = 0
    longest = 0
    nops = {"k": 0, "c": 0, "f": 0, "l": 0}
    for entry in patch.get("partitions", []):
        for zone in entry["zones"]:
            for op in zone["ops"]:
                if op[0] not in nops:
                    problems.append("%s: unknown step %r" % (name, op[0]))
                    continue
                nops[op[0]] += 1
                if op[0] == "l":
                    n = len(op[1]) // 2
                    total += n
                    longest = max(longest, n)
    print("  %s: %d keep, %d copy, %d fill, %d literal steps; %d literal bytes, longest %d"
          % (name, nops["k"], nops["c"], nops["f"], nops["l"], total, longest))
    if total > LITERAL_CAP:
        problems.append("%s: %d literal bytes exceed the %d byte sanity cap" % (name, total, LITERAL_CAP))
    if stock_plain is not None:
        hits = scan_literals(patch, stock_plain)
        print("  %s: literal runs >= 16 bytes that also occur in the official image: %d" % (name, len(hits)))
        for h in hits:
            problems.append("%s: partition %d zone 0x%x: 16-byte run at literal offset %d is in the official image"
                            % (name, h[0], h[1], h[3]))


def scan_literals(patch, stock_plain, win=16):
    """Every 16-byte window inside a literal step that also occurs in the stock partitions."""
    lits = [b for _, _, b in literals(patch)]
    meta = [(p, z) for p, z, _ in literals(patch)]
    grams = {}
    for i, b in enumerate(lits):
        for o in range(len(b) - win + 1):
            grams.setdefault(int.from_bytes(b[o:o + 8], sys.byteorder), []).append((i, o))
    wanted = set(grams)
    cand = set()
    for plain in stock_plain:
        mv = memoryview(plain)
        for s in range(8):
            n = (len(plain) - s) // 8 * 8
            cand |= wanted.intersection(mv[s:s + n].cast("Q"))
    hits = []
    for g in cand:
        for i, o in grams[g]:
            w = lits[i][o:o + win]
            if any(w in plain for plain in stock_plain):
                hits.append((meta[i][0], meta[i][1], i, o))
    return sorted(hits)


def load_stock(path):
    import om10mi
    with open(path, "rb") as f:
        data = f.read()
    return [bytes(p.plain()) for p in om10mi.split_image(data)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stock", metavar="FILE", help="official E113 v1.4 .BIN, for the 16-byte literal scan")
    args = ap.parse_args()
    problems = []
    names = check_files(problems)
    print("checked %d files" % len(names))
    stock = load_stock(args.stock) if args.stock else None
    if stock is None:
        print("  (no --stock given: the 16-byte literal scan is skipped)")
    for name in names:
        if name.startswith("patch/") and name.endswith(".json"):
            check_patch(name, problems, stock)
    if problems:
        print()
        for p in problems:
            print("FAIL:", p)
        print("\n%d problem(s). Do not push." % len(problems))
        return 1
    print("OK: nothing that looks like firmware.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
