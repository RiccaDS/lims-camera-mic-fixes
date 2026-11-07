#!/bin/bash
D=$(grep -l ov08x40 /sys/class/video4linux/v4l-subdev*/name 2>/dev/null | head -1)
[ -z "$D" ] && exit 0
N=$(basename "$(dirname "$D")")
v4l2-ctl -d "/dev/$N" --set-ctrl vertical_blanking=1000 >/dev/null 2>&1
v4l2-ctl -d "/dev/$N" --set-ctrl exposure=6000 >/dev/null 2>&1
v4l2-ctl -d "/dev/$N" --set-ctrl analogue_gain=1984 >/dev/null 2>&1
exit 0
