"""Pill-shaped inline audio player for one converted output file.

Layout matches the style of Gmail / Google Docs voice clips:
    [▶  0:08 / 0:30  ━━●━━━━━━━━━  🔊  ⋮]

Uses the shared pygame-backed AudioPlayer from `audio_player.py` — real
seeking and volume, no flet_audio.
"""
from __future__ import annotations

import time
from pathlib import Path

import flet as ft

from . import theme as T
from .audio_player import AudioPlayer
from .utils import fmt_time, reveal_in_finder, wav_duration_ms
from .waveform import compute_bars

TICK_MS = 100          # progress refresh rate while playing
WAVE_BARS = 56         # number of waveform bars behind the slider
WAVE_MAX_HEIGHT = 22   # tallest bar in px


def build_result_row(
    output_filename: str,
    outputs_dir: Path,
    player: AudioPlayer,
    page: ft.Page,
) -> ft.Container:
    """Return a pill-shaped audio player row. `player` is shared across all
    rows — starting playback here stops playback on any other row."""

    output_file = outputs_dir / output_filename
    duration_ms = wav_duration_ms(output_file)

    # Row-local flags so the tracker thread can stop itself when this row
    # is no longer the active one.
    state = {
        "tracker_running": False,
        "seeking": False,
    }

    # --- controls -----------------------------------------------------------
    play_btn = ft.IconButton(
        icon=ft.Icons.PLAY_ARROW_ROUNDED,
        icon_color=T.TEXT,
        icon_size=26,
        tooltip="Play",
    )
    time_label = ft.Text(
        f"0:00 / {fmt_time(duration_ms)}",
        color=T.TEXT,
        size=12,
        weight=ft.FontWeight.W_500,
        width=92,
        no_wrap=True,
    )
    # Compute + render a decorative waveform behind the slider — real
    # amplitude peaks from the WAV file, normalised to fit WAVE_MAX_HEIGHT.
    bar_values = compute_bars(output_file, n_bars=WAVE_BARS)
    waveform_row = ft.Row(
        controls=[
            ft.Container(
                width=2,
                height=max(2.0, WAVE_MAX_HEIGHT * v),
                bgcolor=T.BORDER,
                border_radius=1,
            )
            for v in bar_values
        ],
        spacing=1,
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        expand=True,
    )

    seek_slider = ft.Slider(
        min=0,
        max=duration_ms if duration_ms > 0 else 1000,
        value=0,
        active_color=T.ACCENT,
        inactive_color="#00000000",       # transparent — waveform shows through
        thumb_color=T.ACCENT,
        expand=True,
        height=24,
    )

    # Stack the slider over the waveform. The slider's active track still
    # colors the played portion; the inactive track is transparent so the
    # waveform bars show behind it.
    seek_area = ft.Stack(
        controls=[
            ft.Container(
                content=waveform_row,
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.symmetric(horizontal=10),
                expand=True,
                height=WAVE_MAX_HEIGHT + 4,
            ),
            ft.Container(
                content=seek_slider,
                alignment=ft.Alignment.CENTER,
                expand=True,
                height=WAVE_MAX_HEIGHT + 4,
            ),
        ],
        expand=True,
        height=WAVE_MAX_HEIGHT + 4,
    )
    # Click-to-cycle volume. Keeps the pill compact (matches the reference
    # screenshot) — the old inline slider left no room for the seek bar.
    VOLUME_LEVELS = [1.0, 0.66, 0.33, 0.0]

    def _volume_icon_for(v: float) -> str:
        if v == 0:
            return ft.Icons.VOLUME_OFF_ROUNDED
        if v < 0.5:
            return ft.Icons.VOLUME_DOWN_ROUNDED
        return ft.Icons.VOLUME_UP_ROUNDED

    volume_btn = ft.IconButton(
        icon=_volume_icon_for(player.volume()),
        icon_color=T.TEXT_DIM,
        icon_size=22,
        tooltip=f"Volume {int(player.volume() * 100)}%",
    )

    menu_btn = ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT_ROUNDED,
        items=[
            ft.PopupMenuItem(
                content="Show in Finder",
                icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                on_click=lambda _: reveal_in_finder(output_file),
            ),
        ],
        tooltip="More",
    )

    # --- helpers ------------------------------------------------------------
    def _safe_update(ctrl: ft.Control) -> None:
        try:
            ctrl.update()
        except (RuntimeError, AssertionError):
            pass

    def _safe_page_update() -> None:
        """Force a page-level flush. Control-level .update() from our
        background tick thread doesn't always reach the client without a
        subsequent user event — page.update() does."""
        try:
            page.update()
        except (RuntimeError, AssertionError):
            pass

    def _set_playing_visual(playing: bool) -> None:
        play_btn.icon = (
            ft.Icons.PAUSE_ROUNDED if playing else ft.Icons.PLAY_ARROW_ROUNDED
        )
        play_btn.tooltip = "Pause" if playing else "Play"
        _safe_update(play_btn)

    def _reset_visual() -> None:
        seek_slider.value = 0
        time_label.value = f"0:00 / {fmt_time(duration_ms)}"
        _safe_update(seek_slider)
        _safe_update(time_label)
        _set_playing_visual(False)

    def _is_this_row_active() -> bool:
        return player.current_path() == output_file

    def _tick_loop() -> None:
        state["tracker_running"] = True
        try:
            while state["tracker_running"] and _is_this_row_active():
                if state["seeking"]:
                    time.sleep(TICK_MS / 1000.0)
                    continue
                pos = player.position_ms()
                if duration_ms > 0:
                    if pos >= duration_ms:
                        player.stop()
                        break
                    seek_slider.value = min(pos, duration_ms)
                time_label.value = f"{fmt_time(pos)} / {fmt_time(duration_ms)}"
                playing_now = player.is_playing()
                expected_icon = (
                    ft.Icons.PAUSE_ROUNDED if playing_now else ft.Icons.PLAY_ARROW_ROUNDED
                )
                if play_btn.icon != expected_icon:
                    play_btn.icon = expected_icon
                    play_btn.tooltip = "Pause" if playing_now else "Play"
                # One page-level flush per frame — flushes all dirty controls
                # without needing a user event.
                _safe_page_update()
                time.sleep(TICK_MS / 1000.0)
        finally:
            state["tracker_running"] = False
            if not _is_this_row_active():
                return
            _reset_visual()
            _safe_page_update()

    # --- click handlers -----------------------------------------------------
    def on_play_click(_) -> None:
        # Toggle: if this row is loaded, pause/resume; otherwise start fresh.
        if _is_this_row_active():
            if player.is_playing():
                player.pause()
                _set_playing_visual(False)
            else:
                player.resume()
                _set_playing_visual(True)
                if not state["tracker_running"]:
                    page.run_thread(_tick_loop)
            return
        player.play(output_file)
        _set_playing_visual(True)
        # page.run_thread runs in Flet's executor with the page context
        # bound, so page.update() inside _tick_loop flushes to the client.
        page.run_thread(_tick_loop)

    def on_seek_start(_) -> None:
        state["seeking"] = True

    def on_seek_end(e) -> None:
        target = int(float(e.data))
        if _is_this_row_active():
            player.seek(target)
        else:
            player.play(output_file, start_ms=target)
            _set_playing_visual(True)
            page.run_thread(_tick_loop)
        state["seeking"] = False

    def on_volume_click(_) -> None:
        current = player.volume()
        # Find the next level below current; wrap to the highest.
        try:
            idx = next(i for i, lvl in enumerate(VOLUME_LEVELS) if lvl < current - 1e-3)
            new_v = VOLUME_LEVELS[idx]
        except StopIteration:
            new_v = VOLUME_LEVELS[0]
        player.set_volume(new_v)
        volume_btn.icon = _volume_icon_for(new_v)
        volume_btn.tooltip = f"Volume {int(new_v * 100)}%"
        _safe_update(volume_btn)

    play_btn.on_click = on_play_click
    seek_slider.on_change_start = on_seek_start
    seek_slider.on_change_end = on_seek_end
    volume_btn.on_click = on_volume_click

    # --- layout -------------------------------------------------------------
    # The pill: rounded ends, dark BG_CARD, controls in a single row.
    pill = ft.Container(
        content=ft.Row(
            [
                play_btn,
                time_label,
                seek_area,
                volume_btn,
                menu_btn,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        border_radius=28,
        bgcolor=T.BG_CARD,
        border=ft.Border.all(1, T.BORDER),
    )

    return ft.Column(
        [
            ft.Text(
                output_filename,
                color=T.TEXT_DIM,
                size=11,
                weight=ft.FontWeight.W_500,
            ),
            pill,
        ],
        spacing=6,
        tight=True,
    )
