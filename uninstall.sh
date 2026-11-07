#!/bin/bash
# Remove everything LIMS installed (camera + mic). Root. Reversible by re-running install.sh.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LIMS_USER="${SUDO_USER:-$(id -un)}"
UID_N="$(id -u "$LIMS_USER")"
if [ "$(id -u)" != 0 ]; then echo "run as root"; exit 1; fi
echo "== LIMS uninstall =="
runuser -u "$LIMS_USER" -- env XDG_RUNTIME_DIR="/run/user/$UID_N" \
   DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" \
   systemctl --user disable --now cam-bridge.service cam-calib-gui.service 2>/dev/null || true
rm -f "/home/$LIMS_USER/.config/systemd/user/cam-bridge.service" \
      "/home/$LIMS_USER/.config/systemd/user/cam-calib-gui.service"
systemctl disable --now lancia-cam-writer.service lancia-cam-exposure.service 2>/dev/null || true
rm -f /etc/systemd/system/lancia-cam-writer.service /etc/systemd/system/lancia-cam-exposure.service
systemctl daemon-reload
rm -rf /opt/lims-camera
bash "$HERE/mic/uninstall-mic.sh" || true
echo "== uninstalled (reboot to fully restore audio; rmmod v4l2loopback if the node lingers) =="
