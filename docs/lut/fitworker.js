// fitworker.js - module Web Worker: runs fit.js fitCandidateFull for one job at a time and streams progress.
// Cancelling = the pool terminates the worker (a synchronous fit cannot see messages); nothing is left running.
import { prepareModel } from "./model.js";
import { fitCandidateFull } from "./fit.js";

let model = null;
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === "init") { model = prepareModel(m.modelJson); self.postMessage({ type: "ready" }); return; }
  if (m.type !== "fit") return;
  try {
    const cand = model.candidates.find((c) => c.name === m.candidate);
    if (!cand) throw new Error("unknown candidate " + m.candidate);
    const result = fitCandidateFull({ model, cand, xS: m.xS, lt: m.lt, scenes: m.scenes, hdr: m.hdr, opts: m.opts },
      { onProgress: (p) => self.postMessage({ type: "progress", id: m.id, ...p }) });
    self.postMessage({ type: "done", id: m.id, result });
  } catch (err) {
    self.postMessage({ type: "error", id: m.id, message: String((err && err.message) || err) });
  }
};
