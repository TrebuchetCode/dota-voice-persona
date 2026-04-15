"""UI package for the Dota Voice Persona Flet app.

The public entry point is `ui.run_app()` which handles launching the
backend server as a subprocess and starting the Flet event loop.
"""
from .server_lifecycle import start_server
from .main_view import main

__all__ = ["main", "start_server", "run_app"]


def run_app() -> None:
    """Start the backend server, then run the Flet UI event loop."""
    import flet as ft

    start_server()
    ft.run(main)
