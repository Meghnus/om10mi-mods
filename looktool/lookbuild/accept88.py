#!/usr/bin/env python3
"""accept88.py - the mandatory acceptance battery of a pack-built image (STATIC, stdlib only; addresses / counts only, no firmware bytes).

    python looktool/lookbuild/accept88.py --base BASE.BIN --built BUILT.BIN [--order 11,7,6,Portrait] [--hidden 12] [--replaced 7=Name ...]
                                                [--renamed 3=Name ...] [--keep-icon 7 ...] [--neg]            exit 1 on any FAIL

    run(base_bin, built_bin, touched) -> [(id, 'PASS'|'FAIL'|'INFO', detail)]
        touched = dict(replaced={slot: name}, renamed={slot: name}, order=[slot | stock name, ...], hidden=[slot, ...], keep_icon=[slot, ...] (optional))
    format_report(results) -> text;  negative_controls(base_bin, built_bin, touched) -> byte-flip / plain-base controls (each must FAIL its matching check)

Every id starts with the owner criterion it proves:
  A1  the look is selectable from Picture Mode in the shooting MENU (row, name on highlight, per-look page chain) and from SCP / Live Control; dial stepping
  A2  every basic picture-mode function: SCP C/S/Sat sync = base mode, per-look User Hue cells, tone tables (T2 monotone, T3 legal), base-bearing tables,
      colour-wheel / Color Creator code + tables untouched
  A3  in-camera RAW Data Edit: Current / Custom1 / Custom2 strips and maps (505 / 506, LOOKBASE, a35 / b35 / L35 / LABELS36), z27+ bank-pass (F1b) caves untouched
  A4  LCD and EVF: the z28 EVF caves / transform bytes are byte-identical to the base; names + icons are drawn from the same lists on both outputs
  U   every UNTOUCHED slot is byte-identical (matrix / T3 / T2 / name in 34 languages / icons)
  O   order + hide: exact row order of every list, rows travel whole, hidden rows behind the counts of the UI lists but kept everywhere a RAW / Myset resolves
  G   container, layout, confinement (every changed byte inside a declared site)
Statuses: PASS / FAIL / INFO (INFO = not applicable on this base, or a documented limit). A FAIL anywhere refuses the build.
All checks are STATIC: bytes of the written image read through the layout facts of the 18-look release layout. z26 / z27 / z28 share every address used here (they differ
only in the caves named in CAVES). Own code, Apache-2.0.
"""
import sys

if __package__ in (None, ""):                         # script mode: run the package module (relative imports)
    import os
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
    from lookbuild.accept88 import main
    sys.exit(main())

import argparse
import hashlib
import struct
from collections import Counter

from . import container as C
from . import icons88 as IC
from . import names88 as N
from . import p1strings as P
from . import slots88 as S

B = S.P0_BASE
NS = S.NSLOT
PINNED = {"baf96f07b86f40aa91bb100a3658f64d9ed4dcf2": "release 94"}

# ------------------------------------------------------------------------------------------------ layout facts (VA, strides, counts)
STOCK_VALUE = {"i-Enhance": 7, "Vivid": 0, "Natural": 1, "Muted": 2, "Portrait": 5, "Monotone": 3, "Custom": 6, "e-Portrait": 20, "Color Creator": 21}
STOCK_VALUE.update({"ART%d" % n: 7 + n for n in range(1, 13)})
GUI_OF_BASE = {"Vivid": 0, "Natural": 1, "Muted": 2, "Portrait": 5, "Monotone": 3}
RAWMONO = {"Vivid": (1, 0), "Natural": (2, 0), "Muted": (3, 0), "Portrait": (4, 0), "Monotone": (5, 1)}
FLAG = {"Vivid": 345, "Natural": 346, "Muted": 347, "Portrait": 348, "Monotone": 349}
LVORD = {"Vivid": 2, "Natural": 3, "Muted": 4, "Portrait": 5, "Monotone": 6}
RAW_OF = {"Vivid": 1, "Natural": 2, "Muted": 3, "Portrait": 4, "Monotone": 5}
D111, D505, D506 = 0x7dc47dcc, 0x7dc48038, 0x7dc4804c
MENU_D, SCP_D, LC_D = 0x7e5cb744, 0x7e5af38c, 0x7e5a7e9c
SEL2REC_VA, SEL2REC_N = 0x7d9bb4d4, 19
CC2_VA, CC2_ROWS = 0x7d9bb4fc, 18
STUB_VA, LIST2_VA, LIST2_STRIDE, LIST2_ROWS = 0x7d9b7780, 0x7e5c9b30, 24, 17
CELLS_RAM, CELL_STRIDE, HSLB_RAM = 0x609cb204, 36, 0x609cb480
JT_PTR_VA, JT_MAX_VA = 0x7db716a4, 0x7db7169b
LOOKBASE_PTR_VA = 0x7d9b950a
LAB36_VA, LAB36_N = 0x7d9b7950, 40          # head 0 + one caption id per strip position, then two 0xffff
CB_HOME, TBL_LEN = 0x7d9b77e9, 19
TBL_VA = CB_HOME + 18 + 22 + 19
CB0 = (0x7db6ec64, 0x7db6ec7d, 0x7db6ec96, 0x7db6ecaf, 0x7db6ecc8)
CB1 = (0x7db70798, 0x7db707b6, 0x7db707d4, 0x7db707f2, 0x7db70810)
TSCF, TSCF_STRIDE, TSCF_ROWS = 0x7d9bd000, 0xC0, 24
ICONT_BASE = 0x7d9bafc0
FF32 = 0xFFFFFFFF
NVAL = 39                                    # 38 items + i-Enhance
SPARE_VALUE = 36

# the order-bearing lists: name -> (pointer / address source, physical rows, stride); every one holds ALL 39 (40) rows physically, hidden ones behind the visible count
#   role: 'shrink' physical order V + H, count word = |V|;  'svc' V + [36] + H, desc total = (|V| + 1) * 12;  'full' V + H, count fixed;  'title' V + H + [36]
LISTS = ("tblB", "tblA", "menu", "scpa", "scpb", "lca", "lcb", "lctext", "en", "title", "a35", "b35", "L35", "map505b", "map505a", "map506b", "map506a")
ROLE = {"tblB": "svc", "tblA": "svc", "menu": "shrink", "scpa": "shrink", "scpb": "shrink", "lca": "shrink", "lcb": "shrink", "lctext": "shrink", "en": "full",
        "title": "title", "a35": "full", "b35": "full", "L35": "full", "map505b": "full", "map505a": "full", "map506b": "full", "map506a": "full"}
PARTNER = {"tblA": "tblB", "map505a": "map505b", "map506a": "map506b"}
# visible-count words: (VA, width, kind) kind 'n' = |V|, 'svc' = (|V| + 1) * 12
COUNT_WORDS = (("desc111 total", D111 + 12, 2, "svc"), ("menu count", MENU_D + 8, 4, "n"), ("scp count", SCP_D + 2, 2, "n"), ("lc count", LC_D + 12, 4, "n"), ("lctext count", LC_D + 40, 4, "n"))
FIXED_WORDS = (("enable bound", 0x7db6f7cb, 1, 39), ("title count", 0x7e2e1faa, 1, 40), ("labels36 bound", 0x7e28e26b, 1, 39), ("l35 count 505", 0x7d9b6188, 4, 39), ("l35 count 506", 0x7d9b6224, 4, 39),
               ("desc111 id / elsize", D111, 2, 111), ("desc111 elsize", D111 + 14, 2, 12), ("desc505 id", D505, 2, 505), ("desc506 id", D506, 2, 506), ("desc505 total", D505 + 12, 2, 624),
               ("desc506 total", D506 + 12, 2, 624), ("desc505 elsize", D505 + 14, 2, 16), ("desc506 elsize", D506 + 14, 2, 16))
# readers of the lists: pointer sites that must still hold the list bases
A35_READERS = (0x7d9b87ec, 0x7d9b890c, 0x7d9b8a04, 0x7d9b8b68, 0x7e5f6b14, 0x7e5f6ba4, 0x7e5f763c, 0x7e5f76f0)
# value / selector keyed regions with their own order: byte-identical to the base whatever the pack does (name, VA, length)
VALUE_KEYED = (("info icon list", 0x7d9b9ff0, 480), ("loader jump table", 0x7d9b9c08, 164), ("jump-S + stub", 0x7d9baefc, 180), ("iconT", 0x7d9bafc0, 72), ("PM-cell T (pmt)", 0x7d9bb018, 204),
               ("LV ordinal", 0x7d9bb380, 324), ("cc2 (SEL2REC, LOOKBASE, Look list)", 0x7d9bb4d0, 276), ("LV image list", 0x7e5b6bc8, 320), ("scf id tables", 0x7d9bd000, 768),
               ("rules arrays", 0x7d9bb930, 936), ("per-look page rows (list2)", LIST2_VA, LIST2_ROWS * LIST2_STRIDE), ("per-look page stubs", STUB_VA, 68))
