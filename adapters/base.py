"""
Base adapter interface for all IDE log sniffers.
Each adapter reads conversation history from a specific IDE and yields PulseNode-ready data.

Standard Sniff Strategy:
    Every adapter defines a multi-layer scan strategy via get_sniff_strategy().
    Each layer is a named data source with priority, expected speed, and a scan function.
    The engine executes layers in priority order and reports progress per layer.
    This guarantees no data source is silently skipped.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger("openbbox.adapter")


@dataclass
class RawConversation:
    """Raw prompt/response pair extracted from an IDE's local storage."""

    timestamp: datetime
    prompt: str
    response: str
    model_name: str = ""
    session_id: str = ""
    context_files: list[str] | None = None
    project_name: str = ""
    project_path: str = ""

    def __post_init__(self):
        import re
        self.prompt = re.sub(r"</?user_query>\s*", "", self.prompt).strip()
        self.prompt = re.sub(r"</?system_reminder>.*?</system_reminder>", "", self.prompt, flags=re.DOTALL).strip()
        self.response = re.sub(r"</?system_reminder>.*?</system_reminder>", "", self.response, flags=re.DOTALL).strip()


@dataclass
class SniffLayer:
    """One data-source layer in a multi-layer sniff strategy."""

    name: str
    description: str
    priority: int  # lower = scanned first
    speed: str  # "fast" (<1s), "medium" (1-10s), "slow" (10s+)
    scan_fn: Callable[[Optional[datetime]], list[RawConversation]] = field(repr=False)


@dataclass
class LayerResult:
    """Result of scanning one layer."""

    layer_name: str
    conversations: list[RawConversation]
    projects_found: set[str]
    error: str = ""
    elapsed_ms: int = 0


# Callback type for progress reporting during scan
ProgressCallback = Callable[[dict], None]


class BaseAdapter(abc.ABC):
    """Interface that every IDE adapter must implement."""

    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name of this adapter (e.g. 'Cursor', 'Trae')."""

    @abc.abstractmethod
    def detect(self) -> bool:
        """Return True if this IDE's data is present on the local machine."""

    @abc.abstractmethod
    def get_db_paths(self) -> list[str]:
        """Return filesystem paths to the IDE's conversation databases."""

    @abc.abstractmethod
    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        """
        Return conversations newer than `since`.
        If since is None, return all available conversations.
        """

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """
        Return the ordered list of data-source layers for this adapter.
        Override in subclasses to define a multi-layer strategy.
        Default: single layer wrapping poll_new().
        """
        return [
            SniffLayer(
                name="default",
                description=f"{self.name()} default scan",
                priority=0,
                speed="medium",
                scan_fn=self.poll_new,
            )
        ]

    def poll_with_progress(
        self,
        since: Optional[datetime] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> list[RawConversation]:
        """
        Execute the full sniff strategy layer by layer, reporting progress.
        Returns deduplicated conversations from all layers.
        """
        import time

        strategy = self.get_sniff_strategy()
        strategy.sort(key=lambda l: l.priority)

        all_conversations: list[RawConversation] = []
        total_layers = len(strategy)

        for idx, layer in enumerate(strategy):
            if on_progress:
                on_progress({
                    "step": "layer_start",
                    "layer_name": layer.name,
                    "layer_desc": layer.description,
                    "layer_index": idx + 1,
                    "layer_total": total_layers,
                    "speed": layer.speed,
                })

            t0 = time.monotonic()
            try:
                convos = layer.scan_fn(since)
                elapsed = int((time.monotonic() - t0) * 1000)

                projects = {c.project_name for c in convos if c.project_name}

                if on_progress:
                    on_progress({
                        "step": "layer_done",
                        "layer_name": layer.name,
                        "conversations_found": len(convos),
                        "projects_found": sorted(projects),
                        "elapsed_ms": elapsed,
                    })

                all_conversations.extend(convos)

            except Exception as e:
                elapsed = int((time.monotonic() - t0) * 1000)
                logger.warning("Layer %s failed: %s", layer.name, e)
                if on_progress:
                    on_progress({
                        "step": "layer_error",
                        "layer_name": layer.name,
                        "error": str(e)[:200],
                        "elapsed_ms": elapsed,
                    })

        return self._deduplicate_base(all_conversations)

    @staticmethod
    def _deduplicate_base(conversations: list[RawConversation]) -> list[RawConversation]:
        """Default deduplication by prompt prefix."""
        seen: set[str] = set()
        unique: list[RawConversation] = []
        for convo in conversations:
            key = convo.prompt[:200].strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(convo)
        return unique
