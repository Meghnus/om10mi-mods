# pyodide/ - the build engine of the in-browser build

Self-hosted (no CDN, no network beyond this folder). The page's Web Worker (`../buildworker.js`) runs the public builder in WebAssembly:

| File | What | Source |
|---|---|---|
| `pyodide.js`, `pyodide.asm.js`, `pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json` | Pyodide (CPython 3.13 for WebAssembly), MPL-2.0 | `https://cdn.jsdelivr.net/pyodide/v0.29.3/full/` (unchanged) |
| `numpy-2.2.5-cp313-cp313-pyodide_2025_0_wasm32.whl` | numpy 2.2.5 built for Pyodide, BSD-3-Clause; sha256 `6eaab6a7bb658d71ebe702911a3deab715323642462eb41b65565ca6a7cc23f1` | same folder |
| `om10mi_py.zip` | our sources: `om10mi.py`, `patch/looks94.json`, `looktool/` modules, the camera model | made by `tools/make_web_bundle.py` |

No firmware is stored here. The user's own official firmware is read with the browser's File API, stays in the page's memory, and is never uploaded.