# the name tables: (label, list, id offset in the row, id width, id kind 'L' = LOOKSTR (plain) / 'D' = DONOR (glyph ids)); LABELS36 and the cc2 list are handled apart
LABEL_TABLES = (("lctext (LC text / info labels)", "lctext", 6, 2, "L"), ("PM menu rows", "menu", 6, 2, "D"), ("L35 (RAW-edit strip caption)", "L35", 4, 4, "L"))
PMT_VA, PMT_ROWS = 0x7d9bb01c, 25                           # PM-cell T {value, id} rows (value-keyed, never reordered)
# the nine icon fields: (list, id offset, id width, role)
ICON_FIELDS = {"info": ("info", 6, 2, "U"), "scpa": ("scpa", 6, 2, "U"), "lca": ("lca", 6, 2, "U"), "scpb": ("scpb", 6, 2, "S"), "lcb": ("lcb", 6, 2, "S"),
               "a35": ("a35", 4, 4, "U"), "b35": ("b35", 4, 4, "S"), "lvimg": ("lvimg", 4, 4, "U")}
VALUE_LISTS = {"info": (0x7d9b9ff0, 40, 12), "lvimg": (0x7e5b6bc8, 40, 8), "lvord": (0x7d9bb384, 40, 8), "pmt": (PMT_VA, PMT_ROWS, 8)}
# caves / regions that must stay byte-identical to the base (declared in the builds' reports; addresses only)
CAVES = {
    "A3": [("z27 RAW-edit bank-pass zone (CAVE1 / F1b entry cave 0x7d9b7a00 + FILL / SUB3 neighbours)", 0x7d9b79b0, 0x7d9b8700 - 0x7d9b79b0),
           ("z27 F1b arming site in the leak-cure zone", 0x7d9bbf60, 16)],
    "A4": [("z28 WBG cave (WB in Color Creator)", 0x7d9bbf00, 54), ("z28 hint cave (EVF hint transform)", 0x7d9bc960, 116), ("z28 WRAP cave (per-paint centre select)", 0x7d9bc9e4, 31),
           ("z28 cx cell", 0x7d9bc030, 2), ("z28 rule-engine hook", 0x7db6c4b6, 6), ("z28 paint slot word", 0x7e4881a8, 4)],
    "A2": [("colour-wheel / Color Creator zone (HOME2, cw caves)", 0x7d9bbdb0, 0x7d9bd000 - 0x7d9bbdb0), ("colour-wheel hint / paint zone", 0x7d9b1710, 0x7d9b1ff0 - 0x7d9b1710),
           ("guide-text switch (GSW)", 0x7d9b2728, 172), ("z26 SCP sync cave", CB_HOME, 78), ("SCP C/S/Sat scf tables", TSCF, TSCF_STRIDE * 4),
           ("loader callbacks bank 0", CB0[0], CB0[-1] + 25 - CB0[0]), ("loader callbacks bank 1", CB1[0], CB1[-1] + 30 - CB1[0]), ("MAIN4 / SUB3 develop code", 0x7d9b9390, 0x7d9b9500 - 0x7d9b9390),
           ("look descriptors + pointer table", S.DESC_VA, 12 * NS), ("look pointer table", S.TBL_N_VA, 4 * NS)],
}
HOMES = list(S.HOMES)


def pm_value(s):
    return s + 21 if s <= 14 else s + 22


def value_slot(v):
    return v - 21 if 22 <= v <= 35 else (v - 22 if 37 <= v <= 40 else None)


def item_value(it):
    """pack item (look slot int / digit string / stock name) -> GUI picture-mode value"""
    if isinstance(it, bool):
        raise ValueError("bad item %r" % (it,))
    if isinstance(it, int) or (isinstance(it, str) and it.strip().isdigit()):
        s = int(it)
        if not 1 <= s <= NS:
            raise ValueError("look slot %r out of range" % (it,))
        return pm_value(s)
    if it in STOCK_VALUE:
        return STOCK_VALUE[it]
    raise ValueError("unknown item %r" % (it,))


def item_label(v):
    s = value_slot(v)
    if s:
        return "slot %d" % s
    return next((k for k, x in STOCK_VALUE.items() if x == v), "value %d" % v)


# ------------------------------------------------------------------------------------------------ image access
class Img:
    """p0 / p1 plain bytes (+ the stored p2 payload) of an image; or built from planes (negative controls)"""

    def __init__(self, data=None, p0=None, p1=None, raw2=None):
        self.parts = None
        if data is not None:
            self.parts = C.split_image(data)
            p0, p1, raw2 = self.parts[0].plain(), self.parts[1].plain(), self.parts[2].raw if len(self.parts) > 2 else b""
        self.p0, self.p1, self.raw2 = bytearray(p0), bytearray(p1), bytes(raw2)
        self._lists, self._nb = {}, None

    def u8(self, va):
        return self.p0[va - B]

    def u16(self, va):
        return struct.unpack_from("<H", self.p0, va - B)[0]

    def u32(self, va):
        return struct.unpack_from("<I", self.p0, va - B)[0]

    def rd(self, va, n):
        return bytes(self.p0[va - B:va - B + n])

    def namebook(self):
        if self._nb is None:
            self._nb = N.NameBook(self.p1)
        return self._nb

    # ---- lists
    def loc(self, name):
        """(va, physical rows, stride) of a list, the pointer read from the image's own descriptor"""
        u32, u16, u8 = self.u32, self.u16, self.u8
        if name in ("tblA", "tblB"):
            return u32(D111 + (4 if name == "tblA" else 8)), 40, 12 if name == "tblA" else 4
        if name == "en":
            return u32(0x7db6f7b9), 39, 8
        if name == "title":
            return u32(0x7e2e1fa5), 40, 8
        if name == "menu":
            return u32(MENU_D + 4), 39, 36
        if name in ("scpa", "scpb"):
            return u32(SCP_D + (4 if name == "scpa" else 8)), 39, 12
        if name in ("lca", "lcb"):
            return u32(LC_D + (4 if name == "lca" else 8)), 39, 12
        if name == "lctext":
            return u32(LC_D + 36), 39, 12
        if name in ("map505a", "map505b", "map506a", "map506b"):
            d = D505 if "505" in name else D506
            return u32(d + (4 if name.endswith("a") else 8)), 39, 16 if name.endswith("a") else 4
        if name == "a35":
            return 0x7d9bb0f4, 39, 8
        if name == "b35":
            return 0x7d9bb23c, 39, 8
        if name == "L35":
            return 0x7d9b67c0, 39, 8
        if name in VALUE_LISTS:
            va, n, st = VALUE_LISTS[name]
            return va, n, st
        raise KeyError(name)

    def lst(self, name):
        """(va, [row bytes], [keys]) over the PHYSICAL rows; key = u32 at 0 (tblA / map*a: the key of the partner list at the same index)"""
        if name not in self._lists:
            va, n, st = self.loc(name)
            if not (B <= va and va + n * st <= B + len(self.p0)):
                raise ValueError("list %s: pointer %#x outside the image" % (name, va))
            rows = [self.rd(va + st * i, st) for i in range(n)]
            keys = self.lst(PARTNER[name])[2][:n] if name in PARTNER else [struct.unpack_from("<I", r, 0)[0] for r in rows]
            self._lists[name] = (va, rows, keys)
        return self._lists[name]

    def vis(self, name):
        """visible row count of a list (rows behind it are hidden); lists without a count word are fully visible"""
        if name == "menu":
            return self.u32(MENU_D + 8)
        if name in ("scpa", "scpb"):
            return self.u16(SCP_D + 2)
        if name in ("lca", "lcb"):
            return self.u32(LC_D + 12)
        if name == "lctext":
            return self.u32(LC_D + 40)
        if name in ("tblA", "tblB"):
            return (self.u32(D111 + 12) & 0xFFFF) // 12 - 1
        return len(self.lst(name)[1])

    def base_modes(self):
        """{slot: base mode} from the PHYSICAL value-map records (hidden looks' records sit behind the visible count, where slots88.base_mode no longer looks)"""
        out = {}
        for sl in range(1, NS + 1):
            hits = [struct.unpack("<III", r) for r in self.lst("tblA")[1]]
            hits = [(raw, mem) for raw, mem, sel in hits if sel == sl and 1 <= raw <= 5 and mem in (0, 1)]
            if len(hits) != 1:
                raise ValueError("slot %d: %d value-map records (expected 1)" % (sl, len(hits)))
            out[sl] = "Monotone" if hits[0][0] == 5 else S.BASES[hits[0][0]]
        return out

    def row(self, name, key):
        """(index, VA, row bytes) of the first PHYSICAL row of `key`, or None"""
        va, rows, keys = self.lst(name)
        for i, (r, k) in enumerate(zip(rows, keys)):
            if k == key:
                return i, va + i * len(r), r
        return None


