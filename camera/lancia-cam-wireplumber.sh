#!/bin/bash
# Restart WirePlumber so the Virtual Camera VIDEO SOURCE node re-appears after the loopback
# device is (re)created. Runs as root (from the writer service ExecStartPost).
sleep 3
U="${LIMS_USER:-$(id -un)}"
UID_N=$(id -u "$U" 2>/dev/null || echo 1000)
runuser -u "$U" -- env XDG_RUNTIME_DIR="/run/user/$UID_N" \
     DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_N/bus" \
     systemctl --user restart wireplumber
exit 0
