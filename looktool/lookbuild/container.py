"""container.py - the Olympus firmware container (E-M10 Mark I update file), standard library only.

A .BIN is a concatenation of partitions: 32-byte header, payload, 32-byte footer (a copy of the header whose last word is a
checksum). The payload is the plain flash image passed through a fixed byte shuffle and inversion. The checksum makes the whole
partition (header + plain payload + footer with a zero checksum word) sum to 0 modulo 2**32 as little-endian words.
Own code, Apache-2.0, no firmware data. The same format as the public builder (om10mi.py).
"""
import array
import struct
import sys

HDR = 32
FTR = 32
MODEL_ID = 0x1130          # E-M10 Mark I
SHUFFLE = ((1, 3, 0, 2), (2, 0, 3, 1), (3, 2, 1, 0), (1, 2, 0, 3))
INVERT = bytes(i ^ 0xFF for i in range(256))


class ContainerError(Exception):
    pass


def decode_payload(raw):
    """stored payload -> plain flash image"""
    n = len(raw) // 16 * 16
    out = bytearray(len(raw))
    for ph in range(4):
        for j in range(4):
            out[4 * ph + j:n:16] = raw[4 * ph + SHUFFLE[ph][j]:n:16]
    out[n:] = raw[n:]
    return bytes(out).translate(INVERT)


def encode_payload(plain):
    """plain flash image -> stored payload (inverse of decode_payload)"""
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
    a.frombytes(bytes(buf[:len(buf) // 4 * 4]))
    if sys.byteorder != "little":
        a.byteswap()
    return sum(a) & 0xFFFFFFFF


def footer_checksum(header, plain):
    footer0 = bytes(header[:0x1C]) + b"\0\0\0\0"
    return (-(_word_sum(header) + _word_sum(plain) + _word_sum(footer0))) & 0xFFFFFFFF


class Part:
    __slots__ = ("index", "header", "raw", "footer", "model", "stored_sum")

    def __init__(self, index, header, raw, footer):
        self.index, self.header, self.raw, self.footer = index, header, raw, footer
        self.model = struct.unpack_from(">H", header, 2)[0]
        self.stored_sum = struct.unpack_from("<I", footer, 0x1C)[0]

    def plain(self):
        return decode_payload(self.raw)


def split_image(data):
    parts, off = [], 0
    while off < len(data):
        if data[off:off + 2] != b"OE":
            raise ContainerError("not an Olympus firmware file (bad block marker at 0x%x)" % off)
        n = struct.unpack_from("<I", data, off + 12)[0]
        end = off + HDR + n + FTR
        if end > len(data):
            raise ContainerError("file is truncated (partition %d)" % len(parts))
        parts.append(Part(len(parts), data[off:off + HDR], data[off + HDR:off + HDR + n], data[off + HDR + n:end]))
        off = end
    if not parts:
        raise ContainerError("empty file")
    return parts


def join_image(parts):
    return b"".join(bytes(p.header) + bytes(p.raw) + bytes(p.footer) for p in parts)


def with_plain(part, plain):
    """a copy of `part` carrying `plain` as its payload (footer checksum recomputed)"""
    footer = bytes(part.header[:0x1C]) + struct.pack("<I", footer_checksum(part.header, plain))
    return Part(part.index, part.header, encode_payload(bytes(plain)), footer)


def check_parts(parts):
    """structure + footer checksum problems (empty list = fine)"""
    problems = []
    for p in parts:
        if p.model != MODEL_ID:
            problems.append("partition %d: model id 0x%04x (not the E-M10 Mark I)" % (p.index, p.model))
        if p.footer[:0x1C] != p.header[:0x1C]:
            problems.append("partition %d: footer does not match header" % p.index)
        if footer_checksum(p.header, p.plain()) != p.stored_sum:
            problems.append("partition %d: footer checksum wrong" % p.index)
    return problems
