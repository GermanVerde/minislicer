# MiniSlicer for Blender

**English** | [Español](README.es.md)

Blender add-on that **slices the active object and exports native
`.phz` / `.ctb` files** ready to print on **Phrozen** resin printers,
without leaving Blender and with no intermediate software.

**Free and open source.** If MiniSlicer is useful to you, you can support
its development with a donation on Ko-fi:
[ko-fi.com/micotico36213](https://ko-fi.com/micotico36213) ☕

## Supported printers

| Model | Resolution | Plate (mm) | Format | Status |
|---|---|---|---|---|
| Sonic Mini | 1080×1920 | 67.8×120×130 | `.phz` | ✅ Verified on hardware |
| Sonic | 1080×1920 | 67.8×120×170 | `.phz` | 🧪 Beta |
| Transform | 3840×2160 | 291.8×164.2×400 | `.phz` | 🧪 Beta |
| Sonic Mini 4K | 3840×2160 | 134.4×75.6×130 | `.ctb` | 🧪 Beta |
| Sonic Mini 8K | 7500×3240 | 165×71.3×180 | `.ctb` | 🧪 Beta |
| Sonic 4K | 3840×2160 | 134.4×75.6×200 | `.ctb` | 🧪 Beta |
| Sonic XL 4K | 3840×2400 | 192×120×200 | `.ctb` | 🧪 Beta |
| Sonic Mighty 4K | 3840×2400 | 200×125×220 | `.ctb` | 🧪 Beta |
| Sonic Mighty 8K | 7680×4320 | 218×123×235 | `.ctb` | 🧪 Beta |
| Sonic Mega 8K | 7680×4320 | 330×185×400 | `.ctb` | 🧪 Beta |
| Sonic Mini 8K S | 7536×3240 | 165.8×71.3×170 | `.prz` | 🚧 Coming soon |
| Sonic Mighty 12K | 11520×5120 | 218.9×123.1×235 | `.prz` | 🚧 Coming soon |
| Sonic Mega 8K S | 7680×4320 | 330×185×300 | `.prz` | 🚧 Coming soon |

**About the beta status**: profiles come from the specifications published
by Phrozen, and the generated files are validated against the reference
implementations (pixel-by-pixel round-trip, UVtools, uv3dp), but for now
only the **Sonic Mini** has been verified with real prints. If you print
with another model, [open an issue][issues] and tell us how it went — that
is what moves a profile from beta to verified. The `.prz` models (2023+)
appear in the panel but have no file writer yet.

[issues]: ../../issues

## Features

- **Integrated panel**: 3D viewport sidebar (`N` key), "MiniSlicer" tab,
  UI translated into 10 languages.
- **13 Phrozen profiles** with the build volume drawn in the viewport;
  the part is auto-centered when slicing.
- **Layer viewer**: shows the exact image of each layer at the native LCD
  resolution of the selected profile, navigable layer by layer.
- **Slices the active object directly**: modifiers (Boolean, Remesh,
  supports…) are applied automatically; object scale and rotation are
  respected.
- **Non-blocking export**: modal operator with progress in the status bar
  (`Esc` cancels).
- Scanline fill with the **even-odd** rule: holes and internal cavities of
  watertight meshes come out right with zero setup.
- Resin (ml) and print-time estimates; warning when the part does not fit
  the plate; thumbnails for the printer screen.
- **Zero dependencies, zero network**: only uses the numpy bundled with
  Blender — no activation keys, no telemetry, no connection to anything.

## Requirements

- Blender **4.2 or newer** (tested on 5.1.2).
- A Phrozen resin printer from the table above.

## Installation

1. Download `MiniSlicer_Blender.zip` (or build it, see below).
2. In Blender: `Edit → Preferences → Add-ons → ▼ → Install from Disk…`
   and pick the zip.
3. Make sure the add-on checkbox is **enabled**.
4. In the 3D viewport press `N` → **MiniSlicer** tab.

## Usage

1. Pick your **printer** in the panel dropdown.
2. Select your part (watertight mesh, with supports already modeled).
3. **Load / Refresh Model** — check size in mm, layer count and time.
4. **Open Layer Viewer** — inspect the sections before exporting.
5. Adjust exposure for your resin (typical: 1.5–3 s per 0.05 mm layer;
   bottom 30–40 s).
6. **Export** (`.phz` or `.ctb` depending on the profile) → copy the file
   to the USB drive → print.

**Units**: by default it uses the scene units (1 m = 1000 mm). If you model
with the "1 unit = 1 mm" convention, change it in the panel selector.

## Building the zip from source

```
blender --command extension build --source-dir minislicer_blender --output-filepath MiniSlicer_Blender.zip
```

## File format details

The `.phz` and `.ctb` (ChiTu) formats are implemented after the reference
implementation in [UVtools](https://github.com/sn4k3/UVtools) and the
[catibo](https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc)
documentation:

- Binary header and per-layer table according to each spec.
- Layer image: 7-bit grayscale RLE (`.phz`) / `.ctb` RLE; XOR encryption
  supported (files are written unencrypted, `EncryptionKey=0`).
- RGB15 + RLE previews (400×300 and 200×125).

Generated files were validated round-trip (pixel-by-pixel re-read) and with
[uv3dp](https://github.com/ezrec/uv3dp) as an independent reader.

## First print

Print a 20 mm calibration cube first: if it measures 20.0 mm per side and
the orientation is correct (nothing mirrored), the profile is fine. If
something comes out inverted, untick "Mirror Image in X".

## License

[GPL-3.0-or-later](LICENSE) — like every Blender add-on. Free, with no
activation keys and no registration.

This software comes with no warranty; always verify your first print with
a small part.
