"""slots88.py - the 18 look slots of the release layout (folder 88 / z25, image sha1 7f35e97b...), read and write, stdlib only.

What a look slot is made of in the main-code partition (p0, flash virtual address VA; file offset = VA - P0_BASE):
  matrix   MATS_VA + 18*(s-1)           9 x s16   the cave constants L16 of the slot's colour matrix (olylook: MATS)
  T3       descriptor[s].t3  (192 B)    3 channels x 8 segments x {u32 128k | slope<<12, u32 y_k}   per-channel tone, 10 bit
  T2       descriptor[s].t2  (512 B)    256 x u16 (10 bit)                                           luma-only tone table
The descriptors are rows {t3, t2, hue} of the table TBL_N (18 rows, reached from the F7 cave operand at 0x7d9b2434) -> DESC rows at
0x7d9b2640 + 12*(s-1). They are read from the image and must equal the release layout below, so a different build is refused.
Slot 2 (Acros, monotone base) has no T3 and uses the firmware's own luma table: it is never written. No slot has a hue table in this
layout (hue pointer 0).
Slot -> base mode is the value-map record {raw, members, selector} of the slot (raw 1..4 = Vivid, Natural, Muted, Portrait); this
writer never changes it, so a look may only be written into a slot whose base mode is the look's mode (`base_mode`, `slots_for_mode`).
Everything a slot writer touches is listed by `sites(s)`; the confinement audit (audit.py) proves nothing else changed.
Own code, Apache-2.0. The addresses and counts are layout facts of the published image; no firmware bytes are stored here.
"""
import struct

P0_BASE = 0x7d991020          # VA of file offset 0 of the main-code partition
NSLOT = 18
MATS_VA = 0x7d9b2214
TBL_OPERAND_VA = 0x7d9b2434   # F7 cave: imm32 = pointer table of descriptors
TBL_BOUND_VA = 0x7d9b242b     # F7 cave: selector bound byte = NSLOT - 1
TBL_N_VA = 0x7d9b2500
DESC_VA = 0x7d9b2640
TBLA_VA = 0x7d9b9820          # value-map records {raw, members, selector}, 39 rows
TBLA_ROWS = 39
BASES = {1: "Vivid", 2: "Natural", 3: "Muted", 4: "Portrait"}

T3_LEN, T2_LEN, MAT_LEN = 192, 512, 18
# the release layout (rg56_layout.md section 2 + pc4 zones): descriptor pointers per slot
T3_VA = {1: 0x7d9b2800, 2: 0, 3: 0x7d9b28c0, 4: 0x7d9b2980, 5: 0x7d9b2a40, 6: 0x7d9b2b00, 7: 0x7d9b2bc0, 8: 0x7d9b2c80, 9: 0x7d9b2d40,
         10: 0x7d9b2e00, 11: 0x7d9b2ec0, 12: 0x7d9b2f80, 13: 0x7d9b3040, 14: 0x7d9b3100, 15: 0x7d9b31c0, 16: 0x7d9b3280, 17: 0x7d9b3340,
         18: 0x7d9b5008}
T2_VA = {1: 0x7d9b3400, 2: 0x7df17ac2, 3: 0x7d9b3600, 4: 0x7d9b3800, 5: 0x7d9b3a00, 6: 0x7d9b3c00, 7: 0x7d9b3e00, 8: 0x7d9b4000, 9: 0x7d9b4200,
         10: 0x7d9b4400, 11: 0x7d9b4600, 12: 0x7d9b4800, 13: 0x7d9b4a00, 14: 0x7d9b4c00, 15: 0x7d9b50c8, 16: 0x7d9b52c8, 17: 0x7d9b54c8,
         18: 0x7d9b56c8}
WRITABLE = [s for s in range(1, NSLOT + 1) if s != 2]

# hue tables: the layout has none (every descriptor's hue pointer is 0). From z26 on, a hue-table count above 1 would overwrite the z26 homes
# and live data (0x7d9b5bc8..0x7d9b5fa8), so the writer refuses any count above MAX_HUE_TABLES (aug93 / handon: the hue-table count MUST stay 1).
MAX_HUE_TABLES = 1
# regions that belong to later builds (z26: SCP C/S/Sat sync) and that a look write must never touch: (va, length, what)
HOMES = [(0x7d9b6480, 208, "z26 home R1 code"), (0x7d9b6748, 84, "z26 home R2 data"), (0x7e5c9dcc, 0x7e5c9e60 - 0x7e5c9dcc, "z26 page-data tail")]


class SlotError(ValueError):
    pass


def off(va):
    return va - P0_BASE


def u16(p0, va):
    return struct.unpack_from("<H", p0, off(va))[0]


def u32(p0, va):
    return struct.unpack_from("<I", p0, off(va))[0]


def check_layout(p0):
    """the image must be the 18-slot release layout; raises SlotError with the first difference"""
    if len(p0) < off(0x7df20000):
        raise SlotError("main-code partition too short")
    if u32(p0, TBL_OPERAND_VA) != TBL_N_VA or p0[off(TBL_BOUND_VA)] != NSLOT - 1:
        raise SlotError("the look table operand / bound of the F7 cave is not the 18-slot layout (is this the v88 image?)")
    for s in range(1, NSLOT + 1):
        d = u32(p0, TBL_N_VA + 4 * (s - 1))
        if d != DESC_VA + 12 * (s - 1):
            raise SlotError("slot %d: descriptor pointer %#x is not the release layout" % (s, d))
        t3, t2, hue = struct.unpack_from("<III", p0, off(d))
        if (t3, t2) != (T3_VA[s], T2_VA[s]) or hue != 0:
            raise SlotError("slot %d: descriptor {t3 %#x, t2 %#x, hue %#x} is not the release layout" % (s, t3, t2, hue))
    if u32(p0, TBL_N_VA + 4 * NSLOT) != 0xFFFFFFFF:
        raise SlotError("the look table has more than %d rows" % NSLOT)


