"""
OpenAI Codex CLI Adapter — Standard Sniff Strategy
===================================================

Codex CLI stores conversation data under ~/.codex/:
  - ~/.codex/sessions/{YYYY}/{MM}/{DD}/rollout-*.jsonl — session transcripts
  - ~/.codex/sqlite/codex-dev.db — automation/inbox metadata (not conversations)

Session JSONL format:
  Each line is {"timestamp": "...", "type": "...", "payload": {...}}
  Types:
    - session_meta: session info (id, cwd, model)
    - response_item: message with role (user/developer/assistant) and content blocks
    - event_msg: user_message events with actual user input
    - turn_context: per-turn metadata (cwd, approval_policy)

┌─────────────────────────────────────────────────────────────────────┐
│                     CODEX SNIFF STRATEGY                            │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ SESSION_JSONL — Session rollout files                    │
│          │   Source: ~/.codex/sessions/{Y}/{M}/{D}/rollout-*.jsonl  │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: session_meta.cwd → project path       │
│          │   Coverage: All conversations with full context           │
├──────────┴──────────────────────────────────────────────────────────┤
│ Single layer, always executed.                                      │
│ Deduplication: prompt[:200] prefix matching.                        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.codex")


def _codex_base_path() -> Path:
    return Path.home() / ".codex"


class CodexAdapter(BaseAdapter):
    def name(self) -> str:
        return "Codex"

    def detect(self) -> bool:
        base = _codex_base_path()
        return base.exists() and (base / "sessions").exists()

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        sessions_dir = _codex_base_path() / "sessions"
        if sessions_dir.exists():
            for jsonl in sessions_dir.rglob("*.jsonl"):
                paths.append(str(jsonl))
        sqlite_db = _codex_base_path() / "sqlite" / "codex-dev.db"
        if sqlite_db.exists():
            paths.append(str(sqlite_db))
        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        return [
            SniffLayer(
                name="session_jsonl",
                description="Session rollout JSONL files (~/.codex/sessions/)",
                priority=1,
                speed="fast",
                scan_fn=self._layer_session_jsonl,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Layer 1: Session JSONL ──

    def _layer_session_jsonl(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        sessions_dir = _codex_base_path() / "sessions"
        if not sessions_dir.exists():
            return results

        for jsonl_file in sessions_dir.rglob("*.jsonl"):
            convos = self._parse_session_file(jsonl_file, since)
            results.extend(convos)

        logger.info("[session_jsonl] Found %d conversations from %d files",
                     len(results), len(list(sessions_dir.rglob("*.jsonl"))))
        return results

    def _parse_session_file(
        self, path: Path, since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []

        session_id = ""
        session_cwd = ""
        session_model = ""

        user_messages: list[tuple[str, Optional[datetime]]] = []
        assistant_responses: list[tuple[str, Optional[datetime]]] = []

        current_user_msg = ""
        current_assistant_resp = ""
        current_ts: Optional[datetime] = None

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = entry.get("type", "")
                    payload = entry.get("payload", {})
                    ts_str = entry.get("timestamp", "")
                    ts = self._parse_iso_timestamp(ts_str) if ts_str else None

                    if etype == "session_meta":
                        session_id = payload.get("id", "")
                        session_cwd = payload.get("cwd", "")
                        session_model = payload.get("model", "")

                    elif etype == "event_msg":
                        msg_type = payload.get("type", "")
                        if msg_type == "user_message":
                            if current_user_msg and current_assistant_resp:
                                results.append(self._build_conversation(
                                    current_user_msg, current_assistant_resp,
                                    current_ts, session_cwd, session_model, since
                                ))
                                current_assistant_resp = ""

                            current_user_msg = payload.get("message", "")
                            current_ts = ts

                    elif etype == "response_item":
                        role = payload.get("role", "")
                        content_blocks = payload.get("content", [])

                        if role == "user":
                            text = self._extract_text_from_blocks(content_blocks)
                            if text and not text.startswith("<") and len(text) > 10:
                                if not current_user_msg:
                                    current_user_msg = text
                                    current_ts = ts

                        elif role == "assistant":
                            text = self._extract_assistant_content(content_blocks)
                            if text:
                                current_assistant_resp += text + "\n"

                        elif role == "developer":
                            pass

        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read Codex session %s: %s", path, e)

        if current_user_msg and current_assistant_resp:
            results.append(self._build_conversation(
                current_user_msg, current_assistant_resp,
                current_ts, session_cwd, session_model, since
            ))

        return [r for r in results if r is not None]

    def _build_conversation(
        self,
        prompt: str,
        response: str,
        ts: Optional[datetime],
        cwd: str,
        model: str,
        since: Optional[datetime],
    ) -> Optional[RawConversation]:
        if not prompt.strip() or not response.strip():
            return None

        effective_ts = ts or datetime.utcnow()
        if since and effective_ts < since:
            return None

        project_path = cwd
        project_name = Path(cwd).name if cwd else ""

        return RawConversation(
            timestamp=effective_ts,
            prompt=prompt.strip(),
            response=response.strip(),
            model_name=model,
            project_name=project_name,
            project_path=project_path,
        )

    # ── Content extractors ──

    @staticmethod
    def _extract_text_from_blocks(blocks) -> str:
        if not isinstance(blocks, list):
            return ""
        parts = []
        for block in blocks:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "input_text":
                    parts.append(block.get("text", ""))
                elif btype == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _extract_assistant_content(blocks) -> str:
        if not isinstance(blocks, list):
            return ""
        parts = []
        for block in blocks:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "output_text":
                    parts.append(block.get("text", ""))
                elif btype == "text":
                    parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    name = block.get("name", "unknown")
                    parts.append(f"[Tool: {name}]")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _parse_iso_timestamp(raw: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _deduplicate(conversations: list[RawConversation]) -> list[RawConversation]:
        seen: set[str] = set()
        unique: list[RawConversation] = []
        for convo in conversations:
            key = convo.prompt[:200].strip()
            if key and key not in seen:
                seen.add(key)
                unique.append(convo)
        return unique
