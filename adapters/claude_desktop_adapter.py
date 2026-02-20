"""
Claude Desktop App Adapter
===========================

Claude Desktop (Claude.app) is Anthropic's Electron-based desktop chat application.
Unlike Claude Code CLI, it stores conversations on Anthropic's cloud servers.

Local data available:
  - ~/Library/Application Support/Claude/ — app config, session data (LevelDB)
  - Conversations are NOT stored locally (cloud-only)

This adapter detects the installation but cannot extract conversation history.
It serves as a placeholder to inform users about the limitation and distinguish
it from Claude Code CLI.
"""

from __future__ import annotations

import logging
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.claude_desktop")


def _claude_desktop_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude"
    elif system == "Windows":
        import os
        appdata = os.environ.get("APPDATA", str(Path.home()))
        return Path(appdata) / "Claude"
    else:
        return Path.home() / ".config" / "Claude"


def _claude_desktop_app_exists() -> bool:
    system = platform.system()
    if system == "Darwin":
        return Path("/Applications/Claude.app").exists()
    elif system == "Windows":
        candidates = [
            Path.home() / "AppData" / "Local" / "Programs" / "claude" / "Claude.exe",
            Path("C:/Program Files/Claude/Claude.exe"),
        ]
        return any(p.exists() for p in candidates)
    return False


class ClaudeDesktopAdapter(BaseAdapter):
    def name(self) -> str:
        return "ClaudeDesktop"

    def detect(self) -> bool:
        if _claude_desktop_app_exists():
            return True
        return _claude_desktop_path().exists()

    def get_db_paths(self) -> list[str]:
        base = _claude_desktop_path()
        if not base.exists():
            return []
        return [str(base)]

    def get_sniff_strategy(self) -> list[SniffLayer]:
        return [
            SniffLayer(
                name="cloud_only_notice",
                description="Claude Desktop stores conversations in the cloud, not locally",
                priority=1,
                speed="fast",
                scan_fn=self._layer_notice,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        if on_progress:
            on_progress({
                "type": "info",
                "adapter": self.name(),
                "message": "Claude Desktop detected — conversations are stored in the cloud and cannot be read locally.",
            })
        return []

    def _layer_notice(self, since: Optional[datetime] = None) -> list[RawConversation]:
        logger.info(
            "Claude Desktop detected at %s — conversations are cloud-only, "
            "no local data to extract. Consider installing Claude Code CLI "
            "(npm install -g @anthropic-ai/claude-code) for local conversation history.",
            _claude_desktop_path(),
        )
        return []
