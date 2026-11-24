"""p1strings.py - the string table of the data partition (p1), read-only walker + same-length writer (stdlib only).

p1 = [16-byte entries {dest, len, z1, z2} ... {0, 0}] followed by the blobs in order. Language blob L (1..34) carries a pointer run of string
pointers at its tail, blob L+1 carries the head of the same run; string id V = index in that joined run. A pointer p addresses
file offset p - ARENA + blob offset of L. Strings are UTF-16LE, NUL terminated; a name is written over the existing string in place
(same length: shorter names are NUL padded), never by moving a pointer. Layout facts only; no text of the firmware is stored here.
"""
import struct

PTR_LO, PTR_HI = 0xbd000000, 0xc0000000
ARENA = 0xbfd29c80
NLANG = 34
GLYPH = "@A06A@"


class StringError(ValueError):
    pass


def _is_ptr(w):
    return PTR_LO <= w < PTR_HI


def geometry(p1):
    ents, o = [], 0
    while o + 16 <= len(p1):
        dest, ln, _z1, _z2 = struct.unpack_from("<IIII", p1, o)
        if dest == 0 and ln == 0:
            break
        ents.append((dest, ln))
        o += 16
    bo, o = [], 16 * len(ents)
    for _, ln in ents:
        bo.append(o)
        o += ln
    return ents, bo


def _tail_run(p1, start, ln):
    """(offset, count) of the last run of >= 4 pointer words in the blob (a single foreign word inside the run is tolerated)"""
    best, i = None, 0
    words = struct.unpack_from("<%dI" % (ln // 4), p1, start)
    n = len(words)
    while i < n:
        if _is_ptr(words[i]):
            j = i
            while j < n and _is_ptr(words[j]):
                j += 1
            best_run = (i, j - i)
            if j - i >= 4:
                best = best_run
            i = j
        else:
            i += 1
    return (best[0] * 4, best[1]) if best else None


def table(p1, lang):
    """-> list of (file offset or None, text or None) per string id for language `lang` (1..34)"""
    ents, bo = geometry(p1)
    if not 1 <= lang <= NLANG or lang >= len(ents):
        raise StringError("language %r out of range" % lang)
    b0, n0 = bo[lang], ents[lang][1]
    t = _tail_run(p1, b0, n0)
    if t is None:
        raise StringError("language %d: no pointer run" % lang)
    ptrs = list(struct.unpack_from("<%dI" % t[1], p1, b0 + t[0]))
    b1, n1 = bo[lang + 1], ents[lang + 1][1]
    k = 0
    while 4 * k + 4 <= n1 and _is_ptr(struct.unpack_from("<I", p1, b1 + 4 * k)[0]):
        k += 1
    ptrs += list(struct.unpack_from("<%dI" % k, p1, b1))
    out = []
    for p in ptrs:
        off = p - ARENA + b0
        if not (b0 <= off < b0 + n0):
            out.append((None, None))
            continue
        cu = []
        while off + 1 < len(p1):
            c = struct.unpack_from("<H", p1, off)[0]
            if c == 0:
                break
            cu.append(c)
            off += 2
        out.append((p - ARENA + b0, "".join(chr(c) for c in cu)))
    return out


def capacity(entry):
    """code units the existing string holds"""
    return len(entry[1])


def string_sites(p1, ids, glyph_ids=()):
    """[(lang, id, file offset, bytes available incl. NUL, prefix)] for every language; `glyph_ids` carry the film glyph token in front of the name"""
    out = []
    for lang in range(1, NLANG + 1):
        t = table(p1, lang)
        for sid in ids:
            off, txt = t[sid]
            if off is None:
                raise StringError("language %d id %d: string outside its blob" % (lang, sid))
            out.append((lang, sid, off, 2 * len(txt) + 2, GLYPH if sid in glyph_ids else ""))
    return out


def max_name_len(p1, ids, glyph_ids=()):
    cap = None
    for lang, sid, off, n, pre in string_sites(p1, ids, glyph_ids):
        c = n // 2 - 1 - len(pre)
        cap = c if cap is None else min(cap, c)
    return cap


def write_name(p1, sites, name):
    """write `name` into every site (same length, NUL padded); returns [(offset, length)] written"""
    written = []
    for lang, sid, off, n, pre in sites:
        txt = (pre + name).encode("utf-16-le")
        if len(txt) + 2 > n:
            raise StringError("name %r does not fit string id %d (language %d)" % (name, sid, lang))
        p1[off:off + n] = txt + b"\0" * (n - len(txt))
        written.append((off, n))
    return written
