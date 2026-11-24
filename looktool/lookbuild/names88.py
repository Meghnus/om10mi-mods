"""names88.py - the menu name of a look slot (p1 strings of the release layout), read and write, stdlib only.

Slot s shows its name through one string id (slots 15..18) or two (slots 1..14: the plain name id and the menu-row id, which is the
film glyph token '@A06A@' + the name). Each id exists once per language (34 languages), at a fixed offset. A name is written in place:
`name` + NUL over the existing text; the capacity is the shortest STOCK string of the id over the 34 languages (NAME_CAP: layout facts
measured once on the official firmware; the zero padding behind the current text is verified at run time). Names are printable ASCII
without '@' (the glyph escape). The label icons of the menu are bitmaps and are NOT changed here: a renamed slot keeps its icon label.
"""
import struct

from . import p1strings as P

LOOKSTR = [2139, 1410, 1351, 1203, 1549, 2108, 2261, 1445, 1363, 2151, 2094, 2251, 2110, 2137]
DONOR = {1: 1069, 2: 1811, 3: 1233, 4: 1783, 5: 1817, 6: 1605, 7: 1469, 8: 1470, 9: 1474, 10: 1834, 11: 1197, 12: 1837, 13: 1103, 14: 723}
NAME_IDS = {s: (LOOKSTR[s - 1], DONOR[s]) for s in range(1, 15)}
NAME_IDS.update({15: (1699,), 16: (1477,), 17: (1481,), 18: (1487,)})
NAME_CAP = {1: 6, 2: 5, 3: 7, 4: 7, 5: 5, 6: 14, 7: 11, 8: 11, 9: 11, 10: 13, 11: 9, 12: 13, 13: 15, 14: 8, 15: 10, 16: 17, 17: 24, 18: 8}


class NameError_(ValueError):
    pass


def glyph_ids(s):
    return (DONOR[s],) if s <= 14 else ()


def check_name(s, name):
    if not name or name != name.strip():
        raise NameError_("name must be non-empty without leading/trailing spaces")
    if any(not (0x20 <= ord(c) < 0x7f) or c == "@" for c in name):
        raise NameError_("name %r: printable ASCII only, no '@'" % name)
    if len(name) > NAME_CAP[s]:
        raise NameError_("name %r has %d characters; slot %d holds at most %d" % (name, len(name), s, NAME_CAP[s]))


class NameBook:
    """the 34 language string tables of a p1 image, read once"""

    def __init__(self, p1):
        self.p1 = p1
        self.tabs = {lang: P.table(p1, lang) for lang in range(1, P.NLANG + 1)}

    def current_name(self, s):
        """the name shown by slot s, verified identical in all 34 languages and in both ids"""
        names = set()
        for lang, t in self.tabs.items():
            for sid in NAME_IDS[s]:
                txt = t[sid][1]
                if txt is None:
                    raise NameError_("slot %d id %d: string missing in language %d" % (s, sid, lang))
                names.add(txt[len(P.GLYPH):] if sid in glyph_ids(s) and txt.startswith(P.GLYPH) else txt)
        if len(names) != 1:
            raise NameError_("slot %d: the 34 languages / both ids do not carry one name: %s" % (s, sorted(names)[:4]))
        return names.pop()

    def sites_for(self, s, name):
        """[(lang, id, offset, nbytes, prefix)] the bytes a rename to `name` may change (existing text or the new one, whichever is longer, + NUL)"""
        check_name(s, name)
        out = []
        for lang, t in self.tabs.items():
            for sid in NAME_IDS[s]:
                off, cur = t[sid]
                if off is None:
                    raise NameError_("slot %d id %d: string outside its blob (language %d)" % (s, sid, lang))
                pre = P.GLYPH if sid in glyph_ids(s) else ""
                n = 2 * max(len(pre + name), len(cur)) + 2
                # the padding behind the current text up to the stock capacity must be zeros (the layout this table was measured on)
                cap_bytes = 2 * (NAME_CAP[s] + len(pre)) + 2
                if any(self.p1[off + 2 * len(cur) + 2:off + max(cap_bytes, 2 * len(cur) + 2)]):
                    raise NameError_("slot %d id %d language %d: the string slot is not NUL padded as expected" % (s, sid, lang))
                out.append((lang, sid, off, n, pre))
        return out


def write_name(p1, book, s, name):
    """in-place rename of slot s (book = NameBook of the same image); returns the written (offset, length) list"""
    written = []
    for lang, sid, off, n, pre in book.sites_for(s, name):
        txt = (pre + name).encode("utf-16-le")
        p1[off:off + n] = txt + b"\0" * (n - len(txt))
        written.append((off, n))
    return written
