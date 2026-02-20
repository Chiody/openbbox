"""
VS Code Adapter — Standard Sniff Strategy
==========================================

VS Code (with Copilot Chat) stores conversation data in:
  - chatSessions/ JSONL files (per-workspace and global)
  - state.vscdb ItemTable (chat session index)
  - AI extension directories (Cline, Roo Code, Continue, Cody)

┌─────────────────────────────────────────────────────────────────────┐
│                    VS CODE SNIFF STRATEGY                           │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ WORKSPACE_CHAT — chatSessions/ JSONL per workspace       │
│          │   Source: workspaceStorage/{hash}/chatSessions/*.jsonl   │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: workspace.json → folder URI           │
│          │   Format: kind=0 (init), kind=1 (request), kind=2 (resp)│
│          │                                                          │
│    2     │ GLOBAL_CHAT — emptyWindowChatSessions/ + global DB       │
│          │   Source: globalStorage/emptyWindowChatSessions/*.jsonl  │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: NONE                                  │
│          │                                                          │
│    3     │ AI_EXTENSIONS — Cline, Roo Code, Continue, Cody          │
│          │   Source: globalStorage/{ext-id}/ (SQLite, JSON, JSONL)  │
│          │   Speed: MEDIUM (1-5s)                                   │
│          │   Project context: varies by extension                   │
├──────────┴──────────────────────────────────────────────────────────┤
│ All layers are ALWAYS executed. No skipping.                        │
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

logger = logging.getLogger("openbbox.vscode")

KNOWN_AI_EXTENSIONS = {
    "saoudrizwan.claude-dev": "Cline",
    "rooveterinaryinc.roo-cline": "Roo Code",
    "continue.continue": "Continue",
    "sourcegraph.cody-ai": "Cody",
}


def _vscode_base() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User"
    elif system == "Linux":
        return Path.home() / ".config" / "Code" / "User"
    elif system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Code" / "User"
    return Path.home() / ".vscode"


def _vscode_global_storage() -> Path:
    return _vscode_base() / "globalStorage"


def _vscode_workspace_storage() -> Path:
    return _vscode_base() / "workspaceStorage"


class VSCodeAdapter(BaseAdapter):
    def name(self) -> str:
        return "VSCode"

    def detect(self) -> bool:
        base = _vscode_global_storage()
        if not base.exists():
            return False
        global_db = base / "state.vscdb"
        if global_db.exists():
            return True
        for ext_id in KNOWN_AI_EXTENSIONS:
            if (base / ext_id).exists():
                return True
        return False

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        base = _vscode_global_storage()
        if base.exists():
            global_db = base / "state.vscdb"
            if global_db.exists():
                paths.append(str(global_db))
            chat_dir = base / "emptyWindowChatSessions"
            if chat_dir.exists():
                for f in chat_dir.iterdir():
                    if f.suffix in (".json", ".jsonl"):
                        paths.append(str(f))

        ws_dir = _vscode_workspace_storage()
        if ws_dir.exists():
            for sub in ws_dir.iterdir():
                chat_sessions = sub / "chatSessions"
                if chat_sessions.exists():
                    for f in chat_sessions.iterdir():
                        if f.suffix == ".jsonl":
                            paths.append(str(f))
                db = sub / "state.vscdb"
                if db.exists():
                    paths.append(str(db))

        for ext_id in KNOWN_AI_EXTENSIONS:
            ext_dir = base / ext_id
            if ext_dir.exists():
                for pattern in ("*.db", "*.sqlite", "*.vscdb", "*.json", "*.jsonl"):
                    for f in ext_dir.rglob(pattern):
                        if f.is_file() and f.stat().st_size > 0:
                            paths.append(str(f))
        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """Three layers, all always executed."""
        return [
            SniffLayer(
                name="workspace_chat",
                description="Workspace chatSessions JSONL (Copilot Chat per project)",
                priority=1,
                speed="fast",
                scan_fn=self._layer_workspace_chat,
            ),
            SniffLayer(
                name="global_chat",
                description="Global emptyWindowChatSessions + global DB",
                priority=2,
                speed="fast",
                scan_fn=self._layer_global_chat,
            ),
            SniffLayer(
                name="ai_extensions",
                description="AI extensions (Cline, Roo Code, Continue, Cody)",
                priority=3,
                speed="medium",
                scan_fn=self._layer_ai_extensions,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Layer 1: Workspace Chat Sessions ──

    def _layer_workspace_chat(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        ws_dir = _vscode_workspace_storage()
        if not ws_dir.exists():
            return results

        for sub in ws_dir.iterdir():
            if not sub.is_dir():
                continue

            project_name, project_path = self._resolve_workspace_project(sub)
            chat_dir = sub / "chatSessions"
            if not chat_dir.exists():
                continue

            for jsonl_file in chat_dir.iterdir():
                if jsonl_file.suffix == ".jsonl":
                    convos = self._parse_chat_session_jsonl(jsonl_file, since)
                    for c in convos:
                        c.project_name = project_name
                        c.project_path = project_path
                    results.extend(convos)

        logger.info("[workspace_chat] Found %d conversations", len(results))
        return results

    # ── Layer 2: Global Chat Sessions ──

    def _layer_global_chat(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        base = _vscode_global_storage()
        if not base.exists():
            return results

        chat_dir = base / "emptyWindowChatSessions"
        if chat_dir.exists():
            for f in chat_dir.iterdir():
                if f.suffix == ".jsonl":
                    results.extend(self._parse_chat_session_jsonl(f, since))
                elif f.suffix == ".json":
                    results.extend(self._parse_chat_session_json(f, since))

        logger.info("[global_chat] Found %d conversations", len(results))
        return results

    # ── Layer 3: AI Extensions ──

    def _layer_ai_extensions(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        base = _vscode_global_storage()
        if not base.exists():
            return results

        for ext_id, ext_name in KNOWN_AI_EXTENSIONS.items():
            ext_dir = base / ext_id
            if not ext_dir.exists():
                continue

            for db_file in ext_dir.rglob("*.vscdb"):
                results.extend(self._read_sqlite(str(db_file), since))
            for db_file in ext_dir.rglob("*.db"):
                results.extend(self._read_sqlite(str(db_file), since))
            for jsonl_file in ext_dir.rglob("*.jsonl"):
                results.extend(self._read_generic_jsonl(str(jsonl_file), since))
            for json_file in ext_dir.rglob("*.json"):
                results.extend(self._read_generic_json(str(json_file), since))

        logger.info("[ai_extensions] Found %d conversations", len(results))
        return results

    # ── VS Code Chat Session JSONL Parser ──
    # Format: each line is {"kind": N, "v": {...}}
    #   kind=0: session init (has requests array)
    #   kind=1: new request (user message)
    #   kind=2: response update

    def _parse_chat_session_jsonl(
        self, path: Path, since: Optional[datetime]
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        requests: list[dict] = []
        session_ts: Optional[datetime] = None

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

                    kind = entry.get("kind")
                    v = entry.get("v", {})

                    if kind == 0:
                        creation = v.get("creationDate")
                        if creation:
                            session_ts = self._parse_ts_value(creation)
                        init_requests = v.get("requests", [])
                        for req in init_requests:
                            results.extend(self._extract_from_request(req, session_ts, since))

                    elif kind == 1:
                        requests.append(v)
                        results.extend(self._extract_from_request(v, session_ts, since))

        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read chat session %s: %s", path, e)

        return results

    def _parse_chat_session_json(
        self, path: Path, since: Optional[datetime]
    ) -> list[RawConversation]:
        """Parse .json chat session files (older format)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        results: list[RawConversation] = []
        session_ts = None
        creation = data.get("creationDate")
        if creation:
            session_ts = self._parse_ts_value(creation)

        for req in data.get("requests", []):
            results.extend(self._extract_from_request(req, session_ts, since))

        return results

    def _extract_from_request(
        self, req: dict, session_ts: Optional[datetime], since: Optional[datetime]
    ) -> list[RawConversation]:
        if not isinstance(req, dict):
            return []

        msg = req.get("message", {})
        if isinstance(msg, dict):
            prompt = msg.get("text", msg.get("content", ""))
        elif isinstance(msg, str):
            prompt = msg
        else:
            prompt = ""

        if not prompt or not prompt.strip():
            return []

        response_parts: list[str] = []
        resp = req.get("response", {})
        if isinstance(resp, dict):
            for val in resp.get("value", []):
                if isinstance(val, dict):
                    if val.get("kind") == "markdownContent":
                        md = val.get("content", {})
                        if isinstance(md, dict):
                            response_parts.append(md.get("value", ""))
                        elif isinstance(md, str):
                            response_parts.append(md)
                    elif "value" in val:
                        response_parts.append(str(val["value"]))
            if not response_parts and "message" in resp:
                response_parts.append(str(resp["message"]))

        response = "\n".join(p for p in response_parts if p).strip()
        if not response:
            return []

        ts = session_ts or datetime.utcnow()
        if since and ts < since:
            return []

        return [RawConversation(
            timestamp=ts,
            prompt=prompt.strip(),
            response=response,
        )]

    # ── Generic file readers (for AI extensions) ──

    def _read_sqlite(self, db_path: str, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            for table in tables:
                if table.startswith("sqlite_"):
                    continue
                try:
                    rows = conn.execute(f'SELECT * FROM "{table}" LIMIT 500').fetchall()
                    for row in rows:
                        row_dict = dict(row)
                        convo = self._try_extract_conversation(row_dict, since)
                        if convo:
                            results.append(convo)
                except sqlite3.OperationalError:
                    continue

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            logger.debug("Failed to read VS Code DB %s: %s", db_path, e)
        return results

    def _read_generic_jsonl(self, path: str, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        prompt_buf = ""
        response_buf = ""
        ts = datetime.utcnow()

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

                    role = entry.get("role", entry.get("type", ""))
                    content = self._extract_content(entry)
                    if not content:
                        continue

                    msg_ts = self._parse_timestamp(entry)

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
                    elif role in ("assistant", "ai"):
                        response_buf += content + "\n"
        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read JSONL %s: %s", path, e)

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf, response=response_buf.strip()
                ))

        return results

    def _read_generic_json(self, path: str, since: Optional[datetime]) -> list[RawConversation]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return []

        results: list[RawConversation] = []
        if isinstance(data, list):
            results.extend(self._parse_messages(data, since))
        elif isinstance(data, dict):
            for key in ("messages", "conversations", "history", "chats"):
                if key in data and isinstance(data[key], list):
                    results.extend(self._parse_messages(data[key], since))
                    break
        return results

    def _parse_messages(self, messages: list, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        prompt_buf = ""
        response_buf = ""
        ts = datetime.utcnow()

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", msg.get("type", ""))
            content = self._extract_content(msg)
            if not content:
                continue

            msg_ts = self._parse_timestamp(msg)

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
                response_buf += content + "\n"

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf, response=response_buf.strip()
                ))
        return results

    def _try_extract_conversation(
        self, row: dict, since: Optional[datetime]
    ) -> Optional[RawConversation]:
        for col in ("value", "data", "content"):
            if col in row and isinstance(row[col], str):
                try:
                    data = json.loads(row[col])
                    if isinstance(data, dict):
                        prompt = data.get("prompt", data.get("query", data.get("userMessage", "")))
                        response = data.get("response", data.get("answer", data.get("assistantMessage", "")))
                        if prompt and response:
                            ts = self._parse_timestamp(data)
                            if since and ts and ts < since:
                                return None
                            return RawConversation(
                                timestamp=ts or datetime.utcnow(),
                                prompt=str(prompt),
                                response=str(response),
                            )
                except (json.JSONDecodeError, TypeError):
                    continue
        return None

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
    def _extract_content(entry: dict) -> str:
        content = entry.get("content", entry.get("text", entry.get("message", "")))
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p)
        return str(content) if content else ""

    @staticmethod
    def _parse_timestamp(data: dict) -> Optional[datetime]:
        for key in ("timestamp", "createdAt", "created_at", "time"):
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
    def _parse_ts_value(raw) -> Optional[datetime]:
        try:
            if isinstance(raw, (int, float)):
                return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (ValueError, OSError):
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
