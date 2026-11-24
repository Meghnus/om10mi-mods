// pool.js - Web Worker pool for the fits. One job per worker; results come back in input order; cancel() terminates the workers.
export class FitCancelled extends Error {}

export class FitPool {
  // modelJson: the parsed model json (cloned to each worker once); maxWorkers defaults to min(hardwareConcurrency - 1, 4)
  constructor(modelJson, { maxWorkers = null, url = new URL("./fitworker.js", import.meta.url) } = {}) {
    this.modelJson = modelJson; this.url = url;
    this.max = maxWorkers || Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1));
    this.workers = []; this.cancelled = false; this.rej = null;
  }
  get size() { return this.max; }
  _spawn() {
    const w = new Worker(this.url, { type: "module" });
    const ready = new Promise((res, rej) => { w.addEventListener("message", (e) => { if (e.data.type === "ready") res(); }, { once: false }); w.addEventListener("error", (e) => rej(new Error("worker failed: " + (e.message || "load error")))); });
    w.postMessage({ type: "init", modelJson: this.modelJson });
    return { w, ready };
  }
  // jobs: [{candidate, xS, lt, scenes, hdr, opts}], onProgress(jobIndex, progress). Resolves to [{result}|{error}] in input order.
  run(jobs, onProgress = () => {}) {
    this.cancelled = false;
    const n = Math.min(this.max, jobs.length), out = new Array(jobs.length);
    let next = 0, done = 0;
    this.workers = Array.from({ length: n }, () => this._spawn());
    return new Promise((resolve, reject) => {
      this.rej = reject;
      const feed = async (slot) => {
        if (this.cancelled) return;
        if (next >= jobs.length) return;
        const idx = next++, job = jobs[idx];
        try { await slot.ready; } catch (e) { out[idx] = { error: e.message }; if (++done === jobs.length) { this._close(); resolve(out); } else feed(slot); return; }
        slot.w.onmessage = (e) => {
          const m = e.data;
          if (this.cancelled || m.id !== idx) return;
          if (m.type === "progress") onProgress(idx, m);
          else if (m.type === "done" || m.type === "error") {
            out[idx] = m.type === "done" ? { result: m.result } : { error: m.message };
            if (++done === jobs.length) { this._close(); resolve(out); } else feed(slot);
          }
        };
        slot.w.postMessage({ type: "fit", id: idx, ...job });
      };
      this.workers.forEach((s) => feed(s));
    });
  }
  _close() { this.workers.forEach((s) => s.w.terminate()); this.workers = []; this.rej = null; }
  cancel() {
    if (!this.workers.length) return;
    this.cancelled = true;
    const rej = this.rej;
    this._close();
    if (rej) rej(new FitCancelled("cancelled"));
  }
}