def check_hue_count(nh):
    """the hard guard: more than MAX_HUE_TABLES hue tables are refused (this writer cannot place any hue table, see the module doc)"""
    if int(nh) > MAX_HUE_TABLES:
        raise SlotError("%d hue tables requested: refused (the hue-table count must stay <= %d; more would overwrite the z26 homes and live data)" % (nh, MAX_HUE_TABLES))


def hue_count(p0):
    """number of slots whose descriptor carries a hue table (0 in the release layout)"""
    return sum(1 for s in range(1, NSLOT + 1) if u32(p0, DESC_VA + 12 * (s - 1) + 8) != 0)


def base_mode(p0, s, rows=TBLA_ROWS):
    """base picture mode of slot s from the value-map records (Monotone for slot 2)"""
    hits = []
    for i in range(rows):
        raw, members, sel = struct.unpack_from("<III", p0, off(TBLA_VA + 12 * i))
        if sel == s and 1 <= raw <= 5 and members in (0, 1):
            hits.append((raw, members))
    if len(hits) != 1:
        raise SlotError("slot %d: %d value-map records (expected 1)" % (s, len(hits)))
    raw, members = hits[0]
    return "Monotone" if raw == 5 else BASES[raw]


def slots_for_mode(p0, mode):
    return [s for s in WRITABLE if base_mode(p0, s) == mode]


def sites(s):
    """[(va, length, what)] every byte range the slot writer may change for slot s"""
    if s not in WRITABLE:
        raise SlotError("slot %d cannot be written (slots 1..%d except 2, the monotone slot)" % (s, NSLOT))
    return [(MATS_VA + MAT_LEN * (s - 1), MAT_LEN, "matrix L16 slot %d" % s), (T3_VA[s], T3_LEN, "T3 slot %d" % s),
            (T2_VA[s], T2_LEN, "T2 slot %d" % s)]


# ------------------------------------------------------------------------------------------------ encode / decode
def t3_words(t3):
    """t3 = 3 x 9 ints (10 bit) on x = 0,128..1024 -> 192 bytes (R+136 layout)"""
    out = bytearray()
    for c in range(3):
        y = t3[c]
        for k in range(8):
            out += struct.pack("<II", (128 * k) | ((y[k + 1] - y[k]) << 12), y[k])
    return bytes(out)


def parse_t3(blob):
    t3 = []
    for c in range(3):
        y, last = [], 0
        for k in range(8):
            w0, w1 = struct.unpack_from("<II", blob, 8 * (8 * c + k))
            if w0 & 0xFFF != 128 * k:
                raise SlotError("T3 segment word0 is not 128*k | slope<<12")
            y.append(w1)
            last = w1 + (w0 >> 12)
        y.append(last)
        t3.append(y)
    return t3


def check_tone(t3, t2):
    """the pc4 tone-data rules: T3 = 3 x 9, T2 = 256, 10 bit, non-decreasing"""
    if len(t3) != 3 or any(len(y) != 9 for y in t3) or len(t2) != 256:
        raise SlotError("T3 must be 3 x 9 values and T2 256 values")
    for y in list(t3) + [t2]:
        if any(int(v) != v or not (0 <= v <= 1023) for v in y):
            raise SlotError("tone values must be integers in 0..1023")
        if any(b < a for a, b in zip(y, y[1:])):
            raise SlotError("tone tables must be non-decreasing")


def check_l16(L16):
    if len(L16) != 9 or any(int(v) != v or not (-32768 <= v < 32768) for v in L16):
        raise SlotError("matrix must be 9 signed 16-bit integers")


def read_slot(p0, s):
    """-> dict(L16, t3 (3 x 9), t2 (256)) as stored for slot s"""
    if s < 1 or s > NSLOT:
        raise SlotError("slot %d out of range" % s)
    L16 = list(struct.unpack_from("<9h", p0, off(MATS_VA + MAT_LEN * (s - 1))))
    t3 = parse_t3(bytes(p0[off(T3_VA[s]):off(T3_VA[s]) + T3_LEN])) if T3_VA[s] else None
    t2 = list(struct.unpack_from("<256H", p0, off(T2_VA[s])))
    return dict(L16=L16, t3=t3, t2=t2)


def write_slot(p0, s, L16, t3, t2, nh=0):
    """write the slot's matrix, T3 and T2 into the bytearray p0 (validated); returns the list of ranges written.
    nh = number of hue tables the caller wants with this write: above MAX_HUE_TABLES it is refused (and this writer writes none)"""
    check_hue_count(nh)
    check_layout(p0)
    check_hue_count(hue_count(p0))
    check_l16(L16)
    check_tone(t3, t2)
    sm, st3, st2 = sites(s)
    p0[off(sm[0]):off(sm[0]) + sm[1]] = struct.pack("<9h", *[int(v) for v in L16])
    p0[off(st3[0]):off(st3[0]) + st3[1]] = t3_words([[int(v) for v in y] for y in t3])
    p0[off(st2[0]):off(st2[0]) + st2[1]] = struct.pack("<256H", *[int(v) for v in t2])
    return [sm, st3, st2]