# ------------------------------------------------------------------------------------------------ expected order
def expected_order(base, order, hidden):
    """-> (V, H): visible values (i-Enhance + ordered items + the rest in the base's current order) and hidden values (in the base's physical order)"""
    P0 = list(base.lst("menu")[2])
    if base.vis("menu") != NVAL or len(set(P0)) != NVAL or P0[0] != 7:
        raise ValueError("the base is not the stock 39-row Picture Mode list (menu count %d, i-Enhance first %s)" % (base.vis("menu"), P0[:1] == [7]))
    ov = [item_value(i) for i in order or []]
    hv = [item_value(i) for i in hidden or []]
    if len(set(ov)) != len(ov) or any(v not in P0[1:] for v in ov) or any(v in ov for v in hv) or len(set(hv)) != len(hv) or any(value_slot(v) is None for v in hv):
        raise ValueError("order / hidden: duplicates, unknown items, hidden inside order, or a stock item hidden")
    V = [7] + ov + [v for v in P0[1:] if v not in ov and v not in hv]
    return V, [v for v in P0 if v in hv]


def expected_keys(name, V, H):
    r = ROLE[name]
    return V + [SPARE_VALUE] + H if r == "svc" else (V + H + [SPARE_VALUE] if r == "title" else V + H)


def diff_idx(a, b, blk=1 << 16):
    out = []
    for o in range(0, len(a), blk):
        if a[o:o + blk] != b[o:o + blk]:
            out += [o + j for j in range(min(blk, len(a) - o)) if a[o + j] != b[o + j]]
    return out


def _runs(idx):
    out = []
    for i in idx:
        if out and i == out[-1][1]:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return out


def _outside(idx, ranges):
    """indices not covered by any [(lo, hi)] range"""
    rs = sorted(ranges)
    return [i for i in idx if not any(lo <= i < hi for lo, hi in rs)]


