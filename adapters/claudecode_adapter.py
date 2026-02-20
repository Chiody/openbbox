"""
Claude Code CLI Adapter — Standard Sniff Strategy
==================================================

Claude Code stores conversation data under ~/.claude/:
  - ~/.claude/projects/{encoded-path}/*.jsonl — per-project sessions
  - ~/.claude/projects/{encoded-path}/CLAUDE.md — project memory
  - ~/.claude/*.jsonl — top-level session files

The encoded path format: -Users-username-project → /Users/username/project

┌─────────────────────────────────────────────────────────────────────┐
│                  CLAUDE CODE SNIFF STRATEGY                         │
├──────────┬──────────────────────────────────────────────────────────┤
│ Priority │ Layer                                                    │
├──────────┼──────────────────────────────────────────────────────────┤
│    1     │ PROJECT_SESSIONS — Per-project JSONL session files       │
│          │   Source: ~/.claude/projects/{path}/*.jsonl              │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: directory name → decoded path          │
│          │   Coverage: All project-specific conversations            │
│          │                                                          │
│    2     │ TOP_LEVEL_FILES — Root-level JSONL/JSON files            │
│          │   Source: ~/.claude/*.jsonl, ~/.claude/*.json             │
│          │   Speed: FAST (<1s)                                      │
│          │   Project context: NONE                                  │
│          │   Coverage: Non-project conversations                    │
├──────────┴──────────────────────────────────────────────────────────┤
│ Both layers are ALWAYS executed. No skipping.                       │
│ Deduplication: prompt[:200] prefix matching.                        │
└─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from adapters.base import BaseAdapter, RawConversation, SniffLayer

logger = logging.getLogger("openbbox.claudecode")


def _claude_base_path() -> Path:
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home()))
        return Path(appdata) / ".claude"
    return Path.home() / ".claude"


class ClaudeCodeAdapter(BaseAdapter):
    def name(self) -> str:
        return "ClaudeCode"

    def detect(self) -> bool:
        base = _claude_base_path()
        if base.exists():
            return True
        try:
            result = subprocess.run(
                ["which", "claude"], capture_output=True, timeout=3
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def get_db_paths(self) -> list[str]:
        base = _claude_base_path()
        if not base.exists():
            return []

        paths: list[str] = []
        projects_dir = base / "projects"
        if projects_dir.exists():
            for project_dir in projects_dir.iterdir():
                if project_dir.is_dir():
                    for jsonl in project_dir.glob("*.jsonl"):
                        paths.append(str(jsonl))

        for jsonl in base.glob("*.jsonl"):
            paths.append(str(jsonl))
        for jf in base.glob("*.json"):
            paths.append(str(jf))

        return paths

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """Two layers, both always executed."""
        return [
            SniffLayer(
                name="project_sessions",
                description="Per-project JSONL sessions (~/.claude/projects/)",
                priority=1,
                speed="fast",
                scan_fn=self._layer_project_sessions,
            ),
            SniffLayer(
                name="top_level_files",
                description="Root-level JSONL/JSON files (~/.claude/)",
                priority=2,
                speed="fast",
                scan_fn=self._layer_top_level_files,
            ),
        ]

    def poll_new(self, since: Optional[datetime] = None) -> list[RawConversation]:
        return self.poll_with_progress(since=since)

    def poll_with_progress(self, since=None, on_progress=None):
        result = super().poll_with_progress(since=since, on_progress=on_progress)
        return self._deduplicate(result)

    # ── Layer 1: Project Sessions ──

    def _layer_project_sessions(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        projects_dir = _claude_base_path() / "projects"
        if not projects_dir.exists():
            return results

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_path = self._decode_project_path(project_dir.name)
            project_name = Path(project_path).name if project_path else project_dir.name

            for jsonl_file in sorted(project_dir.glob("*.jsonl")):
                session_id = self._extract_session_id(jsonl_file)
                convos = self._read_jsonl(jsonl_file, since)
                for c in convos:
                    c.project_name = project_name
                    c.project_path = project_path
                    c.session_id = session_id
                results.extend(convos)

        logger.info("[project_sessions] Found %d conversations", len(results))
        return results

    # ── Layer 2: Top-level Files ──

    def _layer_top_level_files(self, since: Optional[datetime] = None) -> list[RawConversation]:
        results: list[RawConversation] = []
        base = _claude_base_path()
        if not base.exists():
            return results

        for jsonl in base.glob("*.jsonl"):
            results.extend(self._read_jsonl(jsonl, since))
        for jf in base.glob("*.json"):
            results.extend(self._read_json(jf, since))

        logger.info("[top_level_files] Found %d conversations", len(results))
        return results

    # ── JSONL Parser (Claude Code format) ──

    def _read_jsonl(self, path: Path, since: Optional[datetime]) -> list[RawConversation]:
        """
        Claude Code JSONL format: each line is a message object with
        role (user/assistant/system) and content (string or content blocks).
        """
        results: list[RawConversation] = []
        prompt_buf = ""
        response_buf = ""

        try:
            file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            file_mtime = datetime.utcnow()

        ts = file_mtime

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
                    msg_ts = self._parse_timestamp(entry)

                    if role in ("user", "human"):
                        if prompt_buf and response_buf:
                            if not since or ts >= since:
                                results.append(RawConversation(
                                    timestamp=ts,
                                    prompt=prompt_buf,
                                    response=response_buf,
                                ))
                        prompt_buf = content if content else ""
                        response_buf = ""
                        ts = msg_ts or file_mtime

                    elif role in ("assistant", "ai"):
                        if content:
                            response_buf += content + "\n"
                        tool_blocks = self._extract_tool_use(entry)
                        if tool_blocks:
                            response_buf += tool_blocks

        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Failed to read JSONL %s: %s", path, e)

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts,
                    prompt=prompt_buf,
                    response=response_buf.strip(),
                ))

        return results

    def _read_json(self, path: Path, since: Optional[datetime]) -> list[RawConversation]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        if isinstance(data, list):
            return self._parse_message_list(data, since)
        if isinstance(data, dict):
            for key in ("messages", "conversation", "history"):
                if key in data and isinstance(data[key], list):
                    return self._parse_message_list(data[key], since)
        return []

    def _parse_message_list(
        self, messages: list, since: Optional[datetime]
    ) -> list[RawConversation]:
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
            elif role in ("assistant", "ai"):
                response_buf += content + "\n"

        if prompt_buf and response_buf:
            if not since or ts >= since:
                results.append(RawConversation(
                    timestamp=ts, prompt=prompt_buf, response=response_buf.strip()
                ))

        return results

    # ── Helpers ──

    @staticmethod
    def _extract_content(entry: dict) -> str:
        content = entry.get("content", entry.get("text", entry.get("message", "")))
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        parts.append(f"[Tool: {block.get('name', '')}]")
                    elif btype == "tool_result":
                        parts.append(f"[Result: {str(block.get('content', ''))[:100]}]")
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p)
        return str(content) if content else ""

    @staticmethod
    def _extract_tool_use(entry: dict) -> str:
        content = entry.get("content", [])
        if not isinstance(content, list):
            return ""
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = json.dumps(block.get("input", {}), ensure_ascii=False)[:200]
                parts.append(f"\n[Tool: {tool_name} — {tool_input}]")
        return "".join(parts)

    @staticmethod
    def _parse_timestamp(entry: dict) -> Optional[datetime]:
        for key in ("timestamp", "createdAt", "created_at", "time"):
            if key in entry:
                try:
                    raw = entry[key]
                    if isinstance(raw, (int, float)):
                        return datetime.fromtimestamp(raw / 1000 if raw > 1e12 else raw)
                    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except (ValueError, OSError):
                    pass
        return None

    @staticmethod
    def _decode_project_path(encoded: str) -> str:
        """Decode: -Users-username-project → /Users/username/project"""
        if encoded.startswith("-"):
            return "/" + encoded[1:].replace("-", "/")
        return encoded

    @staticmethod
    def _extract_session_id(path: Path) -> str:
        stem = path.stem
        if stem.startswith("session-"):
            return stem.replace("session-", "")
        return stem

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
