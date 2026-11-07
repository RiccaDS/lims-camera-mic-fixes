#!/usr/bin/env python3
"""cam_common.py — shared colour pipeline + config for the LANCIA camera (tasks #341/#357).
Single source of truth: cam_bridge.py (stream) and cam_calib_gui.py (calibration) both import it,
so what you calibrate is EXACTLY what the stream sends."""
import json, os, socket, struct, subprocess, time
import numpy as np
import cv2

DEV = os.environ.get('CAM_DEV', '/dev/video1')
W, H, STRIDE = 3856, 2176, 7744
OUT_W, OUT_H = 1280, 720

# Defaults = the values measured good on 2026-11-07 (night scene):
DEFAULTS = {
    'cfa_order': 'GBRG',  # cv2 Bayer demosaic order picked by eye 2026-11-07 (GB): 'RGGB'|'GRBG'|'GBRG'|'BGGR'
    'awb_live': 0,     # 1 = continuous grey-world white balance (auto), 0 = manual gain_r/g/b
    'temp': 0.00,     # colour temperature: >0 warmer (amber), <0 cooler (blue)
    'tint': 0.00,     # tint: >0 more magenta, <0 more green
    'gain_r': 1.00,   # per-channel gains (white balance)
    'gain_g': 1.00,
    'gain_b': 1.00,
    'gamma': 0.68,    # <1 brightens dark scenes (LUT exponent)
    'saturation': 1.35,
    'brightness': 0.00,  # added after gamma, in 0..255 units
    'contrast': 1.00,    # around mid-grey
}
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cam_config.json')


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            for k, v in json.load(f).items():
                if k not in DEFAULTS:
                    continue
                cfg[k] = float(v) if isinstance(DEFAULTS[k], (int, float)) and not isinstance(DEFAULTS[k], bool) else str(v)
    except Exception:
        pass
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + '.tmp'
    def _v(k):
        v = cfg.get(k, DEFAULTS[k])
        return float(v) if isinstance(DEFAULTS[k], (int, float)) and not isinstance(DEFAULTS[k], bool) else str(v)
    with open(tmp, 'w') as f:
        json.dump({k: _v(k) for k in DEFAULTS}, f, indent=1)
    os.replace(tmp, CONFIG_PATH)
    return CONFIG_PATH