# ------------------------------------------------------------------------------------------------ the battery
class Battery:
    def __init__(self, A, Bt, touched, container=True, base_sha=None):
        self.A, self.B, self.t = A, Bt, touched or {}
        self.res = []
        self.container = container
        self.base_sha = base_sha
        t = self.t
        self.replaced = {int(k): v for k, v in (t.get("replaced") or {}).items()}
        self.renamed = {int(k): v for k, v in (t.get("renamed") or {}).items()}
        self.order = list(t.get("order") or [])
        self.hidden = list(t.get("hidden") or [])
        self.keep_icon = {int(x) for x in (t.get("keep_icon") or [])}
        self.moved = {value_slot(item_value(i)) for i in self.order} - {None}
        self.hidden_slots = {int(h) for h in self.hidden}
        self.focus = sorted(set(self.replaced) | set(self.renamed) | self.moved | self.hidden_slots)
        self.sync = self.wbg = False
        self.V = self.H = None

    def add(self, cid, status, detail):
        self.res.append((cid, status, detail))

    def chk(self, cid, ok, detail):
        self.add(cid, "PASS" if ok else "FAIL", detail)

    def guard(self, cid, fn):
        try:
            fn()
        except (ValueError, KeyError, IndexError, struct.error, S.SlotError, N.NameError_, IC.IconError, StopIteration) as e:
            self.add(cid, "FAIL", "check could not run on this image: %s: %s" % (type(e).__name__, e))

    # ---------------------------------------------------------------------------------------- G: container / layout / confinement
    def g_container(self):
        A, Bt = self.A, self.B
        if not self.container:
            self.add("G1.container", "INFO", "plane-level run (negative control): container checks skipped")
            return
        pa, pb = A.parts, Bt.parts
        probs = C.check_parts(pb)
        same = len(pa) == len(pb) and all(a.header == b.header for a, b in zip(pa, pb))
        self.chk("G1.container", not probs and same and A.raw2 == Bt.raw2 and len(A.p0) == len(Bt.p0) and len(A.p1) == len(Bt.p1),
                 "%d partitions, headers == base %s, model id + footer copies + footer checksums %s, p2 payload identical %s, sizes equal %s" % (
                     len(pb), same, "OK" if not probs else probs[:2], A.raw2 == Bt.raw2, len(A.p0) == len(Bt.p0) and len(A.p1) == len(Bt.p1)))

    def g_layout(self):
        for im in (self.A, self.B):
            S.check_layout(im.p0)
        a = self.A
        self.wbg, self.sync = a.u8(0x7d9bbf00) != 0xFF, a.u8(CB_HOME) != 0xFF
        sha = self.base_sha
        self.tier = PINNED.get(sha) if sha else None
        self.tier = self.tier or ("z28-class (EVF / WB caves present)" if self.wbg else ("z26/z27-class (SCP sync cave present)" if self.sync else "pre-z26 (no sync cave)"))
        self.V, self.H = expected_order(a, self.order, self.hidden)
        self.chk("G2.layout", True, "18-slot release layout (look table, descriptors, T3/T2 homes) on base and built; base = %s; SCP sync cave %s, EVF/WB caves %s; base Picture Mode list = %d rows, all visible" % (
            self.tier, "present" if self.sync else "absent", "present" if self.wbg else "absent", NVAL))

    def list_regions(self):
        out = []
        for nm in LISTS:
            va, n, st = self.A.loc(nm)
            out.append((va - B, va - B + n * st))
        out.append((LAB36_VA - B, LAB36_VA - B + 2 * LAB36_N))
        return out

    def allowed_p0(self):
        """[(lo, hi)] file offsets the pack may change: sites of the replaced slots + the whole order-list regions + LABELS36 (+ the count words when something is hidden)"""
        out = []
        for s in self.replaced:
            out += [(va - B, va - B + n) for va, n, _ in S.sites(s)]
        if self.order or self.hidden:
            out += self.list_regions()
            if self.hidden:
                out += [(va - B, va - B + w) for _n, va, w, _k in COUNT_WORDS]
        return out

    def allowed_p1(self):
        """[(lo, hi)] of p1: name strings of the replaced + renamed slots, icon data of the replaced slots (not keep)"""
        out = []
        nb = self.A.namebook()
        for s in set(self.replaced) | set(self.renamed):
            for lang, t in nb.tabs.items():
                for sid in N.NAME_IDS[s]:
                    off, cur = t[sid]
                    pre = len(P.GLYPH) if sid in N.glyph_ids(s) else 0
                    out.append((off, off + 2 * max(N.NAME_CAP[s] + pre, len(cur)) + 2))
        for s in self.replaced:
            if s not in self.keep_icon:
                for iid in self.icon_ids(self.A, s):
                    h = IC.header(self.A.p1, iid)
                    out.append((h["df"], h["df"] + h["size"]))
        return out

    def g_confine(self):
        A, Bt = self.A, self.B
        d0 = diff_idx(A.p0, Bt.p0)
        bad0 = _outside(d0, self.allowed_p0())
        same_len = len(A.p1) == len(Bt.p1)
        d1 = diff_idx(A.p1, Bt.p1) if same_len else []
        bad1 = _outside(d1, self.allowed_p1())
        self.chk("G3.confine", not bad0 and not bad1 and same_len and A.raw2 == Bt.raw2,
                 "p0: %d changed bytes in %d runs, all inside the declared sites (matrix/T3/T2 of slot(s) %s%s); p1: %d changed bytes, all inside the name strings of slot(s) %s and the icon data of slot(s) %s; "
                 "outside p0 %s, outside p1 %s; p2 identical %s" % (
                     len(d0), len(_runs(d0)), sorted(self.replaced) or "none", " + the order-list regions" + (" + count words" if self.hidden else "") if (self.order or self.hidden) else "", len(d1),
                     sorted(set(self.replaced) | set(self.renamed)) or "none", sorted(s for s in self.replaced if s not in self.keep_icon) or "none",
                     [hex(B + x) for x in bad0[:3]] or "none", [hex(x) for x in bad1[:3]] or "none", A.raw2 == Bt.raw2))

    # ---------------------------------------------------------------------------------------- icons (keyed by value, any row order)
    def icon_ids(self, im, s):
        """-> (U id, S id) of slot s read by value key from the 8 icon lists + iconT; ValueError when the fields disagree"""
        v = pm_value(s)
        U, Sx = set(), set()
        for f, (lname, off, w, role) in ICON_FIELDS.items():
            r = im.row(lname, v)
            if r is None:
                raise ValueError("slot %d: no row of value %d in the %s icon list" % (s, v, f))
            (U if role == "U" else Sx).add(struct.unpack_from("<H" if w == 2 else "<I", r[2], off)[0])
        U.add(im.u32(ICONT_BASE + 4 * (v - 22)))
        if len(U) != 1 or len(Sx) != 1:
            raise ValueError("slot %d: icon fields disagree (U %s, S %s)" % (s, sorted(U), sorted(Sx)))
        return U.pop(), Sx.pop()

    def icons(self):
        A, Bt = self.A, self.B
        bad, ids_all = [], []
        for s in range(1, NS + 1):
            try:
                ia, ib = self.icon_ids(A, s), self.icon_ids(Bt, s)
            except ValueError as e:
                bad.append(str(e))
                continue
            if ia != ib:
                bad.append("slot %d: icon ids %s != base %s" % (s, ib, ia))
            for iid in ib:
                h = IC.header(Bt.p1, iid)
                if (h["type"], h["w"], h["h"], h["bpp"], h["flags"], h["key"]) != (14, IC.W, IC.H, 8, 0, 0):
                    bad.append("slot %d id %d: header is not type 14, 44x32, 8 bpp" % (s, iid))
                ids_all.append(iid)
        uniq = len(ids_all) == len(set(ids_all))
        self.chk("A4.icons", not bad and uniq, "9 icon fields per slot (info / scpa / lca / a35 / lvimg / iconT = U, scpb / lcb / b35 = S) found by value key, any row order: one U + one S id per slot, ids == base, "
                 "44x32 8 bpp headers, %d own ids unique %s; the same lists feed LCD and EVF (no output-specific icon list) [I]; %s" % (len(ids_all), uniq, bad[:2] or "bad none"))
        if bad:
            return
        rolls, keeps, same, badr = [], [], 0, []
        for s in range(1, NS + 1):
            ua, sa = self.icon_ids(A, s)
            data = []
            for kind, iid in (("U", ua), ("S", sa)):
                h, ha = IC.header(Bt.p1, iid), IC.header(A.p1, iid)
                data.append((kind, iid, bytes(Bt.p1[h["df"]:h["df"] + h["size"]]), bytes(A.p1[ha["df"]:ha["df"] + ha["size"]])))
            identical = all(b == a for _k, _i, b, a in data)
            if s in self.replaced and s not in self.keep_icon:
                ok = True
                for kind, _iid, b, _a in data:
                    try:
                        px, used, _w, _h = IC.decode(b)
                        ok &= px == IC.design(kind) and not any(b[used:])
                    except IC.IconError:
                        ok = False
                if ok and not IC.alias_problems(Bt.p1, (ua, sa)):
                    rolls.append(s)
                else:
                    badr.append((s, "not the universal roll"))
            elif s in self.replaced:                  # keep_icon declared
                (keeps.append(s) if identical else badr.append((s, "icon changed although keep_icon")))
            elif identical:
                same += 1
            else:
                badr.append((s, "icon data differs from the base"))
        self.chk("U3.icons", not badr, "icon data: slot(s) %s = the universal film roll (U + S decode == design pixel-exact, zero tail, no alias); keep-icon slot(s) %s identical; %d other slots byte-identical to the base; bad %s" % (
            rolls or "none", sorted(keeps) or "none", same, badr[:3] or "none"))
        if self.renamed:
            self.add("A1.icon_label", "INFO", "slot(s) %s were only renamed: their icon bitmaps keep the old label text baked into the pixels (documented limit; replace the slot to get the roll)" % sorted(self.renamed))

    # ---------------------------------------------------------------------------------------- A1: names
    def names(self):
        A, Bt = self.A, self.B
        nb_a, nb_b = A.namebook(), Bt.namebook()
        try:
            names_a = {s: nb_a.current_name(s) for s in range(1, NS + 1)}
        except N.NameError_ as e:
            self.add("A1.names", "FAIL", "the BASE image's names are not uniform: %s" % e)
            return
        try:
            names_b = {s: nb_b.current_name(s) for s in range(1, NS + 1)}
        except N.NameError_ as e:
            for cid in ("A1.names", "U2.names"):
                self.add(cid, "FAIL", "a slot's 34 languages / both ids do not carry ONE name in the built image: %s" % e)
            return
        touched = set(self.replaced) | set(self.renamed)
        want = dict(names_a)
        want.update(self.renamed)
        want.update(self.replaced)
        wrong = [(s, names_b[s], want[s]) for s in range(1, NS + 1) if names_b[s] != want[s]]
        self.chk("A1.names", not wrong, "name of every slot read from all 34 languages x both ids: touched slot(s) %s == %s; %d untouched slots unchanged; wrong %s" % (
            sorted(touched) or "none", {s: want[s] for s in sorted(touched)} or "-", NS - len(touched), wrong[:3] or "none"))
        for i, (nm, lname, off, w, kind) in enumerate(LABEL_TABLES, 1):
            bad, rows, txt = [], 0, []
            for s in range(1, NS + 1):
                r = Bt.row(lname, pm_value(s))
                if r is None:
                    bad.append((s, "row missing"))
                    continue
                rows += 1
                sid = struct.unpack_from("<H" if w == 2 else "<I", r[2], off)[0]
                ids = N.NAME_IDS[s]
                exp = ids[0] if (kind == "L" or len(ids) == 1) else ids[1]
                if sid != exp:
                    bad.append((s, "id", sid, exp))
                    continue
                if r[2] != A.row(lname, pm_value(s))[2]:
                    bad.append((s, "row bytes differ from the base"))
                if s in self.focus:
                    wanted = (P.GLYPH if sid in N.glyph_ids(s) else "") + names_b[s]
                    txt += [(s, lang, t[sid][1]) for lang, t in nb_b.tabs.items() if t[sid][1] != wanted]
            self.chk("A1.table%d" % i, not bad and not txt, "%s: every slot's row (found by value key, %d rows incl. hidden ones) carries its own writer id (%s ids), row == the base's row; the text of the id of touched slots "
                     "is the name in 34 languages%s%s" % (nm, rows, "LOOKSTR" if kind == "L" else "DONOR/glyph", "; id problems %s" % bad[:3] if bad else "", "; text %s" % txt[:3] if txt else ""))
        # pmt: {value, id} rows, value-keyed, byte-identical (VALUE_KEYED) and carrying the DONOR id
        bad, txt = [], []
        for s in range(1, NS + 1):
            r = Bt.row("pmt", pm_value(s))
            ids = N.NAME_IDS[s]
            exp = ids[0] if len(ids) == 1 else ids[1]
            if r is None or struct.unpack_from("<I", r[2], 4)[0] != exp:
                bad.append(s)
            elif s in self.focus:
                wanted = (P.GLYPH if exp in N.glyph_ids(s) else "") + names_b[s]
                txt += [(s, lang) for lang, t in nb_b.tabs.items() if t[exp][1] != wanted]
        self.chk("A1.table4", not bad and not txt, "pmt (PM-T: SCP / LV picture-mode cell, %d value-keyed rows at %#x): every look row carries its DONOR/glyph id; the text of touched slots is the name in 34 languages; bad %s" % (
            PMT_ROWS, PMT_VA, bad[:3] or txt[:2] or "none"))
        # LABELS36 (position-keyed caption, follows L35)
        va, rows, keys = Bt.lst("L35")
        lab = [struct.unpack_from("<H", Bt.p0, LAB36_VA - B + 2 * i)[0] for i in range(LAB36_N + 2)]
        l35ids = [struct.unpack_from("<I", r, 4)[0] for r in rows]
        bad = [(i, keys[i], lab[i + 1], l35ids[i]) for i in range(len(rows)) if lab[i + 1] != (l35ids[i] & 0xFFFF)]
        self.chk("A1.table5", not bad and lab[0] == 0 and lab[LAB36_N:] == [0xFFFF, 0xFFFF], "LABELS36 (strip caption by POSITION, head 0 + %d ids + two 0xffff at %#x) == the L35 id of the same position (captions follow whatever order L35 has); bad %s" % (
            len(rows), LAB36_VA, bad[:3] or "none"))
        # cc2 Look list (selector-keyed, order independent)
        bad, txt = [], []
        for s in range(1, NS + 1):
            kk = 1 if s == 1 else (0 if s == 2 else s - 1)
            if kk == 0:
                continue
            row = Bt.rd(CC2_VA + 12 * kk, 12)
            sid = struct.unpack_from("<H", row, 6)[0]
            ids = N.NAME_IDS[s]
            exp = ids[0] if len(ids) == 1 else ids[1]
            if struct.unpack_from("<I", row, 0)[0] != kk or sid != exp or row != A.rd(CC2_VA + 12 * kk, 12):
                bad.append((s, kk, sid, exp))
            elif s in self.focus:
                wanted = (P.GLYPH if sid in N.glyph_ids(s) else "") + names_b[s]
                txt += [(s, lang) for lang, t in nb_b.tabs.items() if t[sid][1] != wanted]
        self.chk("A1.table6", not bad and not txt, "cc2 Look list (User-Hue page Look row, %d selector-keyed rows at %#x, order independent): row k of slot s carries its writer id, identical to the base; bad %s" % (
            CC2_ROWS, CC2_VA, bad[:3] or txt[:2] or "none"))
        stale = []
        for s in touched:
            old = names_a[s]
            if old != names_b[s]:
                for lang, t in nb_b.tabs.items():
                    for sid in N.NAME_IDS[s]:
                        txt = t[sid][1] or ""
                        if (txt[len(P.GLYPH):] if sid in N.glyph_ids(s) and txt.startswith(P.GLYPH) else txt) == old:      # exact: a new name may contain the old one ("Provia" -> "Provia2")
                            stale.append((s, lang, sid))
        self.chk("A1.stale", not stale, "no touched slot's string still carries its old name (%d slot(s) checked); %s" % (len(touched), stale[:3] or "none stale"))
        txt = [(s, lang, sid) for s in range(1, NS + 1) if s not in touched for lang, t in nb_b.tabs.items() for sid in N.NAME_IDS[s] if t[sid][1] != nb_a.tabs[lang][sid][1]]
        self.chk("U2.names", not txt, "untouched slots (%d): name text identical to the base in 34 languages x both ids; bad %s" % (NS - len(touched), txt[:3] or "none"))

    # ---------------------------------------------------------------------------------------- O / A1: order, lists, stepping
    def lists_order(self):
        A, Bt = self.A, self.B
        V, H = self.V, self.H
        n = len(V)
        # (1) every list: the exact physical key sequence
        bad = []
        for nm in LISTS:
            keys = Bt.lst(nm)[2]
            want = expected_keys(nm, V, H)
            if keys != want:
                i = next((i for i, (a, b) in enumerate(zip(keys, want)) if a != b), min(len(keys), len(want)))
                bad.append("%s row %d: %s != %s" % (nm, i, item_label(keys[i]) if i < len(keys) else "-", item_label(want[i]) if i < len(want) else "-"))
        det = ", ".join("%s: menu %s / scp %s / lc %s" % (item_label(pm_value(s)), (lambda r: "hidden" if r is None or r[0] >= n else r[0])(Bt.row("menu", pm_value(s))),
                                                         (lambda r: "hidden" if r is None or r[0] >= n else r[0])(Bt.row("scpa", pm_value(s))),
                                                         (lambda r: "hidden" if r is None or r[0] >= n else r[0])(Bt.row("lctext", pm_value(s)))) for s in self.focus[:5])
        self.chk("O1.order", not bad, "all %d order-bearing lists (service map tblA/tblB, menu, SCP A/B, LC icon A/B, LC text, enable map, title, RAW strips a35/b35/L35, RAW maps 505/506 x 2) hold exactly the expected key sequence: "
                 "visible = i-Enhance + %d ordered item(s) + the rest in base order (%d rows), hidden %d behind the count%s; mismatch %s" % (len(LISTS), len(self.order), n, len(H), "; positions of touched looks " + det if det else "", bad[:2] or "none"))
        # (2) visible-count words + fixed words + reader pointers
        bad = []
        for nm, va, w, kind in COUNT_WORDS:
            got = int.from_bytes(Bt.rd(va, w), "little")
            want = (n + 1) * 12 if kind == "svc" else n
            if got != want:
                bad.append("%s %d != %d" % (nm, got, want))
        for nm, va, w, want in FIXED_WORDS:
            if int.from_bytes(Bt.rd(va, w), "little") != want or Bt.rd(va, w) != A.rd(va, w):
                bad.append("%s changed" % nm)
        ptrs = [(D111 + 4, "tblA"), (D111 + 8, "tblB"), (0x7db6f7b9, "en"), (0x7e2e1fa5, "title"), (MENU_D + 4, "menu"), (SCP_D + 4, "scpa"), (SCP_D + 8, "scpb"), (LC_D + 4, "lca"), (LC_D + 8, "lcb"), (LC_D + 36, "lctext"),
                (D505 + 4, "map505a"), (D505 + 8, "map505b"), (D506 + 4, "map506a"), (D506 + 8, "map506b")]
        ptrs += [(a, "a35") for a in A35_READERS] + [(a + 4, "b35") for a in A35_READERS] + [(0x7e5f7594, "L35"), (0x7e5f75dc, "L35"), (0x7e28e277, None)]
        for site, nm in ptrs:
            va = LAB36_VA if nm is None else A.loc(nm)[0]
            if Bt.u32(site) != va or A.u32(site) != va:
                bad.append("reader %#x -> %#x != list base %#x" % (site, Bt.u32(site), va))
        self.chk("O2.counts", not bad, "visible-count words (service map total, menu, SCP, LC, LC text) == the visible count %d; %d fixed counts / bounds / descriptors unchanged; %d reader pointers still hold the list bases (lists never move); %s" % (
            n, len(FIXED_WORDS), len(ptrs), bad[:3] or "ok"))
        # (3) rows travel whole: the multiset of physical rows of every list == the base's, LABELS36 follows
        bad = []
        for nm in LISTS:
            if Counter(Bt.lst(nm)[1]) != Counter(A.lst(nm)[1]):
                bad.append(nm)
        ra, rb = [(k, A.lst("tblA")[1][i]) for i, k in enumerate(A.lst("tblB")[2])], [(k, Bt.lst("tblA")[1][i]) for i, k in enumerate(Bt.lst("tblB")[2])]
        if dict(ra) != dict(rb):
            bad.append("tblB->tblA value -> record pairs")
        for a_, b_ in (("map505a", "map505b"), ("map506a", "map506b")):
            if dict(zip(A.lst(b_)[2], A.lst(a_)[1])) != dict(zip(Bt.lst(b_)[2], Bt.lst(a_)[1])):
                bad.append("%s value -> record pairs" % a_)
        self.chk("O3.rows", not bad, "all %d lists: the physical rows are a pure permutation of the base rows (multiset identical, no row byte changed, none lost or invented); value -> record pairs of the service map and of "
                 "maps 505 / 506 unchanged; bad %s" % (len(LISTS), bad[:3] or "none"))
        # (4) value / selector keyed regions
        bad = [nm for nm, va, ln in VALUE_KEYED if Bt.rd(va, ln) != A.rd(va, ln)]
        vp = [(JT_PTR_VA, 4), (LOOKBASE_PTR_VA, 4)]
        bad += ["pointer %#x" % va for va, w in vp if Bt.rd(va, w) != A.rd(va, w)]
        self.chk("O4.fixed", not bad, "%d value-keyed / selector-keyed regions (info list, loader jump table, jump-S, iconT, PM-cell T, LV ordinal + image list, cc2 SEL2REC / LOOKBASE / Look list, scf id tables, rules arrays, "
                 "per-look page rows + stubs) are byte-identical to the base (order never touches them); changed %s" % (len(VALUE_KEYED), bad or "none"))
        # (5) anchors
        bad = []
        if Bt.lst("tblB")[2][n] != SPARE_VALUE or Bt.lst("tblA")[1][n] != A.lst("tblA")[1][-1] or A.lst("tblB")[2][-1] != SPARE_VALUE:
            bad.append("spare record / sentinel 36 not right behind the visible rows")
        if Bt.lst("title")[2][-1] != SPARE_VALUE:
            bad.append("title table does not end with 36")
        for nm in ("menu", "scpa", "scpb", "lca", "lcb", "lctext", "en", "title", "tblB", "a35", "b35", "L35"):
            if Bt.lst(nm)[2][0] != 7:
                bad.append("%s does not start with i-Enhance" % nm)
        if Bt.lst("tblA")[1][0] != A.lst("tblA")[1][0]:
            bad.append("i-Enhance record moved")
        self.chk("O5.anchors", not bad, "i-Enhance (value 7) first in every list, the spare record {7,0,19} + sentinel 36 right behind the %d visible service-map rows (index-of miss -> spare, set-miss -> i-Enhance semantics unchanged); %s" % (n, bad or "ok"))
        # (6) hidden semantics
        gone = [(nm, s) for nm in ("menu", "scpa", "scpb", "lca", "lcb", "lctext") for s in self.hidden_slots if (Bt.row(nm, pm_value(s)) or (n, 0, 0))[0] < n]
        gone += [("tblB", s) for s in self.hidden_slots if pm_value(s) in Bt.lst("tblB")[2][:n]]
        keep = [(nm, s) for nm in LISTS for s in self.hidden_slots if pm_value(s) not in Bt.lst(nm)[2]]
        keep += [(nm, s) for nm in VALUE_LISTS for s in self.hidden_slots if pm_value(s) not in Bt.lst(nm)[2]]
        self.chk("O6.hidden", not gone and not keep, "hidden slot(s) %s: behind the visible count %d of the service map / menu / SCP A+B / LC A+B / LC text (so dial stepping, the menu, SCP and LC never show them), still present as rows in enable map, "
                 "title, a35 / b35 / L35 / LABELS36 (RAW strips), maps 505 / 506, info, LV, PM-cell lists (a stored RAW / Myset / RAW Data Edit still resolves); visible %s, missing %s" % (
                     sorted(self.hidden_slots) or "none", n, gone or "none", keep or "none"))
        # (7) A1: the touched looks' rows
        bad = []
        for s in self.focus:
            v = pm_value(s)
            for nm in ("menu", "scpa", "scpb", "lca", "lcb", "lctext", "tblB"):
                r = Bt.row(nm, v)
                if r is None:
                    bad.append((s, nm, "no row"))
                elif (r[0] < n) == (s in self.hidden_slots):
                    bad.append((s, nm, "hidden but visible" if s in self.hidden_slots else "behind the count"))
        self.chk("A1.rows", not bad, "every touched look (%s) has its row in the Picture Mode menu, SCP picker A/B, LC icon A/B, LC text and the service map: visible (selectable, name on highlight, SCP / LC strip) unless "
                 "declared hidden (*); bad %s" % (", ".join(item_label(pm_value(s)) + ("*" if s in self.hidden_slots else "") for s in self.focus) or "no touched look", bad[:3] or "none"))

    def stepping(self):
        """content-based replay (mv 2 / rg56 class) of dial / arrow stepping, set / get round trips and the miss semantics on the BUILT tables"""
        Bt = self.B
        V, H = self.V, self.H
        m = len(V) + 1
        _, rowsA, _k = Bt.lst("tblA")
        _, _r, keysB = Bt.lst("tblB")
        nB, nA = keysB[:m], rowsA[:m]
        en = set(Bt.lst("en")[2])
        bad = []
        index_of = lambda b: next((i for i in range(m - 1) if nA[i] == b), m - 1)       # the last record is never compared; a miss returns it (spare)
        set_index = lambda v: nB.index(v) if v in nB else 0                                 # set-miss -> i-Enhance
        for i, v in enumerate(nB[:m - 1]):
            if nB[index_of(nA[i])] != v or index_of(nA[set_index(v)]) != set_index(v):
                bad.append(("round trip", v))
        stray = 0
        for raw in (7, 1, 2, 3, 4, 5, 100, 120):
            for sel in range(1, NS + 2):
                b = struct.pack("<III", raw, 1 if raw == 5 else 0, sel)
                if b not in nA[:m - 1]:
                    stray += 1
                    if index_of(b) != m - 1:
                        bad.append(("stray", raw, sel))

        def walk(d):
            seq, i = [], 0
            for _ in range(m):
                seq.append(nB[i])
                j = i
                for _t in range(m):
                    j = (j + d) % m
                    if nB[j] in en:
                        break
                i = j
                if i == 0:
                    break
            return seq, i
        fwd, i1 = walk(1)
        back, i2 = walk(-1)
        ok_walk = fwd == V and i1 == 0 and back == [V[0]] + V[:0:-1] and i2 == 0 and SPARE_VALUE not in en
        hid = all(index_of(Bt.lst("tblA")[1][Bt.lst("tblB")[2].index(v)]) == m - 1 and set_index(v) == 0 for v in H)
        self.chk("A1.step", ok_walk and not bad and hid, "dial / arrow / LC stepping replay over the built service map (%d visible values + the spare, enable map %d rows, sentinel 36 skipped): forward walk == the expected order and wraps to i-Enhance, "
                 "backward == its mirror; set / get round trips for all %d visible records, %d stray (raw, mono, sel) states -> spare; %d hidden value(s) are never stepped (set-miss -> i-Enhance, record-miss -> spare); %s" % (
                     len(V), len(en), len(V), stray, len(H), bad[:3] or ([] if ok_walk and hid else ["walk != expected"]) or "problems none"))

    # ---------------------------------------------------------------------------------------- A1 / A2: per-look page
    def page(self):
        A, Bt = self.A, self.B
        sel = list(Bt.rd(SEL2REC_VA, SEL2REC_N))
        want = [0] + [1 if s == 1 else (0 if s == 2 else s - 1) for s in range(1, NS + 1)]
        self.chk("A2.cells_sel", sel == want and Bt.rd(SEL2REC_VA, SEL2REC_N) == A.rd(SEL2REC_VA, SEL2REC_N),
                 "SEL2REC %#x: selector -> per-look hue-cell row k = %s, identical to the base (slot 2 = 0: monotone has no hue cells); the cells of slot s are at %#x + 36(k-1); k never depends on the list order" % (SEL2REC_VA, sel, CELLS_RAM))
        bad = []
        for s in range(1, NS + 1):
            if s == 2:
                continue
            v, k = pm_value(s), want[s]
            va = LIST2_VA
            hit = None
            for i in range(LIST2_ROWS):
                rr = struct.unpack_from("<IHHIIII", Bt.p0, va + LIST2_STRIDE * i - B)
                if rr[1] == v:
                    hit = rr
            if hit is None:
                bad.append((s, "no list2 row"))
                continue
            stub = Bt.rd(hit[3], 2) if STUB_VA <= hit[3] < STUB_VA + 68 else b""
            if not (hit[0] == 1 and hit[4] == 14 and len(stub) == 2 and stub[1] == k):
                bad.append((s, v, k, hit[:5], stub))
        self.chk("A1.page", not bad, "per-look right-arrow page: the list2 row of every look (found by value, %d rows x %d B at %#x) = {1, value, stub, 14, page}; its stub (mov k) k == SEL2REC k; rows + stubs byte-identical to the base (O4.fixed); bad %s" % (
            LIST2_ROWS, LIST2_STRIDE, LIST2_VA, bad[:2] or "none"))
        last = CELLS_RAM + CELL_STRIDE * 17 - 1
        self.chk("A2.cells_ram", last < HSLB_RAM, "per-look hue cells RAM %#x..%#x (17 rows x 36 B) end below the wheel bank HSLB %#x; address = f(k), k = f(selector) only: no matrix / T2 / T3 / name / order input [I: RAM formula from b90_plan]" % (CELLS_RAM, last, HSLB_RAM))

    # ---------------------------------------------------------------------------------------- A2: sync, base-bearing tables, tone
    def sync_and_base(self):
        A, Bt = self.A, self.B
        bm, bma = Bt.base_modes(), A.base_modes()
        self.chk("A2.basemode", bm == bma, "base mode (value-map record) of all 18 slots identical to the base (same-base rule: the look keeps its base's C/S/Sat, Gradation, Highlight/Shadow, WB, DR cells): %s" % (
            {s: bm[s] for s in sorted(self.replaced)} or "no replaced slot"))
        if not self.sync:
            self.add("A2.sync", "INFO", "no z26 SCP sync cave in this base (%#x is FF): SCP C/S/Sat sync surfaces n/a" % CB_HOME)
        else:
            tbl = Bt.rd(TBL_VA, TBL_LEN)
            bad = [(s, tbl[pm_value(s) - 22], GUI_OF_BASE[bm[s]]) for s in range(1, NS + 1) if tbl[pm_value(s) - 22] != GUI_OF_BASE[bm[s]]]
            jt = lambda x: Bt.u32(Bt.u32(JT_PTR_VA) + 4 * x)
            badj = [s for s in range(1, NS + 1) if jt(pm_value(s)) != jt(GUI_OF_BASE[bm[s]])]
            bads = []
            for cur in (14, 15, 16, 17):
                t = TSCF + TSCF_STRIDE * (cur - 14)
                m = {Bt.u32(t + 8 * r): Bt.u32(t + 8 * r + 4) for r in range(TSCF_ROWS)}
                for s in range(1, NS + 1):
                    if pm_value(s) not in m or m[pm_value(s)] != m.get(GUI_OF_BASE[bm[s]]):
                        bads.append((cur, s))
            cb = all(Bt.rd(va, 25) == A.rd(va, 25) for va in CB0) and all(Bt.rd(va, 30) == A.rd(va, 30) for va in CB1)
            same = Bt.rd(CB_HOME, 78) == A.rd(CB_HOME, 78) and Bt.rd(TSCF, TSCF_STRIDE * 4) == A.rd(TSCF, TSCF_STRIDE * 4)
            self.chk("A2.sync", not bad and not badj and not bads and tbl[36 - 22] == 0xFF and cb and same,
                     "SCP C/S/Sat sync: wrapper TBL %#x (PM 22..40 -> base mode), loader jump-table case and the 4 scf id tables %#x (24 value rows each) == the base mode of every look slot, keyed by VALUE (any row order); "
                     "callbacks + sync cave + scf bytes identical to the base %s/%s; bad %s" % (TBL_VA, TSCF, cb, same, bad[:2] or badj[:2] or bads[:2] or "none"))
        bad = []
        tA = Bt.lst("tblA")
        recs = {k: struct.unpack("<III", r) for k, r in zip(Bt.lst("tblB")[2], tA[1])}
        en = {k: struct.unpack_from("<I", r, 4)[0] & 0xFFFF for k, r in zip(Bt.lst("en")[2], Bt.lst("en")[1])}
        lvo = {k: struct.unpack_from("<I", r, 4)[0] for k, r in zip(Bt.lst("lvord")[2], Bt.lst("lvord")[1])}
        maps = {nm: {k: struct.unpack("<IIII", r) for k, r in zip(Bt.lst(nm + "b")[2], Bt.lst(nm + "a")[1])} for nm in ("map505", "map506")}
        lbp = Bt.u32(LOOKBASE_PTR_VA)
        for s in range(1, NS + 1):
            v, b = pm_value(s), bm[s]
            r = recs.get(v)
            if not r or r[:2] != RAWMONO[b] or r[2] != s:
                bad.append((s, "tblA", r))
            if en.get(v) != FLAG[b]:
                bad.append((s, "enable", en.get(v)))
            if lvo.get(v) != LVORD[b]:
                bad.append((s, "LV ordinal", lvo.get(v)))
            for nm, mp in maps.items():
                r = mp.get(v)
                if not r or r[:2] != RAWMONO[b] or r[2] != s or r[3]:
                    bad.append((s, nm, r))
            if Bt.u8(lbp + s) != RAW_OF[b]:
                bad.append((s, "LOOKBASE", Bt.u8(lbp + s)))
        self.chk("A2.tables", not bad, "base-bearing tables agree with base_mode(s) for all 18 slots, read by value key (hidden looks included): tblA (111, %d records) {raw, members, selector}, enable-map flags 345..349, LV ordinal, "
                 "RAW strip maps 505 / 506 (sel == slot), rw4 LOOKBASE; bad %s" % (len(tA[1]), bad[:3] or "none"))
        self.maps = maps

    def tone(self):
        A, Bt = self.A, self.B
        bad = []
        for s in S.WRITABLE:
            try:
                rb = S.read_slot(Bt.p0, s)
                S.check_tone(rb["t3"], rb["t2"])
                S.check_l16(rb["L16"])
            except S.SlotError as e:
                bad.append((s, str(e)))
        diff = [s for s in S.WRITABLE if any(A.rd(va, n) != Bt.rd(va, n) for va, n, _ in S.sites(s))]
        self.chk("A2.tone", not bad, "every writable slot (17): matrix 9 x s16, T3 3 x 9 x 10 bit non-decreasing, T2 256 x 10 bit non-decreasing, read back from the written bytes; bad %s" % (bad[:2] or "none"))
        miss = [s for s in self.replaced if s not in diff]
        self.chk("A2.written", not miss, "replaced slot(s) %s: matrix / T3 / T2 differ from the base (the look was written); slot(s) whose data changed: %s" % (sorted(self.replaced) or "none", diff))
        extra = [s for s in diff if s not in self.replaced]
        self.chk("U1.slots", not extra, "untouched slots (%d): matrix / T3 / T2 byte-identical to the base; changed without being declared: %s" % (len(S.WRITABLE) - len(self.replaced), extra or "none"))

    # ---------------------------------------------------------------------------------------- A2 / A3 / A4: caves
    def caves(self, crit):
        changed = [nm for nm, va, n in CAVES[crit] if self.B.rd(va, n) != self.A.rd(va, n)]
        return changed, sum(n for _nm, _va, n in CAVES[crit])

    def a3_bank(self):
        changed, total = self.caves("A3")
        self.chk("A3.bank", not changed, "RAW Data Edit Current / Custom1 / Custom2 bank pass (z27 F1b arming -> stock HSL3 gate -> SUB3): the %d zone bytes of the F1b / CAVE1 caves and the arming site are byte-identical to the base (changed: %s)" % (total, changed or "none"))

    def a4_evf(self):
        changed, total = self.caves("A4")
        self.chk("A4.evf", not changed, "LCD + EVF: z28 EVF caves / transform bytes (hint cave, WRAP, cx cell, WBG cave, rule hook, paint slot word; %d bytes) byte-identical to the base (changed: %s); %s" % (
            total, changed or "none", "z28 caves present" if self.wbg else "this base has no z28 caves (the ranges are then plain stock bytes)"))

    def a2_wheel(self):
        changed, total = self.caves("A2")
        homes = [h[2] for h in HOMES if self.B.rd(h[0], h[1]) != self.A.rd(h[0], h[1])]
        self.chk("A2.wheel", not changed and not homes, "colour-wheel interplay: wheel / Color Creator code + tables, SCP sync cave + scf tables + loader callbacks, MAIN4 / SUB3, look descriptors (%d bytes in %d ranges) and the z26 homes are byte-identical to the base; changed %s" % (
            total, len(CAVES["A2"]), (changed + homes) or "none"))

    def a4_lists(self):
        self.add("A4.lists", "INFO", "LCD and EVF draw the menu / SCP / LC rows and their name + icon ids from the SAME lists (one descriptor per list, no output-specific copy; the EVF differs only in the z28 transform caves, A4.evf) "
                 "[I: static trace, evf_REPORT]; the name strings have one table (34 languages), no per-output variant")

    # ---------------------------------------------------------------------------------------- A3: RAW strips
    def strips(self):
        A, Bt = self.A, self.B
        l35k = Bt.lst("L35")[2]
        bad = []
        for nm in ("a35", "b35"):
            if Bt.lst(nm)[2] != l35k:
                bad.append("%s keys differ from L35 by position" % nm)
        for nm in ("map505b", "map506b"):
            if Bt.lst(nm)[2] != l35k:
                bad.append("%s keys differ from L35 by position" % nm)
        lab = [struct.unpack_from("<H", Bt.p0, LAB36_VA - B + 2 * (i + 1))[0] for i in range(len(l35k))]
        l35id = [struct.unpack_from("<I", r, 4)[0] & 0xFFFF for r in Bt.lst("L35")[1]]
        if lab != l35id:
            bad.append("LABELS36 != L35 ids by position")
        miss = [s for s in range(1, NS + 1) if pm_value(s) not in l35k]
        self.chk("A3.strip", not bad and not miss, "RAW Data Edit Current / Custom1 / Custom2 strips: a35 / b35 {value, icon id}, L35 {value, caption id}, LABELS36 (by position) and the value maps 505 / 506 (ORDER indexed) list the same %d values "
                 "in the same positions; every look incl. hidden ones present (a stored RAW resolves); caption + icon ids per value == the shooting menu's (A1.table*, A4.icons); bad %s missing %s" % (len(l35k), bad[:3] or "none", miss or "none"))
        base_maps = {nm: dict(zip(A.lst(nm + "b")[2], A.lst(nm + "a")[1])) for nm in ("map505", "map506")}
        new_maps = {nm: dict(zip(Bt.lst(nm + "b")[2], Bt.lst(nm + "a")[1])) for nm in ("map505", "map506")}
        self.chk("A3.maps", base_maps == new_maps and all(len(m) == NVAL for m in new_maps.values()), "RAW strip maps 505 (Custom1) / 506 (Custom2): {value -> record} of all %d values identical to the base (keyed by value; the arrays are ORDER-indexed and "
                 "permuted in step with the order, O1 / O3), descriptors unchanged, LOOKBASE of every slot == its base mode (A2.tables)" % NVAL)

    # ---------------------------------------------------------------------------------------- order88 delegation
    def order88(self):
        try:
            from . import order88 as O
        except ImportError:
            self.add("O7.order88", "INFO", "lookbuild/order88.py not importable: the independent order checks above stand alone")
            return
        try:
            cur = O.current_order(bytearray(self.B.p0))
            vals = [item_value(it) for it in cur]
            self.chk("O7.current_order", vals == self.V[1:], "order88.current_order(built p0) (%d items after i-Enhance: %s ...) == the expected visible order read independently here" % (len(cur), [str(x) for x in cur[:5]]))
            pseudo = bytearray(self.A.p0)                     # the base with the replaced slots' data already written: verify() then sees ONLY the order / hide edits
            for s in self.replaced:
                for va, n, _ in S.sites(s):
                    pseudo[va - B:va - B + n] = self.B.p0[va - B:va - B + n]
            vr = O.verify(pseudo, bytearray(self.B.p0), self.order, self.hidden)
            badv = [x for x in vr if not x[1]]
            self.chk("O7.verify", not badv, "order88.verify(base + replaced slot data, built, order, hidden): %d proofs, failed %s" % (len(vr), [(x[0], x[2]) for x in badv[:3]] or "none"))
        except Exception as e:                       # a battery that cannot run its delegate must not pass silently
            self.add("O7.order88", "FAIL", "order88 call failed: %s: %s" % (type(e).__name__, e))

    def run_all(self):
        self.guard("G1", self.g_container)
        self.guard("G2", self.g_layout)
        if any(r[1] == "FAIL" for r in self.res) or self.V is None:
            return self.res
        for cid, fn in (("G3", self.g_confine), ("U1", self.tone), ("A2", self.sync_and_base), ("A1n", self.names), ("A1i", self.icons), ("O", self.lists_order), ("A1s", self.stepping),
                        ("A1p", self.page), ("A3s", self.strips), ("A3b", self.a3_bank), ("A4", self.a4_evf), ("A2w", self.a2_wheel), ("A4n", self.a4_lists), ("O7", self.order88)):
            self.guard(cid, fn)
        return self.res


