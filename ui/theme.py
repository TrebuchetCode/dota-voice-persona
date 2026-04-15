"""Theme constants: colors, animation curves, fonts.

One source of truth so the whole UI stays visually consistent. If you want
to retheme the app, only this file needs to change.
"""
import flet as ft

# Fonts -----------------------------------------------------------------------
# Cinzel (Google Fonts) for the title and hero names — has an epic/ancient
# letterform that fits the Dota 2 aesthetic. SF Pro Display for body UI.
FONT_DISPLAY = "Cinzel"
FONT_UI = "SF Pro Display"

# Passed into `page.fonts` at boot so Flet fetches the webfont.
FONT_SOURCES: dict[str, str] = {
    "Cinzel": "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&display=swap",
}

# Backgrounds
BG = "#0a0b13"
BG_ELEVATED = "#13141f"
BG_CARD = "#1a1c2a"

# Accents
ACCENT = "#ff5a1f"          # dota orange
ACCENT_GLOW = "#ff7a3a"
ACCENT_DIM = "#33180c"

# Neutrals
TEXT = "#f5f5f7"
TEXT_DIM = "#7a7c8a"
BORDER = "#262837"
BORDER_INACTIVE = "#2a2c3c"

# Status
SUCCESS = "#3ddc97"
ERROR = "#ff4d6d"

# Animation curves — used consistently for hover/select transitions.
EASE = ft.AnimationCurve.EASE_OUT
EASE_BACK = ft.AnimationCurve.EASE_OUT_BACK
EASE_IN_OUT = ft.AnimationCurve.EASE_IN_OUT
