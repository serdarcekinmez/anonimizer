#!/usr/bin/env python3
"""Start the existing sandboxed UI and expose it on WSL loopback, without enabling sandbox networking.

One instance per runtime folder, guarded by a lock that is held for as long as the instance lives.
Files in that folder belong to the lock holder: only the holder writes or removes them.

  python3 tools/launch_wsl.py                  start, or show the address of the running instance
  python3 tools/launch_wsl.py --restart        stop the running instance (after verifying it) and start again
  python3 tools/launch_wsl.py --no-browser     do not open the Windows browser
  python3 tools/launch_wsl.py --no-prompt      never ask on the terminal (the Windows launcher asks itself)
  python3 tools/launch_wsl.py --write-launcher write Start-Anonimizer.cmd for this machine from the template
"""
import datetime
import fcntl
import http.cookiejar
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The runtime folder can be moved for tests, so that a test never touches a running instance's files.
RUNTIME = Path(os.environ.get('ANONIMIZER_DESKTOP_DIR') or ROOT / '.tools' / 'tmp' / 'desktop')
METADATA_WAIT = float(os.environ.get('ANONIMIZER_METADATA_WAIT') or 10)  # seconds to wait for a starting instance
STOP_WAIT = 25  # seconds to wait for a verified instance to stop
EXIT_OK, EXIT_FAILED, EXIT_OTHER_INSTANCE = 0, 1, 3
YES = ('y', 'yes', 'o', 'oui', 'e', 'evet')


def say(*lines):
    print(*lines, sep='\n', flush=True)


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
    say('Open the full address above in your Windows browser.')


_stop_requested = False
_backend = None


def _stop(*_):
    """Ctrl+C, a closed console window (SIGHUP) or a stop request from a newer launcher.

    The UI is told to stop here as well as through the exception: an exception raised by a signal can be
    lost if it lands inside a finaliser, and the instance would then keep running. A repeated signal
    never interrupts the clean-up that the first one started.
    """
    global _stop_requested
    first = not _stop_requested
    _stop_requested = True
    if _backend is not None and _backend.poll() is None:
        try:
            os.killpg(_backend.pid, signal.SIGINT)
        except OSError:
            pass
    if first:
        raise KeyboardInterrupt


def _listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


