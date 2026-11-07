#!/usr/bin/env python3
"""cam_calib_gui.py (task #357) — live colour-calibration GUI for the LANCIA virtual camera.
Grades the LIVE mosaic from cam-bridge (:8094) with the current sliders; Save writes
cam_config.json which cam-bridge re-reads within 2 s (no service restart needed).
No root required; preview runs at ~10 fps (grading ~90 ms/frame on this CPU)."""
import http.server, json, socket, threading, time, os, sys, io
import numpy as np
import cam_common as cc

RAW_PORT = int(os.environ.get('CAM_BRIDGE_RAW_PORT', '8094'))
HTTP_PORT = int(os.environ.get('CAM_CALIB_PORT', '8192'))
FRAME_BYTES = cc.STRIDE * cc.H


class RawFeed(threading.Thread):
    """Keeps ONE mosaic stream alive from the cam-bridge hub; exposes the latest frame."""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.buf = None
        self.seq = 0
        self.ok = False

    def run(self):
        acc = bytearray()
        s = None
        while True:
            if s is None:
                try:
                    s = socket.create_connection(('127.0.0.1', RAW_PORT), timeout=5)
                    s.settimeout(10)
                    acc.clear()
                except OSError:
                    time.sleep(1)
                    continue
            try:
                d = s.recv(262144)
            except (socket.timeout, OSError):
                d = b''
            if not d:
                try:
                    s.close()
                except OSError:
                    pass
                s = None
                time.sleep(0.5)
                continue
            acc += d
            if len(acc) >= FRAME_BYTES:
                with self.lock:
                    self.buf = bytes(acc[:FRAME_BYTES])
                    self.seq += 1
                    self.ok = True
                del acc[:FRAME_BYTES]

    def snapshot(self):
        with self.lock:
            return self.buf, self.seq


FEED = RawFeed()
STATE = {'cfg': cc.load_config()}


def grade_png(cfg, buf):
    """mosaic -> graded RGB png bytes (for the preview)."""
    import zlib, struct
    rgb = cc.grade_rgb(cc.mosaic_to_rgb(buf), cfg).astype(np.uint8)

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    H, W, _ = rgb.shape
    rows = b''.join(b'\x00' + rgb[j].tobytes() for j in range(H))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 3)) + chunk(b'IEND', b''))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>LANCIA camera colour calibration</title>
