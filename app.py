"""Flet UI for the Dota Voice Persona app.

Spawns server.py as a subprocess on launch, polls /health until the RVC
engine is ready, then renders the main UI. All conversion + downloads go
through the local FastAPI server.
"""
from __future__ import annotations

import atexit
import io
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import flet as ft
import httpx

ROOT = Path(__file__).parent
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# --- Theme -------------------------------------------------------------------
BG = "#0a0b13"
BG_ELEVATED = "#13141f"
BG_CARD = "#1a1c2a"
ACCENT = "#ff5a1f"          # dota orange
ACCENT_GLOW = "#ff7a3a"
ACCENT_DIM = "#33180c"
TEXT = "#f5f5f7"
TEXT_DIM = "#7a7c8a"
SUCCESS = "#3ddc97"
ERROR = "#ff4d6d"

EASE = ft.AnimationCurve.EASE_OUT
EASE_BACK = ft.AnimationCurve.EASE_OUT_BACK


# --- Server lifecycle --------------------------------------------------------

def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py")],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(lambda: proc.terminate())
    return proc


def wait_for_engine(timeout: float = 60.0) -> bool:
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


# --- API client --------------------------------------------------------------

class Api:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=SERVER_URL, timeout=600.0)

    def heroes(self) -> list[dict]:
        return self.client.get("/heroes").json()

    def start_install(self, hero_id: str) -> dict:
        return self.client.post(f"/heroes/{hero_id}/install").json()

    def install_status(self, hero_id: str) -> dict:
        return self.client.get(f"/heroes/{hero_id}/install").json()

    def convert(self, hero_id: str, audio_path: Path) -> str:
        with open(audio_path, "rb") as f:
            r = self.client.post(
                "/convert",
                data={"hero_id": hero_id},
                files={"audio": (audio_path.name, f, "audio/wav")},
            )
        r.raise_for_status()
        return r.json()["output"]

    def audio_url(self, filename: str) -> str:
        return f"{SERVER_URL}/audio/{filename}"


# --- UI components -----------------------------------------------------------

