"""HTTP client for the local FastAPI backend.

All UI code interacts with the RVC engine through this `Api` class — no
direct imports of server or engine internals.
"""
from __future__ import annotations

from pathlib import Path

import httpx

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


class Api:
    def __init__(self) -> None:
        # Large timeout because /convert does heavy inference synchronously.
        self.client = httpx.Client(base_url=SERVER_URL, timeout=600.0)

    # --- heroes -------------------------------------------------------------
    def heroes(self) -> list[dict]:
        return self.client.get("/heroes").json()

    def start_install(self, hero_id: str) -> dict:
        return self.client.post(f"/heroes/{hero_id}/install").json()

    def install_status(self, hero_id: str) -> dict:
        return self.client.get(f"/heroes/{hero_id}/install").json()

    # --- community ----------------------------------------------------------
    def browse_community(self) -> list[dict]:
        r = self.client.get("/community/browse", timeout=15.0)
        r.raise_for_status()
        return r.json()

    def register_community(self, hero: dict) -> dict:
        r = self.client.post("/community/register", json=hero)
        r.raise_for_status()
        return r.json()

    # --- conversion ---------------------------------------------------------
    def convert(
        self, hero_id: str, audio_path: Path, transpose: int | None = None,
    ) -> str:
        form: dict[str, str] = {"hero_id": hero_id}
        if transpose is not None:
            form["transpose"] = str(int(transpose))
        with open(audio_path, "rb") as f:
            r = self.client.post(
                "/convert",
                data=form,
                files={"audio": (audio_path.name, f, "audio/wav")},
            )
        r.raise_for_status()
        return r.json()["output"]

    def save_transpose(self, hero_id: str, transpose: int) -> dict:
        r = self.client.post(
            f"/heroes/{hero_id}/prefs", json={"transpose": int(transpose)},
        )
        r.raise_for_status()
        return r.json()

    def audio_url(self, filename: str) -> str:
        return f"{SERVER_URL}/audio/{filename}"
