# Development and testing method

How the firmware features in this repository are developed and proven, for contributors. This document contains
no OM firmware, no decodes and no byte dumps, on purpose (see 1.3).

## 1. Ground rules

1. **Never flash another model's image.** The model ID is checked by the camera's updater, but do not rely on
   that. This project targets the E-M10 Mark I only (model ID `0x1130`, server code `E113`, firmware v1.4). Other
   bodies (including the E-M10 Mark II) are used at most as read-only references.
2. **Keep recovery ready before any test.** Official firmware for going back, a full battery, and a known-good
   update route (the update mode does not run any of our code). Do not test on a camera you cannot afford to
   lose. Everything here was tested on one body; there is no warranty.
3. **Licence boundaries.**
   - Do not commit or share OM Digital Solutions firmware, decoded partitions, built firmware files, large byte
     excerpts, disassembly dumps, or logs that contain them. The OM licence forbids redistribution of the
     images and of blobs derived from them.
   - The repository carries tools, recipes (addresses, our own new bytes, hashes) and reference SHA-1s only.
     The *old* bytes are always read from the contributor's own official download.
   - `mndis` (MN10300 disassembler, derived from GNU binutils) is GPL and is kept separate from the Apache-2.0
     tools. `cmdada` (GPL-3.0) is cited only; none of its code is copied. Caduceus and fishcu (Apache-2.0) are
     references, credited in NOTICE.
4. **Nothing is written to the camera by the tooling.** Analysis and emulation run on the PC. Only the owner
   flashes, by hand, from a card.
5. If a step could stop the camera working and you are not sure, stop and ask the owner.

## 2. Developer workflow

```
official download  ->  decode LOCALLY  ->  build  ->  test  ->  (audit)  ->  field test
```

1. **Download.** The tool fetches the official E-M10 Mark I v1.4 firmware from the OM server; the user accepts
   the OM licence first (same as the end-user builder).
2. **Decode locally.** `oly_fw.py` splits the image into partitions and decodes them into local `.dec` files.
   These never leave the machine.
3. **Build.** The builder applies the recipes (address, expected old bytes by hash, our new bytes) to the local
   decodes and re-packs the image with a valid header, footer and checksum.
4. **Test.** The harness (section 3) runs on the local `.dec` files and the built image.
5. **Publish only recipes.** A change is shared as rows: address, length, SHA-1 of the old bytes, our new bytes.
   Large tables are kept as generator scripts plus hashes where possible; a row never contains OM bytes.

**Keeping the boundary.** A strict `.gitignore` excludes `*.BIN`, `*.bin`, `*.dec`, `*.part`, dumps, `out/`, run
directories and logs. The **pre-push check** (`tools/prepush_check.py`) refuses a push that contains any of
those, any file with a firmware signature, an oversized file, or a long hex string; given your own copy of the
official firmware (`--stock`) it also checks that no run of 16 or more literal bytes in a patch file occurs in it.

## 3. Verification ladder

Each rung catches things the one below cannot. A build is staged for a camera only after the ladder passes.

### 3.1 Feature manifest and byte oracle
- The **feature manifest** maps every patch row to the feature that owns it (looks, colour editor, wheel core,
  wheel UI, live-view bit, dial hooks, tables, HUD, guide text). A row the manifest does not know is
  "unmapped" and forces the full lane. A row with two owners changes both features.
- The **byte oracle** compares the new image with the last fully passing image ("the pin"): every byte outside
  the declared rows must be identical (decoded partitions, raw partition, headers, footers). A failure names
  the address and, if known, the row and owner. It catches stray edits, not defects inside declared rows.

### 3.2 Reference census
A static pass over the whole image for every address we use:
- **dangling references**: a pointer, jump or table entry that names bytes we removed or moved;
- **cave zones**: code or data placed in free space must sit in a verified-empty run with guard bytes on both
  sides, and nothing else may name that run by accident (LE32 coincidences are listed and declared);
- **runtime-written zones**: ranges the firmware itself writes at run time (buffers, cells) must contain no
  cave of ours; a watch with a positive control proves the walk really writes them.

### 3.3 Real-route emulation, with negative controls
- Each feature is exercised in an MN10300 emulator on its **real route** (the key path, the paint path, the
  dial reader), not on a hand-picked function: the same entry points the camera uses.
- Every check has a **negative control**: the same check run on the previous build must FAIL where the new
  feature is expected to change behaviour. A check that cannot fail proves nothing.

### 3.4 Mutant proofs
Defective images are built on purpose and the harness must reject each. Defect classes this caught or proved
catchable:

