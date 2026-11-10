# Installing

## Requirements

- Python 3.10 or newer (standard library only; nothing to install).
- An internet connection to download the official firmware (about 67 MB), or an official v1.4 file you already
  have.
- An SD card, and a **fully charged** camera battery.
- About 250 MB free disk space for the output.

## 1. Build

Open a terminal in this folder.

```
python om10mi.py build
```

The builder will:
1. ask the OM Digital Solutions server for the E-M10 Mark I v1.4 firmware and show the licence the server
   attaches to it. Type `yes` if you accept (or pass `--accept-license`);
2. check that the downloaded file is the expected firmware (sha1 `5a0703ac...`);
3. apply the edits, fix the checksums, and compare the result with the published hash (sha1 `0d4e1649...`). If
   they differ, nothing is written;
4. write two folders:
   - `out/DCOLYMP/E1139999.BIN`: version 56, to install;
   - `out/RESTORE/DCOLYMP/E1139999.BIN`: the official v1.4, to go back.

Already have the official file? `python om10mi.py build --stock OLY_E_113_1400_0000_0000.BIN`.
Only want to download and check it? `python om10mi.py fetch`. Want to check a file?
`python om10mi.py verify FILE.BIN`.

If the OM server now offers a version newer than 1.4, the builder stops with a message; this pack fits v1.4
only.

## 2. Install on the camera

1. Full battery. Back up the card, then **format the card in the camera**.
2. Copy the folder `DCOLYMP` (from `out/DCOLYMP`) to the root of the card, so that `DCOLYMP/E1139999.BIN`
   exists.
3. Camera off. Insert the card.
4. **Hold the OK button** while switching the camera on. The screen stays black.
5. The AF lamp on the front lights orange. **Do not switch the camera off** while this runs; wait until the lamp
   blinks rapidly, which means it is finished.
6. Switch off, remove the battery briefly, reinsert it, switch on.
7. Delete the `DCOLYMP` folder from the card, then follow [docs/GUIDE-56.md](docs/GUIDE-56.md) (User Hue Reset
   once, then the test list).

Lamp rules:
- steady orange = working, do not switch off;
- rapid blinking = finished.

## 3. Going back to the official firmware

Copy `out/RESTORE/DCOLYMP` to the card and repeat step 2. Update mode (hold OK while switching on) does not run
any of the added code, so this route stays available as long as the camera can be started in that mode.