def read_mosaic(dev=DEV):
    """Yield stride-padded 10-bit BA10 mosaic buffers from the sensor.
    Closing the generator terminates v4l2-ctl (STREAMOFF) -> privacy LED off."""
    p = subprocess.Popen(['v4l2-ctl', '-d', dev,
                          '--set-fmt-video=width=%d,height=%d,pixelformat=BA10' % (W, H),
                          '--stream-mmap', '--stream-to=/dev/stdout', '--stream-count=1000000'],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    FS = STRIDE * H
    try:
        while True:
            buf = p.stdout.read(FS)
            if len(buf) < FS:
                break
            yield buf
    finally:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


_CFA_CFG = {'cfa_order': 'RGGB'}


def set_cfa(order):
    """Select the Bayer demosaic order (live, no restart): 'RGGB'|'GRBG'|'GBRG'|'BGGR'."""
    if order in ('RGGB', 'GRBG', 'GBRG', 'BGGR'):
        _CFA_CFG['cfa_order'] = order
        return True
    return False


def mosaic_to_rgb(buf):
    """stride-aware mosaic -> 1280x720 float RGB in 0..255 (pre-grade, post-demosaic+crop+resize)."""
    a = np.frombuffer(buf, dtype='<u2').reshape(H, STRIDE // 2)[:, :W]
    a8 = (a >> 2).astype(np.uint8)                     # 10-bit -> 8-bit for cv2
    _ORDER = {'RGGB': cv2.COLOR_BayerRG2BGR, 'GRBG': cv2.COLOR_BayerGR2BGR,
              'GBRG': cv2.COLOR_BayerGB2BGR, 'BGGR': cv2.COLOR_BayerBG2BGR}
    _o = _ORDER.get(_CFA_CFG.get('cfa_order', 'RGGB'), cv2.COLOR_BayerRG2BGR)
    bgr = cv2.demosaicing(a8, _o)
    ar = OUT_W / OUT_H
    cw = int(round(H * ar))
    if cw <= W:
        x0 = (W - cw) // 2
        bgr = bgr[:, x0:x0 + cw]
    elif cw > W:
        pad = (cw - W) // 2
        bgr = cv2.copyMakeBorder(bgr, 0, 0, pad, cw - W - pad, cv2.BORDER_REPLICATE)
    bgr = cv2.resize(bgr, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
    rgb = bgr[..., ::-1].astype(np.float32)            # BGR -> RGB float
    return rgb


_GAMMA_CACHE = {}


def autowb_gains(rgb, strength=1.0):
    """Grey-world white-balance gains from a frame: bright 40% of pixels are treated as
    scene content; returns clipped per-channel gains (neutralise -> equal channel means).
    strength=1 full correction, 0.5 half (softer)."""
    m = rgb.reshape(-1, 3)
    lum = m.mean(1)
    mask = lum > np.percentile(lum, 60)
    means = m[mask].mean(0)
    if float(means.max()) <= 1.0:
        return None
    grey = means / means.mean()
    gains = (1.0 / grey) ** strength
    return np.clip(gains, 0.5, 2.0).astype(np.float32)


def grade_rgb(rgb, cfg):
    """Apply calibration: colour temperature/tint -> white-balance gains -> gamma LUT ->
    brightness -> contrast -> saturation. Pure function of (rgb, cfg); used identically by
    the stream and the GUI preview."""
    out = rgb
    # colour temperature (amber/blue axis) and tint (green/magenta axis), luminance-preserving
    temp = float(cfg.get('temp', 0.0))
    tint = float(cfg.get('tint', 0.0))
    if temp or tint:
        m = np.array([1.0, 1.0, 1.0], np.float32)
        # temp: +1 -> R x1.18 B x0.85 ; -1 inverse (approximate Planckian direction on sRGB)
        m[0] *= 1.0 + 0.18 * temp
        m[1] *= 1.0 - 0.06 * temp
        m[2] *= 1.0 - 0.15 * temp
        # tint: +1 (magenta) -> G down, R/B slightly up ; -1 (green) inverse
        m[1] *= 1.0 - 0.16 * tint
        m[0] *= 1.0 + 0.05 * tint
        m[2] *= 1.0 + 0.05 * tint
        out = out * m
    if cfg.get('awb_live'):
        ag = autowb_gains(out, strength=1.0)
        g = ag if ag is not None else np.array([1.0, 1.0, 1.0], np.float32)
    else:
        g = np.array([cfg['gain_r'], cfg['gain_g'], cfg['gain_b']], np.float32)
    out = out * g
    gm = round(float(cfg['gamma']), 3)
    if gm not in _GAMMA_CACHE:
        _GAMMA_CACHE[gm] = (np.clip((np.arange(256) / 255.0) ** gm * 255.0, 0, 255)).astype(np.uint8)
    out = _GAMMA_CACHE[gm][np.clip(out, 0, 255).astype(np.uint8)].astype(np.float32)
    out = out + cfg['brightness']
    out = (out - 128.0) * cfg['contrast'] + 128.0
    np.clip(out, 0, 255, out=out)
    lum = (0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2])[..., None]
    out = lum + (out - lum) * cfg['saturation']
    np.clip(out, 0, 255, out=out)
    return out


def rgb_to_yuy2(rgb):
    """BT.601 RGB(float 0..255) -> 1280x720 YUY2 bytes (same math as the original bridge)."""
    r = rgb[..., 0]; g = rgb[..., 1]; b = rgb[..., 2]
    Y = (0.257 * r + 0.504 * g + 0.098 * b) * 0.716 + 16.0
    U = ((-0.148 * r - 0.291 * g + 0.439 * b)) * 0.716 + 128.0
    V = ((0.439 * r - 0.368 * g - 0.071 * b)) * 0.716 + 128.0
    Y = np.clip(Y, 0, 255).astype(np.uint8)
    U = np.clip(U, 0, 255).astype(np.uint8)
    V = np.clip(V, 0, 255).astype(np.uint8)
    out = np.empty((OUT_H, OUT_W * 2), np.uint8)
    out[:, 0::2] = Y
    U2 = U.reshape(OUT_H, OUT_W // 2, 2).mean(axis=2).astype(np.uint8)
    V2 = V.reshape(OUT_H, OUT_W // 2, 2).mean(axis=2).astype(np.uint8)
    out[:, 1::4] = U2
    out[:, 3::4] = V2
    return out.tobytes()


def process_frame(buf, cfg):
    """mosaic buffer -> YUY2 bytes with the given calibration (the stream path)."""
    return rgb_to_yuy2(grade_rgb(mosaic_to_rgb(buf), cfg))


def yuy2_to_rgb(fr):
    """YUY2 (Y U Y V interleaved) bytes -> uint8 RGB array (for previews)."""
    a = np.frombuffer(fr, np.uint8).reshape(OUT_H, OUT_W * 2).astype(np.float32)
    Y = a[:, 0::2]
    U = a[:, 1::4].repeat(2, axis=1) - 128.0
    V = a[:, 3::4].repeat(4, axis=1)[:, :OUT_W] - 128.0
    # each quad covers 4 bytes = 2 pixels: expand 2x:
    U = np.repeat(a[:, 1::4], 2, axis=1) - 128.0
    V = np.repeat(a[:, 3::4], 2, axis=1) - 128.0
    R = Y + 1.402 * V
    G = Y - 0.344136 * U - 0.714136 * V
    B = Y + 1.772 * U
    rgb = np.stack([np.clip(R, 0, 255), np.clip(G, 0, 255), np.clip(B, 0, 255)], -1)
    return rgb.astype(np.uint8)




def grab_mosaic(dev=DEV, count=1):
    """One-shot grab (stops cleanly): return the first mosaic buffer."""
    p = subprocess.Popen(['v4l2-ctl', '-d', dev,
                          '--set-fmt-video=width=%d,height=%d,pixelformat=BA10' % (W, H),
                          '--stream-mmap', '--stream-to=/dev/stdout', '--stream-count=%d' % count],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    FS = STRIDE * H
    buf = p.stdout.read(FS)
    try:
        p.terminate()
    except Exception:
        pass
    return buf if len(buf) == FS else None
