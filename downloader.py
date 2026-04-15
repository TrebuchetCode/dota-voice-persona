"""Hero/asset downloader.

Pure functions for the UI to call (`ensure_base_assets`, `install_hero`, etc.)
plus a thin CLI (`python downloader.py`) for power users / setup.

The CLI now only fetches the always-required engine files by default; hero
models are downloaded on demand from inside the UI.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Callable, Literal, Optional

import requests

ROOT = Path(__file__).parent
ASSETS_DIR = ROOT / "assets"
MODELS_DIR = ROOT / "models"
OUTPUTS_DIR = ROOT / "outputs"
DATA_DIR = ROOT / "data"
MANIFEST = DATA_DIR / "heroes.json"
COMMUNITY_INSTALLED = DATA_DIR / "community_installed.json"
USER_PREFS = DATA_DIR / "user_prefs.json"

BASE_ASSETS = {
    "hubert_base.pt": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt",
    "rmvpe.pt": "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt",
}

# (label, bytes_done, total_bytes_or_None) -> None
ProgressCb = Callable[[str, int, Optional[int]], None]


def ensure_dirs() -> None:
    for d in (ASSETS_DIR, MODELS_DIR, OUTPUTS_DIR):
        d.mkdir(exist_ok=True)


def load_manifest() -> list[dict]:
    """Return the merged list of built-in heroes plus any community heroes
    the user has installed locally. Built-in IDs win on collision."""
    with open(MANIFEST) as f:
        heroes = json.load(f)["heroes"]
    if COMMUNITY_INSTALLED.exists():
        try:
            with open(COMMUNITY_INSTALLED) as f:
                community = json.load(f).get("heroes", [])
        except (json.JSONDecodeError, OSError):
            community = []
        existing_ids = {h["id"] for h in heroes}
        heroes.extend(h for h in community if h["id"] not in existing_ids)
    return heroes


def save_community_hero(hero: dict) -> None:
    """Persist a community hero dict to community_installed.json. Idempotent."""
    if COMMUNITY_INSTALLED.exists():
        try:
            with open(COMMUNITY_INSTALLED) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {"heroes": []}
    else:
        data = {"heroes": []}
    if not any(h["id"] == hero["id"] for h in data.get("heroes", [])):
        data.setdefault("heroes", []).append(hero)
        COMMUNITY_INSTALLED.parent.mkdir(parents=True, exist_ok=True)
        with open(COMMUNITY_INSTALLED, "w") as f:
            json.dump(data, f, indent=2)


def hero_status(hero: dict) -> Literal["installed", "missing"]:
    pth = MODELS_DIR / hero["id"] / f"{hero['id']}.pth"
    return "installed" if pth.exists() else "missing"


# --- user prefs (per-hero pitch memory) --------------------------------------

def _load_prefs() -> dict:
    if not USER_PREFS.exists():
        return {}
    try:
        with open(USER_PREFS) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_user_transpose(hero_id: str, default: int = 0) -> int:
    """Return the last pitch-shift (semitones) the user chose for this hero,
    or `default` (typically heroes.json's own `transpose`) if none."""
    return int(_load_prefs().get("transpose", {}).get(hero_id, default))


def save_user_transpose(hero_id: str, transpose: int) -> None:
    prefs = _load_prefs()
    prefs.setdefault("transpose", {})[hero_id] = int(transpose)
    USER_PREFS.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_PREFS, "w") as f:
        json.dump(prefs, f, indent=2)


def download_file(
    url: str,
    dest: Path,
    label: Optional[str] = None,
    on_progress: Optional[ProgressCb] = None,
) -> None:
    """Download `url` to `dest`, skipping if the file already exists.

    Writes to a `.part` file first then renames, so an interrupted download
    won't be mistaken for a complete one on the next run.
    """
    if dest.exists():
        return
    label = label or dest.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or None
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(label, done, total)
    tmp.replace(dest)


def ensure_base_assets(on_progress: Optional[ProgressCb] = None) -> None:
    """Download hubert+rmvpe if missing. Always required for inference."""
    ensure_dirs()
    for name, url in BASE_ASSETS.items():
        download_file(url, ASSETS_DIR / name, label=f"engine:{name}", on_progress=on_progress)


def install_hero(hero: dict, on_progress: Optional[ProgressCb] = None) -> None:
    """Download + extract a hero's RVC model. Idempotent."""
    if hero_status(hero) == "installed":
        return
    if "zip_url" not in hero:
        raise ValueError(f"Hero {hero['name']} has no zip_url")

    hero_id = hero["id"]
    hero_dir = MODELS_DIR / hero_id
    hero_dir.mkdir(parents=True, exist_ok=True)

    zip_tmp = ROOT / f"{hero_id}_temp.zip"
    download_file(hero["zip_url"], zip_tmp, label=hero["name"], on_progress=on_progress)

    try:
        with zipfile.ZipFile(zip_tmp) as zf:
            zf.extractall(hero_dir)
        # The zip's internal filenames vary; canonicalize to {hero_id}.pth/.index.
        pth_target = hero_dir / f"{hero_id}.pth"
        idx_target = hero_dir / f"{hero_id}.index"
        for f in hero_dir.iterdir():
            if f.suffix == ".pth" and f != pth_target:
                f.replace(pth_target)
            elif f.suffix == ".index" and f != idx_target:
                f.replace(idx_target)
    finally:
        zip_tmp.unlink(missing_ok=True)


# --- CLI ----------------------------------------------------------------------

def _cli_progress(label: str, done: int, total: Optional[int]) -> None:
    mb = done / (1024 * 1024)
    if total:
        pct = done * 100 // total
        total_mb = total / (1024 * 1024)
        print(f"\r  {label}: {pct:>3}%  ({mb:.1f} / {total_mb:.1f} MB)", end="", flush=True)
    else:
        print(f"\r  {label}: {mb:.1f} MB", end="", flush=True)


def cli_main() -> None:
    ensure_dirs()

    print("\n--- Engine Assets ---")
    ensure_base_assets(on_progress=_cli_progress)
    print()

    if not MANIFEST.exists():
        print("X  heroes.json not found")
        return

    heroes = load_manifest()

    print("\n--- Hero Models ---")
    for i, hero in enumerate(heroes, 1):
        tag = "[installed]" if hero_status(hero) == "installed" else "[available]"
        print(f"  {i}. {hero['name']:<20} {tag}")

    print(
        "\nHeroes are normally downloaded inside the app on demand."
        "\nFor bulk download here, enter numbers (e.g. 1,3) or 'all'. Press Enter to skip."
    )
    choice = input("> ").strip().lower()

    selected: list[dict] = []
    if choice == "all":
        selected = heroes
    elif choice:
        try:
            idx = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [heroes[i] for i in idx if 0 <= i < len(heroes)]
        except ValueError:
            print("Invalid input — skipping.")

    for hero in selected:
        try:
            install_hero(hero, on_progress=_cli_progress)
            print(f"\n  OK {hero['name']}")
        except Exception as exc:
            print(f"\n  FAIL {hero['name']}: {exc}")


if __name__ == "__main__":
    cli_main()
