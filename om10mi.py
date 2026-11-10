#!/usr/bin/env python3
"""om10mi - builder for the om10mi-mods look pack (OM-D E-M10 Mark I, firmware 1.4).

This repository contains no firmware. The builder takes the official firmware
update (E113, v1.4) that you download yourself from the OM Digital Solutions
server, applies the edits listed in patch/looks56.json, and writes a card-ready
copy that is checked byte for byte against the published result hash.

    python om10mi.py build                    download the official file, then build
    python om10mi.py build --stock FILE.BIN   use a copy you already have
    python om10mi.py build --sd E:            also copy the result to the SD card in drive E:
    python om10mi.py fetch                    only download and verify the official file
    python om10mi.py verify FILE.BIN          check a firmware file (structure, checksums, hash)

Needs Python 3.10 or newer and nothing else. It never talks to the camera and
never writes anywhere except the output folder (default: ./out) and, only when you ask
for it, DCOLYMP/E1139999.BIN on the SD card you name.

Copyright 2026 Meghnus. This file is licensed under the Apache License 2.0 (see LICENSE).
The patch data in patch/looks56.json is licensed separately (CC BY-NC-SA 4.0, see LICENSE-DATA).
"""

import argparse
import array
import hashlib
import html
import json
import os
import re
import shutil
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED_HOSTS = ("om-digitalsolutions.net",)   # hosts seen in the real reply: fw01. and dl01.

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, "frozen", False))          # true in the packaged Windows exe
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE   # where "out" lives by default
RES_DIR = getattr(sys, "_MEIPASS", HERE)              # where patch/ lives
PATCH_FILE = os.path.join(RES_DIR, "patch", "looks56.json")

MODEL_ID = 0x1130                      # E-M10 Mark I; the builder refuses anything else
STOCK_NAME = "OLY_E_113_1400_0000_0000.BIN"
CARD_NAME = "E1139999.BIN"             # the name the camera looks for in DCOLYMP
SERVER = "https://fw01.om-digitalsolutions.net/ww_inform/fcache.do"
HARD_CODE = "OLYE113000000000"

HDR = 32
FTR = 32

# Payload storage: inside every 16-byte block the four 32-bit words are
# byte-shuffled in a fixed pattern, then every byte is inverted.
SHUFFLE = ((1, 3, 0, 2), (2, 0, 3, 1), (3, 2, 1, 0), (1, 2, 0, 3))
INVERT = bytes(i ^ 0xFF for i in range(256))


class BuildError(Exception):
    pass


# ----------------------------------------------------------------- container

def decode_payload(raw):
    """Stored payload -> plain flash image."""
    n = len(raw) // 16 * 16
    out = bytearray(len(raw))
    for ph in range(4):
        for j in range(4):
            out[4 * ph + j:n:16] = raw[4 * ph + SHUFFLE[ph][j]:n:16]
    out[n:] = raw[n:]
    return bytes(out).translate(INVERT)


def encode_payload(plain):
    """Plain flash image -> stored payload (inverse of decode_payload)."""
    inv = plain.translate(INVERT)
    n = len(inv) // 16 * 16
    out = bytearray(len(inv))
    for ph in range(4):
        for j in range(4):
            out[4 * ph + SHUFFLE[ph][j]:n:16] = inv[4 * ph + j:n:16]
    out[n:] = inv[n:]
    return bytes(out)