# ---- session metadata: written and removed by the lock holder only ---------------------------------
def write_metadata(info, payload):
    tmp = info.with_name(f'{info.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, info)  # never a half-written file


def read_metadata(info):
    """The metadata of a live instance, or None when it is missing, unreadable or left by a dead process."""
    try:
        meta = json.loads(info.read_text())
        url, pid = meta['url'], int(meta['pid'])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(url, str) or not os.path.exists(f'/proc/{pid}'):
        return None
    return meta


def remove_own_metadata(info):
    """Remove the session file only if this process wrote it."""
    try:
        if int(json.loads(info.read_text())['pid']) == os.getpid():
            info.unlink()
    except (OSError, ValueError, KeyError, TypeError):
        pass


def keep_metadata(info, payload, stopped):
    """If the session file disappears while the instance runs, put it back."""
    while not stopped.wait(2):
        if not info.exists():
            try:
                write_metadata(info, payload)
            except OSError:
                pass


# ---- the other instance -----------------------------------------------------------------------------
def lock_holders(lock_path):
    """Processes that are verifiably this launcher: same user, this script, this checkout, lock file open."""
    found = []
    for name in os.listdir('/proc'):
        if not name.isdigit() or int(name) == os.getpid():
            continue
        proc = Path('/proc') / name
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if not any(a.endswith(b'launch_wsl.py') for a in args[1:4]):
                continue
            if Path(os.readlink(proc / 'cwd')) != ROOT:
                continue
            if any(os.path.samefile(proc / 'fd' / fd, lock_path) for fd in os.listdir(proc / 'fd')):
                found.append(int(name))
        except OSError:
            continue  # the process ended, or it is not ours to look at
    return found


def try_lock(lock):
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def other_instance(lock, lock_path, info, restart, browser):
    """Called when the lock is held. Returns None once this process holds the lock, else an exit code."""
    meta = None
    deadline = time.monotonic() + METADATA_WAIT
    while True:
        if try_lock(lock):
            return None  # the other instance ended while we waited
        meta = read_metadata(info)
        if meta or time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    if meta and not restart:
        say('Anonimizer is already running:', meta['url'])
        if browser:
            open_browser(meta['url'])
        return EXIT_OK
    holders = lock_holders(lock_path)
    if len(holders) != 1:
        say('Another process holds the Anonimizer lock, and it could not be identified as an Anonimizer launcher',
            f'({len(holders)} matching processes). Nothing was stopped and nothing was deleted.',
            'What to do: close the other "Anonimizer - WSL" window, then start this launcher again.')
        return EXIT_FAILED
    pid = holders[0]
    started = datetime.datetime.fromtimestamp((Path('/proc') / str(pid)).stat().st_mtime).strftime('%H:%M')
    if not restart:
        say(f'An Anonimizer instance is running (process {pid}, started around {started}), but its session file is',
            f'missing after {METADATA_WAIT:g} s, so its address cannot be shown again.',
            'If its browser tab is still open, that tab keeps working.')
        if '--no-prompt' in sys.argv or not sys.stdin.isatty():
            say('To stop that instance and start a new one, run this launcher again with --restart',
                '(the Windows launcher asks you about it now).')
            return EXIT_OTHER_INSTANCE
        answer = input('Stop that instance and start a new one now? The file open in it and any unsaved result are '
                       'lost. Type y and press Enter (anything else leaves it running): ')
        if answer.strip().lower() not in YES:
            say('Left running. Nothing was changed.')
            return EXIT_OTHER_INSTANCE
    say(f'Stopping the running instance (process {pid})...')
    try:
        os.kill(pid, signal.SIGINT)  # the same as Ctrl+C in its window: it stops the UI and removes its files
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + STOP_WAIT
    while time.monotonic() < deadline:
        if try_lock(lock):
            say('Stopped.')
            return None
        time.sleep(0.25)
    say(f'Process {pid} did not stop within {STOP_WAIT} s. Nothing else was done.',
        'What to do: close its "Anonimizer - WSL" window, then start this launcher again.')
    return EXIT_FAILED


def old_session_folders():
    """Session folders of earlier versions, which kept them outside the runtime folder."""
    tmp = ROOT / '.tools' / 'tmp'
    try:
        return sorted(p.name for p in tmp.iterdir() if p.is_dir() and p.name.startswith('anonimizer-ui-'))
    except OSError:
        return []


# ---- Windows launcher ---------------------------------------------------------------------------------
def write_launcher():
    distro = os.environ.get('WSL_DISTRO_NAME')
    if not distro:
        say('WSL_DISTRO_NAME is not set: run this inside the WSL distribution that holds the project.')
        return EXIT_FAILED
    template = (ROOT / 'tools' / 'Start-Anonimizer.cmd.template').read_text()
    text = template.replace('@DISTRO@', distro).replace('@ROOT@', str(ROOT))
    target = ROOT / 'Start-Anonimizer.cmd'
    target.write_bytes(text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
    say(f'Wrote {target.name} for distribution {distro}.',
        'It does not depend on the folder it is started from: it can be copied to the Windows desktop.')
    return EXIT_OK


def main():
    if '--write-launcher' in sys.argv:
        return write_launcher()
    browser = '--no-browser' not in sys.argv
    global _backend
    signal.signal(signal.SIGINT, _stop)  # also when started with SIGINT ignored
    signal.signal(signal.SIGHUP, _stop)
    signal.signal(signal.SIGTERM, _stop)
    os.chdir(ROOT)
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = RUNTIME / 'launcher.lock'
    lock = lock_path.open('a')
    info = RUNTIME / 'session.json'
    if not try_lock(lock):
        code = other_instance(lock, lock_path, info, '--restart' in sys.argv, browser)
        if code is not None:
            return code
    # From here on this process holds the lock: no other instance uses this runtime folder.
    if not shutil.which('socat') or not (ROOT / '.venv/bin/anonimizer').exists():
        say('The existing WSL environment needs .venv/bin/anonimizer and socat. No installation was attempted.')
        return EXIT_FAILED
    bridge_path = RUNTIME / 'ui.sock'
    work = RUNTIME / 'work'  # the UI's temporary files (uploaded copies, runs); removed here whatever happens
    info.unlink(missing_ok=True)  # left by an instance that no longer exists
    bridge_path.unlink(missing_ok=True)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(mode=0o700, exist_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0))
        port = candidate.getsockname()[1]
    children = []
    stopped = threading.Event()
    try:
        inner = ('socat UNIX-LISTEN:"$1",fork,mode=600 TCP4:127.0.0.1:"$2" &\nbridge=$!\n'
                 'trap \'kill "$bridge" 2>/dev/null || true\' EXIT\nTMPDIR="$3" anonimizer ui --no-browser --port "$2"')
        say('Starting Anonimizer in the existing WSL sandbox...')
        backend = subprocess.Popen([str(ROOT / 'tools/sbx'), 'bash', '-c', inner, 'anonimizer-desktop',
                                    str(bridge_path), str(port), str(work)], stdout=subprocess.PIPE, text=True,
                                   start_new_session=True,
                                   preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        children.append(backend)
        _backend = backend
        if _stop_requested:
            raise KeyboardInterrupt
        url = None
        for line in backend.stdout:
            say(line.rstrip())
            if '?token=' in line:
                url = line.strip()
                break
        if _stop_requested:
            raise KeyboardInterrupt
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
        payload = {'url': url, 'pid': os.getpid(), 'port': port}
        write_metadata(info, payload)
        # The helper thread must never receive the stop signals: the kernel may hand a signal to any thread
        # that accepts it, and Python runs the handler only when the main thread wakes up. Blocked there,
        # every Ctrl+C reaches the main thread, which is the one waiting on the UI.
        stop_signals = {signal.SIGINT, signal.SIGHUP, signal.SIGTERM}
        signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)
        try:
            threading.Thread(target=keep_metadata, args=(info, payload, stopped), daemon=True).start()
        finally:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, stop_signals)
        say('', 'Ready. Keep this window open; press Ctrl+C here to stop and remove temporary session files.')
        leftovers = old_session_folders()
        if leftovers:
            say(f'Note: {len(leftovers)} session folder(s) of earlier runs remain in .tools/tmp (anonimizer-ui-*). They can',
                'hold a copy of a file that was picked in the page. When no other Anonimizer or test is running, remove',
                'them with:  rm -rf .tools/tmp/anonimizer-ui-*')
        if browser:
            open_browser(url)
        for line in backend.stdout:
            say(line.rstrip())
        code = backend.wait()
        if _stop_requested:
            raise KeyboardInterrupt
        return code
    except KeyboardInterrupt:
        say('', 'Stopping Anonimizer...')
        return EXIT_OK
    except (OSError, RuntimeError) as exc:
        print(f'Could not start Anonimizer: {exc}', file=sys.stderr, flush=True)
        return EXIT_FAILED
    finally:
        stopped.set()
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=3)
        # Still under the lock: these are this instance's files and nobody else's.
        remove_own_metadata(info)
        bridge_path.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:  # Ctrl+C while waiting for, or asking about, another instance
        raise SystemExit(130) from None