| defect | how it is caught |
|---|---|
| a cave inside a runtime-written buffer | census: runtime window must be untouched; key-route emulation |
| a clobbered register in a cave | route emulation shows the wrong effect on real clicks (not just the table) |
| value accumulation (a missing reset, value drifts each pass) | repeated-pass sequences give distinct values |
| a mirrored ring / table (bytes reversed) | data-image and real key-route checks, painted marks vs the model |
| a dangling reference (target erased, pointer kept) | census; emulation crash at the erased target |
| text in unloaded memory (a pointer to a region the firmware does not load or reads before our write) | found while testing the guide text, then added to the checks |
| re-entrancy (a cave with static save area used from more than one core) | design review + stress emulation; **not** proven by the harness |

Defects outside the declared rows (a stray byte in any partition) are the byte oracle's job and were each
proven to fail.

### 3.5 Fast lane vs full lane
- **Full lane**: every stage (about 43), hours of wall time and several GB per heavy stage. Required for release
  builds, for any unmapped row, and when two or more non-leaf features change.
- **Fast lane**: always runs the build, the byte oracle, the censuses and the lookup-table checks, then only the
  stages mapped to the features whose rows changed. A clean no-change run is about 17 minutes at pool 1; a
  one-feature change is tens of minutes (roughly 50 minutes for a HUD-only change at pool 1, estimate).
- Heavy stages are split in parts (each under about 3 GB except one), with verdicts proven identical to the
  unsplit run.
- After every full-lane pass, the passing image becomes the new pin.

### 3.6 Independent dual audits
Before a build is staged, two independent reviewers (different models) re-derive the claims from the rows and
the code, without the author's scripts, and each must return GO. Findings are folded in and the build is
re-checked.

## 4. Worked example: the HUD hint

**Problem.** In the colour wheel screen the owner could not tell which keys do what. The stock screen has no
room for a hint, and the stock hint is not text: it is three bitmap children of the panel.

**Design.** Cloning the stock hint would mean reshaping a 10-child panel object (about six coordinated stock
structures, none proven). Instead: draw our own small 4-bit bitmaps (a dark box with white glyphs, readable on a
white scene) after the wheel's paint routine, through the same draw call it already uses. A seven-byte hook at
the paint routine's exit jumps to a small cave that replays the draw call per hint piece from a table. Pieces
sit in verified-empty runs with guards; the "built once" flag lives in a spare line of the runtime buffer.

**Proofs.**
- Manifest: five rows, a leaf feature (HUD), so the fast lane applies.
- Census: the hook site is named only by the cave; no stray reference to the cave or the data; the runtime
  window stays clean.
- Emulation on the real paint route over the whole key walk: per pass exactly the expected number of extra draw
  calls, at the expected positions, with every other call unchanged and registers restored.
- Negative control on the previous build: the extra calls must be absent there.
- Mutants of the classes in 3.4 (cave in the buffer, dangling reference) fail as required.

**Field result.** The first version drew the hint on **layer 0** and looked grey and "transparent" on the
camera. A 16-swatch palette probe showed that layer 0 only has an alpha / grey ramp and no true white; the
stock bright labels (for example "HUE") are drawn on **layer 1**, whose palette has an opaque near-white
(index 4) and a dark colour (index 12). The next build drew the same art on layer 1 and the owner confirmed the
hint is bright white like the stock label, with no leftover after leaving the screen.

**Lesson.** A palette index is not a colour until you know *which layer's palette* it indexes. The emulator
shows which calls are made, not what they look like; appearance needs a camera probe.

## 5. Lessons learned

- Prove the check can fail (negative control) before trusting that it passes.
- "The table is right" is not "the route is right": test through the real key and paint paths.
- Free space is not free if the firmware writes it at run time; census the runtime zones.
- Guard bytes and an exact-reference census catch most dangling and overlapping caves.
- Reuse a mechanism the camera already proved (same call, same hook) before inventing a new one.
- Appearance (colour, transparency, glyphs) needs a field probe; emulation cannot see it.
- Keep one change class per build so a field result points at one cause.
- Do not rerun heavy stages for features that did not change, but let a release always run the full lane.
- Write results down as dated entries; do not rewrite history.

## 6. Tools status

The generic tools (firmware splitter / decoder, the MN10300 emulator, the census, the byte oracle, the fast
lane) are **to be published later**, cleaned of project-specific folder chains and of any firmware-derived data.
The GPL parts (`mndis`, from binutils) will be published **separately** under their own licence, not mixed into
the Apache-2.0 repository. Until then this document describes the method only.
