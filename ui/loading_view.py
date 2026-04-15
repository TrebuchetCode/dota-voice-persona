"""Startup splash shown while the RVC engine initialises."""
from __future__ import annotations

import threading
import time
from typing import Callable

import flet as ft

from . import theme as T


class LoadingView:
    """Pulsing-orb splash. Call `mount(page)` to show, `.running = False`
    to stop the pulse thread when the main view takes over."""

    def __init__(self) -> None:
        self.running = True

        self.orb = ft.Container(
            width=72,
            height=72,
            border_radius=36,
            gradient=ft.RadialGradient(
                center=ft.Alignment(0, 0),
                radius=0.9,
                colors=[T.ACCENT_GLOW, T.ACCENT, "#00000000"],
            ),
            animate_scale=ft.Animation(900, T.EASE_IN_OUT),
            scale=1.0,
        )
        self.text = ft.Text("Igniting the engine…", color=T.TEXT_DIM, size=13)

        self.container = ft.Container(
            expand=True,
            bgcolor=T.BG,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                [
                    self.orb,
                    ft.Container(height=24),
                    ft.Text(
                        "DOTA 2 VOICE PERSONA",
                        color=T.TEXT,
                        size=20,
                        weight=ft.FontWeight.W_700,
                    ),
                    self.text,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )

    def mount(self, page: ft.Page) -> None:
        page.add(self.container)
        threading.Thread(target=self._pulse, daemon=True).start()

    def stop(self) -> None:
        self.running = False

    def show_error(self, message: str) -> None:
        self.text.value = message
        self.text.color = T.ERROR
        try:
            self.text.update()
        except Exception:
            pass

    # Private -----------------------------------------------------------------
    def _pulse(self) -> None:
        toggle = False
        while self.running:
            toggle = not toggle
            try:
                self.orb.scale = 1.18 if toggle else 0.92
                self.orb.update()
            except Exception:
                return
            time.sleep(0.9)
