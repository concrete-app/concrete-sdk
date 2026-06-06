#!/usr/bin/env python3
"""dev.py — Start Firebase emulators (forum) + LangGraph dev server (langgraph-agent).

Usage:
    python dev.py
    python dev.py --no-seed      # skip --import/--export-on-exit
    python dev.py --agent-only   # only start LangGraph
    python dev.py --firebase-only
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
FORUM_DIR = ROOT / "forum"
AGENT_DIR = ROOT / "langgraph-agent"
SEED_DIR = FORUM_DIR / "firebase" / "seed-data"

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
BLUE   = "\033[34m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
RED    = "\033[31m"
GREY   = "\033[90m"


def _prefix(label: str, colour: str) -> str:
    return f"{colour}{BOLD}[{label}]{RESET} "


def _pipe(stream, label: str, colour: str) -> None:
    prefix = _prefix(label, colour)
    try:
        for raw in stream:
            line = raw.decode(errors="replace").rstrip()
            print(f"{prefix}{GREY}{line}{RESET}", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

_procs: list[subprocess.Popen] = []
_threads: list[threading.Thread] = []


def _start(cmd: list[str], cwd: Path, label: str, colour: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for stream in [proc.stdout]:
        t = threading.Thread(target=_pipe, args=(stream, label, colour), daemon=True)
        t.start()
        _threads.append(t)
    _procs.append(proc)
    return proc


def _shutdown(signum=None, frame=None) -> None:
    print(f"\n{YELLOW}{BOLD}[dev]{RESET} Shutting down...", flush=True)
    for proc in _procs:
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in _procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"{GREEN}{BOLD}[dev]{RESET} All processes stopped.", flush=True)
    sys.exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

def _require(name: str, install_hint: str) -> str:
    path = shutil.which(name)
    if not path:
        print(f"{RED}{BOLD}[dev]{RESET} '{name}' not found. {install_hint}")
        sys.exit(1)
    return path


def _wait_for_port(host: str, port: int, timeout: int = 45) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(1)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Start local dev stack")
    parser.add_argument("--no-seed", action="store_true", help="Skip Firebase seed data import/export")
    parser.add_argument("--firebase-only", action="store_true")
    parser.add_argument("--agent-only", action="store_true")
    args = parser.parse_args()

    start_firebase = not args.agent_only
    start_agent = not args.firebase_only

    if not FORUM_DIR.is_dir():
        print(f"{RED}[dev]{RESET} forum directory not found: {FORUM_DIR}")
        sys.exit(1)
    if not AGENT_DIR.is_dir():
        print(f"{RED}[dev]{RESET} langgraph-agent directory not found: {AGENT_DIR}")
        sys.exit(1)

    # ---------------------------------------------------------------------------
    # Firebase emulators
    # ---------------------------------------------------------------------------

    if start_firebase:
        firebase = _require("firebase", "Install with: npm install -g firebase-tools")

        emulator_cmd = [firebase, "emulators:start"]
        if not args.no_seed and SEED_DIR.exists():
            emulator_cmd += [f"--import={SEED_DIR}", f"--export-on-exit={SEED_DIR}"]
        elif not args.no_seed:
            print(f"{YELLOW}[dev]{RESET} Seed data not found at {SEED_DIR}, starting without --import.")

        print(f"{BLUE}{BOLD}[dev]{RESET} Starting Firebase emulators from {FORUM_DIR}")
        _start(emulator_cmd, FORUM_DIR, "firebase", BLUE)

        print(f"{BLUE}[dev]{RESET} Waiting for Firestore on port 8080...", flush=True)
        if not _wait_for_port("127.0.0.1", 8080, timeout=60):
            print(f"{RED}[dev]{RESET} Firestore emulator did not start within 60s.")
            _shutdown()
        print(f"{GREEN}[dev]{RESET} Firestore emulator ready.")

    # ---------------------------------------------------------------------------
    # LangGraph dev server
    # ---------------------------------------------------------------------------

    if start_agent:
        langgraph = _require("langgraph", "Install with: pip install langgraph-cli")

        print(f"{YELLOW}{BOLD}[dev]{RESET} Starting LangGraph dev server from {AGENT_DIR}")
        _start([langgraph, "dev"], AGENT_DIR, "langgraph", YELLOW)

    # ---------------------------------------------------------------------------
    # Print endpoints
    # ---------------------------------------------------------------------------

    print()
    print(f"{GREEN}{BOLD}[dev]{RESET} All services started:")
    if start_firebase:
        print(f"  {BLUE}Firebase Emulator UI{RESET}  → http://127.0.0.1:4001")
        print(f"  {BLUE}Firestore{RESET}             → http://127.0.0.1:8080")
        print(f"  {BLUE}Auth{RESET}                  → http://127.0.0.1:9099")
        print(f"  {BLUE}Functions{RESET}             → http://127.0.0.1:5001")
        print(f"  {BLUE}Storage{RESET}               → http://127.0.0.1:9199")
    if start_agent:
        print(f"  {YELLOW}LangGraph API{RESET}         → http://127.0.0.1:2024")
        print(f"  {YELLOW}LangGraph Studio{RESET}      → https://smith.langchain.com/studio")
    print()
    print(f"{GREY}Press Ctrl+C to stop all services.{RESET}")
    print()

    # Keep alive — exit if any child dies unexpectedly
    while True:
        for proc in _procs:
            if proc.poll() is not None:
                print(f"{RED}[dev]{RESET} A process exited unexpectedly (pid={proc.pid}). Shutting down.")
                _shutdown()
        time.sleep(2)


if __name__ == "__main__":
    main()
