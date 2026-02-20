"""
Trae IDE Adapter — Standard Sniff Strategy
===========================================

Trae exists in two variants:
  - Trae CN (中国区): ~/Library/Application Support/Trae CN/
  - Trae (海外版):    ~/Library/Application Support/Trae/

Both are VS Code forks by ByteDance with built-in AI (Doubao/MarsCode).

Storage layout:
  - workspaceStorage/{hash}/state.vscdb — per-project SQLite (ItemTable)
    Contains: icube-ai-agent-storage-input-history (user prompts)
              memento/icube-ai-agent-storage (session metadata)
              ChatStore (turn metadata)
  - globalStorage/state.vscdb — global settings and metadata
  - ModularData/ai-agent/database.db — SQLCipher encrypted (NOT readable)
    Contains: full conversations with AI responses (encrypted)

NOTE: The main conversation database (database.db) is encrypted with
SQLCipher. We cannot read AI responses without the encryption key.
We CAN read user prompts from the workspace ItemTable.

┌─────────────────────────────────────────────────────────────────────┐
│                     TRAE SNIFF STRATEGY                             │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ WORKSPACE_DB — Per-project SQLite in workspaceStorage/   │
│          │   Source: icube-ai-agent-storage-input-history (prompts) │
│          │   Speed: FAST (<1s)  Size: 30-200KB each                │
│          │   Project context: workspace.json → folder URI           │
│          │   Coverage: All user prompts per project                  │
│          │   Limitation: AI responses not available (encrypted DB)   │
│          │                                                          │
│    2     │ GLOBAL_DB — globalStorage/state.vscdb                    │
│          │   Source: ItemTable (global chat metadata)               │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: NONE                                  │
│          │   Coverage: Supplementary metadata only                   │
├──────────┴──────────────────────────────────────────────────────────┤
│ Both layers are ALWAYS executed. No skipping.                       │
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
from urllib.parse import unquote

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.trae")


def _trae_variants() -> list[Path]:
    """
    Return all possible Trae base paths (CN + international).
    Trae CN: "Trae CN" (with space)
    Trae International: "Trae"
    """
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
        return [base / "Trae CN", base / "Trae"]
    elif system == "Linux":
        base = Path.home() / ".config"
        return [base / "Trae CN", base / "Trae"]
    elif system == "Windows":
        base = Path.home() / "AppData" / "Roaming"
        return [base / "Trae CN", base / "Trae"]
    return [Path.home() / ".trae"]


def _find_trae_roots() -> list[Path]:
    """Return existing Trae installation roots."""
    return [p for p in _trae_variants() if p.exists()]


class TraeAdapter(BaseAdapter):
    def __init__(self):
        self._roots = _find_trae_roots()

    def name(self) -> str:
        return "Trae"

    def detect(self) -> bool:
        return len(self._roots) > 0

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        for root in self._roots:
            global_db = root / "User" / "globalStorage" / "state.vscdb"
            if global_db.exists():
                paths.append(str(global_db))
            ws_dir = root / "User" / "workspaceStorage"
            if ws_dir.exists():
                for sub in ws_dir.iterdir():
                    db = sub / "state.vscdb"
                    if db.exists():
                        paths.append(str(db))
            agent_db = root / "ModularData" / "ai-agent" / "database.db"
            if agent_db.exists():
                paths.append(str(agent_db) + " (encrypted)")
        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """Two layers, both always executed."""
        return [
            SniffLayer(
                name="workspace_db",
                description="Workspace SQLite DBs (per-project prompt history)",
                priority=1,
                speed="fast",
                scan_fn=self._layer_workspace_dbs,
            ),
            SniffLayer(
                name="global_db",
                description="Global state.vscdb (metadata)",
                priority=2,
                speed="fast",
                scan_fn=self._layer_global_db,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Layer 1: Workspace DBs ──

    def _layer_workspace_dbs(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []

        for root in self._roots:
            variant = "CN" if "CN" in root.name else "International"
            ws_dir = root / "User" / "workspaceStorage"
            if not ws_dir.exists():
                continue

            for sub in ws_dir.iterdir():
                if not sub.is_dir():
                    continue

                project_name, project_path = self._resolve_workspace_project(sub)
                db = sub / "state.vscdb"
                if not db.exists():
                    continue

                convos = self._read_workspace_prompts(str(db), since)
                for c in convos:
                    c.project_name = project_name
                    c.project_path = project_path
                results.extend(convos)

                logger.debug("[workspace_db] %s/%s: %d prompts", variant, project_name, len(convos))

        logger.info("[workspace_db] Found %d conversations from workspace DBs", len(results))
        return results

    # ── Layer 2: Global DB ──

    def _layer_global_db(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []

        for root in self._roots:
            global_db = root / "User" / "globalStorage" / "state.vscdb"
            if not global_db.exists():
                continue
            convos = self._read_global_metadata(str(global_db), since)
            results.extend(convos)

        logger.info("[global_db] Found %d conversations from global DB", len(results))
        return results

    # ── Workspace prompt reader ──

    def _read_workspace_prompts(
        self, db_path: str, since: Optional[datetime]
    ) -> list[RawConversation]:
        """
        Read user prompts from Trae's workspace DB.
        Primary source: icube-ai-agent-storage-input-history
        """
        results: list[RawConversation] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "ItemTable" not in tables:
                conn.close()
                return results

            # Source 1: icube-ai-agent-storage-input-history (Trae CN specific)
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key='icube-ai-agent-storage-input-history'"
            ).fetchone()
            if row and row["value"]:
                try:
                    prompts = json.loads(row["value"])
                    if isinstance(prompts, list):
                        for i, entry in enumerate(prompts):
                            text = entry.get("inputText", "")
                            if not text or not text.strip():
                                continue
                            if since:
                                pass  # no timestamp in prompt history, include all

                            results.append(RawConversation(
                                timestamp=datetime.utcnow(),
                                prompt=text.strip(),
                                response="[Trae AI response — stored in encrypted database]",
                                model_name=self._detect_model(conn),
                            ))
                except (json.JSONDecodeError, TypeError):
                    pass

            # Source 2: KV-style tables (for international version)
            kv_tables = [t for t in tables if "kv" in t.lower() or "disk" in t.lower()]
            for table_name in kv_tables:
                results.extend(self._read_kv_table(conn, table_name, since))

            # Source 3: Generic chat/composer keys in ItemTable
            for row in conn.execute("SELECT key, value FROM ItemTable").fetchall():
                key = row["key"]
                value = row["value"]
                if not value or not isinstance(value, str):
                    continue
                if key in ("icube-ai-agent-storage-input-history",):
                    continue  # already processed
                if any(k in key.lower() for k in ("composer", "conversation")):
                    try:
                        data = json.loads(value)
                        results.extend(self._parse_conversation_data(data, since))
                    except (json.JSONDecodeError, TypeError):
                        continue

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read Trae workspace DB %s: %s", db_path, e)
        return results

    def _read_global_metadata(
        self, db_path: str, since: Optional[datetime]
    ) -> list[RawConversation]:
        """Read from global DB — mainly metadata, may have some conversation data."""
        results: list[RawConversation] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "ItemTable" not in tables:
                conn.close()
                return results

            kv_tables = [t for t in tables if "kv" in t.lower() or "disk" in t.lower()]
            for table_name in kv_tables:
                results.extend(self._read_kv_table(conn, table_name, since))

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read Trae global DB %s: %s", db_path, e)
        return results

    def _read_kv_table(
        self, conn: sqlite3.Connection, table_name: str, since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        try:
            rows = conn.execute(
                f'SELECT key, value FROM "{table_name}" WHERE key LIKE ? ORDER BY key',
                ("%bubble%",)
            ).fetchall()

            for row in rows:
                value = row["value"]
                if not value:
                    continue
                try:
                    data = json.loads(value)
                    convo = self._parse_bubble(data, since)
                    if convo:
                        results.append(convo)
                except (json.JSONDecodeError, TypeError):
                    continue
        except sqlite3.OperationalError:
            pass
        return results

    # ── Parsers ──

    def _parse_bubble(self, data: dict, since: Optional[datetime]) -> Optional[RawConversation]:
        ts = self._parse_timestamp(data)
        if since and ts and ts < since:
            return None

        prompt = data.get("userMessage", data.get("query", data.get("text", "")))
        response = data.get("assistantMessage", data.get("answer", data.get("content", "")))

        if isinstance(prompt, dict):
            prompt = prompt.get("text", prompt.get("content", str(prompt)))
        if isinstance(response, dict):
            response = response.get("text", response.get("content", str(response)))

        if prompt and response:
            return RawConversation(
                timestamp=ts or datetime.utcnow(),
                prompt=str(prompt).strip(),
                response=str(response).strip(),
                model_name=str(data.get("modelName", data.get("model", ""))),
            )
        return None

    def _parse_conversation_data(
        self, data, since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        if isinstance(data, dict):
            for key in ("allComposers", "composers", "messages", "conversations", "history", "tabs"):
                if key in data and isinstance(data[key], list):
                    results.extend(self._parse_message_list(data[key], since))
                    break
        elif isinstance(data, list):
            results.extend(self._parse_message_list(data, since))
        return results

    def _parse_message_list(
        self, items: list, since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        prompt_buf = ""
        response_buf = ""
        ts = datetime.utcnow()

        for item in items:
            if not isinstance(item, dict):
                continue

            if "messages" in item and isinstance(item["messages"], list):
                results.extend(self._parse_message_list(item["messages"], since))
                continue

            role = item.get("role", item.get("type", ""))
            content = item.get("content", item.get("text", item.get("message", "")))
            if not content or not isinstance(content, str):
                continue

            msg_ts = self._parse_timestamp(item)

            if role in ("user", "human"):
                if prompt_buf and response_buf:
                    if not since or ts >= since:
                        results.append(RawConversation(
                            timestamp=ts, prompt=prompt_buf, response=response_buf
                        ))
                prompt_buf = content
                response_buf = ""
                if msg_ts:
                    ts = msg_ts
            elif role in ("assistant", "ai", "bot"):
                response_buf += content

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf, response=response_buf
                ))

        return results

    # ── Helpers ──

    @staticmethod
    def _resolve_workspace_project(ws_dir: Path) -> tuple[str, str]:
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                folder = data.get("folder", "")
                if folder.startswith("file://"):
                    decoded = unquote(folder[7:])
                    return Path(decoded).name, decoded
            except (json.JSONDecodeError, OSError):
                pass
        return ws_dir.name, ""

    @staticmethod
    def _detect_model(conn: sqlite3.Connection) -> str:
        """Try to detect which model Trae is using from settings."""
        try:
            for row in conn.execute("SELECT key, value FROM ItemTable").fetchall():
                key = row["key"]
                if "selected_model" in key:
                    data = json.loads(row["value"])
                    if isinstance(data, dict):
                        return data.get("display_name", data.get("name", ""))
        except (sqlite3.OperationalError, json.JSONDecodeError):
            pass
        return ""

    @staticmethod
    def _parse_timestamp(data: dict) -> Optional[datetime]:
        for key in ("createdAt", "timestamp", "created_at", "time"):
            if key in data:
                try:
                    raw = data[key]
                    if isinstance(raw, (int, float)):
                        return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
                    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except (ValueError, OSError):
                    pass
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
