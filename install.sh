#!/bin/bash
# LIMS — laptop internal-mic & camera fixes (HP Spectre x360 16-aa0xxx family)
# Installs: internal microphone via SOF, virtual-camera pipeline, sensor exposure,
# privacy LED gate, colour-calibration GUI. Run as root:  sudo bash install.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LIMS_USER="${SUDO_USER:-$(id -un)}"
LIMS_DIR="/opt/lims-camera"
PYTHON="$(command -v python3)"
echo "== LIMS install (user=$LIMS_USER) =="
if [ "$(id -u)" != 0 ]; then echo "run as root: sudo bash install.sh"; exit 1; fi

# 0) selectable parts:  sudo bash install.sh            -> camera + mic (default)
#                        sudo bash install.sh --camera   -> camera only (no audio-driver change)
#                        sudo bash install.sh --mic      -> microphone only (no camera packages/units)
DO_CAM=1; DO_MIC=1
for A in "$@"; do
  case "$A" in
    --camera) DO_CAM=1; DO_MIC=0;;
    --mic)    DO_CAM=0; DO_MIC=1;;
    -h|--help) echo "usage: sudo bash install.sh [--camera|--mic]   (default: both)"; exit 0;;
    *) echo "unknown option: $A (try --help)"; exit 1;;
  esac
done
echo "parts: camera=$([ $DO_CAM = 1 ] && echo yes || echo no) mic=$([ $DO_MIC = 1 ] && echo yes || echo no)"

# 1) dependencies -------------------------------------------------------------
if [ "$DO_CAM" = 1 ]; then
  apt-get update -qq || true
  apt-get install -y -qq v4l2loopback-dkms v4l-utils gstreamer1.0-tools \
      gstreamer1.0-plugins-base gstreamer1.0-plugins-good python3-opencv python3-numpy \
      pipewire wireplumber 2>&1 | tail -2
  PYTHON_SITE="$("$PYTHON" -c 'import cv2; print(cv2.__file__)' 2>/dev/null || true)"
  if [ -z "$PYTHON_SITE" ]; then
    echo "!! python3-opencv missing -> trying pip"
    "$PYTHON" -m pip install --break-system-packages -q opencv-python-headless numpy || {
       echo "!! install OpenCV manually and re-run"; exit 1; }
  fi
fi

# 2) program files ------------------------------------------------------------
if [ "$DO_CAM" = 1 ]; then
mkdir -p "$LIMS_DIR"
install -m 644 "$HERE"/camera/cam_common.py   "$LIMS_DIR/"
install -m 644 "$HERE"/camera/cam_bridge.py   "$LIMS_DIR/"
install -m 644 "$HERE"/camera/cam_calib_gui.py "$LIMS_DIR/"
install -m 755 "$HERE"/camera/lancia-cam-exposure.sh    "$LIMS_DIR/"
install -m 755 "$HERE"/camera/lancia-cam-wireplumber.sh "$LIMS_DIR/"
if [ ! -f "$LIMS_DIR/cam_config.json" ]; then
  install -m 644 "$HERE"/camera/cam_config.default.json "$LIMS_DIR/cam_config.json"
fi

# 3) system units -------------------------------------------------------------
render() { sed "s|@INSTALL_DIR@|$LIMS_DIR|g; s|@PYTHON@|$PYTHON|g; s|@USER@|$LIMS_USER|g" \
             "$1" > "$2"; }
render "$HERE/camera/units/lancia-cam-exposure.service" /etc/systemd/system/lancia-cam-exposure.service
render "$HERE/camera/units/lancia-cam-writer.service"   /etc/systemd/system/lancia-cam-writer.service
# 4) user units ---------------------------------------------------------------
UDIR="/home/$LIMS_USER/.config/systemd/user"
mkdir -p "$UDIR"; chown -R "$LIMS_USER:" "$UDIR" 2>/dev/null || true
render "$HERE/camera/units/cam-bridge.service"    "$UDIR/cam-bridge.service"
render "$HERE/camera/units/cam-calib-gui.service"  "$UDIR/cam-calib-gui.service"
chown "$LIMS_USER:" "$UDIR"/cam-bridge.service "$UDIR"/cam-calib-gui.service 2>/dev/null || true
fi   # end DO_CAM (program files + units)

# 5) microphone (SOF) ---------------------------------------------------------
if [ "$DO_MIC" = 1 ]; then
  bash "$HERE/mic/install-mic.sh" || echo "!! mic step failed (camera unaffected)"
fi

# 6) start --------------------------------------------------------------------
UID_N="$(id -u "$LIMS_USER")"
if [ "$DO_CAM" = 1 ]; then
  systemctl daemon-reload
  systemctl enable --now lancia-cam-exposure.service lancia-cam-writer.service
  runuser -u "$LIMS_USER" -- env XDG_RUNTIME_DIR="/run/user/$UID_N" \
     DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" \
     systemctl --user daemon-reload
  runuser -u "$LIMS_USER" -- env XDG_RUNTIME_DIR="/run/user/$UID_N" \
     DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" \
     systemctl --user enable --now cam-bridge.service cam-calib-gui.service
  sleep 4
  echo "== status (camera) =="
  systemctl is-active lancia-cam-exposure.service lancia-cam-writer.service
  runuser -u "$LIMS_USER" -- env XDG_RUNTIME_DIR="/run/user/$UID_N" \
     DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" \
     systemctl --user is-active cam-bridge.service cam-calib-gui.service
  echo "Calibration GUI:  http://127.0.0.1:8192"
  echo "Virtual Camera:   /dev/video0 'Virtual Camera'"
fi
if [ "$DO_MIC" = 1 ]; then
  echo "MIC: reboot if the internal mic is not yet listed (SOF takes over on next boot)."
fi
echo "== done =="
