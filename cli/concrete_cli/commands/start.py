"""concrete start — launch local dev services."""

import argparse
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project roots relative to this file's install location
# ---------------------------------------------------------------------------

_CLI_ROOT = Path(__file__).resolve().parents[3]   # .../concrete-sdk/cli → concrete-sdk
_SDK_ROOT  = _CLI_ROOT.parent                      # .../Documents/github
FORUM_DIR  = _SDK_ROOT / "forum"
AGENT_DIR  = _SDK_ROOT / "langgraph-agent"
SEED_DIR   = FORUM_DIR / "firebase" / "seed-data"

# ---------------------------------------------------------------------------
# ANSI colours (graceful degradation on non-TTY)
# ---------------------------------------------------------------------------

_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text

def _blue(s: str)   -> str: return _c("1;34", s)
def _yellow(s: str) -> str: return _c("1;33", s)
def _green(s: str)  -> str: return _c("1;32", s)
def _red(s: str)    -> str: return _c("1;31", s)
def _grey(s: str)   -> str: return _c("90",   s)

# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

_procs: list[subprocess.Popen] = []


def _pipe(stream, prefix: str) -> None:
    try:
        for raw in stream:
            print(f"{prefix} {_grey(raw.decode(errors='replace').rstrip())}", flush=True)
    except Exception:
        pass


def _spawn(cmd: list[str], cwd: Path, label: str, colour_fn) -> subprocess.Popen:
    prefix = colour_fn(f"[{label}]")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    threading.Thread(target=_pipe, args=(proc.stdout, prefix), daemon=True).start()
    _procs.append(proc)
    return proc


def _shutdown(signum=None, frame=None) -> None:
    print(f"\n{_yellow('[dev]')} Shutting down...", flush=True)
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in _procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    print(f"{_green('[dev]')} All processes stopped.")
    sys.exit(0)


def _wait_for_port(host: str, port: int, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    return False


def _require(binary: str, hint: str, fallback_dirs: list[Path] | None = None) -> str:
    path = shutil.which(binary)
    if not path and fallback_dirs:
        for d in fallback_dirs:
            candidate = d / binary
            if candidate.is_file():
                path = str(candidate)
                break
    if not path:
        print(f"{_red('[dev]')} '{binary}' not found. {hint}")
        sys.exit(1)
    return path


# ---------------------------------------------------------------------------
# Service starters
# ---------------------------------------------------------------------------

_FIREBASE_PORTS = [4400, 4001, 5005, 5001, 9099, 8080, 9199, 8085]
_LANGGRAPH_PORTS = [2024]


def _start_firebase(no_seed: bool) -> None:
    firebase = _require("firebase", "Install: npm install -g firebase-tools")

    for port in _FIREBASE_PORTS:
        _free_port(port)

    cmd = [firebase, "emulators:start"]
    if not no_seed and SEED_DIR.exists():
        cmd += [f"--import={SEED_DIR}", f"--export-on-exit={SEED_DIR}"]
    elif not no_seed:
        print(f"{_yellow('[dev]')} Seed data not found at {SEED_DIR}, starting without --import.")

    print(f"{_blue('[dev]')} Starting Firebase emulators → {FORUM_DIR}")
    _spawn(cmd, FORUM_DIR, "firebase", _blue)

    print(f"{_blue('[dev]')} Waiting for Firestore (port 8080)...", flush=True)
    if not _wait_for_port("127.0.0.1", 8080):
        print(f"{_red('[dev]')} Firestore did not start within 60s.")
        _shutdown()
    print(f"{_green('[dev]')} Firestore ready.")


def _free_port(port: int) -> None:
    """Kill any process occupying the given port."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True,
        )
        pids = result.stdout.strip().splitlines()
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], check=False)
                print(f"{_yellow('[dev]')} Killed stale process (pid={pid}) on port {port}.")
            except Exception:
                pass
    except FileNotFoundError:
        pass  # lsof not available


def _start_agent() -> None:
    langgraph = _require(
        "langgraph",
        "Install: pip install langgraph-cli",
        fallback_dirs=[AGENT_DIR / ".venv" / "bin"],
    )
    for port in _LANGGRAPH_PORTS:
        _free_port(port)
    print(f"{_yellow('[dev]')} Starting LangGraph dev server → {AGENT_DIR}")
    _spawn([langgraph, "dev"], AGENT_DIR, "langgraph", _yellow)


def _print_endpoints(firebase: bool, agent: bool) -> None:
    print()
    print(f"{_green('[dev]')} Services running:")
    if firebase:
        print(f"  {_blue('Emulator UI')}   http://127.0.0.1:4001")
        print(f"  {_blue('Firestore')}     http://127.0.0.1:8080")
        print(f"  {_blue('Auth')}          http://127.0.0.1:9099")
        print(f"  {_blue('Functions')}     http://127.0.0.1:5001")
        print(f"  {_blue('Storage')}       http://127.0.0.1:9199")
    if agent:
        print(f"  {_yellow('LangGraph API')} http://127.0.0.1:2024")
        print(f"  {_yellow('LG Studio')}    https://smith.langchain.com/studio")
    print()
    print(_grey("Ctrl+C to stop all services."))
    print()


# ---------------------------------------------------------------------------
# Command entry point
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    run_firebase = args.service in ("emulator", "all")
    run_agent    = args.service in ("agent", "all")
    no_seed      = getattr(args, "no_seed", False)

    if run_firebase:
        _start_firebase(no_seed)
    if run_agent:
        _start_agent()

    _print_endpoints(run_firebase, run_agent)

    # Keep alive — exit if any child dies unexpectedly
    while True:
        for proc in _procs:
            if proc.poll() is not None:
                print(f"{_red('[dev]')} Process (pid={proc.pid}) exited unexpectedly. Shutting down.")
                _shutdown()
        time.sleep(2)
