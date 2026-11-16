"""The desktop launcher: one instance per runtime folder, and what happens when its session file is lost.

Every test uses its own runtime folder, so a running instance of the developer is never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAUNCHER = os.path.join(ROOT, "tools", "launch_wsl.py")


def _usable() -> bool:
    if not shutil.which("socat") or not os.path.exists(os.path.join(ROOT, ".venv", "bin", "anonimizer")):
        return False
    return subprocess.run([os.path.join(ROOT, "tools", "sbx"), "true"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _usable(), reason="needs socat, the project environment and the sandbox wrapper")


class Instance:
    """One launcher process. Its output goes to a file, so that reading it never depends on which
    process still holds a pipe open."""

    count = 0

    def __init__(self, runtime, *args, wait="1"):
        Instance.count += 1
        os.makedirs(os.path.dirname(runtime), exist_ok=True)
        self.log_path = f"{runtime}.{Instance.count}.log"
        env = dict(os.environ, ANONIMIZER_DESKTOP_DIR=str(runtime), ANONIMIZER_METADATA_WAIT=wait)
        with open(self.log_path, "w", encoding="utf-8") as log:
            self.proc = subprocess.Popen([sys.executable, LAUNCHER, "--no-browser", *args], cwd=ROOT, env=env,
                                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))

    @property
    def out(self) -> str:
        with open(self.log_path, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def finish(self, timeout=40):
        return self.proc.wait(timeout=timeout)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
        try:
            return self.finish(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
            return "did not stop on SIGINT"


def _wait(condition, seconds=30.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.1)
    return False


def _meta(runtime):
    try:
        with open(os.path.join(runtime, "session.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


@pytest.fixture()
def runtime(tmp_path):
    return str(tmp_path / "desktop")


def test_lost_session_file_is_restored_and_a_second_start_shows_the_address(runtime):
    first = Instance(runtime)
    try:
        assert _wait(lambda: _meta(runtime)), "the instance did not become ready"
        meta = _meta(runtime)
        assert meta["pid"] == first.proc.pid and "?token=" in meta["url"]
        # The session file disappears while the instance runs (this is what happened on 2026-11-16).
        os.unlink(os.path.join(runtime, "session.json"))
        second = Instance(runtime, wait="15")
        assert second.finish() == 0, second.out
        assert "already running" in second.out and meta["url"] in second.out
        assert _meta(runtime) == meta and first.proc.poll() is None  # restored by its owner, which kept running
        # A second start never removes the files of the running instance.
        assert os.path.exists(os.path.join(runtime, "launcher.lock")) and os.path.isdir(os.path.join(runtime, "work"))
    finally:
        assert first.stop() == 0, first.out
    # The owner removed its own files on the way out; the lock file stays and is free again.
    assert sorted(os.listdir(runtime)) == ["launcher.lock"]


def test_unidentified_lock_holder_is_left_alone_after_a_bounded_wait(runtime):
    os.makedirs(runtime)
    lock = os.path.join(runtime, "launcher.lock")
    # Some other process holds the lock and never writes a session file. It is not a launcher.
    holder = subprocess.Popen([sys.executable, "-c",
                               "import fcntl, sys, time; f = open(sys.argv[1], 'a'); fcntl.flock(f, fcntl.LOCK_EX); "
                               "print('held', flush=True); time.sleep(120)", lock], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        began = time.monotonic()
        for args in ((), ("--restart",)):
            second = Instance(runtime, *args, wait="1")
            assert second.finish() == 1, second.out
            assert "could not be identified" in second.out and "Nothing was stopped and nothing was deleted" in second.out
            assert "What to do:" in second.out
        assert time.monotonic() - began < 20  # the wait is bounded
        assert holder.poll() is None and os.path.exists(lock)
    finally:
        holder.kill()
        holder.wait()


def test_restart_stops_the_verified_instance_and_starts_a_new_one(runtime):
    first = Instance(runtime)
    second = None
    try:
        assert _wait(lambda: _meta(runtime)), "the instance did not become ready"
        old = _meta(runtime)
        second = Instance(runtime, "--restart")
        assert _wait(lambda: (_meta(runtime) or old)["pid"] == second.proc.pid), "the new instance did not take over"
        new = _meta(runtime)
        assert new["url"] != old["url"]
        assert first.finish(20) == 0 and "Stopping Anonimizer" in first.out  # it stopped the way Ctrl+C stops it
    finally:
        if second is not None:
            assert second.stop() == 0, second.out
            assert f"Stopping the running instance (process {first.proc.pid})" in second.out
        first.stop()
    assert sorted(os.listdir(runtime)) == ["launcher.lock"]


def test_missing_session_file_without_a_terminal_gives_the_recovery_command(runtime, monkeypatch):
    # The owner's safety net (it rewrites the file) is switched off here, to reach the state an older
    # instance was left in: lock held by a real launcher, no session file.
    first = Instance(runtime)
    try:
        assert _wait(lambda: _meta(runtime)), "the instance did not become ready"
        os.kill(first.proc.pid, signal.SIGSTOP)  # frozen: it cannot restore the file, and it still holds the lock
        os.unlink(os.path.join(runtime, "session.json"))
        second = Instance(runtime, "--no-prompt", wait="1")
        code = second.finish()
        assert code == 3, second.out
        assert f"An Anonimizer instance is running (process {first.proc.pid}" in second.out
        assert "session file is" in second.out and "--restart" in second.out
        assert os.path.isdir(os.path.join(runtime, "work"))  # nothing of the other instance was removed
    finally:
        os.kill(first.proc.pid, signal.SIGCONT)
        assert first.stop() == 0, first.out


def test_windows_launcher_is_generated_from_the_tracked_template(tmp_path, monkeypatch):
    with open(os.path.join(ROOT, "tools", "Start-Anonimizer.cmd.template"), encoding="utf-8") as fh:
        template = fh.read()
    # The template names no machine; the distribution and the path are filled in where it is generated.
    assert "@DISTRO@" in template and "@ROOT@" in template and "/home/" not in template
    lines = [line.strip() for line in template.splitlines() if not line.startswith("rem")]
    # A network folder cannot be cmd.exe's working directory: the script moves to a local one before anything else,
    # reaches WSL by an absolute path, and never uses its own location.
    assert lines[:2] == ["@echo off", 'cd /d "%SystemRoot%" >nul 2>&1']
    assert '"%SystemRoot%\\System32\\wsl.exe"' in template and "%~dp0" not in template and "%CD%" not in template
    # A running instance without a session file is answered by a question, then by --restart; never by a deletion.
    assert 'if "%CODE%"=="3" goto ask' in template and 'set "ARGS=--restart %*"' in template
    assert not any(word in template.lower() for word in ("del ", "rmdir", "taskkill", "--shutdown", "--terminate"))
