"""Manage the lifetime of the FastAPI server subprocess.

`start_server` spawns `server.py` and registers an atexit hook to terminate
it when the UI exits. `wait_for_engine` polls /health until the RVC engine
reports ready.
"""
from __future__ import annotations

import atexit
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .api_client import SERVER_URL

ROOT = Path(__file__).parent.parent
SERVER_SCRIPT = ROOT / "server.py"


def start_server() -> subprocess.Popen:
    """Launch server.py as a background subprocess. Silent stdout/stderr."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(lambda: proc.terminate())
    return proc


def wait_for_engine(timeout: float = 90.0) -> bool:
    """Poll /health every 400ms, return True once the engine reports ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{SERVER_URL}/health", timeout=1.0)
            if r.status_code == 200 and r.json().get("ready"):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False
