"""FastAPI server wrapping the RVC inference engine.

Run directly (`python server.py`) for development, or let `app.py` spawn it
as a subprocess. Listens on 127.0.0.1:8765.

Endpoints:
    GET  /health                     engine ready check
    GET  /heroes                     list of heroes + installed status
    POST /heroes/{id}/install        kick off background download
    GET  /heroes/{id}/install        poll download progress
    POST /convert                    multipart audio + hero_id -> output filename
    GET  /audio/{filename}           stream a wav from outputs/
"""
from __future__ import annotations

# --- noise suppression must precede heavy imports ---
import os
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Allow PyTorch MPS (Apple Silicon) to fall back to CPU for ops not yet
# implemented on MPS (e.g. aten::_weight_norm_interface used by fairseq's
# hubert model). Must be set before `import torch`.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import torch
import functools
torch.load = functools.partial(torch.load, weights_only=False)
try:
    import fairseq
    torch.serialization.add_safe_globals([fairseq.data.dictionary.Dictionary])
except Exception:
    pass

import asyncio
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import requests
import rvc_python
from fastapi import Body, FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from rvc_python.infer import RVCInference

import downloader

ROOT = Path(__file__).parent
OUTPUTS_DIR = ROOT / "outputs"
MODELS_DIR = ROOT / "models"

HOST = "127.0.0.1"
PORT = 8765

COMMUNITY_URL = "https://raw.githubusercontent.com/TrebuchetCode/dota-voice-persona/main/community.json"
COMMUNITY_LOCAL = ROOT / "data" / "community.json"


def _patch_rvc_assets() -> None:
    """Copy our assets/ files into rvc_python's bundled `base_model` dir.

    rvc_python looks for hubert/rmvpe inside its own install path, not the
    project's assets folder. Replaces the brittle path math the old main.py used.
    """
    target_dir = Path(rvc_python.__file__).parent / "base_model"
    source_dir = ROOT / "assets"
    if not source_dir.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for f in source_dir.iterdir():
        target_file = target_dir / f.name
        if not target_file.exists():
            shutil.copy(f, target_file)


class Engine:
    """RVC wrapper. Loads once, caches the active hero so back-to-back
    conversions on the same voice skip the .pth reload."""

    def __init__(self) -> None:
        self.rvc: Optional[RVCInference] = None
        self.loaded_hero: Optional[str] = None
        self.lock = threading.Lock()
        self.ready = False

    def initialize(self) -> None:
        _patch_rvc_assets()
        try:
            self.rvc = RVCInference(device="cuda:0")
        except Exception:
            self.rvc = RVCInference(device="cpu")
        self.ready = True

    def convert(
        self,
        hero: dict,
        input_path: Path,
        output_path: Path,
        transpose: Optional[int] = None,
    ) -> None:
        with self.lock:
            assert self.rvc is not None, "engine not initialized"
            hero_id = hero["id"]
            pth_path = MODELS_DIR / hero_id / f"{hero_id}.pth"
            if not pth_path.exists():
                raise FileNotFoundError(f"Model not installed for {hero['name']}")

            if self.loaded_hero != hero_id:
                self.rvc.load_model(str(pth_path))
                self.loaded_hero = hero_id

            # Explicit `transpose` overrides the hero's default semitone shift.
            self.rvc.f0_up_key = (
                int(transpose) if transpose is not None else hero.get("transpose", 0)
            )
            self.rvc.f0_method = "rmvpe"
            self.rvc.infer_file(str(input_path), str(output_path))


engine = Engine()


# --- background download tracking --------------------------------------------

class DownloadJob:
    """Tracks one hero's installation. Updated from a worker thread, read by
    the polling endpoint."""

    def __init__(self) -> None:
        self.state: str = "downloading"  # downloading | done | error
        self.percent: int = 0
        self.bytes_done: int = 0
        self.bytes_total: Optional[int] = None
        self.error: Optional[str] = None


download_jobs: dict[str, DownloadJob] = {}
download_lock = threading.Lock()


