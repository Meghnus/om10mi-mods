"""imp_cube.py - .cube importer (exact: the file's own values are the node values)."""
import os

from lutcore import COMMON_N, read_cube
from result import ImportResult, sha256_file


def import_cube(path, space="display", licence=""):
    title, lut = read_cube(path)
    name = title or os.path.splitext(os.path.basename(path))[0]
    r = ImportResult("cube", os.path.basename(path))
    r.native = lut
    r.lut33 = lut.resample(COMMON_N)
    r.exact_nodes = lut.n == COMMON_N
    r.source.update({"licence": licence, "sha256": sha256_file(path), "space": space, "title": name})
    if lut.n != COMMON_N:
        r.note("native size %d^3 resampled trilinearly to %d^3 (nodes are not the source's own values)" % (lut.n, COMMON_N))
    return r
