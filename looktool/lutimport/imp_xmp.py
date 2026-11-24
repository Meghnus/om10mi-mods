"""imp_xmp.py - Adobe Creative Profile (.xmp with crs:RGBTable) importer (exact).

Format (DNG SDK dng_big_table), confirmed by the MD5 self-check on every file:

  crs:RGBTable="<md5>"            md5 of the uncompressed block
  crs:Table_<md5>="<base85>"      the payload
  base85  : own alphabet, 5 chars -> 4 bytes, LITTLE-endian within a group (first char least significant);
            a short final group yields 1-3 bytes
  payload : uint32 uncompressed size, then a zlib stream
  block   : <4I> (v1, v2, dims, size) then size^3 * 3 uint16
  samples : stored as DELTAS from the identity lattice; value = (delta + nop[i]) & 0xFFFF,
            nop[i] = (i*0xFFFF + size//2)//(size-1)
  order   : index = r + g*size + b*size^2 (red fastest = .cube order)
  footer  : 28 bytes after the samples (Eterna.xmp: u32 3, u32 1, u32 0, f64 1.0, f64 1.0); not interpreted
            here (probably gamut / gamma / amount range of the DNG SDK table [inference]); the MD5 covers it.

Reimplemented from the format description of the CUBE-to-XMP project (lut_core.py); the project's own
Tested against an independent reference implementation (same numbers).
Adobe Creative Profile RGB tables are applied in ProPhoto primaries in the Lightroom pipeline, so the
default source.space is "prophoto" (the repo convention 'fuji' in cm_part1).

A file may be an Adobe preset WITHOUT a table (slider preset): has_rgb_table() tells the two apart.
"""
import hashlib
import os
import re
import struct
import zlib

from lutcore import COMMON_N, Lut, LutError
from result import ImportResult, sha256_file

ALPHABET = ("0123456789abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#")
assert len(ALPHABET) == 85 and len(set(ALPHABET)) == 85
_IDX = {c: i for i, c in enumerate(ALPHABET)}


def b85_decode(text):
    out = bytearray()
    val = phase = 0
    for c in text:
        if c.isspace():
            continue
        d = _IDX[c]
        val += d * (85 ** phase)
        phase += 1
        if phase == 5:
            if val > 0xFFFFFFFF:
                raise LutError("base85 group overflows 32 bits")
            out += struct.pack("<I", val)
            val = phase = 0
    if phase == 1:
        raise LutError("truncated base85 data")
    if phase == 2:
        out += struct.pack("<B", val & 0xFF)
    elif phase == 3:
        out += struct.pack("<H", val & 0xFFFF)
    elif phase == 4:
        out += struct.pack("<I", val)[:3]
    return bytes(out)


def has_rgb_table(text):
    return re.search(r'crs:RGBTable="[0-9A-Fa-f]{32}"', text) is not None


def decode_table(encoded, digest):
    """-> (Lut in 0..1, md5_ok). Raises LutError for structurally broken data."""
    raw = b85_decode(encoded)
    if len(raw) < 4:
        raise LutError("payload too short")
    want = struct.unpack("<I", raw[:4])[0]
    try:
        block = zlib.decompress(raw[4:])
    except zlib.error as e:
        raise LutError("zlib: %s" % e)
    if len(block) != want:
        raise LutError("size mismatch: header %d, got %d" % (want, len(block)))
    ok = hashlib.md5(block).hexdigest().lower() == digest.lower()
    _v1, _v2, dims, size = struct.unpack("<4I", block[:16])
    if dims != 3:
        raise LutError("not a 3D table (dims=%d)" % dims)
    if size < 2 or 16 + size ** 3 * 6 > len(block):
        raise LutError("table size %d does not match the block length" % size)
    nop = [(i * 0xFFFF + size // 2) // (size - 1) for i in range(size)]
    vals = struct.unpack_from("<%dH" % (size ** 3 * 3), block, 16)
    data = [0.0] * (size ** 3 * 3)
    k = 0
    for r in range(size):
        for g in range(size):
            for b in range(size):
                o = (r + g * size + b * size * size) * 3
                data[o] = ((vals[k] + nop[r]) & 0xFFFF) / 65535.0
                data[o + 1] = ((vals[k + 1] + nop[g]) & 0xFFFF) / 65535.0
                data[o + 2] = ((vals[k + 2] + nop[b]) & 0xFFFF) / 65535.0
                k += 3
    return Lut(size, data), ok


def parse_profile(text):
    """-> (name, digest, Lut, md5_ok, amount or None)"""
    m = re.search(r'crs:RGBTable="([0-9A-Fa-f]{32})"', text)
    if not m:
        raise LutError("no crs:RGBTable digest")
    digest = m.group(1)
    t = re.search(r'crs:Table_%s="([^"]+)"' % digest, text, re.S)
    if not t:
        raise LutError("no crs:Table_%s" % digest)
    lut, ok = decode_table(t.group(1), digest)
    nm = re.search(r"<crs:Name>.*?<rdf:li[^>]*>(.*?)</rdf:li>", text, re.S)
    name = nm.group(1).strip() if nm else ""
    am = re.search(r'crs:Amount="([-+0-9.eE]+)"', text)
    amount = float(am.group(1)) if am else None
    return name, digest, lut, ok, amount


def import_xmp_profile(path, space="prophoto", licence=""):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    name, digest, lut, ok, amount = parse_profile(text)
    r = ImportResult("xmp-profile", os.path.basename(path))
    if not ok:
        raise LutError("MD5 self-check failed: the table is damaged or not a supported variant")
    r.native = lut
    if amount is not None and amount != 1.0 and amount != 100.0:
        frac = amount / 100.0 if amount > 1.0 else amount
        ident = Lut.identity(lut.n)
        lut = Lut(lut.n, [i + frac * (v - i) for v, i in zip(lut.data, ident.data)])
        r.note("crs:Amount %g applied as a blend toward identity (assumed linear in 0..1 / 0..100 [inference])" % amount)
    r.lut33 = lut.resample(COMMON_N)
    r.exact_nodes = lut.n == COMMON_N and amount in (None, 1.0, 100.0)
    r.source.update({"licence": licence, "sha256": sha256_file(path), "space": space,
                     "title": name or os.path.splitext(os.path.basename(path))[0], "table_md5": digest})
    if lut.n != COMMON_N:
        r.note("native size %d^3 resampled trilinearly to %d^3 (the .cube of this table is at %d^3)" % (lut.n, COMMON_N, lut.n))
    extra = sorted(set(re.findall(r'crs:((?:Tone|Hue|Grain|Parametric|Contrast|Exposure)[A-Za-z0-9]*)=', text)))
    if extra:
        r.drop("slider settings next to the table ignored: " + ", ".join(extra))
    return r
