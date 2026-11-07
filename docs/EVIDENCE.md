# Measured evidence (reference machine: HP Spectre x360 16-aa0xxx, Ubuntu 24.10, kernel 6.11.0-29)

All numbers measured during development (2026-11-06/07). No personal data in this file.

## Microphone
| Check | Legacy (dsp_driver=1) | SOF (dsp_driver=3) |
|---|---|---|
| Kernel log | — | `DMICs detected in NHLT tables: 2` |
| Internal mic node | absent (pin sense: only 0x19 jack) | `HiFi__Mic1__source` Digital Microphone |
| Recording noise floor (rms) | ≈ 12 (dead) | ≈ 87, signal spikes ≈ 1227 / max 9332 |

## Camera pipeline
| Check | Value |
|---|---|
| Raw stream | 3856×2176 BA10, row stride **7744 B** (32 B pad) |
| Bayer order | **GBRG** (side-by-side same-frame review; RGGB → whites 1.11/0.78/1.11 = magenta) |
| Virtual camera output | 1280×720 YUY2 @15 fps caps (device enumerates 30 fps, accepts 15 via S_PARM) |
| Consumer fps (v4l2-ctl on /dev/video0) | ≈ 9 fps from the bridge at night exposure (videorate pads to 15) |
| Pipeline cost | ≈ 54-97 ms/frame demosaic+grade (OpenCV path, was 1650 ms in pure numpy) |
| v4l2-relayd (replaced) | delivered **0.6 fps** to consumers → replaced by plain gst-launch writer |
| Exposure controls | vertical_blanking=1000, exposure=6000 (max 6344 at this blanking), analogue_gain=1984 (max) — sensor has **no 3A** on Linux |
| Privacy LED | sysfs brightness = 1 while streaming, 0 when stopped (measured 1/0/1); gate: idle 6 s → off, app opens → on in 1-2 s |
| Discovery | `wpctl status` → Video → Sources: `Virtual (V4L2)` after the WirePlumber hook; GStreamer DeviceMonitor lists `DEV: Virtual (V4L2) | Video/Source` |

## Historical bugs fixed (kept in docs for context)
1. libgstbayer ignores padded stride → diagonal stripes (kernel pads 7712→7744).
2. Wrong Bayer order (RGGB) → grey/green mids + magenta highlights.
3. systemd/sh quoting mangled the GStreamer pipeline → argv-form wrapper.
4. `do-timestamp=true` → sink never prerolls (0 frames).
5. Writer restart loop: `rmmod` failing when the module was in use → 76 restarts (made tolerant).
6. WirePlumber not re-reading device capabilities → source node missing for apps.