def _run_install(hero: dict, job: DownloadJob) -> None:
    def progress(label: str, done: int, total: Optional[int]) -> None:
        job.bytes_done = done
        job.bytes_total = total
        if total:
            job.percent = min(99, done * 100 // total)

    try:
        downloader.install_hero(hero, on_progress=progress)
        job.state = "done"
        job.percent = 100
    except Exception as exc:
        job.state = "error"
        job.error = str(exc)


# --- FastAPI app -------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUTS_DIR.mkdir(exist_ok=True)
    threading.Thread(target=engine.initialize, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, title="Dota Voice Persona Server")


@app.get("/health")
def health():
    return {"ready": engine.ready}


@app.get("/heroes")
def list_heroes():
    return [
        {
            **h,
            "installed": downloader.hero_status(h) == "installed",
            # Saved user pitch, falling back to the manifest's default.
            "user_transpose": downloader.get_user_transpose(
                h["id"], default=h.get("transpose", 0),
            ),
        }
        for h in downloader.load_manifest()
    ]


@app.post("/heroes/{hero_id}/prefs")
def save_prefs(hero_id: str, transpose: int = Body(..., embed=True)):
    _find_hero(hero_id)  # validate existence
    # Clamp to a sane range so we don't save nonsense.
    transpose = max(-24, min(24, int(transpose)))
    downloader.save_user_transpose(hero_id, transpose)
    return {"status": "saved", "transpose": transpose}


@app.get("/community/browse")
def browse_community():
    """Return community models not already known. Tries remote GitHub first,
    falls back to a local community.json (useful during development)."""
    remote: list[dict] = []
    remote_err: Optional[str] = None
    try:
        r = requests.get(COMMUNITY_URL, timeout=10)
        r.raise_for_status()
        remote = r.json().get("community_heroes", [])
    except Exception as exc:
        remote_err = str(exc)

    if not remote and COMMUNITY_LOCAL.exists():
        try:
            import json as _json
            with open(COMMUNITY_LOCAL) as f:
                remote = _json.load(f).get("community_heroes", [])
        except Exception as exc:
            if remote_err is None:
                remote_err = str(exc)

    if not remote:
        raise HTTPException(502, f"No community source available: {remote_err}")

    known_ids = {h["id"] for h in downloader.load_manifest()}
    return [h for h in remote if h["id"] not in known_ids]


@app.post("/community/register")
def register_community_hero(hero: dict = Body(...)):
    """Persist a community hero dict so it's findable by install/convert flows."""
    required = {"id", "name", "zip_url", "portrait_url"}
    missing = required - set(hero.keys())
    if missing:
        raise HTTPException(400, f"Missing fields: {sorted(missing)}")
    existing_ids = {h["id"] for h in downloader.load_manifest()}
    if hero["id"] in existing_ids:
        raise HTTPException(409, f"Hero {hero['id']} already registered")
    downloader.save_community_hero(hero)
    return {"status": "registered", "id": hero["id"]}


def _find_hero(hero_id: str) -> dict:
    hero = next((h for h in downloader.load_manifest() if h["id"] == hero_id), None)
    if not hero:
        raise HTTPException(404, f"Hero not found: {hero_id}")
    return hero


@app.post("/heroes/{hero_id}/install")
def start_install(hero_id: str):
    hero = _find_hero(hero_id)
    if downloader.hero_status(hero) == "installed":
        return {"state": "done", "percent": 100}
    with download_lock:
        existing = download_jobs.get(hero_id)
        if existing and existing.state == "downloading":
            return {"state": existing.state, "percent": existing.percent}
        job = DownloadJob()
        download_jobs[hero_id] = job
    threading.Thread(target=_run_install, args=(hero, job), daemon=True).start()
    return {"state": "downloading", "percent": 0}


@app.get("/heroes/{hero_id}/install")
def install_status(hero_id: str):
    _find_hero(hero_id)  # validate id
    job = download_jobs.get(hero_id)
    if not job:
        installed = downloader.hero_status(_find_hero(hero_id)) == "installed"
        return {"state": "done" if installed else "idle", "percent": 100 if installed else 0}
    return {
        "state": job.state,
        "percent": job.percent,
        "error": job.error,
    }


@app.post("/convert")
async def convert(
    hero_id: str = Form(...),
    audio: UploadFile = ...,
    transpose: Optional[int] = Form(None),
):
    if not engine.ready:
        raise HTTPException(503, "Engine not ready")
    hero = _find_hero(hero_id)
    if downloader.hero_status(hero) != "installed":
        raise HTTPException(409, f"{hero['name']} model not installed")

    suffix = Path(audio.filename or "in.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(audio.file, tmp)
        input_path = Path(tmp.name)

    output_filename = f"{hero_id}_{os.urandom(4).hex()}.wav"
    output_path = OUTPUTS_DIR / output_filename

    try:
        await asyncio.to_thread(
            engine.convert, hero, input_path, output_path, transpose,
        )
    finally:
        input_path.unlink(missing_ok=True)

    return {"output": output_filename}


@app.get("/audio/{filename}")
def get_audio(filename: str):
    safe = (OUTPUTS_DIR / filename).resolve()
    if not str(safe).startswith(str(OUTPUTS_DIR.resolve())) or not safe.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(safe, media_type="audio/wav", filename=filename)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
