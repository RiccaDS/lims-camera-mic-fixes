#!/bin/bash
# Revert the microphone to the LEGACY HDA driver (as before the fix). Root.
set -u
if [ "$(id -u)" != 0 ]; then echo "run as root"; exit 1; fi
CONF=/etc/modprobe.d/alsa-base.conf
BAK="$(ls -1t "$CONF".bak-* 2>/dev/null | head -1 || true)"
if [ -n "$BAK" ]; then cp -a "$BAK" "$CONF"; echo "restored $BAK"; else
  sed -i '/^options snd-intel-dspcfg .*dsp_driver=/d' "$CONF"
  echo 'options snd-intel-dspcfg dsp_driver=1' >> "$CONF"; echo "wrote dsp_driver=1"; fi
command -v update-initramfs >/dev/null && update-initramfs -u -k all >/dev/null 2>&1 || true
echo "reboot to return to legacy HDA (internal mic will disappear again)."
