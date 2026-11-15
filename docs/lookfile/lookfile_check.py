#!/usr/bin/env python3
"""lookfile_check.py - validate an om10mi look file (format "om10mi-look", version 1).

    python lookfile_check.py FILE.json [FILE2.json ...]

Implements the rules of section 9 of LOOKFILE_SPEC.md. Standard library only.
Exit code 0: every file passes (warnings allowed). 1: at least one error or unreadable file.
"""
import json
import math
import re
import sys

MAX_BYTES = 1 << 20
MAX_LOOKS = 17
SLOTS = range(1, 19)
RESERVED = {2}
# name length limit per slot (shortest of the camera's language strings)
NAME_CAP = {1: 6, 3: 7, 4: 7, 5: 5, 6: 14, 7: 11, 8: 11, 9: 11, 10: 13, 11: 9, 12: 13, 13: 15, 14: 8,
            15: 10, 16: 17, 17: 10, 18: 8}
ICON_SLOTS = range(1, 15)
HUE_TABLE_SLOTS = 0          # per-hue tables the current layout can hold (spec 5.4)
BASES = ("auto", "Vivid", "Natural", "Muted", "Portrait")
LABEL_RE = re.compile(r"^[A-Z0-9 .\-]{1,7}$")
TOP_KEYS = {"format", "version", "target", "generator", "looks"}
LOOK_KEYS = {"slot", "name", "label", "base", "strength", "notes", "hsl", "global", "wb", "tone",
             "camera_settings", "per_hue_table", "extras"}
HSL_KEYS = {"centre_deg", "hue_deg", "sat_pct", "light_pct"}


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, where, msg):
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where, msg):
        self.warnings.append("%s: %s" % (where, msg))


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def num_in(r, where, v, lo, hi, what):
    if not is_num(v):
        r.err(where, "%s must be a finite number" % what)
        return False
    if not lo <= v <= hi:
        r.err(where, "%s = %r outside %s..%s" % (what, v, lo, hi))
        return False
    return True


def unknown(r, where, obj, allowed):
    for k in obj:
        if k not in allowed:
            r.warn(where, "unknown key %r ignored" % k)


def check_curve(r, where, pts):
    if not isinstance(pts, list) or not 2 <= len(pts) <= 33:
        r.err(where, "curve needs 2 to 33 points")
        return
    ok = True
    for i, p in enumerate(pts):
        if not (isinstance(p, list) and len(p) == 2 and is_num(p[0]) and is_num(p[1])):
            r.err(where, "point %d must be [x, y] with finite numbers" % i)
            return
        if not (0 <= p[0] <= 1 and 0 <= p[1] <= 1):
            r.err(where, "point %d outside 0..1" % i)
            ok = False
    if not ok:
        return
    if pts[0][0] != 0 or pts[-1][0] != 1:
        r.err(where, "first x must be 0 and last x must be 1")
    for a, b in zip(pts, pts[1:]):
        if not b[0] > a[0]:
            r.err(where, "x must be strictly increasing (%r then %r)" % (a[0], b[0]))
            break
        if b[1] < a[1]:
            r.err(where, "y must not decrease (%r then %r)" % (a[1], b[1]))
            break


def check_hsl(r, where, hsl):
    if not isinstance(hsl, list) or len(hsl) != 12:
        r.err(where, "hsl needs exactly 12 entries")
        return
    centres = []
    for i, e in enumerate(hsl):
        w = "%s[%d]" % (where, i)
        if not isinstance(e, dict):
            r.err(w, "must be an object")
            return
        unknown(r, w, e, HSL_KEYS)
        if "centre_deg" not in e:
            r.err(w, "centre_deg is required")
            return
        if not num_in(r, w, e["centre_deg"], 0, 360, "centre_deg") or e["centre_deg"] >= 360:
            r.err(w, "centre_deg must be 0 <= x < 360")
            return
        centres.append(float(e["centre_deg"]))
        num_in(r, w, e.get("hue_deg", 0), -60, 60, "hue_deg")
        num_in(r, w, e.get("sat_pct", 0), -100, 100, "sat_pct")
        num_in(r, w, e.get("light_pct", 0), -50, 50, "light_pct")
    for i in range(12):
        a, b = centres[i], centres[(i + 1) % 12]
        gap = (b - a) % 360 if i < 11 else (b + 360 - a) % 360
        if i < 11 and not b > a:
            r.err(where, "centre_deg must be strictly increasing")
            return
        if gap < 5:
            r.err(where, "sectors %d and %d are closer than 5 degrees" % (i, (i + 1) % 12))
            return


