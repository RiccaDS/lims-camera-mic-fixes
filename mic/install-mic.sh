#!/bin/bash
# Internal microphone fix — Meteor Lake HP laptops whose alsa-base.conf forces
# LEGACY HDA (dsp_driver=1): the PDM mic array is only exposed by the SOF driver.
# Sets dsp_driver=3 (SOF), keeps the speaker quirk, refreshes initramfs. Root.
set -u
echo "== LIMS mic fix =="
if [ "$(id -u)" != 0 ]; then echo "run as root"; exit 1; fi
CONF=/etc/modprobe.d/alsa-base.conf
if [ -f "$CONF" ] && ! grep -q 'dsp_driver=3' "$CONF"; then
  cp -a "$CONF" "$CONF.bak-lims-$(date +%Y%m%d-%H%M%S)"
fi
if [ -f "$CONF" ]; then
  sed -i '/^options snd-intel-dspcfg .*dsp_driver=/d' "$CONF"
fi
cat >> "$CONF" <<'EOF'
options snd-intel-dspcfg dsp_driver=3
options snd-hda-intel model=alc245-hp-x360-amp
EOF
QUIRK=/etc/modprobe.d/hp-speaker-quirk.conf
if [ ! -f "$QUIRK" ]; then
  echo 'options snd-sof-intel-hda-common hda_model=alc245-hp' > "$QUIRK"
fi
echo "  $CONF -> dsp_driver=3 (SOF)"
PCI=0000:00:1f.3
DRVS=/sys/bus/pci/drivers
if command -v update-initramfs >/dev/null; then update-initramfs -u -k all >/dev/null 2>&1 || true; fi
CUR="$(basename "$(readlink /sys/bus/pci/devices/$PCI/driver 2>/dev/null)" 2>/dev/null || echo none)"
echo "  current driver on $PCI: $CUR"
if [ "$CUR" != "sof-audio-pci-intel-mtl" ]; then
  echo "  attempting live switch to SOF (fallback: reboot applies it)..."
  echo 3 > /sys/module/snd_intel_dspcfg/parameters/dsp_driver 2>/dev/null || true
  if [ "$(cat /sys/module/snd_intel_dspcfg/parameters/dsp_driver 2>/dev/null)" = "3" ]; then
    for P in $PCI; do
      D=$(basename "$(readlink /sys/bus/pci/devices/$P/driver 2>/dev/null)" 2>/dev/null || true)
      [ -n "$D" ] && echo "$P" > "$DRVS/$D/unbind" 2>/dev/null || true
    done
    rmmod snd_hda_intel 2>/dev/null || true
    modprobe snd-sof-pci-intel-mtl 2>/dev/null || modprobe snd_sof_pci_intel_mtl 2>/dev/null || true
    echo "$PCI" > "$DRVS/sof-audio-pci-intel-mtl/bind" 2>/dev/null || true
  fi
fi
sleep 2
echo "  dmics: $(dmesg 2>/dev/null | grep -c 'DMICs detected')"
echo "== mic step done =="
