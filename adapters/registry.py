"""
Adapter Registry — discovers and manages all available IDE adapters.
Supports dynamic adapter loading and priority-based ordering.
"""

from __future__ import annotations

import logging
from typing import Optional

from adapters.base import BaseAdapter
from adapters.claude_desktop_adapter import ClaudeDesktopAdapter
from adapters.claudecode_adapter import ClaudeCodeAdapter
from adapters.codex_adapter import CodexAdapter
from adapters.cursor_adapter import CursorAdapter
from adapters.trae_adapter import TraeAdapter
from adapters.vscode_adapter import VSCodeAdapter
from adapters.windsurf_adapter import WindsurfAdapter
from adapters.kiro_adapter import KiroAdapter

logger = logging.getLogger("openbbox.registry")

# Ordered by 2026 market influence
ALL_ADAPTERS: list[type[BaseAdapter]] = [
    CursorAdapter,
    VSCodeAdapter,
    ClaudeCodeAdapter,
    ClaudeDesktopAdapter,
    TraeAdapter,
    WindsurfAdapter,
    CodexAdapter,
    KiroAdapter,
]


def get_available_adapters() -> list[BaseAdapter]:
    """Return instantiated adapters for IDEs detected on this machine."""
    available = []
    for adapter_cls in ALL_ADAPTERS:
        try:
            adapter = adapter_cls()
            if adapter.detect():
                available.append(adapter)
                logger.info("Detected: %s", adapter.name())
        except Exception as e:
            logger.debug("Failed to initialize %s: %s", adapter_cls.__name__, e)
    return available


def get_all_adapters() -> list[BaseAdapter]:
    """Return all adapter instances regardless of detection."""
    result = []
    for cls in ALL_ADAPTERS:
        try:
            result.append(cls())
        except Exception:
            pass
    return result


def get_adapter_by_name(name: str) -> Optional[BaseAdapter]:
    """Return a specific adapter by IDE name (case-insensitive)."""
    for cls in ALL_ADAPTERS:
        try:
            adapter = cls()
            if adapter.name().lower() == name.lower():
                return adapter
        except Exception:
            pass
    return None


def get_adapter_names() -> list[str]:
    """Return names of all registered adapters."""
    return [cls().name() for cls in ALL_ADAPTERS]