def check_look(r, idx, look, seen_slots, hue_requests):
    w = "looks[%d]" % idx
    if not isinstance(look, dict):
        r.err(w, "must be an object")
        return
    unknown(r, w, look, LOOK_KEYS)
    slot = look.get("slot")
    if not is_int(slot) or slot not in SLOTS:
        r.err(w, "slot must be an integer 1..18")
        slot = None
    elif slot in RESERVED:
        r.err(w, "slot %d is reserved (Monotone only)" % slot)
        slot = None
    elif slot in seen_slots:
        r.err(w, "slot %d used twice" % slot)
    else:
        seen_slots.add(slot)
    name = look.get("name")
    if not isinstance(name, str) or not name:
        r.err(w, "name is required (non-empty string)")
    else:
        if any(not 0x20 <= ord(c) <= 0x7E for c in name):
            r.err(w, "name must be printable ASCII")
        if "@" in name:
            r.err(w, "name must not contain '@'")
        cap = NAME_CAP.get(slot)
        if cap and len(name) > cap:
            r.err(w, "name %r is %d characters, slot %d allows %d" % (name, len(name), slot, cap))
    if "label" in look:
        lab = look["label"]
        if not isinstance(lab, str) or not LABEL_RE.match(lab):
            r.err(w, "label must be 1..7 characters of A-Z 0-9 space . -")
        elif slot is not None and slot not in ICON_SLOTS:
            r.warn(w, "slot %d borrows an existing icon: label ignored" % slot)
    if look.get("base", "auto") not in BASES:
        r.err(w, "base must be one of %s" % ", ".join(BASES))
    if "strength" in look:
        num_in(r, w, look["strength"], 1, 100, "strength")
    if "notes" in look and (not isinstance(look["notes"], str) or len(look["notes"]) > 200):
        r.err(w, "notes must be a string of at most 200 characters")
    if "hsl" in look:
        check_hsl(r, w + ".hsl", look["hsl"])
    if "global" in look:
        g = look["global"]
        if not isinstance(g, dict):
            r.err(w, "global must be an object")
        else:
            unknown(r, w + ".global", g, {"hue_deg", "sat_pct"})
            num_in(r, w + ".global", g.get("hue_deg", 0), -60, 60, "hue_deg")
            num_in(r, w + ".global", g.get("sat_pct", 0), -100, 100, "sat_pct")
    if "wb" in look:
        b = look["wb"]
        if not isinstance(b, dict):
            r.err(w, "wb must be an object")
        else:
            unknown(r, w + ".wb", b, {"amber_blue", "green_magenta"})
            num_in(r, w + ".wb", b.get("amber_blue", 0), -7, 7, "amber_blue")
            num_in(r, w + ".wb", b.get("green_magenta", 0), -7, 7, "green_magenta")
    if "tone" in look:
        t = look["tone"]
        if not isinstance(t, dict):
            r.err(w, "tone must be an object")
        else:
            unknown(r, w + ".tone", t, {"curve", "curve_rgb"})
            if "curve" in t:
                check_curve(r, w + ".tone.curve", t["curve"])
            if "curve_rgb" in t:
                c = t["curve_rgb"]
                if not isinstance(c, dict):
                    r.err(w, "curve_rgb must be an object")
                else:
                    for k, v in c.items():
                        if k not in ("r", "g", "b"):
                            r.err(w, "curve_rgb key %r (only r, g, b)" % k)
                        else:
                            check_curve(r, "%s.tone.curve_rgb.%s" % (w, k), v)
    if "camera_settings" in look:
        c = look["camera_settings"]
        if not isinstance(c, dict):
            r.err(w, "camera_settings must be an object")
        else:
            unknown(r, w + ".camera_settings", c, {"contrast", "sharpness", "saturation"})
            for k, v in c.items():
                if k in ("contrast", "sharpness", "saturation") and not (is_int(v) and -2 <= v <= 2):
                    r.err(w, "camera_settings.%s must be an integer -2..2" % k)
    if "per_hue_table" in look:
        if not isinstance(look["per_hue_table"], bool):
            r.err(w, "per_hue_table must be true or false")
        elif look["per_hue_table"]:
            hue_requests.append(w)
    if "extras" in look and not isinstance(look["extras"], dict):
        r.err(w, "extras must be an object")
    elif look.get("extras"):
        r.warn(w, "extras not honoured by this body: %s" % ", ".join(sorted(look["extras"])))
    if not any(k in look for k in ("hsl", "global", "wb", "tone")):
        r.warn(w, "no colour or tone parameters: the look is the identity")


def check(data, size=0):
    r = Report()
    if size > MAX_BYTES:
        r.err("file", "larger than 1 MiB")
    if not isinstance(data, dict):
        r.err("file", "top level must be an object")
        return r
    unknown(r, "file", data, TOP_KEYS)
    if data.get("format") != "om10mi-look":
        r.err("file", 'format must be "om10mi-look"')
    if not is_int(data.get("version")):
        r.err("file", "version must be an integer")
    elif data["version"] != 1:
        r.err("file", "version %d not supported (this checker reads 1)" % data["version"])
    if data.get("target") != "E113":
        r.err("file", 'target must be "E113" (E-M10 Mark I); other bodies are refused')
    looks = data.get("looks")
    if not isinstance(looks, list) or not 1 <= len(looks) <= MAX_LOOKS:
        r.err("file", "looks must be a list of 1 to %d objects" % MAX_LOOKS)
        return r
    seen, hue_requests = set(), []
    for i, look in enumerate(looks):
        check_look(r, i, look, seen, hue_requests)
    for w in hue_requests[HUE_TABLE_SLOTS:]:
        r.warn(w, "per_hue_table requested but the current layout has %d table(s): ignored" % HUE_TABLE_SLOTS)
    return r


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    bad = 0
    for path in argv:
        try:
            with open(path, "rb") as f:
                raw = f.read()
            data = json.loads(raw.decode("utf-8"), parse_constant=lambda c: (_ for _ in ()).throw(
                ValueError("non-finite number %s" % c)))
        except (OSError, ValueError) as e:
            print("%s: cannot read: %s" % (path, e))
            bad += 1
            continue
        r = check(data, len(raw))
        for m in r.warnings:
            print("%s: warning: %s" % (path, m))
        for m in r.errors:
            print("%s: ERROR: %s" % (path, m))
        n = len(data.get("looks", [])) if isinstance(data, dict) and isinstance(data.get("looks"), list) else 0
        print("%s: %s (%d look(s), %d error(s), %d warning(s))"
              % (path, "FAIL" if r.errors else "OK", n, len(r.errors), len(r.warnings)))
        bad += bool(r.errors)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
