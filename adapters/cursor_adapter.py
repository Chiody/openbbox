"""
Cursor IDE Adapter — Standard Sniff Strategy
=============================================

Cursor stores conversation data across multiple locations. This adapter
defines a fixed, deterministic two-layer strategy that guarantees full
coverage on every scan — no data source is ever silently skipped.

┌─────────────────────────────────────────────────────────────────────┐
│                    CURSOR SNIFF STRATEGY                            │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ WORKSPACE_DB — Per-project SQLite in workspaceStorage/   │
│          │   Source: composer.composerData + aiService.prompts      │
│          │   Speed: FAST (<1s)  Size: 30-500KB each                │
│          │   Project context: workspace.json → folder URI           │
│          │   Coverage: ALL projects that were ever opened in Cursor  │
│          │   Includes: Chat mode, Composer mode, inline edits       │
│          │                                                          │
│    2     │ AGENT_TRANSCRIPTS — JSONL in ~/.cursor/projects/         │
│          │   Source: agent-transcripts/{uuid}.jsonl                  │
│          │   Speed: FAST (<1s)  Size: 10-500KB each                │
│          │   Project context: directory name → decoded path          │
│          │   Coverage: Agent-mode sessions (richer detail)           │
│          │   Includes: Full multi-turn conversations, tool calls     │
├──────────┴──────────────────────────────────────────────────────────┤
│ Both layers are ALWAYS executed on every scan. No skipping.         │
│ Deduplication: prompt[:200] prefix matching across all layers.      │
│ Total expected time: <1s.                                           │
│                                                                     │
│ NOT included (by design):                                           │
│   globalStorage/state.vscdb — This is the global DB (often 1-5GB). │
│   It contains the same conversations as workspace DBs but WITHOUT   │
│   project context (all conversations mixed together). Reading it    │
│   takes 30-120s and produces unattributed data. The workspace DBs   │
│   already contain all the same data WITH project attribution.       │
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

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.cursor")


# ── Path helpers (cross-platform) ──

def _cursor_global_storage() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage"
    elif system == "Linux":
        return Path.home() / ".config" / "Cursor" / "User" / "globalStorage"
    elif system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage"
    return Path.home() / ".cursor"


def _cursor_workspace_storage() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
    elif system == "Linux":
        return Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
    elif system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "workspaceStorage"
    return Path.home() / ".cursor" / "workspaceStorage"


def _cursor_projects_dir() -> Path:
    return Path.home() / ".cursor" / "projects"


class CursorAdapter(BaseAdapter):

    def name(self) -> str:
        return "Cursor"

    def detect(self) -> bool:
        return _cursor_global_storage().exists() or _cursor_projects_dir().exists()

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        global_db = _cursor_global_storage() / "state.vscdb"
        if global_db.exists():
            paths.append(str(global_db))
        ws_dir = _cursor_workspace_storage()
        if ws_dir.exists():
            for sub in ws_dir.iterdir():
                db = sub / "state.vscdb"
                if db.exists():
                    paths.append(str(db))
        return paths

    # ── Standard Sniff Strategy ──

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """
        Two layers, both ALWAYS executed. No conditional skipping.
        Layer 1 covers all projects via workspace DBs.
        Layer 2 adds richer Agent-mode transcripts.
        Together they provide complete coverage.
        """
        return [
            SniffLayer(
                name="workspace_db",
                description="Workspace SQLite DBs (composer + prompts per project)",
                priority=1,
                speed="fast",
                scan_fn=self._layer_workspace_dbs,
            ),
            SniffLayer(
                name="agent_transcripts",
                description="Agent-mode JSONL transcripts (~/.cursor/projects/)",
                priority=2,
                speed="fast",
                scan_fn=self._layer_agent_transcripts,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        """Standard entry point — runs the full strategy."""
        return self.poll_with_progress(since=since)

    # ── Layer 1: Workspace Storage DBs ──

    def _layer_workspace_dbs(self, since: Optional[datetime] = None) -> list[RawConversation]:
        """
        Scan all workspace storage directories.
        Each has a small SQLite DB (<500KB) with project-specific conversation data,
        and a workspace.json that maps to the real project path.
        """
        results: list[RawConversation] = []
        ws_root = _cursor_workspace_storage()
        if not ws_root.exists():
            logger.info("[workspace_db] workspaceStorage not found at %s", ws_root)
            return results

        scanned = 0
        for ws_dir in ws_root.iterdir():
            if not ws_dir.is_dir():
                continue

            db_path = ws_dir / "state.vscdb"
            if not db_path.exists():
                continue

            project_name, project_path = self._resolve_workspace_project(ws_dir)
            scanned += 1

            convos = []
            convos.extend(self._read_composer_data(str(db_path), since))
            convos.extend(self._read_workspace_prompts(str(db_path), since))

            for c in convos:
                c.project_name = project_name
                c.project_path = project_path

            results.extend(convos)

        logger.info("[workspace_db] Scanned %d workspace(s), found %d conversation(s)", scanned, len(results))
        return results

    # ── Layer 2: Agent Transcripts ──

    def _layer_agent_transcripts(self, since: Optional[datetime] = None) -> list[RawConversation]:
        """
        Scan ~/.cursor/projects/{encoded-path}/agent-transcripts/ for JSONL files.
        Only projects that used Agent mode will have these files.
        """
        results: list[RawConversation] = []
        projects_dir = _cursor_projects_dir()
        if not projects_dir.exists():
            logger.info("[agent_transcripts] projects dir not found at %s", projects_dir)
            return results

        scanned_dirs = 0
        scanned_files = 0

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            transcripts_dir = project_dir / "agent-transcripts"
            if not transcripts_dir.exists():
                continue

            scanned_dirs += 1
            project_path = self._decode_project_path(project_dir.name)
            project_name = Path(project_path).name if project_path else project_dir.name

            try:
                for entry in transcripts_dir.iterdir():
                    if entry.suffix == ".jsonl":
                        scanned_files += 1
                        self._process_transcript(entry, since, project_name, project_path, results)
                    elif entry.is_dir():
                        for jsonl_file in entry.iterdir():
                            if jsonl_file.suffix == ".jsonl":
                                scanned_files += 1
                                self._process_transcript(jsonl_file, since, project_name, project_path, results)
            except OSError as e:
                logger.debug("[agent_transcripts] Error scanning %s: %s", transcripts_dir, e)

        logger.info(
            "[agent_transcripts] Scanned %d project dir(s), %d JSONL file(s), found %d conversation(s)",
            scanned_dirs, scanned_files, len(results),
        )
        return results

    def poll_with_progress(self, since=None, on_progress=None):
        """Run the standard two-layer strategy, then deduplicate with our own method."""
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Workspace helpers ──

    @staticmethod
    def _resolve_workspace_project(ws_dir: Path) -> tuple[str, str]:
        """Extract project name and path from workspace.json."""
        workspace_json = ws_dir / "workspace.json"
        if workspace_json.exists():
            try:
                with open(workspace_json, "r") as f:
                    ws_data = json.load(f)
                folder_uri = ws_data.get("folder", "")
                if folder_uri.startswith("file:///"):
                    project_path = folder_uri[7:]
                    return Path(project_path).name, project_path
            except (json.JSONDecodeError, OSError):
                pass
        return ws_dir.name, ""

    # ── Data readers ──

    def _read_workspace_prompts(self, db_path: str, since: Optional[datetime]) -> list[RawConversation]:
        """Read aiService.prompts — Chat mode conversations."""
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

            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key='aiService.prompts'"
            ).fetchone()

            if row and row["value"] and isinstance(row["value"], str) and len(row["value"]) > 10:
                try:
                    data = json.loads(row["value"])
                    if isinstance(data, list):
                        for entry in data:
                            if not isinstance(entry, dict):
                                continue
                            prompt = entry.get("prompt", entry.get("text", entry.get("message", "")))
                            response = entry.get("response", entry.get("answer", entry.get("result", "")))
                            if not prompt or not isinstance(prompt, str):
                                continue
                            if not response:
                                response = "(no response recorded)"

                            ts = datetime.utcnow()
                            raw_ts = entry.get("timestamp", entry.get("createdAt", entry.get("time")))
                            if raw_ts:
                                ts = self._parse_generic_timestamp(raw_ts) or ts

                            if since and ts < since:
                                continue

                            results.append(RawConversation(
                                timestamp=ts,
                                prompt=str(prompt).strip(),
                                response=str(response).strip()[:2000],
                                model_name=str(entry.get("model", entry.get("modelName", ""))),
                            ))
                except (json.JSONDecodeError, TypeError):
                    pass

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read prompts from %s: %s", db_path, e)
        return results

    def _read_composer_data(self, db_path: str, since: Optional[datetime]) -> list[RawConversation]:
        """Read composer.composerData — Composer mode conversations."""
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

            rows = conn.execute("SELECT key, value FROM ItemTable").fetchall()
            for row in rows:
                key = row["key"]
                value = row["value"]
                if not value or not isinstance(value, str):
                    continue

                if key in ("composer.composerData",) or "chat" in key.lower():
                    try:
                        data = json.loads(value)
                        results.extend(self._parse_composer_json(data, since))
                    except (json.JSONDecodeError, TypeError):
                        continue

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read Cursor ItemTable from %s: %s", db_path, e)
        return results

    def _parse_composer_json(self, data, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []

        composers = []
        if isinstance(data, dict):
            composers = data.get("allComposers", data.get("composers", []))
            if not composers:
                for key in ("messages", "tabs", "conversations", "history"):
                    if key in data and isinstance(data[key], list):
                        composers = data[key]
                        break
        elif isinstance(data, list):
            composers = data

        for composer in composers:
            if not isinstance(composer, dict):
                continue
            messages = composer.get("messages", composer.get("conversation", []))
            if not isinstance(messages, list):
                continue

            prompt_buf = ""
            response_buf = ""
            ts = datetime.utcnow()

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role", msg.get("type", ""))
                content = msg.get("content", msg.get("text", msg.get("message", "")))
                if not content or not isinstance(content, str):
                    continue

                msg_ts = self._parse_generic_timestamp(
                    msg.get("timestamp", msg.get("createdAt", msg.get("time")))
                )

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

    def _read_bubble_data(self, db_path: str, since: Optional[datetime]) -> list[RawConversation]:
        """
        Read cursorDiskKV bubbleId entries from the global DB.

        DEPRECATED: Not used in the standard two-layer strategy.
        Kept for manual data recovery or future opt-in "deep scan" mode.
        The global DB (1-5GB) contains conversations WITHOUT project context,
        so importing this data produces unattributed entries.
        """
        results: list[RawConversation] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "cursorDiskKV" not in tables:
                conn.close()
                return results

            rows = conn.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%' ORDER BY key"
            ).fetchall()

            conversations_map: dict[str, list[dict]] = {}
            for row in rows:
                key = row["key"]
                value = row["value"]
                if not value:
                    continue
                parts = key.split(":")
                if len(parts) < 3:
                    continue
                conv_id = parts[1]
                try:
                    bubble = json.loads(value)
                    conversations_map.setdefault(conv_id, []).append(bubble)
                except (json.JSONDecodeError, TypeError):
                    continue

            for conv_id, bubbles in conversations_map.items():
                results.extend(self._bubbles_to_conversations(bubbles, since))

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read Cursor bubbles from %s: %s", db_path, e)
        return results

    def _bubbles_to_conversations(self, bubbles: list[dict], since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        for bubble in bubbles:
            ts = self._parse_generic_timestamp(
                bubble.get("createdAt", bubble.get("timestamp", bubble.get("time")))
            )
            if since and ts and ts < since:
                continue

            prompt = ""
            response = ""
            context_files: list[str] = []

            msg_type = bubble.get("type", bubble.get("role", ""))
            if msg_type in ("user", "human"):
                prompt = self._extract_text(bubble)
            elif msg_type in ("assistant", "ai"):
                response = self._extract_text(bubble)

            if not prompt:
                prompt = bubble.get("userMessage", bubble.get("query", ""))
            if not response:
                response = bubble.get("assistantMessage", bubble.get("answer", ""))

            if "suggestedCodeBlocks" in bubble:
                for block in (bubble["suggestedCodeBlocks"] or []):
                    if isinstance(block, dict) and "code" in block:
                        response += f"\n```\n{block['code']}\n```"

            if "gitDiffs" in bubble and bubble["gitDiffs"]:
                context_files.extend(
                    d.get("filePath", "") for d in bubble["gitDiffs"] if isinstance(d, dict)
                )
            if "attachedCodeChunks" in bubble:
                for chunk in (bubble["attachedCodeChunks"] or []):
                    if isinstance(chunk, dict) and "filePath" in chunk:
                        context_files.append(chunk["filePath"])

            model_name = bubble.get("modelName", bubble.get("model", ""))

            if prompt and response:
                results.append(RawConversation(
                    timestamp=ts or datetime.utcnow(),
                    prompt=prompt.strip(),
                    response=response.strip(),
                    model_name=str(model_name),
                    context_files=[f for f in context_files if f],
                ))
        return results

    # ── Transcript helpers ──

    def _process_transcript(self, jsonl_file, since, project_name, project_path, results):
        try:
            convos = self._parse_transcript_jsonl(jsonl_file, since)
            for c in convos:
                c.project_name = project_name
                c.project_path = project_path
            results.extend(convos)
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read transcript %s: %s", jsonl_file, e)

    def _parse_transcript_jsonl(self, path: Path, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        prompt_buf = ""
        response_buf = ""

        try:
            file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            file_mtime = datetime.utcnow()

        ts = file_mtime

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role", "")
                message = entry.get("message", {})
                content_blocks = message.get("content", []) if isinstance(message, dict) else []

                text_parts: list[str] = []
                for block in content_blocks:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            text_parts.append(f"[Tool: {block.get('name', '')}]")
                    elif isinstance(block, str):
                        text_parts.append(block)

                content = "\n".join(text_parts)
                if not content:
                    continue

                if role == "user":
                    if prompt_buf and response_buf:
                        if not since or ts >= since:
                            results.append(RawConversation(
                                timestamp=ts, prompt=prompt_buf,
                                response=response_buf, session_id=path.stem,
                            ))
                    prompt_buf = content
                    response_buf = ""
                    ts = file_mtime
                elif role == "assistant":
                    response_buf += content + "\n"

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf,
                    response=response_buf.strip(), session_id=path.stem,
                ))

        return results

    # ── Shared helpers ──

    @staticmethod
    def _decode_project_path(encoded: str) -> str:
        if not encoded:
            return ""
        return "/" + encoded.replace("-", "/")

    @staticmethod
    def _extract_text(bubble: dict) -> str:
        text = bubble.get("text", bubble.get("content", bubble.get("message", "")))
        if isinstance(text, list):
            return "\n".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in text
            )
        return str(text) if text else ""

    @staticmethod
    def _parse_generic_timestamp(raw) -> Optional[datetime]:
        if raw is None:
            return None
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except (ValueError, OSError, TypeError):
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
