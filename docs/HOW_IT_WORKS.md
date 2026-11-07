# How it works (and why each piece exists)

## 1. Microphone: legacy HDA has no internal mic

The codec is Realtek **ALC245**. Pin sense dumps (hda-verb `GET_PIN_SENSE`) show only
**pin 0x19 = combo-jack mic** with presence; the internal PDM array has **no HDA pin at all** —
it lives behind the Intel DSP and is exposed only by the **SOF** driver.

The fix sets `dsp_driver=3` (SOF). On boot the kernel loads `sof-audio-pci-intel-mtl`, firmware
2.11.1.1, topology `sof-hda-generic-2ch`, and logs **`DMICs detected in NHLT tables: 2`**, creating:

* `HiFi__Mic1__source` = Meteor Lake-P … Digital Microphone → **internal array**
* `HiFi__Mic2__source` = Headphones Stereo Microphone → combo jack
* speaker + HDMI sinks (CS35L41 amps bound)

Measured: internal mic noise floor rms ≈ 87 vs ≈ 12 in legacy mode, real signal spikes up to
rms ≈ 1227 in 0.5 s windows.

## 2. Camera: raw sensor → Virtual Camera

There is **no libcamera pipeline handler** for IPU6 in Ubuntu 24.10 (`cam -l` → 0 cameras), so
GNOME/Cheese/browser portal apps see nothing. The fix makes a **v4l2loopback** device that every
app understands:

1. **cam_bridge.py** streams the sensor raw (`BA10`, 3856×2176, **stride 7744** — the driver
   pads 32 B/line; naive decoders shear diagonally).
2. Bayer demosaic via OpenCV. **Order matters**: `GBRG` is correct for this sensor — `RGGB`
   suppressed green ~22-30 % and rendered whites as red≈blue>green (the "grey or magenta" image).
3. Colour grade from `cam_config.json`: white balance (manual gains or **Live AWB** grey-world),
   colour temperature, tint, gamma, brightness, contrast, saturation.
4. YUY2 1280×720 → TCP `:8092` (also raw mosaic hub on `:8094` for the GUI).
5. **lancia-cam-writer** (gst-launch) pulls TCP → `videorate` → 15/1 caps → `v4l2sink` on
   `/dev/video0` with `exclusive_caps=1` → apps read "Virtual Camera".
6. **Privacy LED**: `cam_bridge` watches for real consumers (user processes with `/dev/video0`
   open, or an active PipeWire video stream). No consumer for 6 s → capture child killed →
   sensor STREAMOFF → `/sys/class/leds/*privacy_led` = 0. Consumer appears → capture restarts
   in ~1-2 s → LED 1. Measured: LED follows STREAMON exactly (1/0/1 test).

## 3. Traps encoded in the units (do not "simplify" them away)

| Trap | Symptom if removed |
|---|---|
| `videorate ! video/x-raw,…framerate=15/1` before v4l2sink | loopback device only enumerates 30 fps → `not-negotiated`, sink never plays |
| **no** `do-timestamp=true` on tcpclientsrc | sink stuck in PREROLL forever (0 frames to consumers) |
| `ExecStartPre` tolerant rmmod (`|| true`) | restart loop when an app holds the module |
| `ExecStartPost` WirePlumber restart | `wpctl status` Video→Sources empty → apps "no camera" |
| `exclusive_caps=1` on v4l2loopback | device flaps between output/capture modes |
| stride-aware numpy decode (never libgstbayer) | diagonal rainbow stripes |
| `cfa_order=GBRG` in cam_config.json | green/grey or magenta whites |

## 4. Calibration GUI

`cam_calib_gui.py` serves a single page: the preview is generated **from the raw hub with the
same `cam_common.grade_rgb()`** the stream uses, so what you see is what apps get.
Changes POST to `/config` (preview only) and `/save` writes `cam_config.json`; `cam_bridge`
re-reads it within 2 s (even while the LED gate has the capture stopped).
