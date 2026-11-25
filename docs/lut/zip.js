// zip.js - minimal ZIP writer (stored, no compression) for the .omlook.zip export. No dependencies, no network.
// Entries are UTF-8 named (flag bit 11), dated 1980-01-01 so the same input gives the same bytes.

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();

export function crc32(u8) {
  let c = 0xffffffff;
  for (let i = 0; i < u8.length; i++) c = CRC_TABLE[(c ^ u8[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const DOS_TIME = 0, DOS_DATE = (0 << 9) | (1 << 5) | 1;   // 1980-01-01 00:00:00

// files: [{ name: "dir/file.ext", bytes: Uint8Array }] -> Uint8Array
export function makeZip(files) {
  const enc = new TextEncoder(), chunks = [], central = [];
  let off = 0;
  const seen = new Set();
  for (const f of files) {
    if (seen.has(f.name)) throw new Error("zip: duplicate entry " + f.name);
    seen.add(f.name);
    const nm = enc.encode(f.name), crc = crc32(f.bytes), n = f.bytes.length;
    if (n > 0xffffffff - 1 || off > 0xffffffff - 1) throw new Error("zip: too large");
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); lh.setUint16(8, 0, true);
    lh.setUint16(10, DOS_TIME, true); lh.setUint16(12, DOS_DATE, true); lh.setUint32(14, crc, true);
    lh.setUint32(18, n, true); lh.setUint32(22, n, true); lh.setUint16(26, nm.length, true); lh.setUint16(28, 0, true);
    chunks.push(new Uint8Array(lh.buffer), nm, f.bytes);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true); ch.setUint16(10, 0, true);
    ch.setUint16(12, DOS_TIME, true); ch.setUint16(14, DOS_DATE, true); ch.setUint32(16, crc, true);
    ch.setUint32(20, n, true); ch.setUint32(24, n, true); ch.setUint16(28, nm.length, true);
    ch.setUint32(42, off, true);
    central.push(new Uint8Array(ch.buffer), nm);
    off += 30 + nm.length + n;
  }
  const csize = central.reduce((s, c) => s + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, csize, true); end.setUint32(16, off, true);
  const all = [...chunks, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((s, c) => s + c.length, 0));
  let o = 0;
  for (const c of all) { out.set(c, o); o += c.length; }
  return out;
}

// readZip(u8) -> [{ name, bytes }] (stored or deflate entries; reads the central directory; no zip64, no encryption). Caps: 400 entries, 300 MB expanded.
export async function readZip(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength), dec = new TextDecoder();
  let e = u8.length - 22;
  while (e >= 0 && e >= u8.length - 22 - 65535 && dv.getUint32(e, true) !== 0x06054b50) e--;
  if (e < 0 || dv.getUint32(e, true) !== 0x06054b50) throw new Error("not a zip file");
  const n = dv.getUint16(e + 10, true); let p = dv.getUint32(e + 16, true);
  if (n > 400) throw new Error("zip: too many entries");
  const out = []; let total = 0;
  for (let i = 0; i < n; i++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("zip: damaged directory");
    const method = dv.getUint16(p + 10, true), crc = dv.getUint32(p + 16, true), csize = dv.getUint32(p + 20, true), size = dv.getUint32(p + 24, true);
    const nl = dv.getUint16(p + 28, true), xl = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), lo = dv.getUint32(p + 42, true);
    const name = dec.decode(u8.subarray(p + 46, p + 46 + nl)); p += 46 + nl + xl + cl;
    if (name.endsWith("/")) continue;
    total += size; if (total > 300 << 20) throw new Error("zip: expands to more than 300 MB");
    if (dv.getUint32(lo, true) !== 0x04034b50) throw new Error("zip: damaged entry " + name);
    const start = lo + 30 + dv.getUint16(lo + 26, true) + dv.getUint16(lo + 28, true), raw = u8.subarray(start, start + csize);
    let bytes;
    if (method === 0) bytes = raw;
    else if (method === 8) {
      const rd = new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw")).getReader(), parts = [];
      for (;;) { const { done, value } = await rd.read(); if (done) break; parts.push(value); }
      bytes = new Uint8Array(parts.reduce((s, c) => s + c.length, 0)); let o = 0; for (const c of parts) { bytes.set(c, o); o += c.length; }
    } else throw new Error("zip: unsupported compression in " + name);
    if (bytes.length !== size || crc32(bytes) !== crc) throw new Error("zip: checksum mismatch in " + name);
    out.push({ name, bytes });
  }
  return out;
}
