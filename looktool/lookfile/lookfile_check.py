#!/usr/bin/env python3
"""lookfile_check.py - validate an om10mi look file (format "om10mi-look", version 1 or 2).

    python lookfile_check.py FILE.json [FILE2.json ...]

Implements section 9 of LOOKFILE_SPEC.md (version 1) and section 9b of LOOKFILE_SPEC_v2.md (version 2).
A version 1 file is checked by exactly the version 1 rules (the v2 additions are unknown keys there, with a warning).
Standard library only. Exit code 0: every file passes (warnings allowed). 1: at least one error or unreadable file.
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
            15: 10, 16: 17, 17: 24, 18: 8}      # slot 17: the name moved to string id 1481 in z24 (stock text 24 characters); lookbuild/names88.py NAME_CAP is the same table
ICON_SLOTS = range(1, 15)
HUE_TABLE_SLOTS = 0          # per-hue tables the current layout can hold (spec 5.4)
BASES = ("auto", "Vivid", "Natural", "Muted", "Portrait")
LABEL_RE = re.compile(r"^[A-Z0-9 .\-]{1,7}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

TOP_KEYS_V1 = {"format", "version", "target", "generator", "looks"}
TOP_KEYS_V2 = TOP_KEYS_V1 | {"pack"}
# look pack (PACK_SPEC_v2.md): items of the Picture Mode order
PACK_STOCK = ["Vivid", "Natural", "Muted", "Portrait", "Monotone", "Custom", "e-Portrait", "Color Creator"] + ["ART%d" % i for i in range(1, 13)]
PACK_NAME_CAP = {**NAME_CAP, 2: 5}          # slot 2 (Acros) can be renamed, not replaced
SLOT_MODE = {1: "Muted", 2: "Monotone", 3: "Portrait", 4: "Muted", 5: "Muted", 6: "Vivid", 7: "Vivid", 8: "Portrait", 9: "Natural", 10: "Muted", 11: "Vivid", 12: "Vivid",
             13: "Portrait", 14: "Portrait", 15: "Portrait", 16: "Portrait", 17: "Portrait", 18: "Portrait"}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
PACK_KEYS = {"name", "base", "order", "hidden", "renames"}
LOOK_KEYS_V1 = {"slot", "name", "label", "base", "strength", "notes", "hsl", "global", "wb", "tone",
                "camera_settings", "per_hue_table", "extras"}
HSL_KEYS_V1 = {"centre_deg", "hue_deg", "sat_pct", "light_pct"}

LOOK_KEYS_V2 = LOOK_KEYS_V1 | {"source", "split", "calibration", "fx", "fit", "hsl_model", "icon"}
HSL_KEYS_V2 = HSL_KEYS_V1 | {"width_deg"}
TONE_KEYS_V2 = {"curve", "curve_rgb", "exposure_ev", "curve_mode"}
GLOBAL_KEYS_V2 = {"hue_deg", "sat_pct", "vibrance_pct"}

SOURCE_TYPES = ("cube", "xmp-profile", "lr-preset", "rapidraw-preset", "pp3", "photos", "params")
LUT_SOURCE_TYPES = ("cube", "xmp-profile", "pp3")      # the intent lives in a table the file refers to, never embeds
SOURCE_SPACES = ("display", "prophoto", "vlog")
SOURCE_KEYS = {"type", "name", "licence", "sha256", "space", "title", "approximate", "requires_file", "preset_name",
               "table_md5", "clut_file", "clut_profile", "clut_sha256", "lut", "notes"}
RANK_STAGES = ("stock", "refit")
KNOWN_FIT_MODELS = ("cm-v2-web1",)
HSL_MODELS = ("tent", "rapidraw8")
CURVE_MODES = ("luma", "per_channel")


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


def check_hsl(r, where, hsl, v2, model):
    lo_n, hi_n = (3, 16) if v2 else (12, 12)
    if not isinstance(hsl, list) or not lo_n <= len(hsl) <= hi_n:
        r.err(where, "hsl needs exactly 12 entries" if not v2 else "hsl needs 3 to 16 entries")
        return
    n = len(hsl)
    centres = []
    light_lim = 100 if (v2 and model == "rapidraw8") else 50
    for i, e in enumerate(hsl):
        w = "%s[%d]" % (where, i)
        if not isinstance(e, dict):
            r.err(w, "must be an object")
            return
        unknown(r, w, e, HSL_KEYS_V2 if v2 else HSL_KEYS_V1)
        if "centre_deg" not in e:
            r.err(w, "centre_deg is required")
            return
        if not num_in(r, w, e["centre_deg"], 0, 360, "centre_deg") or e["centre_deg"] >= 360:
            r.err(w, "centre_deg must be 0 <= x < 360")
            return
        centres.append(float(e["centre_deg"]))
        num_in(r, w, e.get("hue_deg", 0), -60, 60, "hue_deg")
        num_in(r, w, e.get("sat_pct", 0), -100, 100, "sat_pct")
        num_in(r, w, e.get("light_pct", 0), -light_lim, light_lim, "light_pct")
        if v2 and "width_deg" in e:
            num_in(r, w, e["width_deg"], 5, 180, "width_deg")
        if v2 and model == "rapidraw8" and "width_deg" not in e:
            r.err(w, "width_deg is required with hsl_model rapidraw8")
    for i in range(n):
        a, b = centres[i], centres[(i + 1) % n]
        gap = (b - a) % 360 if i < n - 1 else (b + 360 - a) % 360
        if i < n - 1 and not b > a:
            r.err(where, "centre_deg must be strictly increasing")
            return
        if gap < 5:
            r.err(where, "sectors %d and %d are closer than 5 degrees" % (i, (i + 1) % n))
            return


def check_source(r, w, s):
    if not isinstance(s, dict):
        r.err(w, "source must be an object")
        return
    unknown(r, w, s, SOURCE_KEYS)
    if s.get("type") not in SOURCE_TYPES:
        r.err(w, "type must be one of %s" % ", ".join(SOURCE_TYPES))
    if "name" in s and (not isinstance(s["name"], str) or len(s["name"]) > 200):
        r.err(w, "name must be a string of at most 200 characters")
    if "licence" in s and (not isinstance(s["licence"], str) or len(s["licence"]) > 100):
        r.err(w, "licence must be a string of at most 100 characters")
    if "sha256" in s and not (isinstance(s["sha256"], str) and HEX64.match(s["sha256"])):
        r.err(w, "sha256 must be 64 hex digits")
    if "space" in s and s["space"] not in SOURCE_SPACES:
        r.err(w, "space must be one of %s" % ", ".join(SOURCE_SPACES))
    for k in ("approximate", "requires_file"):
        if k in s and not isinstance(s[k], bool):
            r.err(w, "%s must be true or false" % k)
    for k, v in s.items():
        if isinstance(v, list) or (isinstance(v, dict) and k != "lut"):
            r.err(w, "%s must be a scalar: a look file never embeds the source table" % k)
    if isinstance(s.get("lut"), dict):
        for k, v in s["lut"].items():
            if isinstance(v, (list, dict)):
                r.err(w, "lut.%s must be a scalar" % k)


def check_base(r, w, base, v2):
    if isinstance(base, str):
        if base not in BASES:
            r.err(w, "base must be one of %s" % ", ".join(BASES))
        return
    if not v2:
        r.err(w, "base must be one of %s" % ", ".join(BASES))
        return
    if not isinstance(base, dict):
        r.err(w, "base must be a string or an object")
        return
    unknown(r, w + ".base", base, {"mode", "candidate", "ranking", "stage", "tie_dE"})
    if base.get("mode", "auto") not in BASES:
        r.err(w, "base.mode must be one of %s" % ", ".join(BASES))
    if "candidate" in base and not (isinstance(base["candidate"], str) and 1 <= len(base["candidate"]) <= 60):
        r.err(w, "base.candidate must be a string of 1..60 characters")
    if "stage" in base and base["stage"] not in RANK_STAGES:
        r.err(w, "base.stage must be one of %s" % ", ".join(RANK_STAGES))
    if "tie_dE" in base:
        num_in(r, w, base["tie_dE"], 0, 20, "base.tie_dE")
    rk = base.get("ranking")
    if rk is None:
        return
    if not isinstance(rk, list) or len(rk) > 40:
        r.err(w, "base.ranking must be a list of at most 40 entries")
        return
    for i, e in enumerate(rk):
        we = "%s.base.ranking[%d]" % (w, i)
        if not isinstance(e, dict):
            r.err(we, "must be an object")
            continue
        unknown(r, we, e, {"candidate", "mode", "dE", "pct_lt5", "dE_fit", "stage"})
        if not (isinstance(e.get("candidate"), str) and 1 <= len(e["candidate"]) <= 60):
            r.err(we, "candidate must be a string of 1..60 characters")
        if e.get("mode") not in BASES[1:]:
            r.err(we, "mode must be one of %s" % ", ".join(BASES[1:]))
        if "dE" not in e:
            r.err(we, "dE is required")
        else:
            num_in(r, we, e["dE"], 0, 100, "dE")
        if e.get("pct_lt5") is not None:
            num_in(r, we, e["pct_lt5"], 0, 100, "pct_lt5")
        if e.get("dE_fit") is not None:
            num_in(r, we, e["dE_fit"], 0, 100, "dE_fit")
        if "stage" in e and e["stage"] not in RANK_STAGES:
            r.err(we, "stage must be one of %s" % ", ".join(RANK_STAGES))
    ds = [e["dE"] for e in rk if isinstance(e, dict) and is_num(e.get("dE"))]
    if ds and ds != sorted(ds):
        r.warn(w + ".base.ranking", "entries are not sorted by dE (best first expected)")


def check_split(r, w, sp):
    if not isinstance(sp, dict):
        r.err(w, "split must be an object")
        return
    unknown(r, w, sp, {"shadows", "mid", "highlights", "global", "balance", "blending"})
    for k in ("shadows", "mid", "highlights", "global"):
        if k in sp:
            e = sp[k]
            if not isinstance(e, dict):
                r.err(w, "%s must be an object" % k)
                continue
            wk = "%s.%s" % (w, k)
            unknown(r, wk, e, {"hue", "sat", "lum"})
            num_in(r, wk, e.get("hue", 0), 0, 360, "hue")
            num_in(r, wk, e.get("sat", 0), 0, 100, "sat")
            num_in(r, wk, e.get("lum", 0), -100, 100, "lum")
    if "balance" in sp:
        num_in(r, w, sp["balance"], -100, 100, "balance")
    if "blending" in sp:
        num_in(r, w, sp["blending"], 0, 100, "blending")


def check_calibration(r, w, cal):
    if not isinstance(cal, dict):
        r.err(w, "calibration must be an object")
        return
    unknown(r, w, cal, {"red", "green", "blue", "shadow_tint"})
    for k in ("red", "green", "blue"):
        if k in cal:
            e = cal[k]
            if not isinstance(e, dict):
                r.err(w, "%s must be an object" % k)
                continue
            wk = "%s.%s" % (w, k)
            unknown(r, wk, e, {"hue", "sat"})
            num_in(r, wk, e.get("hue", 0), -100, 100, "hue")
            num_in(r, wk, e.get("sat", 0), -100, 100, "sat")
    if "shadow_tint" in cal:
        num_in(r, w, cal["shadow_tint"], -100, 100, "shadow_tint")


def check_fx(r, w, fx):
    if not isinstance(fx, dict):
        r.err(w, "fx must be an object")
        return
    unknown(r, w, fx, {"grain", "halation", "bloom", "vignette", "active"})
    if "active" in fx:
        if not isinstance(fx["active"], bool):
            r.err(w, "active must be true or false")
        elif fx["active"]:
            r.warn(w, "fx.active is true but this body has no FX engine: ignored, listed as inactive in the build report")
    g = fx.get("grain")
    if g is not None:
        if not isinstance(g, dict):
            r.err(w, "grain must be an object")
        else:
            wg = w + ".grain"
            unknown(r, wg, g, {"amount", "size", "roughness", "seed", "source"})
            num_in(r, wg, g.get("amount", 0), 0, 100, "amount")
            num_in(r, wg, g.get("size", 25), 0, 100, "size")
            num_in(r, wg, g.get("roughness", 50), 0, 100, "roughness")
            if "seed" in g and not (is_int(g["seed"]) and 0 <= g["seed"] <= 2 ** 31 - 1):
                r.err(wg, "seed must be an integer 0..2147483647")
            if "source" in g and not (isinstance(g["source"], str) and len(g["source"]) <= 80):
                r.err(wg, "source must be a string of at most 80 characters")
    h = fx.get("halation")
    if h is not None:
        if not isinstance(h, dict):
            r.err(w, "halation must be an object")
        else:
            wh = w + ".halation"
            unknown(r, wh, h, {"strength", "radius_permille", "threshold", "colour", "source"})
            num_in(r, wh, h.get("strength", 0), 0, 100, "strength")
            num_in(r, wh, h.get("radius_permille", 12), 1, 100, "radius_permille")
            num_in(r, wh, h.get("threshold", 0.85), 0, 1, "threshold")
            c = h.get("colour", [1.0, 0.35, 0.15])
            if not (isinstance(c, list) and len(c) == 3 and all(is_num(x) and 0 <= x <= 1 for x in c)):
                r.err(wh, "colour must be 3 numbers within 0..1")
    b = fx.get("bloom")
    if b is not None:
        if not isinstance(b, dict):
            r.err(w, "bloom must be an object")
        else:
            wb = w + ".bloom"
            unknown(r, wb, b, {"strength", "radius_permille", "source"})
            num_in(r, wb, b.get("strength", 0), 0, 100, "strength")
            num_in(r, wb, b.get("radius_permille", 20), 1, 100, "radius_permille")
    v = fx.get("vignette")
    if v is not None:
        if not isinstance(v, dict):
            r.err(w, "vignette must be an object")
        else:
            wv = w + ".vignette"
            unknown(r, wv, v, {"amount", "midpoint", "feather"})
            num_in(r, wv, v.get("amount", 0), -100, 100, "amount")
            num_in(r, wv, v.get("midpoint", 50), 0, 100, "midpoint")
            num_in(r, wv, v.get("feather", 50), 0, 100, "feather")


def check_fit(r, w, fit):
    if not isinstance(fit, dict):
        r.err(w, "fit must be an object")
        return
    unknown(r, w, fit, {"model", "mode", "matrix_orf", "tone", "hue_table", "guards", "predicted"})
    model = fit.get("model")
    if not (isinstance(model, str) and 1 <= len(model) <= 40):
        r.err(w, "fit.model must be a string")
    elif model not in KNOWN_FIT_MODELS:
        r.warn(w, "fit.model %r is not known to this checker: the builder will ignore `fit` and refit from the intent" % model)
    if fit.get("mode") not in BASES[1:]:
        r.err(w, "fit.mode must be one of %s" % ", ".join(BASES[1:]))
    m = fit.get("matrix_orf")
    if m is not None:
        if not (isinstance(m, list) and len(m) == 9 and all(is_int(x) and -1024 < x < 1024 for x in m)):
            r.err(w, "fit.matrix_orf must be 9 integers within +-1023")
        else:
            for i in range(3):
                s = sum(m[3 * i:3 * i + 3])
                if abs(s - 256) > 1:
                    r.err(w, "fit.matrix_orf row %d sums to %d (must be 256 +-1)" % (i, s))
    t = fit.get("tone")
    if t is not None:
        if not isinstance(t, dict):
            r.err(w, "fit.tone must be an object")
        else:
            unknown(r, w + ".tone", t, {"y_curve", "c_curves", "domain", "luma_arg"})
            if "luma_arg" in t and t["luma_arg"] not in ("yb", "post"):
                r.err(w, "fit.tone.luma_arg must be 'yb' (web1: y = F + d - W.d + h(Yb)) or 'post' (y = F + d + h(Y3), Y3 = W.(F + d)); absent means 'yb'")
            for name, pts in [("y_curve", t.get("y_curve"))] + [("c_curves.%s" % k, v) for k, v in (t.get("c_curves") or {}).items()]:
                if pts is None:
                    continue
                if not (isinstance(pts, list) and 2 <= len(pts) <= 33 and all(
                        isinstance(p, list) and len(p) == 2 and is_num(p[0]) and is_num(p[1]) for p in pts)):
                    r.err(w, "fit.tone.%s must be 2..33 [x, y] points" % name)
                elif any(not b[0] > a[0] for a, b in zip(pts, pts[1:])):
                    r.err(w, "fit.tone.%s: x must be strictly increasing" % name)
            if model == "cm-v2-web1":
                # cm-v2-web1 reading of fit.tone (spec 9c): x in 0..1, |y| <= 0.4, and Y + h must not fall (the camera's luma-only T2 is monotone)
                for name, pts in [("y_curve", t.get("y_curve"))] + [("c_curves.%s" % k, v) for k, v in (t.get("c_curves") or {}).items()]:
                    if not (isinstance(pts, list) and all(isinstance(p, list) and len(p) == 2 and is_num(p[0]) and is_num(p[1]) for p in pts)):
                        continue
                    if any(not 0 <= p[0] <= 1 or abs(p[1]) > 0.4 for p in pts):
                        r.err(w, "fit.tone.%s: x must be in 0..1 and |y| at most 0.4 (cm-v2-web1)" % name)
                yc = t.get("y_curve")
                if isinstance(yc, list) and all(isinstance(p, list) and len(p) == 2 and is_num(p[0]) and is_num(p[1]) for p in yc):
                    if any((b[0] + b[1]) < (a[0] + a[1]) - 1e-4 for a, b in zip(yc, yc[1:])):
                        r.err(w, "fit.tone.y_curve: x + y must be non-decreasing (a luma lift may not invert the tone)")
                if "y_curve" in t and "c_curves" not in t or "c_curves" in t and "y_curve" not in t:
                    r.warn(w, "fit.tone has only one of y_curve / c_curves: the builder lifts what is present and keeps the stock curve for the other")
    g = fit.get("guards")
    if g is not None:
        if not isinstance(g, dict):
            r.err(w, "fit.guards must be an object")
        else:
            unknown(r, w + ".guards", g, {"composed_max", "hdr_clip_pct", "tone_strength"})
            if "composed_max" in g:
                if num_in(r, w, g["composed_max"], 0, 100000, "guards.composed_max") and g["composed_max"] >= 1024:
                    r.err(w, "guards.composed_max %r must stay below 1024" % g["composed_max"])
            if "hdr_clip_pct" in g:
                num_in(r, w, g["hdr_clip_pct"], 0, 100, "guards.hdr_clip_pct")
            if "tone_strength" in g:
                num_in(r, w, g["tone_strength"], 0, 1, "guards.tone_strength")
    p = fit.get("predicted")
    if p is not None:
        if not isinstance(p, dict):
            r.err(w, "fit.predicted must be an object")
        else:
            unknown(r, w + ".predicted", p, {"dE", "pct_lt5", "scenes", "worst"})
            if "dE" in p:
                num_in(r, w, p["dE"], 0, 100, "predicted.dE")
            if "pct_lt5" in p:
                num_in(r, w, p["pct_lt5"], 0, 100, "predicted.pct_lt5")


def check_look(r, idx, look, seen_slots, hue_requests, v2):
    w = "looks[%d]" % idx
    if not isinstance(look, dict):
        r.err(w, "must be an object")
        return
    unknown(r, w, look, LOOK_KEYS_V2 if v2 else LOOK_KEYS_V1)
    slot = look.get("slot")
    if slot is None and v2:
        pass                     # v2: the builder / UI asks for the slot
    elif not is_int(slot) or slot not in SLOTS:
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
        elif slot is None and v2:
            if len(name) > max(NAME_CAP.values()):
                r.err(w, "name %r is %d characters, longer than any slot allows (%d)" % (name, len(name), max(NAME_CAP.values())))
            elif len(name) > min(NAME_CAP.values()):
                r.warn(w, "name %r is %d characters: it will not fit every slot (shortest limit %d)" % (name, len(name), min(NAME_CAP.values())))
    if "label" in look:
        lab = look["label"]
        if not isinstance(lab, str) or not LABEL_RE.match(lab):
            r.err(w, "label must be 1..7 characters of A-Z 0-9 space . -")
        elif slot is not None and slot not in ICON_SLOTS:
            r.warn(w, "slot %d borrows an existing icon: label ignored" % slot)
    if "base" in look:
        check_base(r, w, look["base"], v2)
    if "strength" in look:
        num_in(r, w, look["strength"], 1, 100, "strength")
    if "notes" in look and (not isinstance(look["notes"], str) or len(look["notes"]) > 200):
        r.err(w, "notes must be a string of at most 200 characters")
    model = look.get("hsl_model", "tent")
    if v2 and "hsl_model" in look and look["hsl_model"] not in HSL_MODELS:
        r.err(w, "hsl_model must be one of %s" % ", ".join(HSL_MODELS))
        model = "tent"
    if "hsl" in look:
        check_hsl(r, w + ".hsl", look["hsl"], v2, model)
    if "global" in look:
        g = look["global"]
        if not isinstance(g, dict):
            r.err(w, "global must be an object")
        else:
            unknown(r, w + ".global", g, GLOBAL_KEYS_V2 if v2 else {"hue_deg", "sat_pct"})
            num_in(r, w + ".global", g.get("hue_deg", 0), -60, 60, "hue_deg")
            num_in(r, w + ".global", g.get("sat_pct", 0), -100, 100, "sat_pct")
            if v2 and "vibrance_pct" in g:
                num_in(r, w + ".global", g["vibrance_pct"], -100, 100, "vibrance_pct")
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
            unknown(r, w + ".tone", t, TONE_KEYS_V2 if v2 else {"curve", "curve_rgb"})
            if "curve" in t:
                check_curve(r, w + ".tone.curve", t["curve"])
            if v2 and "exposure_ev" in t:
                num_in(r, w + ".tone", t["exposure_ev"], -5, 5, "exposure_ev")
            if v2 and "curve_mode" in t and t["curve_mode"] not in CURVE_MODES:
                r.err(w + ".tone", "curve_mode must be one of %s" % ", ".join(CURVE_MODES))
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
    lut_source = False
    if v2:
        if "source" in look:
            check_source(r, w + ".source", look["source"])
            s = look["source"]
            if isinstance(s, dict):
                lut_source = s.get("type") in LUT_SOURCE_TYPES
                if lut_source and s.get("requires_file", True) and "sha256" not in s:
                    r.warn(w + ".source", "a %s source without sha256: the builder cannot verify the table it is given" % s.get("type"))
                if s.get("approximate"):
                    r.warn(w + ".source", "imported from a slider preset: the numbers approximate the originating editor")
        if "split" in look:
            check_split(r, w + ".split", look["split"])
        if "calibration" in look:
            check_calibration(r, w + ".calibration", look["calibration"])
        if "fx" in look:
            check_fx(r, w + ".fx", look["fx"])
        if "fit" in look:
            check_fit(r, w + ".fit", look["fit"])
    params = ("hsl", "global", "wb", "tone") + (("split", "calibration", "fit") if v2 else ())
    if not any(k in look for k in params) and not lut_source:
        r.warn(w, "no colour or tone parameters: the look is the identity")


def check_pack(r, pack, looks):
    """PACK_SPEC_v2.md: pack.{name, base{name,sha1}, order, hidden, renames} + per-look rules of a pack (slot required, fit.mode == slot base mode, icon)"""
    w = "pack"
    if not isinstance(pack, dict):
        r.err(w, "must be an object")
        return
    for k in pack:
        if k not in PACK_KEYS:
            r.err(w, "unknown key %r (allowed: %s)" % (k, ", ".join(sorted(PACK_KEYS))))
    nm = pack.get("name")
    if nm is not None and not (isinstance(nm, str) and len(nm) <= 40 and all(0x20 <= ord(c) <= 0x7E for c in nm)):
        r.err(w, "name must be at most 40 printable ASCII characters")
    b = pack.get("base")
    if not isinstance(b, dict):
        r.err(w, "base {name, sha1} is required")
    else:
        unknown(r, w + ".base", b, {"name", "sha1"})
        if not (isinstance(b.get("sha1"), str) and HEX40.match(b["sha1"])):
            r.err(w + ".base", "sha1 must be 40 lower-case hex digits (the exact release image the pack is for)")
        if "name" in b and not (isinstance(b["name"], str) and len(b["name"]) <= 24):
            r.err(w + ".base", "name must be a string of at most 24 characters")

    def item(x):
        return (is_int(x) and x in SLOTS) or (isinstance(x, str) and x in PACK_STOCK)
    hidden = pack.get("hidden", [])
    order = pack.get("order", [])
    if not isinstance(hidden, list) or any(not (is_int(x) and x in SLOTS) for x in hidden) or len(set(hidden)) != len(hidden):
        r.err(w, "hidden must be a list of distinct look slots 1..18")
        hidden = []
    if not isinstance(order, list) or any(not item(x) for x in order) or len(set(map(repr, order))) != len(order):
        r.err(w, "order must be a list of distinct look slots (integers 1..18) / stock items (%s)" % ", ".join(PACK_STOCK[:4]) + ", ...")
        order = []
    both = [x for x in order if x in hidden and is_int(x)]
    if both:
        r.err(w, "hidden slots cannot also be in order: %s" % both)
    rn = pack.get("renames", {})
    slots_in = {l.get("slot") for l in looks if isinstance(l, dict)}
    if not isinstance(rn, dict):
        r.err(w, "renames must be an object {slot: name}")
        rn = {}
    for k, v in rn.items():
        if not (isinstance(k, str) and k.isdigit() and int(k) in SLOTS):
            r.err(w + ".renames", "key %r is not a slot 1..18" % k)
            continue
        slot = int(k)
        if not isinstance(v, str) or not v or v != v.strip() or any(not 0x20 <= ord(c) <= 0x7E for c in v) or "@" in v:
            r.err(w + ".renames", "name of slot %d must be non-empty printable ASCII without '@' or edge spaces" % slot)
        elif len(v) > PACK_NAME_CAP[slot]:
            r.err(w + ".renames", "name %r has %d characters, slot %d allows %d" % (v, len(v), slot, PACK_NAME_CAP[slot]))
        if slot in slots_in:
            r.warn(w + ".renames", "slot %d is also in looks[]: its looks[] name wins" % slot)
    for i, l in enumerate(looks):
        if not isinstance(l, dict):
            continue
        lw = "looks[%d]" % i
        if l.get("slot") is None:
            r.err(lw, "a pack look needs its slot")
        if l.get("icon", "roll") not in ("roll", "keep"):
            r.err(lw, 'icon must be "roll" or "keep"')
        fit = l.get("fit")
        if not isinstance(fit, dict):
            r.err(lw, "a pack look needs a fit block (cm-v2-web1): intent-only looks cannot be built yet")
        elif is_int(l.get("slot")) and l["slot"] in SLOT_MODE and fit.get("mode") != SLOT_MODE[l["slot"]]:
            r.err(lw, "slot %d has the base mode %s but the look was fitted on %s (a look only goes into a slot of its base mode)" % (l["slot"], SLOT_MODE[l["slot"]], fit.get("mode")))
        if is_int(l.get("slot")) and l["slot"] in hidden:
            r.warn(lw, "slot %d is hidden: its new look cannot be selected in the camera" % l["slot"])


def check(data, size=0):
    r = Report()
    if size > MAX_BYTES:
        r.err("file", "larger than 1 MiB")
    if not isinstance(data, dict):
        r.err("file", "top level must be an object")
        return r
    version = data.get("version")
    v2 = version == 2 and is_int(version)
    unknown(r, "file", data, TOP_KEYS_V2 if v2 else TOP_KEYS_V1)
    if data.get("format") != "om10mi-look":
        r.err("file", 'format must be "om10mi-look"')
    if not is_int(version):
        r.err("file", "version must be an integer")
    elif version not in (1, 2):
        r.err("file", "version %d not supported (this checker reads 1 and 2)" % version)
    if data.get("target") != "E113":
        r.err("file", 'target must be "E113" (E-M10 Mark I); other bodies are refused')
    gen = data.get("generator")
    if gen is not None:
        if not isinstance(gen, dict):
            r.err("file", "generator must be an object")
        else:
            unknown(r, "file.generator", gen, {"name", "version", "model"} if v2 else {"name", "version"})
    looks = data.get("looks")
    pack = data.get("pack") if v2 else None
    if "pack" in data and not v2:
        r.err("file", "`pack` needs version 2")
    if not isinstance(looks, list) or not (0 if pack is not None else 1) <= len(looks) <= MAX_LOOKS:
        r.err("file", "looks must be a list of %d to %d objects" % (0 if pack is not None else 1, MAX_LOOKS))
        return r
    seen, hue_requests = set(), []
    for i, look in enumerate(looks):
        check_look(r, i, look, seen, hue_requests, v2)
    if pack is not None:
        check_pack(r, pack, looks)
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
