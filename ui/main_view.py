"""Main view — the post-boot window.

Responsibilities:
    - Start the backend, wait for /health
    - Fetch the hero list and render the main layout
    - Wire up hero-card clicks -> download / select flow
    - Handle file upload, cast (conversion), and result rendering

Most of the cognitive weight is in `_wire_main_view`. Helper builder
functions at the bottom construct the repeatable UI chunks.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import flet as ft

from . import theme as T
from .api_client import Api
from .audio_player import AudioPlayer
from .hero_card import HeroCard
from .loading_view import LoadingView
from .result_row import build_result_row
from .server_lifecycle import wait_for_engine

ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = ROOT / "outputs"


# --- Entry point -------------------------------------------------------------

def main(page: ft.Page) -> None:
    """Flet entry. Shows loading splash, boots server, hands off to main view."""
    _configure_page(page)
    api = Api()

    # Register the FilePicker synchronously in this main() callback — Flet
    # binds service controls to the page during a main-thread update. Doing
    # this from the background boot() thread doesn't reliably propagate the
    # page ref, leaving `fp.page` as None at click time.
    file_picker = ft.FilePicker()
    page.services.append(file_picker)
    page.update()

    loading = LoadingView()
    loading.mount(page)

    def boot() -> None:
        ok = wait_for_engine(timeout=90)
        loading.stop()
        if not ok:
            loading.show_error("Engine failed to start. Check server logs.")
            return
        try:
            heroes = api.heroes()
        except Exception as exc:
            loading.show_error(f"Server unreachable: {exc}")
            return
        page.controls.clear()
        view = _wire_main_view(page, api, heroes, file_picker)
        page.add(view)
        page.update()

    threading.Thread(target=boot, daemon=True).start()


def _configure_page(page: ft.Page) -> None:
    page.title = "Dota Voice Persona"
    page.bgcolor = T.BG
    page.padding = 0
    page.window.width = 1180
    page.window.height = 760
    page.window.min_width = 980
    page.window.min_height = 640
    page.theme_mode = ft.ThemeMode.DARK
    # Pull the Cinzel display font from Google Fonts. Body UI stays on the
    # platform default (SF Pro on macOS). Cinzel is explicitly requested per
    # Text via font_family= where we want the epic game-like look.
    page.fonts = dict(T.FONT_SOURCES)
    page.theme = ft.Theme(font_family=T.FONT_UI)


# --- Main view ---------------------------------------------------------------

def _wire_main_view(
    page: ft.Page,
    api: Api,
    heroes: list[dict],
    file_picker: ft.FilePicker,
) -> ft.Control:
    """Build + wire the primary UI. Returns a single Control to add to the page."""

    # === Shared state ========================================================
    selected_hero: dict = {}
    selected_card_ref: dict = {}     # {"card": HeroCard} — current selection
    input_path_ref: dict = {}        # {"path": Path} — uploaded clip
    hero_results = _scan_outputs_by_hero()   # hero_id -> [output_filename]

    # Shared audio player — one global player means clicking play on a new
    # row cleanly stops the previous one. Uses the OS's native audio player
    # under the hood (see ui/audio_player.py).
    audio_player = AudioPlayer()

    # file_picker is created + registered by main() in the Flet callback
    # thread so its page ref is properly bound; we just hook up its callback.

    # === Right-panel controls ================================================
    selected_portrait = ft.Image(
        src="", width=64, height=64, fit=ft.BoxFit.COVER,
        border_radius=10, visible=False,
    )
    selected_name = ft.Text(
        "Select a hero",
        color=T.TEXT_DIM,
        size=18,
        weight=ft.FontWeight.W_700,
        font_family=T.FONT_DISPLAY,
    )
    selected_tag = ft.Text(
        "No voice chosen",
        color=T.TEXT_DIM,
        size=11,
        italic=True,
    )
    selected_card = ft.Container(
        content=ft.Row(
            [
                selected_portrait,
                ft.Column(
                    [selected_name, selected_tag],
                    spacing=2,
                    tight=True,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.all(12),
        border_radius=14,
        bgcolor=T.BG_CARD,
        border=ft.Border.all(1, T.BORDER),
        animate=ft.Animation(260, T.EASE),
        animate_opacity=ft.Animation(260, T.EASE),
        opacity=0.75,
    )
    file_label = ft.Text("No clip uploaded", color=T.TEXT_DIM, size=13)
    status_switcher = ft.AnimatedSwitcher(
        content=ft.Text("", color=T.TEXT_DIM, size=12),
        transition=ft.AnimatedSwitcherTransition.FADE,
        duration=220,
    )
    cast_progress = ft.ProgressRing(
        width=18, height=18, color=T.TEXT, stroke_width=2, visible=False,
    )
    cast_label = ft.Text(
        "CAST SPELL", color=T.TEXT, size=14, weight=ft.FontWeight.W_700,
    )
    cast_button = _build_cast_button(cast_progress, cast_label)
    upload_zone = _build_upload_zone(file_label)
    # expand=True so its inner scroll=AUTO column has a bounded height.
    result_card = ft.Container(visible=False, expand=True)

    # === Pitch controls ======================================================
    # Semitone shift passed into the server on each cast and persisted per
    # hero so the user's last setting comes back when they re-select.
    pitch_state = {"transpose": 0, "hero_default": 0}
    pitch_value_label = ft.Text(
        "+0",
        color=T.TEXT,
        size=13,
        weight=ft.FontWeight.W_600,
        width=36,
        text_align=ft.TextAlign.RIGHT,
    )
    pitch_slider = ft.Slider(
        min=-12, max=12, divisions=24, value=0,
        active_color=T.ACCENT,
        inactive_color=T.BORDER,
        thumb_color=T.ACCENT,
        expand=True,
    )
    pitch_reset_btn = ft.TextButton(
        text="Reset",
        style=ft.ButtonStyle(color=T.TEXT_DIM),
    )

    # === Helper: status animation ============================================
    def set_status(text: str, color: str = T.TEXT_DIM) -> None:
        status_switcher.content = ft.Text(text, color=color, size=12)
        status_switcher.update()

    # === Helper: cast button enable/disable ==================================
    def update_cast_button() -> None:
        ready = bool(selected_hero) and bool(input_path_ref.get("path"))
        if ready:
            cast_button.bgcolor = None
            cast_button.gradient = ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[T.ACCENT, T.ACCENT_GLOW],
            )
            cast_button.shadow = ft.BoxShadow(
                blur_radius=24, color=T.ACCENT_DIM, spread_radius=1,
            )
            cast_button.on_click = run_cast
            cast_button.on_hover = _hover_scale(cast_button, 1.03)
        else:
            cast_button.gradient = None
            cast_button.bgcolor = T.BORDER_INACTIVE
            cast_button.shadow = None
            cast_button.on_click = None
            cast_button.on_hover = None
            cast_button.scale = 1.0
        cast_button.update()

    # === Helper: re-render the result card for the selected hero =============
    def refresh_results() -> None:
        # Stop any active playback since its row is about to be unmounted.
        audio_player.stop()

        hero_id = selected_hero.get("id")
        files = hero_results.get(hero_id, []) if hero_id else []

        if not files:
            result_card.visible = False
            result_card.update()
            return

        rows = [
            build_result_row(
                f,
                outputs_dir=OUTPUTS_DIR,
                player=audio_player,
                page=page,
            )
            for f in reversed(files)  # newest first
        ]

        result_card.content = ft.Column(
            [
                ft.Text("RESULTS", color=T.TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                *rows,
            ],
            spacing=6,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )
        result_card.padding = ft.Padding.all(18)
        result_card.border_radius = 14
        result_card.bgcolor = T.BG_ELEVATED
        result_card.border = ft.Border.all(1, T.BORDER)
        result_card.visible = True
        result_card.update()

    # === Pitch slider wiring =================================================
    def _apply_pitch(v: int, *, save: bool = False) -> None:
        pitch_state["transpose"] = v
        pitch_slider.value = v
        pitch_value_label.value = f"{v:+d}"
        try:
            pitch_slider.update()
            pitch_value_label.update()
        except Exception:
            pass
        if save:
            hero_id = selected_hero.get("id")
            if hero_id:
                try:
                    api.save_transpose(hero_id, v)
                except Exception:
                    pass  # pref save is best-effort

    def on_pitch_change(e) -> None:
        _apply_pitch(int(float(e.data)), save=True)

    def on_pitch_reset(_) -> None:
        _apply_pitch(pitch_state["hero_default"], save=True)

    pitch_slider.on_change_end = on_pitch_change
    pitch_reset_btn.on_click = on_pitch_reset

    # === Hero card callbacks =================================================
    def on_select(card: HeroCard) -> None:
        prev: Optional[HeroCard] = selected_card_ref.get("card")
        if prev is card:
            return
        if prev:
            prev.set_selected(False)
        card.set_selected(True)
        selected_card_ref["card"] = card
        selected_hero.clear()
        selected_hero.update(card.hero)
        # Fill the portrait card — portrait + name + author/ready tag.
        selected_portrait.src = card.hero.get("portrait_url", "")
        selected_portrait.visible = True
        selected_name.value = card.hero["name"]
        selected_name.color = T.TEXT
        author = card.hero.get("author")
        selected_tag.value = f"by {author}" if author else "Ready to cast"
        selected_tag.color = T.ACCENT if not author else T.TEXT_DIM
        selected_card.opacity = 1.0
        selected_card.border = ft.Border.all(1, T.ACCENT_DIM)
        selected_card.update()
        # Load pitch: saved pref > hero's manifest default > 0
        hero_default = int(card.hero.get("transpose", 0))
        pitch_state["hero_default"] = hero_default
        saved = int(card.hero.get("user_transpose", hero_default))
        _apply_pitch(saved, save=False)
        update_cast_button()
        refresh_results()

    def on_install(card: HeroCard) -> None:
        _run_install_with_polling(page, card, api, set_status, on_done=on_select)

    # === File upload =========================================================
    async def on_upload_click(_) -> None:
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
        file_label.color = T.TEXT
        file_label.update()
        update_cast_button()

    upload_zone.on_click = on_upload_click

    # === Cast handler ========================================================
    def _cast_channel_pulse() -> None:
        """Runs on a background thread while conversion is in flight.
        Pulses the cast button between slightly-larger and slightly-smaller
        so the "channeling" state feels alive, not frozen."""
        toggle = False
        while cast_progress.visible:
            toggle = not toggle
            try:
                cast_button.scale = 1.04 if toggle else 0.98
                cast_button.shadow = ft.BoxShadow(
                    blur_radius=32 if toggle else 18,
                    color=T.ACCENT_GLOW if toggle else T.ACCENT_DIM,
                    spread_radius=2 if toggle else 1,
                )
                cast_button.update()
            except Exception:
                return
            time.sleep(0.6)

    def _cast_success_burst() -> None:
        """One-shot celebration: quick zoom + bright glow, then settle."""
        try:
            cast_button.scale = 1.14
            cast_button.shadow = ft.BoxShadow(
                blur_radius=40, color=T.SUCCESS, spread_radius=3,
            )
            cast_button.gradient = ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[T.SUCCESS, T.ACCENT_GLOW],
            )
            cast_button.update()
        except Exception:
            return

        def settle() -> None:
            try:
                cast_button.scale = 1.0
                update_cast_button()
            except Exception:
                pass

        threading.Timer(0.55, settle).start()

    def run_cast(_) -> None:
        if not selected_hero or not input_path_ref.get("path"):
            return
        # Click flash: quick scale pop to telegraph the action.
        cast_button.scale = 1.1
        cast_button.update()

        cast_button.on_click = None
        cast_button.on_hover = None
        cast_progress.visible = True
        cast_label.value = "CHANNELING"
        cast_button.update()
        set_status(f"Converting to {selected_hero['name']}…", T.ACCENT)
        page.run_thread(_cast_channel_pulse)

        def work() -> None:
            try:
                output = api.convert(
                    selected_hero["id"],
                    input_path_ref["path"],
                    transpose=pitch_state["transpose"],
                )
                hero_id = selected_hero.get("id")
                if hero_id:
                    hero_results.setdefault(hero_id, []).append(output)
                refresh_results()
                set_status("Spell complete.", T.SUCCESS)
                cast_progress.visible = False
                cast_label.value = "CAST SPELL"
                _cast_success_burst()
            except Exception as exc:
                set_status(f"Conversion failed: {exc}", T.ERROR)
                cast_progress.visible = False
                cast_label.value = "CAST SPELL"
                update_cast_button()

        page.run_thread(work)

    # === Hero + community grids ==============================================
    cards = [HeroCard(h, on_select=on_select, on_install=on_install) for h in heroes]
    hero_cards_by_id: dict[str, HeroCard] = {c.hero["id"]: c for c in cards}
    hero_grid = ft.Row(controls=cards, spacing=16, wrap=True, run_spacing=16)

    community_grid = ft.Row(controls=[], spacing=16, wrap=True, run_spacing=16)
    community_status = ft.Text("", color=T.TEXT_DIM, size=12)
    community_loaded = {"done": False}

    def on_community_install(card: HeroCard) -> None:
        _install_community_hero(
            page, card, api, set_status,
            on_installed=lambda c: _mirror_into_heroes_tab(
                c, hero_cards_by_id, cards, hero_grid, on_select, on_install,
            ),
            then_select=on_select,
        )

    def refresh_community() -> None:
        _load_community(
            page, api, community_grid, community_status,
            on_select=on_select, on_install=on_community_install,
            loaded_flag=community_loaded,
        )

    # === Tab navigation ======================================================
    panel_content, heroes_tab_btn, community_tab_btn = _build_tabs(
        hero_grid, community_grid, community_status,
        on_switch_to_community=lambda: (
            refresh_community() if not community_loaded["done"] else None
        ),
    )

    # === Final layout ========================================================
    return ft.Column(
        [
            _build_header(heroes_tab_btn, community_tab_btn),
            ft.Row(
                [
                    ft.Container(
                        expand=True,
                        padding=ft.Padding.symmetric(horizontal=32, vertical=8),
                        content=panel_content,
                    ),
                    _build_right_panel(
                        selected_card, upload_zone,
                        pitch_slider, pitch_value_label, pitch_reset_btn,
                        cast_button, status_switcher, result_card,
                    ),
                ],
                expand=True,
                spacing=0,
            ),
        ],
        expand=True,
        spacing=0,
    )


# === Right-panel builders ====================================================

def _build_cast_button(progress: ft.ProgressRing, label: ft.Text) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [progress, label],
            spacing=10,
            alignment=ft.MainAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.Padding.symmetric(horizontal=28, vertical=16),
        border_radius=14,
        bgcolor=T.BORDER_INACTIVE,
        animate=ft.Animation(220, T.EASE),
        animate_scale=ft.Animation(160, T.EASE_BACK),
        scale=1.0,
    )


def _build_upload_zone(file_label: ft.Text) -> ft.Container:
    zone = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.UPLOAD_FILE_OUTLINED, color=T.TEXT_DIM, size=28),
                ft.Text(
                    "Click to upload a voice clip",
                    color=T.TEXT, size=13, weight=ft.FontWeight.W_500,
                ),
                file_label,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            tight=True,
        ),
        padding=24,
        border_radius=14,
        border=ft.Border.all(1.5, T.BORDER),
        bgcolor=T.BG_ELEVATED,
        animate=ft.Animation(200, T.EASE),
    )

    def on_hover(e: ft.HoverEvent) -> None:
        color = T.ACCENT if e.data == "true" else T.BORDER
        zone.border = ft.Border.all(1.5, color)
        zone.update()

    zone.on_hover = on_hover
    return zone


def _build_right_panel(
    selected_card: ft.Container,
    upload_zone: ft.Container,
    pitch_slider: ft.Slider,
    pitch_value_label: ft.Text,
    pitch_reset_btn: ft.TextButton,
    cast_button: ft.Container,
    status_switcher: ft.AnimatedSwitcher,
    result_card: ft.Container,
) -> ft.Container:
    pitch_section = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("PITCH", color=T.TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                    ft.Container(expand=True),
                    pitch_value_label,
                    pitch_reset_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            pitch_slider,
        ],
        spacing=0,
        tight=True,
    )
    return ft.Container(
        width=360,
        padding=ft.Padding.all(28),
        bgcolor=T.BG_ELEVATED,
        content=ft.Column(
            [
                ft.Text("SELECTED", color=T.TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                ft.Container(height=6),
                selected_card,
                ft.Container(height=18),
                ft.Text("INPUT", color=T.TEXT_DIM, size=10, weight=ft.FontWeight.W_700),
                upload_zone,
                ft.Container(height=14),
                pitch_section,
                ft.Container(height=14),
                cast_button,
                ft.Container(height=14),
                status_switcher,
                ft.Container(height=18),
                result_card,
            ],
            expand=True,
        ),
    )


# === Header + tabs ===========================================================

def _build_header(heroes_tab_btn: ft.Control, community_tab_btn: ft.Control) -> ft.Container:
    title_text = ft.Text(
        "DOTA 2 VOICE PERSONA",
        size=26,
        weight=ft.FontWeight.W_900,
        color=T.TEXT,
        font_family=T.FONT_DISPLAY,
    )
    if hasattr(ft, "ShaderMask"):
        title: ft.Control = ft.ShaderMask(  # type: ignore[attr-defined]
            content=title_text,
            shader=ft.LinearGradient(
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
                colors=[T.ACCENT, T.ACCENT_GLOW],
            ),
            blend_mode=ft.BlendMode.SRC_IN,
        )
    else:
        title = ft.Text(
            "DOTA 2 VOICE PERSONA",
            size=26,
            weight=ft.FontWeight.W_900,
            color=T.ACCENT,
            font_family=T.FONT_DISPLAY,
        )

    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=32, vertical=20),
        content=ft.Row(
            [
                title,
                ft.Container(width=32),
                ft.Row([heroes_tab_btn, community_tab_btn], spacing=8),
                ft.Container(expand=True),
                ft.Text("v2 · Flet UI", color=T.TEXT_DIM, size=11),
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_CENTER,
            end=ft.Alignment.BOTTOM_CENTER,
            colors=[T.BG_ELEVATED, T.BG],
        ),
    )


def _build_tabs(
    hero_grid: ft.Row,
    community_grid: ft.Row,
    community_status: ft.Text,
    on_switch_to_community,
) -> tuple[ft.Container, ft.Container, ft.Container]:
    # Each grid is a wrapping Row — the outer Column gives it vertical scroll
    # so more rows than fit on screen become scrollable.
    heroes_content = ft.Column(
        [
            ft.Text("HEROES", color=T.TEXT_DIM, size=11, weight=ft.FontWeight.W_700),
            ft.Container(height=8),
            ft.Column(
                [hero_grid],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
        ],
        expand=True,
    )
    community_content = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("COMMUNITY", color=T.TEXT_DIM, size=11, weight=ft.FontWeight.W_700),
                    ft.Container(expand=True),
                    community_status,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=8),
            ft.Column(
                [community_grid],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
        ],
        expand=True,
    )

    panel_content = ft.Container(content=heroes_content, expand=True)

    def style_tab(btn: ft.Container, active: bool) -> None:
        btn.bgcolor = T.ACCENT_DIM if active else None
        btn.border = ft.Border.all(1, T.ACCENT if active else T.BORDER)
        txt: ft.Text = btn.content  # type: ignore[assignment]
        txt.color = T.ACCENT if active else T.TEXT_DIM

    def make_tab(label: str, key: str) -> ft.Container:
        btn = ft.Container(
            content=ft.Text(label, size=12, weight=ft.FontWeight.W_600),
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            border_radius=10,
            animate=ft.Animation(160, T.EASE),
        )
        btn.on_click = lambda _, k=key: switch(k)
        return btn

    heroes_btn = make_tab("Heroes", "heroes")
    community_btn = make_tab("Community", "community")

    def switch(tab: str) -> None:
        style_tab(heroes_btn, tab == "heroes")
        style_tab(community_btn, tab == "community")
        heroes_btn.update()
        community_btn.update()
        panel_content.content = heroes_content if tab == "heroes" else community_content
        panel_content.update()
        if tab == "community":
            on_switch_to_community()

    style_tab(heroes_btn, True)
    style_tab(community_btn, False)

    return panel_content, heroes_btn, community_btn


# === Install / community helpers =============================================

def _run_install_with_polling(
    page: ft.Page,
    card: HeroCard,
    api: Api,
    set_status,
    on_done,
) -> None:
    """Kick off server-side install + poll for progress. Drives card state.
    Uses page.run_thread so control.update() inside the card mutators
    actually flushes to the client."""
    if card.state != "available":
        return
    try:
        api.start_install(card.hero["id"])
    except Exception as exc:
        set_status(f"Download failed to start: {exc}", T.ERROR)
        return
    card.set_downloading(0)

    def poll() -> None:
        while True:
            try:
                s = api.install_status(card.hero["id"])
            except Exception:
                time.sleep(0.5)
                continue
            state = s.get("state")
            if state == "downloading":
                card.set_downloading(s.get("percent", 0))
                time.sleep(0.4)
            elif state == "done":
                card.mark_installed()
                on_done(card)
                return
            elif state == "error":
                card.mark_failed(s.get("error", ""))
                return
            else:
                return

    page.run_thread(poll)


def _install_community_hero(
    page: ft.Page,
    card: HeroCard,
    api: Api,
    set_status,
    on_installed,
    then_select,
) -> None:
    """Register a community hero with the server, then run the normal install."""
    if card.state != "available":
        return
    try:
        api.register_community(card.hero)
    except Exception as exc:
        if "409" not in str(exc):  # 409 = already registered (fine)
            set_status(f"Register failed: {exc}", T.ERROR)
            return

    def on_done(c: HeroCard) -> None:
        on_installed(c)
        then_select(c)

    _run_install_with_polling(page, card, api, set_status, on_done=on_done)


def _mirror_into_heroes_tab(
    card: HeroCard,
    hero_cards_by_id: dict[str, HeroCard],
    cards: list[HeroCard],
    hero_grid: ft.Row,
    on_select,
    on_install,
) -> None:
    """Once a community hero is installed, show it in the main Heroes tab too."""
    if card.hero["id"] in hero_cards_by_id:
        return
    mirror = HeroCard(
        {**card.hero, "installed": True},
        on_select=on_select,
        on_install=on_install,
    )
    hero_cards_by_id[card.hero["id"]] = mirror
    cards.append(mirror)
    hero_grid.controls = cards
    try:
        hero_grid.update()
    except Exception:
        pass


def _load_community(
    page: ft.Page,
    api: Api,
    community_grid: ft.Row,
    community_status: ft.Text,
    on_select,
    on_install,
    loaded_flag: dict,
) -> None:
    community_grid.controls = []
    community_status.value = "Loading community models…"
    community_status.color = T.TEXT_DIM
    try:
        community_grid.update()
        community_status.update()
    except Exception:
        pass

    def work() -> None:
        try:
            models = api.browse_community()
        except Exception as exc:
            community_status.value = f"Could not load: {exc}"
            community_status.color = T.ERROR
            try:
                page.update()
            except Exception:
                pass
            return
        new_cards = [
            HeroCard(m, on_select=on_select, on_install=on_install)
            for m in models
        ]
        community_grid.controls = new_cards
        community_status.value = (
            "No new community models available."
            if not new_cards
            else f"{len(new_cards)} community models available"
        )
        community_status.color = T.TEXT_DIM
        try:
            page.update()
        except Exception:
            pass
        loaded_flag["done"] = True

    page.run_thread(work)


# === Misc helpers ============================================================

def _scan_outputs_by_hero() -> dict[str, list[str]]:
    """Pre-populate hero_results from files already in outputs/."""
    results: dict[str, list[str]] = {}
    if not OUTPUTS_DIR.is_dir():
        return results
    for f in sorted(OUTPUTS_DIR.iterdir()):
        if f.suffix == ".wav" and "_" in f.stem:
            hero_id = f.stem.rsplit("_", 1)[0]
            results.setdefault(hero_id, []).append(f.name)
    return results


def _hover_scale(control: ft.Control, scale: float):
    """Return an on_hover callback that scales a control up/down."""
    def on_hover(e: ft.HoverEvent) -> None:
        control.scale = scale if e.data == "true" else 1.0
        control.update()
    return on_hover
