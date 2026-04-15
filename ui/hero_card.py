"""Animated hero card. One card per hero/community model.

Visual states:
    - installed    : full color portrait, selectable
    - available    : greyscale portrait, click triggers download
    - downloading  : animated progress bar
"""
from __future__ import annotations

import threading
from typing import Callable

import flet as ft

from . import theme as T

HEIGHT_PORTRAIT = 112
CARD_WIDTH = 200


class HeroCard(ft.Container):
    """Card for one hero. Fires `on_select(card)` when an installed card is
    clicked, or `on_install(card)` when an available card is clicked."""

    def __init__(
        self,
        hero: dict,
        on_select: Callable[["HeroCard"], None],
        on_install: Callable[["HeroCard"], None],
    ) -> None:
        super().__init__()
        self.hero = hero
        self._on_select = on_select
        self._on_install = on_install
        self.selected = False

        # --- children -------------------------------------------------------
        self.portrait = ft.Image(
            src=hero["portrait_url"],
            width=CARD_WIDTH,
            height=HEIGHT_PORTRAIT,
            fit=ft.BoxFit.COVER,
            border_radius=ft.BorderRadius.only(top_left=14, top_right=14),
        )
        self.name_text = ft.Text(
            hero["name"],
            color=T.TEXT,
            size=15,
            weight=ft.FontWeight.W_700,
            font_family=T.FONT_DISPLAY,
        )
        self.status_text = ft.Text("", color=T.TEXT_DIM, size=11)
        self.progress = ft.ProgressBar(
            value=0, color=T.ACCENT, bgcolor=T.BORDER, height=4, visible=False,
        )

        info_children = [self.name_text]
        if hero.get("author"):
            info_children.append(
                ft.Text(f"by {hero['author']}", color=T.TEXT_DIM, size=10, italic=True)
            )
        info_children.extend([self.status_text, self.progress])

        self.content = ft.Column(
            [
                ft.Stack([self.portrait]),
                ft.Container(
                    content=ft.Column(info_children, spacing=4, tight=True),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                ),
            ],
            spacing=0,
        )

        # --- styling --------------------------------------------------------
        self.width = CARD_WIDTH
        self.bgcolor = T.BG_CARD
        self.border_radius = 14
        self.border = ft.Border.all(2, T.BORDER)
        self.scale = 1.0
        self.animate_scale = ft.Animation(180, T.EASE_BACK)
        self.animate = ft.Animation(220, T.EASE)
        self.shadow = None
        self.on_hover = self._handle_hover
        self.on_click = self._handle_click

        self._refresh_state()

    # --- state ---------------------------------------------------------------
    @property
    def state(self) -> str:
        return "installed" if self.hero.get("installed") else "available"

    def _refresh_state(self) -> None:
        if self.state == "installed":
            self.status_text.value = "Ready"
            self.status_text.color = T.SUCCESS
            self.portrait.color = None
            self.portrait.color_blend_mode = None
        else:
            self.status_text.value = "Click to download"
            self.status_text.color = T.TEXT_DIM
            self.portrait.color = "#80000000"
            self.portrait.color_blend_mode = ft.BlendMode.DARKEN
        self.progress.visible = False
        self._refresh_selection_visual()

    def set_downloading(self, percent: int) -> None:
        self.status_text.value = f"Downloading… {percent}%"
        self.status_text.color = T.ACCENT
        self.progress.value = percent / 100
        self.progress.visible = True
        self.update()

    def mark_installed(self) -> None:
        self.hero["installed"] = True
        self._refresh_state()
        self.update()
        self._pulse_install_success()

    def _pulse_install_success(self) -> None:
        """One-shot scale + glow animation when download completes."""
        try:
            self.scale = 1.08
            self.shadow = ft.BoxShadow(
                spread_radius=2, blur_radius=32, color=T.SUCCESS,
            )
            self.update()
        except Exception:
            return

        def reset() -> None:
            try:
                self.scale = 1.0
                self._refresh_selection_visual()  # restore normal/selected shadow
                self.update()
            except Exception:
                pass

        threading.Timer(0.45, reset).start()

    def mark_failed(self, error: str) -> None:
        self.status_text.value = f"Failed: {error}" if error else "Failed"
        self.status_text.color = T.ERROR
        self.progress.visible = False
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._refresh_selection_visual()
        self.update()

    def _refresh_selection_visual(self) -> None:
        if self.selected:
            self.border = ft.Border.all(2, T.ACCENT)
            self.shadow = ft.BoxShadow(
                spread_radius=1, blur_radius=22, color=T.ACCENT_DIM,
            )
        else:
            self.border = ft.Border.all(2, T.BORDER)
            self.shadow = None

    # --- events --------------------------------------------------------------
    def _handle_hover(self, e: ft.HoverEvent) -> None:
        self.scale = 1.04 if e.data == "true" else 1.0
        self.update()

    def _handle_click(self, _) -> None:
        if self.state == "installed":
            self._on_select(self)
        else:
            self._on_install(self)