<style>
 body{font-family:system-ui,sans-serif;background:#14161a;color:#e8e8ea;margin:0;padding:18px}
 h1{font-size:19px;margin:0 0 4px} .sub{color:#9aa;font-size:13px;margin-bottom:12px}
 .wrap{display:flex;gap:18px;flex-wrap:wrap}
 .prev{flex:1 1 520px;min-width:360px}
 .prev img{width:100%;border-radius:8px;background:#000;border:1px solid #333}
 .panel{flex:0 0 340px;background:#1b1e24;border:1px solid #2c313a;border-radius:10px;padding:14px 16px}
 .row{margin:9px 0}
 .row label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:2px}
 .row label b{color:#8ec7ff}
 input[type=range]{width:100%}
 .btns{display:flex;gap:8px;margin-top:14px}
 button{flex:1;padding:9px 0;border-radius:7px;border:1px solid #3a4150;background:#262b34;color:#e8e8ea;cursor:pointer;font-size:14px}
 button.primary{background:#2b6cd4;border-color:#2b6cd4}
 button:hover{filter:brightness(1.15)}
 .st{font-size:12px;color:#9a6;color-height:12px;margin-top:8px;min-height:16px}
 .hint{font-size:12px;color:#9aa;line-height:1.45;margin-top:10px;border-top:1px solid #2c313a;padding-top:8px}
</style></head><body>
<h1>LANCIA camera — colour calibration</h1>
<div class="sub">Live preview = exactly what the Virtual Camera streams (same grade pipeline, refreshed in ~1&nbsp;s).</div>
<div class="wrap">
 <div class="prev"><img id="p" src="/preview.png"></div>
 <div class="panel" id="sliders">
  <div class="row"><label>Colour temperature (amber &larr;&rarr; blue) <b id="v_temp"></b></label>
    <input type="range" id="temp" min="-1" max="1" step="0.02"></div>
  <div class="row"><label>Tint (green &larr;&rarr; magenta) <b id="v_tint"></b></label>
    <input type="range" id="tint" min="-1" max="1" step="0.02"></div>
  <div class="row"><label>Red gain (white balance) <b id="v_gain_r"></b></label>
    <input type="range" id="gain_r" min="0.5" max="2.0" step="0.01"></div>
  <div class="row"><label>Green gain <b id="v_gain_g"></b></label>
    <input type="range" id="gain_g" min="0.5" max="2.0" step="0.01"></div>
  <div class="row"><label>Blue gain <b id="v_gain_b"></b></label>
    <input type="range" id="gain_b" min="0.5" max="2.0" step="0.01"></div>
  <div class="row"><label>Gamma (&lt;1 = brighter shadows) <b id="v_gamma"></b></label>
    <input type="range" id="gamma" min="0.35" max="1.4" step="0.01"></div>
  <div class="row"><label>Brightness add <b id="v_brightness"></b></label>
    <input type="range" id="brightness" min="-40" max="60" step="1"></div>
  <div class="row"><label>Contrast <b id="v_contrast"></b></label>
    <input type="range" id="contrast" min="0.6" max="1.8" step="0.01"></div>
  <div class="row"><label>Saturation (0 = grey) <b id="v_saturation"></b></label>
    <input type="range" id="saturation" min="0" max="2.5" step="0.01"></div>
  <div class="btns">
    <button class="primary" onclick="save()">Save &amp; apply</button>
    <button onclick="reset()">Reset defaults</button>
  </div>
  <div class="btns">
    <button onclick="autowb()" title="Measures the current scene (grey-world on the bright half) and sets the three channel gains once">Auto white balance (once)</button>
    <button id="awbbtn" onclick="awbtoggle()" title="Continuously neutralises the colour of the light so whites stay white in any room">Live AWB: off</button>
  </div>
  <div class="st" id="st"></div>
  <div class="hint">Tip: if the picture looks purple, raise <b>green gain</b> until skin and whites look neutral, then fix overall brightness with gamma.
  Save applies to the stream within ~2 s (the camera service reloads the config by itself — no restart needed).
  The dark night look is also limited by sensor exposure (no auto-exposure on Linux): for a brighter image, turn on more light.</div>
 </div>
</div>
<script>
const keys=['temp','tint','gain_r','gain_g','gain_b','gamma','brightness','contrast','saturation'];
function fmt(k,v){return (+v).toFixed(k==='brightness'?0:2);}
let awb=0;
async function load(){const r=await fetch('/config');const c=await r.json();
 for(const k of keys){document.getElementById(k).value=c[k];document.getElementById('v_'+k).textContent=fmt(k,c[k]);}
 awb=c.awb_live||0; paintAwb();}
function paintAwb(){const b=document.getElementById('awbbtn');b.textContent='Live AWB: '+(awb?'ON':'off');
 b.style.borderColor=awb?'#3d9b52':'#3a4150';b.style.background=awb?'#1f3a28':'#262b34';}
async function awbtoggle(){awb=awb?0:1;const b=body();b.awb_live=awb;
 await fetch('/config',{method:'POST',body:JSON.stringify(b)});paintAwb();
 document.getElementById('st').textContent=awb?'Live AWB ON — whites stay white automatically (Save to persist)':'Live AWB off — manual gains active (Save to persist)';}
function body(){const o={};for(const k of keys)o[k]=+document.getElementById(k).value;return o;}
async function push(){for(const k of keys)document.getElementById('v_'+k).textContent=fmt(k,document.getElementById(k).value);
 await fetch('/config',{method:'POST',body:JSON.stringify(body())});}
async function save(){await push();const r=await fetch('/save',{method:'POST',body:JSON.stringify(body())});
 document.getElementById('st').textContent=r.ok?'Saved — applied to the stream':'SAVE FAILED';}
async function reset(){const r=await fetch('/reset',{method:'POST'});const c=await r.json();
 for(const k of keys){document.getElementById(k).value=c[k];document.getElementById('v_'+k).textContent=fmt(k,c[k]);}
 document.getElementById('st').textContent='Defaults restored (not saved yet)';}
for(const k of keys)document.getElementById(k).addEventListener('input',push);
async function autowb(){
 const r=await fetch('/autowb');
 const c=await r.json();
 if(c.error){document.getElementById('st').textContent=c.error;return;}
 for(const k of keys){if(c[k]!==undefined){document.getElementById(k).value=c[k];document.getElementById('v_'+k).textContent=fmt(k,c[k]);}}
 document.getElementById('st').textContent='Auto WB applied (gain '+c.gain_r+' / '+c.gain_g+' / '+c.gain_b+') — press Save & apply to keep it';
}
// preview refresh
function refresh(){const img=document.getElementById('p');img.src='/preview.png?'+Date.now();}
setInterval(refresh,1000);
load();
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/preview.png'):
            buf, seq = FEED.snapshot()
            if buf is None:
                self._send(503, b'no frame yet', 'text/plain')
                return
            t0 = time.time()
            png = grade_png(STATE['cfg'], buf)
            self._send(200, png, 'image/png')
        elif self.path.startswith('/autowb'):
            buf, _seq = FEED.snapshot()
            if buf is None:
                self._send(503, json.dumps({'error': 'no frame yet'}).encode(), 'application/json')
                return
            import numpy as _np
            rgb = cc.mosaic_to_rgb(buf)
            m = rgb.reshape(-1, 3)
            lum = m.mean(1)
            mask = lum > _np.percentile(lum, 60)
            means = m[mask].mean(0)
            if float(means.max()) <= 1.0:
                self._send(200, json.dumps({'error': 'scene too dark to measure'}).encode(), 'application/json')
                return
            grey = means / means.mean()
            gains = _np.clip(1.0 / _np.sqrt(grey), 0.5, 2.0)   # half-strength (stable, no over-green)
            cfg = dict(STATE['cfg'])
            cfg['gain_r'] = round(float(gains[0]), 3)
            cfg['gain_g'] = round(float(gains[1]), 3)
            cfg['gain_b'] = round(float(gains[2]), 3)
            cfg['temp'] = 0.0
            cfg['tint'] = 0.0
            STATE['cfg'] = cfg     # preview immediately; not persisted until Save
            self._send(200, json.dumps(cfg).encode(), 'application/json')
        elif self.path.startswith('/config'):
            # pick up external edits (e.g. a new cam_config.json) without restarting the GUI
            try:
                m = os.path.getmtime(cc.CONFIG_PATH)
            except OSError:
                m = 0
            if m != STATE.get('mtime'):
                STATE['mtime'] = m
                STATE['cfg'] = cc.load_config()
            self._send(200, json.dumps(STATE['cfg']).encode(), 'application/json')
        else:
            self._send(200, PAGE.encode(), 'text/html; charset=utf-8')

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(n) if n else b''
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}
        def coerce(key, val):
            # numeric keys -> float, anything else (e.g. cfa_order string) stays as-is
            return float(val) if isinstance(cc.DEFAULTS[key], (int, float)) and not isinstance(cc.DEFAULTS[key], bool) else val
        if self.path.startswith('/save'):
            cfg = {k: coerce(k, data.get(k, STATE['cfg'][k])) for k in cc.DEFAULTS}
            STATE['cfg'] = cfg
            path = cc.save_config(cfg)
            STATE['mtime'] = os.path.getmtime(path)
            self._send(200, json.dumps({'saved': path}).encode(), 'application/json')
        elif self.path.startswith('/reset'):
            STATE['cfg'] = dict(cc.DEFAULTS)
            self._send(200, json.dumps(STATE['cfg']).encode(), 'application/json')
        elif self.path.startswith('/config'):
            cfg = {k: coerce(k, data.get(k, STATE['cfg'].get(k, cc.DEFAULTS[k]))) for k in cc.DEFAULTS}
            STATE['cfg'] = cfg       # live preview only; not persisted until Save
            self._send(200, b'{"ok":1}', 'application/json')
        else:
            self._send(404, b'{}', 'application/json')


def main():
    FEED.start()
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', HTTP_PORT), Handler)
    sys.stderr.write('cam calib GUI: http://127.0.0.1:%d\n' % HTTP_PORT)
    sys.stderr.flush()
    srv.serve_forever()


if __name__ == '__main__':
    main()
