<div align="center">

# 🎤🎙️ LIMS — make the **internal mic** and **camera** actually work on the HP Spectre x360 16 (Ubuntu/Linux)

**One-command fixes for the two things Linux gets wrong on this laptop:**
the PDM microphone array (hidden behind the wrong audio driver) and the IPU6 camera
(no libcamera handler → apps see nothing), plus a privacy-aware **Virtual Camera**
and a colour-calibration GUI.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.10-orange.svg)
![kernel](https://img.shields.io/badge/kernel-6.11-blue.svg)
![status](https://img.shields.io/badge/status-working%20✅-brightgreen.svg)

**[📥 Install](#-quick-install)** · **[💡 How it works](#-how-it-works)** · **[❓ FAQ](#-faq)**

### 💖 Support this work

<a href="https://www.paypal.com/pool/9uauher240?sr=wccr"><img src="https://img.shields.io/badge/Donate-PayPal-00457C?logo=paypal&logoColor=white" alt="Donate via PayPal" height="32"></a>
&nbsp;&nbsp;
<a href="https://www.paypal.com/pool/9uauher240?sr=wccr"><b>→ donate via PayPal</b></a>

</div>

---

## ✨ What you get

| Feature | Detail |
|---|---|
| 🎙️ **Internal microphone** | Switches the Intel audio driver from *legacy HDA* to *SOF* — the PDM mic array that legacy mode cannot see appears as a normal input (kernel logs `DMICs detected in NHLT tables: 2`). |
| 🎥 **Camera for EVERY app** | Streams the raw IPU6 sensor through a stride-correct, colour-correct pipeline into `/dev/video0 “Virtual Camera”` — works with Cheese, Kamoso, GNOME Snapshot, browsers, Google Meet… even though Ubuntu ships **no libcamera IPU6 handler**. |
| 🔒 **Honest privacy LED** | The camera LED lights **only while an app really consumes the camera**; 6 s after the last app closes the sensor is stopped and the LED goes dark. |
| 🎨 **Colour calibration GUI** | Live sliders (colour temperature, tint, R/G/B gains, gamma, brightness, contrast, saturation) + **Live auto white-balance** at `http://127.0.0.1:8192`, previewing exactly what apps will send. |
| ☀️ **Usable exposure** | This sensor has **no auto-exposure on Linux** — the installer sets measured exposure/gain so a normal room isn't pitch black. |


## 🚀 Quick install

```bash
git clone https://github.com/RiccaDS/lims-camera-mic-fixes.git
cd lims-camera-mic-fixes
sudo bash install.sh
# reboot once so the SOF microphone driver takes over cleanly
```

No git? Download the release tarball, extract it, run the same command.

After install:

* **Camera apps** → pick **“Virtual Camera”**
* **Tune colours** → open **http://127.0.0.1:8192** → move sliders → **Save & apply**
* **Microphone** → shows up as *Meteor Lake-P … Digital Microphone*

## 🔧 How it works

```
OV08X40 sensor (raw 3856×2176, padded stride) ─► cam_bridge.py
   stride-correct decode · Bayer GBRG · AWB/grade · privacy LED gate · TCP :8092
        └──► gst writer ──► /dev/video0 “Virtual Camera” (v4l2loopback, 1280×720 YUY2 @15)
```

The units encode several hard-won traps (see [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md)):

* kernel pads rows 7712 → **7744 bytes** — naive Bayer plugins shear the image;
* correct order for this sensor is **GBRG** (RGGB = grey/green mids, magenta whites);
* `videorate` must precede a 15/1 caps filter or the loopback rejects the stream;
* **never** add `do-timestamp=true` on the TCP source — the sink stalls forever;
* WirePlumber must be restarted once after the loopback device appears.

## 🖥️ Compatibility

| | |
|---|---|
| **Tested on** | HP Spectre x360 2-in-1 16-aa0xxx · Ubuntu 24.10 · kernel 6.11.0-29 · GNOME 47 (Wayland) |
| **Likely works on** | Other Meteor-Lake HPs with **ALC245 + OV08X40 + IPU6** (installer warns if devices are missing) |
| **Needs** | `v4l2loopback`, GStreamer 1.24, python3 + OpenCV (installed automatically on Ubuntu/Debian) |

## ❓ FAQ

**Is it safe?** Everything lives in `/opt/lims-camera` + 4 systemd units + one modprobe line
(backed up). `sudo bash uninstall.sh` reverts all of it, including the audio driver.

**Does the LED ever lie?** No — it is driven by the sensor's actual stream state
(`/sys/class/leds/*privacy_led` follows STREAMON exactly). Idle 6 s → capture stopped → LED off.

**Why is my image still dark?** Turn on more light: there is no auto-exposure on Linux for this
sensor, and the calibration GUI's gamma/brightness sliders are the compensation.

**Mic missing after install?** Reboot once — the SOF driver takes over on the next boot.

## 📄 License & contributing

[MIT](LICENSE). Issues and PRs welcome — especially reports from other Meteor-Lake HP models.

<div align="center">
<sub>If this saved you an evening, <a href="https://www.paypal.com/pool/9uauher240?sr=wccr">a coffee is appreciated ☕</a></sub>
</div>
