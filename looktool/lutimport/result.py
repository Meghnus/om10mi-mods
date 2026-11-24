"""result.py - what every importer returns, and the provenance block it fills (look file v2 `source`)."""
import hashlib


class ImportResult:
    """lut33   : Lut on the common 33^3 lattice (None only for pure parameter files that refuse to render)
    native  : the table as stored in the source (None for parameter sources)
    source  : dict for the look-file `source` block (type, name, licence, sha256, space)
    look    : dict of look-file v2 fields (hsl, tone, split, calibration, fx, ...) or None
    approximate : True when the numbers are an approximation of the originating editor (never for .cube / RGBTable)
    exact_nodes : True when lut33 holds the source's own values at its lattice nodes (size 33 only)
    notes / dropped : human-readable lines for the report
    """

    def __init__(self, kind, name):
        self.kind = kind
        self.name = name
        self.lut33 = None
        self.native = None
        self.source = {"type": kind, "name": name}
        self.look = None
        self.approximate = False
        self.exact_nodes = False
        self.notes = []
        self.dropped = []
        self.refused = None

    def note(self, msg):
        self.notes.append(msg)

    def drop(self, msg):
        self.dropped.append(msg)

    def summary(self):
        s = {"kind": self.kind, "name": self.name, "approximate": self.approximate,
             "native_size": self.native.n if self.native else None,
             "exact_nodes": self.exact_nodes, "source": self.source,
             "notes": self.notes, "dropped": self.dropped}
        if self.lut33 is not None:
            s["lut33"] = self.lut33.stats()
        return s


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
