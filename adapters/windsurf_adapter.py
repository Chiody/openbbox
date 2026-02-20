"""
Windsurf IDE Adapter — Standard Sniff Strategy
===============================================

Windsurf (by Codeium) is a VS Code fork. It stores data in:
  macOS:   ~/Library/Application Support/Windsurf/
  Linux:   ~/.config/Windsurf/
  Windows: %APPDATA%/Windsurf/

Cascade conversations are stored in:
  - ~/.codeium/windsurf/cascade/  (conversation history)
  - workspaceStorage/*/state.vscdb (per-workspace SQLite, same schema as VS Code)

┌─────────────────────────────────────────────────────────────────────┐
│                   WINDSURF SNIFF STRATEGY                           │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ WORKSPACE_DB — Per-project SQLite in workspaceStorage/   │
│          │   Source: state.vscdb (VS Code fork schema)              │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: workspace.json → folder URI           │
├──────────┴──────────────────────────────────────────────────────────┤
│ Single layer, always executed.                                      │
│ Deduplication: prompt[:200] prefix matching.                        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import platform
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.windsurf")


def _windsurf_user_data() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Windsurf"
    elif system == "Linux":
        return Path.home() / ".config" / "Windsurf"
    else:
        import os
        return Path(os.environ.get("APPDATA", "")) / "Windsurf"


def _cascade_data() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "cascade"


class WindsurfAdapter(BaseAdapter):
    def name(self) -> str:
        return "Windsurf"

    def detect(self) -> bool:
        user_data = _windsurf_user_data()
        cascade = _cascade_data()
        if cascade.exists():
            return True
        if not user_data.exists():
            return False
        ws_storage = user_data / "User" / "workspaceStorage"
        return ws_storage.exists() and any(ws_storage.iterdir())

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        ws_storage = _windsurf_user_data() / "User" / "workspaceStorage"
        if ws_storage.exists():
            for db in ws_storage.rglob("state.vscdb"):
                paths.append(str(db))
        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        return [
            SniffLayer(
                name="workspace_db",
                description="Windsurf workspace SQLite databases",
                priority=1,
                speed="fast",
                scan_fn=self._layer_workspace_db,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    # ── Layer 1: Workspace DB ──

    def _layer_workspace_db(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        ws_storage = _windsurf_user_data() / "User" / "workspaceStorage"
        if not ws_storage.exists():
            return results

        for ws_dir in ws_storage.iterdir():
            if not ws_dir.is_dir():
                continue
            db_path = ws_dir / "state.vscdb"
            if not db_path.exists():
                continue

            project_name = self._resolve_project_name(ws_dir)
            project_path = self._resolve_project_path(ws_dir)

            try:
                convos = self._read_workspace_db(db_path, project_name, project_path, since)
                results.extend(convos)
            except Exception as e:
                logger.debug("Failed to read Windsurf DB %s: %s", db_path, e)

        logger.info("[workspace_db] Found %d conversations", len(results))
        return results

    def _read_workspace_db(
        self, db_path: Path, project_name: str, project_path: str,
        since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT key, value FROM ItemTable WHERE key LIKE '%composerData%' OR key LIKE '%aiService%' OR key LIKE '%cascade%'")
            for row in cursor.fetchall():
                key = row["key"]
                raw = row["value"]
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                convos = self._extract_conversations(data, project_name, project_path, since)
                results.extend(convos)

            conn.close()
        except (sqlite3.Error, OSError) as e:
            logger.debug("SQLite error for %s: %s", db_path, e)
        return results

    def _extract_conversations(
        self, data, project_name: str, project_path: str,
        since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []

        if isinstance(data, dict):
            for key in ("allComposers", "composers", "chats", "conversations"):
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        convos = self._parse_composer_or_chat(item, project_name, project_path, since)
                        results.extend(convos)

            if "prompts" in data and isinstance(data["prompts"], list):
                for item in data["prompts"]:
                    convo = self._parse_prompt_item(item, project_name, project_path, since)
                    if convo:
                        results.append(convo)

        return results

    def _parse_composer_or_chat(
        self, item: dict, project_name: str, project_path: str,
        since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        if not isinstance(item, dict):
            return results

        messages = item.get("conversation", item.get("messages", []))
        if not isinstance(messages, list):
            return results

        model = item.get("modelId", item.get("model", ""))
        pending_prompt = ""
        pending_ts = None

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", msg.get("type", ""))
            text = msg.get("text", msg.get("content", msg.get("message", "")))
            if isinstance(text, list):
                text = "\n".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in text
                )
            if not isinstance(text, str) or not text.strip():
                continue

            ts = self._parse_timestamp(msg.get("timestamp", msg.get("ts", msg.get("createdAt"))))

            if role in ("user", "human", 1):
                if pending_prompt:
                    pass
                pending_prompt = text.strip()
                pending_ts = ts
            elif role in ("assistant", "ai", "bot", 2) and pending_prompt:
                effective_ts = pending_ts or ts or datetime.utcnow()
                if since and effective_ts < since:
                    pending_prompt = ""
                    continue
                results.append(RawConversation(
                    timestamp=effective_ts,
                    prompt=pending_prompt,
                    response=text.strip(),
                    model_name=str(model),
                    project_name=project_name,
                    project_path=project_path,
                ))
                pending_prompt = ""

        return results

    def _parse_prompt_item(
        self, item: dict, project_name: str, project_path: str,
        since: Optional[datetime]
    ) -> Optional[RawConversation]:
        if not isinstance(item, dict):
            return None
        prompt = item.get("prompt", item.get("text", ""))
        response = item.get("response", item.get("answer", ""))
        if not prompt or not response:
            return None
        ts = self._parse_timestamp(item.get("timestamp", item.get("ts")))
        effective_ts = ts or datetime.utcnow()
        if since and effective_ts < since:
            return None
        return RawConversation(
            timestamp=effective_ts,
            prompt=str(prompt).strip(),
            response=str(response).strip(),
            model_name=item.get("model", ""),
            project_name=project_name,
            project_path=project_path,
        )

    # ── Helpers ──

    @staticmethod
    def _resolve_project_name(ws_dir: Path) -> str:
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                folder = data.get("folder", "")
                if folder:
                    parsed = urlparse(folder)
                    return Path(unquote(parsed.path)).name
            except Exception:
                pass
        return ws_dir.name

    @staticmethod
    def _resolve_project_path(ws_dir: Path) -> str:
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                folder = data.get("folder", "")
                if folder:
                    parsed = urlparse(folder)
                    return unquote(parsed.path)
            except Exception:
                pass
        return ""

    @staticmethod
    def _parse_timestamp(raw) -> Optional[datetime]:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            try:
                if raw > 1e12:
                    raw = raw / 1000
                return datetime.utcfromtimestamp(raw)
            except (ValueError, OSError):
                return None
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