def run(base_bin, built_bin, touched=None):
    """the static acceptance battery -> [(id, 'PASS'|'FAIL'|'INFO', detail)]; base_bin / built_bin = the bytes of the two release images"""
    sha = hashlib.sha1(base_bin).hexdigest()
    try:
        A, Bt = Img(base_bin), Img(built_bin)
    except C.ContainerError as e:
        return [("G1.container", "FAIL", "image does not parse: %s" % e)]
    return Battery(A, Bt, touched, container=True, base_sha=sha).run_all()


def run_planes(base_img, built_img, touched=None):
    """same on already-split images (Img objects; used by the negative controls, no container re-encode)"""
    return Battery(base_img, built_img, touched, container=False).run_all()


# ------------------------------------------------------------------------------------------------ negative controls
def _flip(im, va, delta=1):
    im.p0[va - B] = (im.p0[va - B] + delta) & 0xFF


def _swap_rows(c, va, st, i, j):
    a, b = bytes(c.p0[va - B + st * i:va - B + st * (i + 1)]), bytes(c.p0[va - B + st * j:va - B + st * (j + 1)])
    c.p0[va - B + st * i:va - B + st * (i + 1)], c.p0[va - B + st * j:va - B + st * (j + 1)] = b, a


def negative_controls(base_bin, built_bin, touched):
    """-> [(name, expected ids, ids that FAILED, ok)]: byte flips of the BUILT image, each must fail its matching check(s); plus the plain base run with the touched list"""
    out = []
    A, Bt0 = Img(base_bin), Img(built_bin)
    t = touched or {}

    def trial(name, expect, mutate):
        c = Img(p0=Bt0.p0, p1=Bt0.p1, raw2=Bt0.raw2)
        mutate(c)
        failed = sorted({r[0] for r in run_planes(A, c, t) if r[1] == "FAIL"})
        out.append((name, sorted(expect), failed, all(e in failed for e in expect)))

    rep = sorted(int(s) for s in (t.get("replaced") or {}))
    ren = sorted(int(s) for s in (t.get("renamed") or {}))
    mov = {int(x) for x in (t.get("hidden") or [])} | {value_slot(item_value(i)) for i in (t.get("order") or [])}
    s0 = rep[0] if rep else 7
    sx = next(s for s in (3, 4, 5, 6, 8, 9, 10, 11, 12, 13) if s not in rep and s not in ren and s not in mov)      # an untouched, unmoved slot
    vx = pm_value(sx)
    nbk = A.namebook()
    if rep or ren or t.get("order") or t.get("hidden"):
        failed = sorted({r[0] for r in run_planes(A, Img(p0=A.p0, p1=A.p1, raw2=A.raw2), t) if r[1] == "FAIL"})
        exp = (["A1.names", "A2.written"] if rep else (["A1.names"] if ren else [])) + (["O1.order"] if (t.get("order") or t.get("hidden")) else [])
        out.append(("plain base with the touched list (nothing written)", sorted(set(exp)), failed, all(e in failed for e in exp)))
    trial("flip a T2 byte of untouched slot %d" % sx, ["U1.slots", "G3.confine"], lambda c: _flip(c, S.sites(sx)[2][0]))
    trial("flip a T3 byte of untouched slot %d" % sx, ["U1.slots", "G3.confine"], lambda c: _flip(c, S.sites(sx)[1][0]))
    trial("flip a matrix byte of untouched slot %d" % sx, ["U1.slots", "G3.confine"], lambda c: _flip(c, S.sites(sx)[0][0]))
    trial("flip a cc2 Look-list id (slot %d)" % sx, ["A1.table6"], lambda c: _flip(c, CC2_VA + 12 * (sx - 1) + 6))
    trial("flip a SEL2REC byte (slot %d)" % sx, ["A2.cells_sel", "O4.fixed"], lambda c: _flip(c, SEL2REC_VA + sx))
    trial("flip a sync wrapper TBL byte (look %d)" % sx, ["A2.sync"], lambda c: _flip(c, TBL_VA + vx - 22))
    ma, mb = A.loc("map505a"), A.loc("map505b")
    trial("flip a map-505 record byte (value %d)" % vx, ["A2.tables", "A3.maps", "O3.rows"], lambda c: _flip(c, ma[0] + 16 * A.lst("map505b")[2].index(vx)))
    trial("flip a list2 stub byte (look %d)" % sx, ["A1.page", "O4.fixed"], lambda c: _flip(c, STUB_VA + 4 * (vx - 22 if vx <= 35 else vx - 23) + 1))
    trial("flip a LOOKBASE byte (slot %d)" % sx, ["A2.tables", "O4.fixed"], lambda c: _flip(c, c.u32(LOOKBASE_PTR_VA) + sx))
    other = next(i for i in range(1, 2000) if all(i not in N.NAME_IDS[s] for s in range(1, NS + 1)) and nbk.tabs[1][i][0] is not None and nbk.tabs[1][i][1])
    trial("flip a stray p1 byte (string id %d, language 1)" % other, ["G3.confine"], lambda c: c.p1.__setitem__(nbk.tabs[1][other][0], c.p1[nbk.tabs[1][other][0]] ^ 1))
    trial("flip a character of untouched slot %d's name (language 5)" % sx, ["U2.names", "A1.names", "G3.confine"], lambda c: c.p1.__setitem__(nbk.tabs[5][N.NAME_IDS[sx][0]][0], c.p1[nbk.tabs[5][N.NAME_IDS[sx][0]][0]] ^ 1))
    if rep:
        trial("flip a character of replaced slot %d's name (language 7)" % s0, ["A1.names"], lambda c: c.p1.__setitem__(Bt0.namebook().tabs[7][N.NAME_IDS[s0][0]][0], c.p1[Bt0.namebook().tabs[7][N.NAME_IDS[s0][0]][0]] ^ 1))
    icon_off = lambda im, s: IC.header(im.p1, Battery(A, im, t).icon_ids(im, s)[0])["df"] + 9
    trial("flip an icon data byte of untouched slot %d" % sx, ["U3.icons", "G3.confine"], lambda c: c.p1.__setitem__(icon_off(c, sx), c.p1[icon_off(c, sx)] ^ 1))
    if rep and s0 not in set(int(x) for x in (t.get("keep_icon") or [])):
        trial("flip an icon data byte of replaced slot %d (no longer the roll)" % s0, ["U3.icons"], lambda c: c.p1.__setitem__(icon_off(c, s0), c.p1[icon_off(c, s0)] ^ 1))
    mva, _mn, mst = A.loc("menu")
    trial("swap two menu rows", ["O1.order"], lambda c: _swap_rows(c, mva, mst, 6, 7))
    trial("flip a menu row byte (row of look %d)" % sx, ["O3.rows", "A1.table2"], lambda c: _flip(c, mva + mst * A.lst("menu")[2].index(vx) + 20))
    trial("flip the enable-map bound (39 -> 38)", ["O2.counts"], lambda c: _flip(c, 0x7db6f7cb, -1))
    trial("flip a tblA spare-record byte", ["O5.anchors", "O3.rows"], lambda c: _flip(c, A.loc("tblA")[0] + 12 * Bt0.lst("tblB")[2].index(SPARE_VALUE)))
    trial("move the menu reader pointer", ["O2.counts"], lambda c: _flip(c, MENU_D + 4))
    ev = A.loc("en")
    trial("swap two enable-map rows", ["O1.order"], lambda c: _swap_rows(c, ev[0], ev[2], 8, 9))
    trial("flip a LABELS36 id (strip position 10)", ["A1.table5", "A3.strip"], lambda c: _flip(c, LAB36_VA + 2 * 10))
    trial("flip a z27 F1b cave byte", ["A3.bank", "G3.confine"], lambda c: _flip(c, 0x7d9b7a10))
    trial("flip a z28 hint-cave byte (EVF)", ["A4.evf", "G3.confine"], lambda c: _flip(c, 0x7d9bc965))
    trial("flip a byte of the colour-wheel zone", ["A2.wheel", "G3.confine"], lambda c: _flip(c, 0x7d9bc400))
    if t.get("hidden") or t.get("order"):
        pa = A.lst("menu")

        def unorder(c):                                     # the menu rows back in the base order (order not applied there)
            c.p0[mva - B:mva - B + 39 * mst] = b"".join(pa[1])
        trial("menu list restored to the base order", ["O1.order"], unorder)
    return out


