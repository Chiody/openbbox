"""
Kiro IDE Adapter — Standard Sniff Strategy
===========================================

Kiro (by Amazon) is a VS Code-based AI IDE. It stores conversation data in:
  - workspace-sessions/ JSON files under kiro.kiroagent extension storage
  - state.vscdb per workspace (VS Code-compatible format)

┌─────────────────────────────────────────────────────────────────────┐
│                    KIRO SNIFF STRATEGY                               │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ WORKSPACE_SESSIONS — kiro.kiroagent workspace-sessions/  │
│          │   Source: workspace-sessions/{b64path}/sessions.json     │
│          │          + individual {sessionId}.json conversation files│
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: base64-decoded directory name         │
│          │   Format: sessions.json lists sessions, each {id}.json  │
│          │           has history[] with user/assistant messages     │
│          │                                                          │
│    2     │ WORKSPACE_DB — Per-workspace state.vscdb                 │
│          │   Source: workspaceStorage/{hash}/state.vscdb            │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: workspace.json → folder URI           │
├──────────┴──────────────────────────────────────────────────────────┤
│ Both layers are ALWAYS executed. No skipping.                       │
│ Deduplication: prompt[:200] prefix matching.                        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import base64
import glob
import json
import logging
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.kiro")


def _kiro_app_support() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Kiro" / "User"
    elif system == "Linux":
        return Path.home() / ".config" / "Kiro" / "User"
    elif system == "Windows":
        return Path.home() / "AppData" / "Roaming" / "Kiro" / "User"
    return Path.home() / ".kiro"


def _kiro_global_storage() -> Path:
    return _kiro_app_support() / "globalStorage"


def _kiro_workspace_storage() -> Path:
    return _kiro_app_support() / "workspaceStorage"


def _kiro_agent_dir() -> Path:
    return _kiro_global_storage() / "kiro.kiroagent"


class KiroAdapter(BaseAdapter):

    def name(self) -> str:
        return "Kiro"

    def detect(self) -> bool:
        return _kiro_agent_dir().exists() or _kiro_global_storage().exists()

    def get_db_paths(self) -> list[str]:
        paths: list[str] = []
        agent_dir = _kiro_agent_dir()
        if agent_dir.exists():
            ws_sessions = agent_dir / "workspace-sessions"
            if ws_sessions.exists():
                for f in ws_sessions.rglob("*.json"):
                    paths.append(str(f))

        ws_dir = _kiro_workspace_storage()
        if ws_dir.exists():
            for sub in ws_dir.iterdir():
                db = sub / "state.vscdb"
                if db.exists():
                    paths.append(str(db))
        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        return [
            SniffLayer(
                name="workspace_sessions",
                description="Kiro Agent workspace-sessions JSON conversations",
                priority=1,
                speed="fast",
                scan_fn=self._layer_workspace_sessions,
            ),
            SniffLayer(
                name="workspace_db",
                description="Kiro workspace state.vscdb databases",
                priority=2,
                speed="fast",
                scan_fn=self._layer_workspace_dbs,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Layer 1: Workspace Sessions (kiro.kiroagent) ──

    def _layer_workspace_sessions(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        ws_sessions_dir = _kiro_agent_dir() / "workspace-sessions"
        if not ws_sessions_dir.exists():
            return results

        for project_dir in ws_sessions_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_path = self._decode_b64_dirname(project_dir.name)
            project_name = Path(project_path).name if project_path else project_dir.name

            sessions_file = project_dir / "sessions.json"
            if not sessions_file.exists():
                continue

            try:
                sessions = json.loads(sessions_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(sessions, list):
                continue

            for session_meta in sessions:
                if not isinstance(session_meta, dict):
                    continue
                session_id = session_meta.get("sessionId", "")
                session_title = session_meta.get("title", "")
                date_created = session_meta.get("dateCreated")

                session_file = project_dir / f"{session_id}.json"
                if not session_file.exists():
                    continue

                convos = self._parse_session_file(
                    session_file, since, session_id, session_title, date_created
                )
                for c in convos:
                    c.project_name = project_name
                    c.project_path = project_path
                results.extend(convos)

        logger.info("[workspace_sessions] Found %d conversations", len(results))
        return results

    def _parse_session_file(
        self,
        path: Path,
        since: Optional[datetime],
        session_id: str,
        session_title: str,
        date_created: str | None,
    ) -> list[RawConversation]:
        results: list[RawConversation] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return results

        history = data.get("history", [])
        if not isinstance(history, list):
            return results

        session_ts = self._parse_ts_value(date_created) or datetime.utcnow()

        log_responses = self._load_qchat_responses(session_id)
        resp_idx = 0

        prompt_buf = ""
        response_buf = ""
        ts = session_ts

        for entry in history:
            if not isinstance(entry, dict):
                continue
            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            role = message.get("role", "")
            content = self._extract_message_content(message)
            if not content:
                continue

            if role == "user":
                if prompt_buf and response_buf:
                    if not since or ts >= since:
                        results.append(RawConversation(
                            timestamp=ts,
                            prompt=prompt_buf,
                            response=response_buf.strip(),
                            session_id=session_id,
                            model_name="kiro-agent",
                        ))
                prompt_buf = content
                response_buf = ""
            elif role == "assistant":
                real_resp = ""
                if resp_idx < len(log_responses):
                    real_resp = log_responses[resp_idx]
                    resp_idx += 1
                if real_resp and len(real_resp) > len(content):
                    response_buf += real_resp + "\n"
                else:
                    response_buf += content + "\n"

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts,
                    prompt=prompt_buf,
                    response=response_buf.strip(),
                    session_id=session_id,
                    model_name="kiro-agent",
                ))

        return results

    @staticmethod
    def _extract_message_content(message: dict) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p).strip()
        return ""

    # ── Layer 2: Workspace DBs ──

    def _layer_workspace_dbs(self, since: Optional[datetime] = None) -> list[RawConversation]:
        import sqlite3
        results: list[RawConversation] = []
        ws_dir = _kiro_workspace_storage()
        if not ws_dir.exists():
            return results

        for sub in ws_dir.iterdir():
            if not sub.is_dir():
                continue
            db_path = sub / "state.vscdb"
            if not db_path.exists():
                continue

            project_name, project_path = self._resolve_workspace_project(sub)

            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row

                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}

                if "ItemTable" not in tables:
                    conn.close()
                    continue

                rows = conn.execute("SELECT key, value FROM ItemTable").fetchall()
                for row in rows:
                    key = row["key"]
                    value = row["value"]
                    if not value or not isinstance(value, str):
                        continue
                    if "chat" in key.lower() or "composer" in key.lower() or "kiro" in key.lower():
                        try:
                            data = json.loads(value)
                            convos = self._parse_generic_messages(data, since)
                            for c in convos:
                                c.project_name = project_name
                                c.project_path = project_path
                            results.extend(convos)
                        except (json.JSONDecodeError, TypeError):
                            continue
                conn.close()
            except Exception as e:
                logger.debug("Failed to read Kiro DB %s: %s", db_path, e)

        logger.info("[workspace_db] Found %d conversations", len(results))
        return results

    def _parse_generic_messages(self, data, since: Optional[datetime]) -> list[RawConversation]:
        results: list[RawConversation] = []
        messages = []
        if isinstance(data, list):
            messages = data
        elif isinstance(data, dict):
            for key in ("messages", "history", "conversations", "allComposers"):
                if key in data and isinstance(data[key], list):
                    messages = data[key]
                    break

        prompt_buf = ""
        response_buf = ""
        ts = datetime.utcnow()

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", msg.get("type", ""))
            content = self._extract_message_content(msg) or msg.get("text", "")
            if not content:
                continue

            if role in ("user", "human"):
                if prompt_buf and response_buf:
                    if not since or ts >= since:
                        results.append(RawConversation(
                            timestamp=ts, prompt=prompt_buf, response=response_buf.strip()
                        ))
                prompt_buf = content
                response_buf = ""
            elif role in ("assistant", "ai", "bot"):
                response_buf += content + "\n"

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf, response=response_buf.strip()
                ))
        return results

    # ── Q Chat API Log Parsing ──

    _qchat_cache: dict[str, list[str]] | None = None

    def _load_qchat_responses(self, session_id: str) -> list[str]:
        """Load real AI responses from Kiro Q Chat API logs, keyed by conversationId."""
        if self._qchat_cache is None:
            self._qchat_cache = self._parse_all_qchat_logs()
        return self._qchat_cache.get(session_id, [])

    @staticmethod
    def _parse_all_qchat_logs() -> dict[str, list[str]]:
        """Parse all Q Chat API log files and group responses by conversationId."""
        result: dict[str, list[str]] = {}
        logs_dir = _kiro_app_support().parent / "logs"
        if not logs_dir.exists():
            return result

        log_files = glob.glob(str(logs_dir / "**" / "*Q Chat API*"), recursive=True)
        for log_path in log_files:
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue

            conv_id_for_next_resp = ""
            for block in content.split("=" * 31):
                block = block.strip()
                if not block:
                    continue
                try:
                    data = json.loads(block)
                except (json.JSONDecodeError, ValueError):
                    continue

                if "request" in data:
                    cs = data["request"].get("conversationState", {})
                    conv_id_for_next_resp = cs.get("conversationId", "")
                elif "response" in data and conv_id_for_next_resp:
                    r = data["response"]
                    full = r.get("fullResponse", "")
                    events = r.get("events", [])
                    parts = []
                    for ev in events:
                        are = ev.get("assistantResponseEvent")
                        if are:
                            parts.append(are.get("content", ""))
                        tue = ev.get("toolUseEvent")
                        if tue:
                            name = tue.get("name", "unknown")
                            parts.append(f"[Tool: {name}]")
                    text = "".join(parts) if parts else full
                    if text.startswith("```json") and len(text) < 100:
                        continue
                    stripped = text.strip().strip("`").strip()
                    if stripped.startswith('json\n'):
                        stripped = stripped[5:].strip()
                    if stripped.startswith("{") and stripped.endswith("}") and len(stripped) < 100:
                        try:
                            obj = json.loads(stripped)
                            if isinstance(obj, dict) and {"chat", "do", "spec"} & set(obj.keys()):
                                continue
                        except (json.JSONDecodeError, ValueError):
                            pass
                    if text.strip():
                        result.setdefault(conv_id_for_next_resp, []).append(text.strip())

        return result

    # ── Helpers ──

    @staticmethod
    def _decode_b64_dirname(encoded: str) -> str:
        """Kiro encodes workspace paths as URL-safe base64 directory names."""
        try:
            padded = encoded.replace("_", "=").replace("-", "+")
            padding = 4 - len(padded) % 4
            if padding != 4:
                padded += "=" * padding
            return base64.b64decode(padded).decode("utf-8")
        except Exception:
            return encoded

    @staticmethod
    def _resolve_workspace_project(ws_dir: Path) -> tuple[str, str]:
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                folder = data.get("folder", "")
                if folder.startswith("file://"):
                    from urllib.parse import unquote
                    decoded = unquote(folder[7:])
                    return Path(decoded).name, decoded
            except (json.JSONDecodeError, OSError):
                pass
        return ws_dir.name, ""

    @staticmethod
    def _parse_ts_value(raw) -> Optional[datetime]:
        if raw is None:
            return None
        try:
            if isinstance(raw, str) and raw.isdigit():
                raw = int(raw)
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
