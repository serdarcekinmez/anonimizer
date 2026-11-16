#!/usr/bin/env python3
"""Expose the existing sandboxed UI on WSL loopback, without enabling sandbox networking."""
import fcntl
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.tools' / 'tmp' / 'desktop'


def open_browser(url):
    # WSL interoperability stays outside the application sandbox.
    cmd = shutil.which('cmd.exe')
    if cmd:
        try:
            subprocess.run([cmd, '/d', '/c', 'start', '', url], cwd=os.path.dirname(cmd),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=True)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    print('Open the full address above in your Windows browser.', flush=True)


def _stop(*_):
    # Closing the console window sends SIGHUP: stop the same way as Ctrl+C, so the UI removes its files.
    raise KeyboardInterrupt


def _listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def main():
    signal.signal(signal.SIGINT, signal.default_int_handler)  # also when started with SIGINT ignored
    signal.signal(signal.SIGHUP, _stop)
    signal.signal(signal.SIGTERM, _stop)
    os.chdir(ROOT)
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (RUNTIME / 'launcher.lock').open('a')
    info = RUNTIME / 'session.json'
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            url = json.loads(info.read_text())['url']
        except (OSError, ValueError, KeyError):
            print('Anonimizer is starting. Wait a moment and try again.')
            return 1
        print('Anonimizer is already running:\n' + url, flush=True)
        if '--no-browser' not in sys.argv:
            open_browser(url)
        return 0
    if not shutil.which('socat') or not (ROOT / '.venv/bin/anonimizer').exists():
        print('The existing WSL environment needs .venv/bin/anonimizer and socat. No installation was attempted.')
        return 1
    info.unlink(missing_ok=True)
    bridge_path = RUNTIME / 'ui.sock'
    bridge_path.unlink(missing_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0))
        port = candidate.getsockname()[1]
    children = []
    try:
        inner = 'socat UNIX-LISTEN:"$1",fork,mode=600 TCP4:127.0.0.1:"$2" &\nbridge=$!\ntrap \'kill "$bridge" 2>/dev/null || true\' EXIT\nanonimizer ui --no-browser --port "$2"'
        print('Starting Anonimizer in the existing WSL sandbox...', flush=True)
        backend = subprocess.Popen([str(ROOT / 'tools/sbx'), 'bash', '-c', inner, 'anonimizer-desktop',
                                    str(bridge_path), str(port)], stdout=subprocess.PIPE, text=True, start_new_session=True,
                                   preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        children.append(backend)
        url = None
        for line in backend.stdout:
            print(line.rstrip(), flush=True)
            if '?token=' in line:
                url = line.strip()
                break
        if not url:
            raise RuntimeError('The sandboxed UI could not start. See the error above.')
        # The wrapper normally gives the UI a private network namespace; a loopback-only relay then
        # exposes it on WSL's own 127.0.0.1. Where the wrapper shares the namespace, none is needed.
        if not _listening(port):
            children.append(subprocess.Popen(['socat', f'TCP4-LISTEN:{port},bind=127.0.0.1,reuseaddr,fork',
                                              f'UNIX-CONNECT:{bridge_path}'], start_new_session=True))
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for _ in range(40):
            if any(child.poll() is not None for child in children):
                raise RuntimeError('The local listener stopped during startup.')
            try:
                with client.open(url, timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('The UI did not become ready. Restart the launcher.')
        info.write_text(json.dumps({'url': url, 'pid': os.getpid(), 'port': port}))
        print('\nReady. Keep this window open; press Ctrl+C here to stop and remove temporary session files.', flush=True)
        if '--no-browser' not in sys.argv:
            open_browser(url)
        for line in backend.stdout:
            print(line.rstrip(), flush=True)
        return backend.wait()
    except KeyboardInterrupt:
        print('\nStopping Anonimizer...', flush=True)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f'Could not start Anonimizer: {exc}', file=sys.stderr, flush=True)
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=3)
        info.unlink(missing_ok=True)
        bridge_path.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