class HeroCard(ft.Container):
    """Animated hero card. State = installed | available | downloading."""

    def __init__(self, hero: dict, on_select, on_install):
        super().__init__()
        self.hero = hero
        self._on_select = on_select
        self._on_install = on_install
        self.selected = False

        self.portrait = ft.Image(
            src=hero["portrait_url"],
            width=200,
            height=112,
            fit=ft.BoxFit.COVER,
            border_radius=ft.BorderRadius.only(top_left=14, top_right=14),
        )
        self.name_text = ft.Text(hero["name"], color=TEXT, size=14, weight=ft.FontWeight.W_600)
        self.status_text = ft.Text("", color=TEXT_DIM, size=11)
        self.progress = ft.ProgressBar(
            value=0,
            color=ACCENT,
            bgcolor="#262837",
            height=4,
            visible=False,
        )

        self.content = ft.Column(
            [
                ft.Stack([self.portrait]),
                ft.Container(
                    content=ft.Column(
                        [self.name_text, self.status_text, self.progress],
                        spacing=4,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                ),
            ],
            spacing=0,
        )

        self.width = 200
        self.bgcolor = BG_CARD
        self.border_radius = 14
        self.border = ft.Border.all(2, "#262837")
        self.scale = 1.0
        self.animate_scale = ft.Animation(180, EASE_BACK)
        self.animate = ft.Animation(220, EASE)
        self.shadow = None
        self.on_hover = self._handle_hover
        self.on_click = self._handle_click

        self._refresh_state()

    # State
    @property
    def state(self) -> str:
        if self.hero.get("installed"):
            return "installed"
        return "available"

    def _refresh_state(self):
        s = self.state
        if s == "installed":
            self.status_text.value = "Ready"
            self.status_text.color = SUCCESS
            self.portrait.color = None
            self.portrait.color_blend_mode = None
            self.progress.visible = False
        elif s == "available":
            self.status_text.value = "Click to download"
            self.status_text.color = TEXT_DIM
            self.portrait.color = "#80000000"
            self.portrait.color_blend_mode = ft.BlendMode.DARKEN
            self.progress.visible = False
        self._refresh_selection_visual()

    def set_downloading(self, percent: int):
        self.status_text.value = f"Downloading… {percent}%"
        self.status_text.color = ACCENT
        self.progress.value = percent / 100
        self.progress.visible = True
        self.update()

    def mark_installed(self):
        self.hero["installed"] = True
        self._refresh_state()
        self.update()

    def set_selected(self, selected: bool):
        self.selected = selected
        self._refresh_selection_visual()
        self.update()

    def _refresh_selection_visual(self):
        if self.selected:
            self.border = ft.Border.all(2, ACCENT)
            self.shadow = ft.BoxShadow(
                spread_radius=1,
                blur_radius=22,
                color=ACCENT_DIM,
            )
        else:
            self.border = ft.Border.all(2, "#262837")
            self.shadow = None

    def _handle_hover(self, e: ft.HoverEvent):
        self.scale = 1.04 if e.data == "true" else 1.0
        self.update()

    def _handle_click(self, _):
        if self.state == "installed":
            self._on_select(self)
        elif self.state == "available":
            self._on_install(self)


# --- Main app ---------------------------------------------------------------

def main(page: ft.Page):
    page.title = "Dota Voice Persona"
    page.bgcolor = BG
    page.padding = 0
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 980
    page.window.min_height = 640
    page.theme_mode = ft.ThemeMode.DARK
    page.fonts = {}
    page.theme = ft.Theme(font_family="SF Pro Display")

    api = Api()

    # ---- Loading screen ----
    loading_text = ft.Text("Igniting the engine…", color=TEXT_DIM, size=13)
    loading_orb = ft.Container(
        width=72, height=72,
        border_radius=36,
        gradient=ft.RadialGradient(
            center=ft.Alignment(0, 0),
            radius=0.9,
            colors=[ACCENT_GLOW, ACCENT, "#00000000"],
        ),
        animate_scale=ft.Animation(900, ft.AnimationCurve.EASE_IN_OUT),
        scale=1.0,
    )
    loading_view = ft.Container(
        expand=True,
        bgcolor=BG,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            [
                loading_orb,
                ft.Container(height=24),
                ft.Text("DOTA 2 VOICE PERSONA", color=TEXT, size=20, weight=ft.FontWeight.W_700),
                loading_text,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
    )
    page.add(loading_view)

    # Pulse the loading orb
    def pulse_orb():
        toggle = False
        while not getattr(page, "_engine_ready", False):
            toggle = not toggle
            try:
                loading_orb.scale = 1.18 if toggle else 0.92
                loading_orb.update()
            except Exception:
                return
            time.sleep(0.9)

    threading.Thread(target=pulse_orb, daemon=True).start()

    # ---- Boot the engine ----
    def boot():
        ok = wait_for_engine(timeout=90)
        page._engine_ready = True
        if not ok:
            loading_text.value = "Engine failed to start. Check server logs."
            loading_text.color = ERROR
            page.update()
            return
        try:
            heroes = api.heroes()
        except Exception as exc:
            loading_text.value = f"Server unreachable: {exc}"
            loading_text.color = ERROR
            page.update()
            return
        page.controls.clear()
        page.add(build_main_view(page, api, heroes))
        page.update()

    threading.Thread(target=boot, daemon=True).start()


def build_main_view(page: ft.Page, api: Api, heroes: list[dict]) -> ft.Control:
    selected_hero: dict = {}
    selected_card_ref: dict = {}
    input_path_ref: dict = {}
    playback_proc_ref: dict = {}

    # ---- File picker service ----
    file_picker = ft.FilePicker()
    page._services.register_service(file_picker)

    # ---- Right column: status + cast button + result audio ----
    selected_label = ft.Text("Select a hero", color=TEXT_DIM, size=13)
    file_label = ft.Text("No clip uploaded", color=TEXT_DIM, size=13)

    status_text = ft.Text("", color=TEXT_DIM, size=12)
    status_switcher = ft.AnimatedSwitcher(
        content=status_text,
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=220,
    )

    cast_progress = ft.ProgressRing(width=18, height=18, color=TEXT, stroke_width=2, visible=False)
    cast_label = ft.Text("CAST SPELL", color=TEXT, size=14, weight=ft.FontWeight.W_700)
    cast_button_inner = ft.Row(
        [cast_progress, cast_label],
        spacing=10,
        alignment=ft.MainAxisAlignment.CENTER,
        tight=True,
    )
    cast_button = ft.Container(
        content=cast_button_inner,
        padding=ft.Padding.symmetric(horizontal=28, vertical=16),
        border_radius=14,
        bgcolor="#2a2c3c",
        gradient=None,
        animate=ft.Animation(220, EASE),
        animate_scale=ft.Animation(160, EASE_BACK),
        scale=1.0,
        on_hover=None,
        on_click=None,
    )

    result_card = ft.Container(visible=False)

    def set_status(text: str, color: str = TEXT_DIM):
        # Force a new control instance so AnimatedSwitcher transitions
        new = ft.Text(text, color=color, size=12)
        status_switcher.content = new
        status_switcher.update()

    def update_cast_button():
        ready = bool(selected_hero) and bool(input_path_ref.get("path"))
        if ready:
            cast_button.bgcolor = None
            cast_button.gradient = ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[ACCENT, ACCENT_GLOW],
            )
            cast_button.shadow = ft.BoxShadow(blur_radius=24, color=ACCENT_DIM, spread_radius=1)
            cast_button.on_click = run_cast
            cast_button.on_hover = lambda e: (
                setattr(cast_button, "scale", 1.03 if e.data == "true" else 1.0),
                cast_button.update(),
            )
        else:
            cast_button.gradient = None
            cast_button.bgcolor = "#2a2c3c"
            cast_button.shadow = None
            cast_button.on_click = None
            cast_button.on_hover = None
            cast_button.scale = 1.0
        cast_button.update()

    # ---- Hero card callbacks ----
    def on_select(card: HeroCard):
        prev: Optional[HeroCard] = selected_card_ref.get("card")
        if prev is card:
            return
        if prev:
            prev.set_selected(False)
        card.set_selected(True)
        selected_card_ref["card"] = card
        selected_hero.clear()
        selected_hero.update(card.hero)
        selected_label.value = f"Hero: {card.hero['name']}"
        selected_label.color = TEXT
        selected_label.update()
        update_cast_button()

    def on_install(card: HeroCard):
        if card.state != "available":
            return
        try:
            api.start_install(card.hero["id"])
        except Exception as exc:
            set_status(f"Download failed to start: {exc}", ERROR)
            return
        card.set_downloading(0)

        def poll():
            while True:
                try:
                    s = api.install_status(card.hero["id"])
                except Exception:
                    time.sleep(0.5)
                    continue
                if s["state"] == "downloading":
                    card.set_downloading(s.get("percent", 0))
                    time.sleep(0.4)
                elif s["state"] == "done":
                    card.mark_installed()
                    on_select(card)
                    return
                elif s["state"] == "error":
                    card.status_text.value = f"Failed: {s.get('error','')}"
                    card.status_text.color = ERROR
                    card.progress.visible = False
                    card.update()
                    return
                else:
                    return

        threading.Thread(target=poll, daemon=True).start()

    # ---- File picker ----
    async def on_upload_click(_):
        files = await file_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["mp3", "wav", "m4a", "ogg", "flac"],
            allow_multiple=False,
        )
        if not files:
            return
        path = Path(files[0].path)
        input_path_ref["path"] = path
        file_label.value = path.name
        file_label.color = TEXT
        file_label.update()
        update_cast_button()

    upload_zone = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.UPLOAD_FILE_OUTLINED, color=TEXT_DIM, size=28),
                ft.Text("Click to upload a voice clip", color=TEXT, size=13, weight=ft.FontWeight.W_500),
                file_label,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            tight=True,
        ),
        padding=24,
        border_radius=14,
        border=ft.Border.all(1.5, "#262837"),
        bgcolor=BG_ELEVATED,
        animate=ft.Animation(200, EASE),
        on_hover=lambda e: (
            setattr(upload_zone, "border", ft.Border.all(1.5, ACCENT if e.data == "true" else "#262837")),
            upload_zone.update(),
        ),
        on_click=on_upload_click,
    )

    # ---- Cast handler ----
    def run_cast(_):
        if not selected_hero or not input_path_ref.get("path"):
            return
        cast_button.on_click = None
        cast_progress.visible = True
        cast_label.value = "CHANNELING"
        cast_button.update()
        set_status(f"Converting to {selected_hero['name']}…", ACCENT)

        def work():
            try:
                output = api.convert(selected_hero["id"], input_path_ref["path"])
                show_result(output)
                set_status("Spell complete.", SUCCESS)
            except Exception as exc:
                set_status(f"Conversion failed: {exc}", ERROR)
            finally:
                cast_progress.visible = False
                cast_label.value = "CAST SPELL"
                update_cast_button()

        threading.Thread(target=work, daemon=True).start()

    def show_result(output_filename: str):
        output_file = ROOT / "outputs" / output_filename

        def _play(_):
            # Kill any previous playback first
            prev = playback_proc_ref.get("proc")
            if prev and prev.poll() is None:
                prev.terminate()
            if sys.platform == "darwin":
                cmd = ["afplay", str(output_file)]
            elif sys.platform == "win32":
                # `start` returns immediately; use default handler
                cmd = ["cmd", "/c", "start", "", str(output_file)]
            else:
                cmd = ["xdg-open", str(output_file)]
            playback_proc_ref["proc"] = subprocess.Popen(cmd)

        def _pause(_):
            prev = playback_proc_ref.get("proc")
            if prev and prev.poll() is None:
                prev.terminate()

        play_btn = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILL_ROUNDED,
            icon_color=ACCENT,
            icon_size=44,
            tooltip="Play converted audio",
            on_click=_play,
        )
        stop_btn = ft.IconButton(
            icon=ft.Icons.STOP_CIRCLE_OUTLINED,
            icon_color=TEXT_DIM,
            icon_size=32,
            tooltip="Stop",
            on_click=_pause,
        )
        open_btn = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN_OUTLINED,
            icon_color=TEXT_DIM,
            icon_size=28,
            tooltip="Show in Finder",
            on_click=lambda _: _reveal_in_finder(ROOT / "outputs" / output_filename),
        )

        result_card.content = ft.Column(
            [
                ft.Text("RESULT", color=TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                ft.Text(output_filename, color=TEXT, size=13, weight=ft.FontWeight.W_500),
                ft.Row([play_btn, stop_btn, open_btn], spacing=4),
            ],
            spacing=6,
            tight=True,
        )
        result_card.padding = ft.Padding.all(18)
        result_card.border_radius = 14
        result_card.bgcolor = BG_ELEVATED
        result_card.border = ft.Border.all(1, "#262837")
        result_card.visible = True
        result_card.opacity = 0
        result_card.animate_opacity = ft.Animation(280, EASE)
        result_card.update()
        result_card.opacity = 1
        result_card.update()

    # ---- Hero grid ----
    cards = [HeroCard(h, on_select=on_select, on_install=on_install) for h in heroes]

    hero_grid = ft.Row(
        controls=cards,
        spacing=16,
        wrap=True,
        run_spacing=16,
    )

    # ---- Layout ----
    title = ft.ShaderMask(  # type: ignore[attr-defined]
        content=ft.Text("DOTA 2 VOICE PERSONA", size=24, weight=ft.FontWeight.W_800, color=TEXT),
        shader=ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=[ACCENT, ACCENT_GLOW],
        ),
        blend_mode=ft.BlendMode.SRC_IN,
    ) if hasattr(ft, "ShaderMask") else ft.Text(
        "DOTA 2 VOICE PERSONA", size=24, weight=ft.FontWeight.W_800, color=ACCENT
    )

    header = ft.Container(
        padding=ft.Padding.symmetric(horizontal=32, vertical=20),
        content=ft.Row(
            [
                title,
                ft.Container(expand=True),
                ft.Text("v2 · Flet UI", color=TEXT_DIM, size=11),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER,
            end=ft.Alignment.BOTTOM_CENTER,
            colors=[BG_ELEVATED, BG],
        ),
    )

    left_panel = ft.Container(
        expand=True,
        padding=ft.Padding.symmetric(horizontal=32, vertical=8),
        content=ft.Column(
            [
                ft.Text("HEROES", color=TEXT_DIM, size=11, weight=ft.FontWeight.W_700),
                ft.Container(height=8),
                ft.Container(content=hero_grid, expand=True),
            ],
            expand=True,
        ),
    )

    right_panel = ft.Container(
        width=360,
        padding=ft.Padding.all(28),
        bgcolor=BG_ELEVATED,
        content=ft.Column(
            [
                ft.Text("SELECTED", color=TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                selected_label,
                ft.Container(height=18),
                ft.Text("INPUT", color=TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                upload_zone,
                ft.Container(height=22),
                cast_button,
                ft.Container(height=14),
                status_switcher,
                ft.Container(height=18),
                result_card,
            ],
            expand=True,
        ),
    )

    body = ft.Row([left_panel, right_panel], expand=True, spacing=0)

    return ft.Column([header, body], expand=True, spacing=0)


def _reveal_in_finder(path: Path) -> None:
    if not path.exists():
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


if __name__ == "__main__":
    start_server()
    ft.run(main)
