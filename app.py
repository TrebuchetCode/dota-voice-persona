"""Dota Voice Persona — desktop app entry point.

Run with `python app.py`. This module is deliberately tiny; the UI itself
lives in the `ui/` package and the backend in `server.py`.
"""
from ui import run_app


if __name__ == "__main__":
    run_app()
