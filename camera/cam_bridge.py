#!/usr/bin/env python3
"""cam_bridge.py v2 (tasks #341 + #357) — IPU6 BA10 mosaic -> shared grade (cam_common) -> YUY2 TCP.
Also serves the RAW mosaic over TCP :8094 so the calibration GUI grades the SAME frames live.
Grading config lives in cam_config.json (written by cam_calib_gui.py) and is re-read on file change."""
import socket, subprocess, sys, os, time, threading
import numpy as np
import cam_common as cc

PORT = int(os.environ.get('CAM_BRIDGE_PORT', '8092'))
RAW_PORT = int(os.environ.get('CAM_BRIDGE_RAW_PORT', '8094'))
FPS = float(os.environ.get('CAM_BRIDGE_FPS', '15'))


class MosaicHub:
    """Broadcasts the latest mosaic buffer to any local consumer (the calib GUI)."""

    def __init__(self, port):
        self.port = port
        self.latest = None
        self.lock = threading.Lock()
        self.clients = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', self.port))
        srv.listen(4)
        sys.stderr.write('mosaic hub on %d\n' % self.port)
        sys.stderr.flush()
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with self.lock:
                if self.latest is not None:
                    try:
                        c.sendall(self.latest)
                    except OSError:
                        c.close()
                        continue
                self.clients.append(c)

    def publish(self, buf):
        with self.lock:
            self.latest = buf
            dead = []
            for c in self.clients:
                try:
                    c.sendall(buf)
                except OSError:
                    dead.append(c)
            for c in dead:
                self.clients.remove(c)
                try:
                    c.close()
                except OSError:
                    pass


class ConsumerGate:
    """LED gate (task #358): capture runs ONLY while camera software actually uses the camera.

    A consumer = (a) a USER process with /dev/video0 open (direct V4L2 apps: kamoso, ffmpeg,
    browsers' fallback) — root processes are invisible to us, which conveniently excludes the
    writer itself — or (b) an active PipeWire video stream (wpctl 'Streams' shows it), which
    covers portal/Meet/cheese-style apps. Idle for IDLE_S -> capture stops -> sensor STREAMOFF
    -> privacy LED goes dark (measured: LED follows STREAMON exactly, 1/0/1)."""

    IDLE_S = 6.0

    def __init__(self):
        self.last_seen = time.time()
        self.active = False   # starts OFF: no consumer known yet (avoids startup LED flicker)
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _consumers():
        found = False
        # (a) user-visible openers of /dev/video0
        try:
            for pid in os.listdir('/proc'):
                if not pid.isdigit():
                    continue
                fd_dir = '/proc/%s/fd' % pid
                try:
                    for fd in os.listdir(fd_dir):
                        try:
                            if os.readlink(os.path.join(fd_dir, fd)) == '/dev/video0':
                                found = True
                                break
                        except OSError:
                            pass
                except OSError:
                    continue
                if found:
                    break
        except OSError:
            pass
        if found:
            return True
        # (b) PipeWire video stream active?
        try:
            out = subprocess.run(['wpctl', 'status'], capture_output=True, text=True,
                                 timeout=2,
                                 env={**os.environ,
                                      'XDG_RUNTIME_DIR': os.environ.get('XDG_RUNTIME_DIR', '/run/user/1000'),
                                      'DBUS_SESSION_BUS_ADDRESS': os.environ.get('DBUS_SESSION_BUS_ADDRESS',
                                                                                 'unix:path=/run/user/1000/bus')}).stdout
            tail = out.split('Streams:')[-1] if 'Streams:' in out else ''
            video_part = tail.split('\nVideo')[0]
            if '*' in video_part:
                return True
        except Exception:
            pass
        return False

    def _loop(self):
        while True:
            if self._consumers():
                self.last_seen = time.time()
                self.active = True
            else:
                self.active = (time.time() - self.last_seen) < self.IDLE_S
            time.sleep(1.0)


def main():
    gate = ConsumerGate()
    cfg = cc.load_config()
    cc.set_cfa(cfg.get('cfa_order', 'RGGB'))
    cfg_mtime = os.path.getmtime(cc.CONFIG_PATH) if os.path.exists(cc.CONFIG_PATH) else 0
    last_cfg_check = 0.0
    hub = MosaicHub(RAW_PORT)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', PORT))
    srv.listen(1)
    sys.stderr.write('cam_bridge listening on %d (raw hub %d, LED gate on)\n' % (PORT, RAW_PORT))
    sys.stderr.flush()
    conn = None
    interval = 1.0 / FPS
    t0 = time.time()
    n = 0
    it = None
    led = 'unknown'
    while True:
        if not gate.active:
            # still honour config edits while idle so the next stream starts with fresh values
            if time.time() - last_cfg_check > 2.0:
                last_cfg_check = time.time()
                try:
                    m = os.path.getmtime(cc.CONFIG_PATH)
                except OSError:
                    m = 0
                if m != cfg_mtime:
                    cfg_mtime = m
                    cfg = cc.load_config()
            if it is not None:
                # stop the reader child: v4l2-ctl exits -> STREAMOFF -> LED off
                it.close() if hasattr(it, 'close') else None
                it = None
                sys.stderr.write('consumer idle -> capture STOPPED (LED off)\n')
                sys.stderr.flush()
                led = 'off'
            time.sleep(0.5)
            continue
        if it is None:
            it = cc.read_mosaic()
            sys.stderr.write('consumer present -> capture STARTED (LED on)\n')
            sys.stderr.flush()
            led = 'on'
        try:
            buf = next(it)
        except StopIteration:
            it = None
            time.sleep(0.3)
            continue
        now = time.time()
        if now - last_cfg_check > 2.0:
            last_cfg_check = now
            try:
                m = os.path.getmtime(cc.CONFIG_PATH)
            except OSError:
                m = 0
            if m != cfg_mtime:
                cfg_mtime = m
                cfg = cc.load_config()
                cc.set_cfa(cfg.get('cfa_order', 'RGGB'))
                sys.stderr.write('config reloaded: %s\n' % cfg)
                sys.stderr.flush()
        frame = cc.process_frame(buf, cfg)
        n += 1
        if n % 60 == 1:
            sys.stderr.write('frame %.0f ms\n' % ((time.time() - t0) * 1000))
            t0 = time.time()
        hub.publish(buf)
        if conn is None:
            srv.settimeout(5)
            try:
                conn, addr = srv.accept()
                sys.stderr.write('client %s\n' % str(addr))
                sys.stderr.flush()
            except socket.timeout:
                pass
        if conn is not None:
            try:
                conn.sendall(frame)
            except (BrokenPipeError, ConnectionResetError, OSError):
                try:
                    conn.close()
                except OSError:
                    pass
                conn = None
        t0 += interval
        d = t0 - time.time()
        if d > 0:
            time.sleep(d)
        elif d < -1:
            t0 = time.time()


if __name__ == '__main__':
    main()
