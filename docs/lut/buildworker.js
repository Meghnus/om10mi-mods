// buildworker.js - runs the public Python builder (om10mi.py + looktool, numpy) with Pyodide (WebAssembly), self-hosted in pyodide/. No network except these same-origin files.
// in:  { cmd: "build", stock: Uint8Array, pack: string, luts: { fileName: Uint8Array }, name, file }
// out: { type: "progress", text } ... then { type: "done", image, sha1, howto } or { type: "fail", text }
"use strict";
importScripts("pyodide/pyodide.js");

const say = (text) => self.postMessage({ type: "progress", text });
let engine = null;

async function init() {
  if (engine) return engine;
  say("Loading the build engine (Python in WebAssembly, about 20 MB, once) ...");
  const py = await loadPyodide({ indexURL: new URL("pyodide/", self.location.href).href });
  say("Loading numpy ...");
  await py.loadPackage("numpy");
  const buf = await (await fetch("pyodide/om10mi_py.zip")).arrayBuffer();
  py.unpackArchive(buf, "zip", { extractDir: "/app" });
  py.runPython("import sys; sys.path[:0] = ['/app', '/app/looktool']");
  engine = py;
  return py;
}

self.onmessage = async (e) => {
  const m = e.data;
  if (m.cmd !== "build") return;
  try {
    const py = await init();
    say("Build engine ready.");
    const web = py.pyimport("webbuild");
    const res = web.run(py.toPy(m.stock), m.pack, py.toPy(m.luts), m.name, say, m.file);
    const r = res.toJs({ dict_converter: Object.fromEntries });
    res.destroy();
    if (!r.ok) return self.postMessage({ type: "fail", text: r.message });
    self.postMessage({ type: "done", image: r.image, sha1: r.sha1, howto: r.howto }, [r.image.buffer]);
  } catch (err) {
    self.postMessage({ type: "fail", text: "The build engine failed (" + (err && err.message ? err.message : err) + "). Use a current desktop browser with enough free memory." });
  }
};
