"""Pygame-backed audio player.

Uses `pygame.mixer.music` because it supports:
    - loading + streaming any WAV/MP3/OGG
    - seek (set_pos) on WAV and OGG
    - volume (0.0 – 1.0)
    - pause / unpause

Exposes a shared `AudioPlayer` that tracks "current file" + accumulated
pause offsets so the UI can render position / duration / seek accurately.
"""
from __future__ import annotations

import os
import time
import warnings
from pathlib import Path
from threading import Lock
from typing import Optional

# Silence pygame's greeting banner before import.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pygame


class AudioPlayer:
    """One player instance, shared across all result rows. Starting a new
    playback stops the old one."""

    def __init__(self) -> None:
        pygame.mixer.init()
        self._lock = Lock()
        self._current: Optional[Path] = None
        # Clock-based position tracking. `pygame.mixer.music.get_pos()` only
        # returns elapsed-since-play, and doesn't account for pauses or seeks
        # correctly, so we manage our own clock.
        self._play_started_at: float = 0.0
        self._offset_ms: int = 0           # position at time of last play/unpause/seek
        self._paused: bool = False
        self._volume: float = 1.0

    # --- playback -----------------------------------------------------------
    def play(self, path: Path, start_ms: int = 0) -> None:
        with self._lock:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self._volume)
            pygame.mixer.music.play(start=start_ms / 1000.0)
            self._current = path
            self._play_started_at = time.time()
            self._offset_ms = start_ms
            self._paused = False

    def pause(self) -> None:
        with self._lock:
            if self._current is None or self._paused:
                return
            # Freeze current position then pause.
            self._offset_ms = self._position_ms_unlocked()
            pygame.mixer.music.pause()
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            if self._current is None or not self._paused:
                return
            pygame.mixer.music.unpause()
            self._play_started_at = time.time()
            self._paused = False

    def stop(self) -> None:
        with self._lock:
            pygame.mixer.music.stop()
            self._current = None
            self._play_started_at = 0.0
            self._offset_ms = 0
            self._paused = False

    def seek(self, ms: int) -> None:
        """Seek to an absolute position. Works on WAV via reload+play-at."""
        with self._lock:
            if self._current is None:
                return
            path = self._current
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(self._volume)
            pygame.mixer.music.play(start=ms / 1000.0)
            self._play_started_at = time.time()
            self._offset_ms = ms
            self._paused = False

    def set_volume(self, v: float) -> None:
        v = max(0.0, min(1.0, float(v)))
        self._volume = v
        # Safe to call even when nothing is loaded.
        pygame.mixer.music.set_volume(v)

    # --- queries ------------------------------------------------------------
    def is_playing(self) -> bool:
        return self._current is not None and not self._paused and pygame.mixer.music.get_busy()

    def is_active(self) -> bool:
        """Playing or paused on a file — i.e. there's something loaded."""
        return self._current is not None

    def is_paused(self) -> bool:
        return self._paused

    def current_path(self) -> Optional[Path]:
        return self._current

    def position_ms(self) -> int:
        with self._lock:
            return self._position_ms_unlocked()

    def volume(self) -> float:
        return self._volume

    # --- internals ----------------------------------------------------------
    def _position_ms_unlocked(self) -> int:
        if self._current is None:
            return 0
        if self._paused:
            return self._offset_ms
        return self._offset_ms + int((time.time() - self._play_started_at) * 1000)