def _word_sum(buf):
    a = array.array("I")
    a.frombytes(buf[:len(buf) // 4 * 4])
    if sys.byteorder != "little":
        a.byteswap()
    return sum(a) & 0xFFFFFFFF


def footer_checksum(header, plain):
    """Whole partition (header + plain payload + footer with zeroed checksum),
    read as little-endian 32-bit words, must sum to 0 modulo 2**32."""
    footer0 = header[:0x1C] + b"\0\0\0\0"
    total = _word_sum(header) + _word_sum(plain) + _word_sum(footer0)
    return (-total) & 0xFFFFFFFF


class Part:
    def __init__(self, index, header, raw, footer):
        self.index = index
        self.header = header
        self.raw = raw
        self.footer = footer
        self.model = struct.unpack_from(">H", header, 2)[0]
        self.stored_sum = struct.unpack_from("<I", footer, 0x1C)[0]

    def plain(self):
        return decode_payload(self.raw)


def split_image(data):
    parts = []
    off = 0
    while off < len(data):
        if data[off:off + 2] != b"OE":
            raise BuildError("not an Olympus firmware file (bad block marker at 0x%x)" % off)
        n = struct.unpack_from("<I", data, off + 12)[0]
        end = off + HDR + n + FTR
        if end > len(data):
            raise BuildError("file is truncated (partition %d)" % len(parts))
        parts.append(Part(len(parts), data[off:off + HDR],
                          data[off + HDR:off + HDR + n], data[off + HDR + n:end]))
        off = end
    if not parts:
        raise BuildError("empty file")
    return parts


def join_image(parts):
    return b"".join(p.header + p.raw + p.footer for p in parts)


# ---------------------------------------------------------------- patch data

def load_patch():
    try:
        with open(PATCH_FILE, "r", encoding="utf-8") as f:
            patch = json.load(f)
    except OSError as e:
        raise BuildError("cannot read %s: %s" % (PATCH_FILE, e))
    if patch.get("format") != 1:
        raise BuildError("unknown patch format")
    return patch


def apply_zone(out, stock_plain, part_index, zone):
    """Rewrite one zone of out[part_index] from the untouched stock image.

    ops:  ["k", n]               n bytes stay as they are
          ["c", part, off, n]    n bytes copied from the stock image
          ["f", byte, n]         n bytes of one value
          ["l", "hex"]           bytes that are new in this pack
    """
    at = zone["at"]
    ops = zone["ops"]
    size = 0
    for op in ops:
        size += {"k": lambda: op[1], "c": lambda: op[3],
                 "f": lambda: op[2], "l": lambda: len(op[1]) // 2}[op[0]]()
    base = stock_plain[part_index]
    if hashlib.sha256(base[at:at + size]).hexdigest() != zone["old"]:
        raise BuildError("partition %d at 0x%x: the firmware does not match what this "
                         "pack was made for" % (part_index, at))
    dst = out[part_index]
    pos = at
    for op in ops:
        kind = op[0]
        if kind == "k":
            pos += op[1]
        elif kind == "c":
            _, p, off, n = op
            src = stock_plain[p]
            if off + n > len(src):
                raise BuildError("patch data is corrupt (copy out of range)")
            dst[pos:pos + n] = src[off:off + n]
            pos += n
        elif kind == "f":
            _, b, n = op
            dst[pos:pos + n] = bytes((b,)) * n
            pos += n
        elif kind == "l":
            blob = bytes.fromhex(op[1])
            dst[pos:pos + len(blob)] = blob
            pos += len(blob)
        else:
            raise BuildError("patch data is corrupt (unknown step %r)" % kind)
    if pos != at + size:
        raise BuildError("patch data is corrupt (zone length)")


def sha1_hex(data):
    return hashlib.sha1(data).hexdigest()


def build_image(stock, patch):
    parts = split_image(stock)
    for p in parts:
        if p.model != MODEL_ID:
            raise BuildError("this firmware is not for the E-M10 Mark I (model id 0x%04x)" % p.model)
    stock_plain = [p.plain() for p in parts]
    want = patch["partition_stock_sha256"]
    if len(want) != len(parts):
        raise BuildError("firmware layout differs from what this pack expects")
    for i, plain in enumerate(stock_plain):
        if hashlib.sha256(plain).hexdigest() != want[i]:
            raise BuildError("partition %d differs from the expected firmware 1.4" % i)
    out = [bytearray(x) for x in stock_plain]
    for entry in patch["partitions"]:
        for zone in entry["zones"]:
            apply_zone(out, stock_plain, entry["index"], zone)
    result = []
    for p, plain, new in zip(parts, stock_plain, out):
        if bytes(new) == plain:
            result.append(p)
            continue
        raw = encode_payload(bytes(new))
        footer = p.header[:0x1C] + struct.pack("<I", footer_checksum(p.header, bytes(new)))
        result.append(Part(p.index, p.header, raw, footer))
    return join_image(result)


# ----------------------------------------------------------------- download

def _request_body():
    return ("""<?xml version="1.0"?>
<firmware_demand>
<revision>0001</revision>
<mac_address>00-00-00-00-80-D6</mac_address>
<time>%s</time>
<language>ENU</language>
<application>FWUT</application>
<type>0000</type>
<version>00005000</version>
<os>WIN</os>
<country_code>0001</country_code>
<hardwares>
<firmup_mode>0</firmup_mode>
<hardware_info>
<hard_code>%s</hard_code>
<firmware_version>00001000</firmware_version>
<serial_no>V5PF30000</serial_no>
</hardware_info>
</hardwares>
</firmware_demand>
""" % (time.strftime("%Y%m%d%H%M%S"), HARD_CODE)).encode("utf-8")


def _ask_license(reply, accepted):
    m = re.search(r"<license_agreement>(.*?)</license_agreement>", reply, re.S)
    if not m:
        return
    text = html.unescape(m.group(1)).replace("\\n", "\n")
    print()
    print("The OM Digital Solutions server attaches this licence to the firmware:")
    print("-" * 72)
    print(text.strip())
    print("-" * 72)
    if accepted:
        print("(--accept-license given)")
        return
    if not sys.stdin.isatty():
        raise BuildError("run with --accept-license to confirm you accept the licence above")
    try:
        answer = input("Type yes to accept and download: ").strip().lower()
    except EOFError:
        answer = ""
    if answer != "yes":
        raise BuildError("licence not accepted, nothing downloaded")


def _checked_url(url):
    """Only https downloads from a host under the OM Digital Solutions domain are followed."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    print("  download host: %s" % host)
    if parts.scheme != "https" or not any(host == d or host.endswith("." + d) for d in ALLOWED_HOSTS):
        raise BuildError("the server pointed to an unexpected download address (%s); refusing" % (host or url))
    return url


def download_stock(dest, accepted, want_size, want_sha1):
    """Ask the server, show the licence, then fetch to a temp file and move it into place
    only if size and sha1 are the expected ones. Nothing is created before the licence is accepted."""
    print("asking the OM Digital Solutions server for the E113 firmware ...")
    headers = {"User-Agent": "Olympus", "Content-Type": "text/xml; Charset=UTF-8"}
    tmp = dest + ".part"
    try:
        try:
            req = urllib.request.Request(SERVER, data=_request_body(), headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                reply = r.read().decode("utf-8", "replace")
            m = re.search(r"<url>\s*(\S+?)\s*</url>", reply)
            if not m:
                raise BuildError("the server did not return a download address")
            url = _checked_url(html.unescape(m.group(1)))
            _ask_license(reply, accepted)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            print("downloading ...")
            h = hashlib.sha1()
            got = 0
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "Olympus"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                _checked_url(r.geturl())
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if total:
                        sys.stdout.write("\r  %5.1f%%  %d MB" % (100.0 * got / total, got >> 20))
                        sys.stdout.flush()
            print("\n  %d bytes in %.0f s" % (got, time.time() - t0))
        except (urllib.error.URLError, OSError) as e:
            raise BuildError("download failed: %s\nDownload the E-M10 Mark I firmware 1.4 yourself "
                             "(OM Workspace or the OM support page) and use --stock FILE." % e)
        if got != want_size or h.hexdigest() != want_sha1:
            raise BuildError(
                "the downloaded file is not firmware 1.4 (%d bytes, sha1 %s); discarded.\n"
                "If the OM server now offers a newer version, the pack cannot be applied to it; "
                "use a copy of v1.4 with --stock." % (got, h.hexdigest()))
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def obtain_stock(args, patch):
    """Return the bytes of the official image, downloading it when needed."""
    if args.stock:
        path = args.stock
        if not os.path.isfile(path):
            raise BuildError("file not found: %s" % path)
    else:
        path = os.path.join(args.out, "official", STOCK_NAME)
        if not os.path.exists(path):
            download_stock(path, args.accept_license, patch["stock_size"], patch["stock_sha1"])
        else:
            print("using the earlier download %s" % path)
    with open(path, "rb") as f:
        data = f.read()
    sha = sha1_hex(data)
    if len(data) != patch["stock_size"] or sha != patch["stock_sha1"]:
        raise BuildError(
            "this is not the firmware the pack was made for.\n"
            "  expected: v1.4, %d bytes, sha1 %s\n"
            "  got:      %d bytes, sha1 %s\n"
            "If the OM server now offers a newer version, the pack cannot be applied to it; "
            "use a copy of v1.4 with --stock."
            % (patch["stock_size"], patch["stock_sha1"], len(data), sha))
    print("official firmware OK (sha1 %s)" % sha)
    return data


# ------------------------------------------------------------------ commands

def check_image(data, label):
    """Structure + footer checksums. Returns the list of problems."""
    problems = []
    try:
        parts = split_image(data)
    except BuildError as e:
        return [str(e)]
    for p in parts:
        if p.model != MODEL_ID:
            problems.append("partition %d: model id 0x%04x" % (p.index, p.model))
        if p.footer[:0x1C] != p.header[:0x1C]:
            problems.append("partition %d: footer does not match header" % p.index)
        if footer_checksum(p.header, p.plain()) != p.stored_sum:
            problems.append("partition %d: checksum wrong" % p.index)
    print("%s: %d partitions, %d bytes" % (label, len(parts), len(data)))
    return problems


def cmd_fetch(args):
    patch = load_patch()
    obtain_stock(args, patch)
    return 0


def _sd_root(text):
    t = text.strip().strip('"')
    if re.fullmatch(r"[A-Za-z]:?", t):
        t = t[0].upper() + ":" + os.sep
    return t


def copy_to_sd(image, sd, assume_yes):
    """Put DCOLYMP/E1139999.BIN on a camera card. The only things ever written are that one file
    (through a temporary name next to it) and the DCOLYMP folder if it is missing."""
    root = _sd_root(sd)
    if not os.path.isdir(root):
        raise BuildError("%s is not an available drive or folder" % sd)
    dcim = [n for n in os.listdir(root) if n.lower() == "dcim" and os.path.isdir(os.path.join(root, n))]
    if not dcim:
        raise BuildError("%s does not look like a camera card (no DCIM folder); nothing copied" % root)
    folder = os.path.join(root, "DCOLYMP")
    if os.path.exists(folder) and not os.path.isdir(folder):
        raise BuildError("%s exists and is not a folder; nothing copied" % folder)
    target = os.path.join(folder, CARD_NAME)
    replacing = os.path.isfile(target)
    if os.path.exists(target) and not replacing:
        raise BuildError("%s exists and is not a file; nothing copied" % target)
    free = shutil.disk_usage(root).free + (os.path.getsize(target) if replacing else 0)
    if free < len(image) + (1 << 20):
        raise BuildError("not enough free space on %s (%d MB needed)" % (root, len(image) >> 20))
    print()
    print("SD card: %s (DCIM found)" % root)
    print("  will %s  %s  (%d MB)" % ("REPLACE" if replacing else "write", target, len(image) >> 20))
    print("  nothing else on the card is touched")
    if not assume_yes:
        try:
            answer = input("Type yes to copy: ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("not copied")
            return
    os.makedirs(folder, exist_ok=True)
    tmp = target + ".part"
    try:
        with open(tmp, "wb") as f:
            f.write(image)
        with open(tmp, "rb") as f:
            if sha1_hex(f.read()) != sha1_hex(image):
                raise BuildError("the copy on the card does not match; it was removed")
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("copied. Eject the card safely, then follow the steps in INSTALL.md (hold OK while switching on).")


def cmd_build(args):
    patch = load_patch()
    stock = obtain_stock(args, patch)
    print("applying the look pack (a minute or so) ...")
    image = build_image(stock, patch)
    sha = sha1_hex(image)
    if len(image) != patch["result_size"] or sha != patch["result_sha1"]:
        raise BuildError("the result does not match the published hash (%s); nothing written" % sha)
    problems = check_image(image, "result")
    if problems:
        raise BuildError("; ".join(problems))
    for sub, data in (("DCOLYMP", image), (os.path.join("RESTORE", "DCOLYMP"), stock)):
        folder = os.path.join(args.out, sub)
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, CARD_NAME)
        tmp = target + ".part"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    print()
    print("done. sha1 %s matches the published look pack." % sha)
    print("  to flash   : copy  %s  to the card" % os.path.join(args.out, "DCOLYMP"))
    print("  to go back : copy  %s  instead (official 1.4)" % os.path.join(args.out, "RESTORE", "DCOLYMP"))
    sd = args.sd
    if not sd and args.ask_sd:
        try:
            sd = input("\nCopy to SD card now? Enter the drive letter (or mount path), or leave empty to skip: ")
        except EOFError:
            sd = ""
    if sd and sd.strip():
        copy_to_sd(image, sd, args.yes)
    return 0


def cmd_verify(args):
    with open(args.file, "rb") as f:
        data = f.read()
    problems = check_image(data, os.path.basename(args.file))
    sha = sha1_hex(data)
    patch = load_patch()
    if sha == patch["result_sha1"]:
        print("this is the look pack 56 image")
    elif sha == patch["stock_sha1"]:
        print("this is the official 1.4 image")
    else:
        print("sha1 %s is neither the official 1.4 nor the look pack" % sha)
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


def main(argv):
    interactive = not argv      # started by double-click (the packaged exe): build, offer the SD copy, wait
    if interactive:
        argv = ["build", "--ask-sd"]
    ap = argparse.ArgumentParser(prog="om10mi", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, text in (("build", cmd_build, "build the card image"),
                           ("fetch", cmd_fetch, "download and check the official firmware only")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--stock", metavar="FILE", help="official E113 v1.4 .BIN you already have")
        s.add_argument("--out", default=os.path.join(APP_DIR, "out"), metavar="DIR",
                       help="output folder (default: out, next to this program)")
        s.add_argument("--accept-license", action="store_true",
                       help="accept the OM Digital Solutions firmware licence without asking")
        if name == "build":
            s.add_argument("--sd", metavar="DRIVE", help="also copy the result to this SD card "
                           "(drive letter such as E: or a mount point; must contain a DCIM folder)")
            s.add_argument("--ask-sd", action="store_true", help="ask whether to copy to an SD card")
            s.add_argument("--yes", action="store_true", help="do not ask for confirmation before the SD copy")
        s.set_defaults(fn=fn)
    s = sub.add_parser("verify", help="check a firmware file")
    s.add_argument("file")
    s.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    try:
        code = args.fn(args)
    except BuildError as e:
        print("error:", e, file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        print("interrupted; nothing written", file=sys.stderr)
        code = 130
    except Exception as e:  # anything unforeseen: short message, no traceback, exit 2
        print("unexpected error (%s: %s). Nothing was written to the output folders.\n"
              "Please report this at https://github.com/Meghnus/om10mi-mods/issues with your Python "
              "version and the command you ran." % (type(e).__name__, e), file=sys.stderr)
        code = 2
    if interactive:
        try:
            input("\nPress Enter to close this window ...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