# ------------------------------------------------------------------------------------------------ report / CLI
def format_report(results):
    lines = ["  %-16s %-4s %s" % (cid, st, det) for cid, st, det in results]
    nf = sum(1 for r in results if r[1] == "FAIL")
    lines.append("ACCEPTANCE (static): %s (%d PASS, %d FAIL, %d INFO)" % ("PASS" if not nf else "FAIL", sum(1 for r in results if r[1] == "PASS"), nf, sum(1 for r in results if r[1] == "INFO")))
    return "\n".join(lines)


def _items(s):
    return [int(x) if x.strip().isdigit() else x.strip() for x in s.split(",") if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="static acceptance battery of a pack-built image (owner criteria A1..A4)")
    ap.add_argument("--base", required=True)
    ap.add_argument("--built", required=True)
    ap.add_argument("--order", default="", help="items in the pack's order, e.g. 11,7,6,Portrait")
    ap.add_argument("--hidden", default="", help="hidden look slots, e.g. 12")
    ap.add_argument("--replaced", action="append", default=[], metavar="SLOT=NAME")
    ap.add_argument("--renamed", action="append", default=[], metavar="SLOT=NAME")
    ap.add_argument("--keep-icon", default="", help="replaced slots whose icon was kept")
    ap.add_argument("--neg", action="store_true", help="also run the negative controls (byte flips must fail the matching checks)")
    a = ap.parse_args(argv)
    kv = lambda lst: {int(x.split("=", 1)[0]): x.split("=", 1)[1] for x in lst}
    touched = dict(replaced=kv(a.replaced), renamed=kv(a.renamed), order=_items(a.order), hidden=_items(a.hidden), keep_icon=_items(a.keep_icon))
    base, built = open(a.base, "rb").read(), open(a.built, "rb").read()
    res = run(base, built, touched)
    print(format_report(res))
    rc = 1 if any(r[1] == "FAIL" for r in res) else 0
    if a.neg:
        neg = negative_controls(base, built, touched)
        for name, exp, failed, ok in neg:
            print("  NEG %-4s %s -> expected %s, failed %s" % ("OK" if ok else "BAD", name, exp, failed))
        bad = [n for n in neg if not n[3]]
        print("NEGATIVE CONTROLS: %s (%d/%d)" % ("PASS" if not bad else "FAIL", len(neg) - len(bad), len(neg)))
        rc = rc or (1 if bad else 0)
    return rc
