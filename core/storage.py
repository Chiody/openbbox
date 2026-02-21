"""
OpenBBox Local Storage — SQLite-backed persistence for PulseNodes and ProjectDNA.
All data stays on localhost. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.models import (
    Execution,
    FileDiff,
    Intent,
    NodeStatus,
    ProjectDNA,
    PulseNode,
    SourceIDE,
    SourceMeta,
)

DEFAULT_DB_PATH = Path.home() / ".openbbox" / "openbbox.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pulse_nodes (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    project_name TEXT NOT NULL DEFAULT '',
    source_ide TEXT NOT NULL DEFAULT 'Unknown',
    source_model TEXT NOT NULL DEFAULT '',
    source_session TEXT NOT NULL DEFAULT '',
    raw_prompt TEXT NOT NULL,
    clean_title TEXT NOT NULL DEFAULT '',
    context_files TEXT NOT NULL DEFAULT '[]',
    ai_response TEXT NOT NULL DEFAULT '',
    reasoning TEXT NOT NULL DEFAULT '',
    diffs TEXT NOT NULL DEFAULT '[]',
    affected_files TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    token_usage INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_dna (
    dna_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL DEFAULT '',
    project_path TEXT NOT NULL DEFAULT '',
    source_ide TEXT NOT NULL DEFAULT 'Unknown',
    node_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_key TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    memo_type TEXT NOT NULL DEFAULT 'note',
    pinned INTEGER NOT NULL DEFAULT 0,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_readme (
    project_key TEXT PRIMARY KEY,
    markdown TEXT NOT NULL DEFAULT '',
    blocks TEXT NOT NULL DEFAULT '[]',
    template_id TEXT NOT NULL DEFAULT 'default',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON pulse_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_nodes_timestamp ON pulse_nodes(timestamp);
CREATE INDEX IF NOT EXISTS idx_dna_project ON project_dna(project_name);
CREATE INDEX IF NOT EXISTS idx_memos_project ON project_memos(project_key);
"""


class PulseStorage:
    """Synchronous SQLite storage for OpenBBox data."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA_SQL)
            self._migrate()
        return self._conn

    def _migrate(self):
        """Add columns that may be missing from older DB versions."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(project_memos)").fetchall()}
        if "memo_type" not in cols:
            self._conn.execute('ALTER TABLE project_memos ADD COLUMN memo_type TEXT NOT NULL DEFAULT "note"')
        if "meta" not in cols:
            self._conn.execute('ALTER TABLE project_memos ADD COLUMN meta TEXT NOT NULL DEFAULT "{}"')
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── PulseNode CRUD ──

    def save_node(self, node: PulseNode) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO pulse_nodes
            (id, timestamp, project_id, project_name, source_ide, source_model,
             source_session, raw_prompt, clean_title, context_files,
             ai_response, reasoning, diffs, affected_files, status, token_usage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                node.id,
                node.timestamp.isoformat(),
                node.project_id,
                node.project_name,
                node.source.ide.value,
                node.source.model_name,
                node.source.session_id,
                node.intent.raw_prompt,
                node.intent.clean_title,
                json.dumps(node.intent.context_files),
                node.execution.ai_response,
                node.execution.reasoning,
                json.dumps([d.model_dump() for d in node.execution.diffs]),
                json.dumps(node.execution.affected_files),
                node.status.value,
                node.token_usage,
            ),
        )
        self.conn.commit()

    def get_node(self, node_id: str) -> Optional[PulseNode]:
        row = self.conn.execute(
            "SELECT * FROM pulse_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def list_nodes(
        self,
        project_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PulseNode]:
        if project_id:
            rows = self.conn.execute(
                "SELECT * FROM pulse_nodes WHERE project_id = ? ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM pulse_nodes ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def aggregate_projects(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT
                project_name,
                project_id,
                GROUP_CONCAT(DISTINCT source_ide) as source_ides,
                COUNT(*) as total_prompts,
                MIN(timestamp) as first_timestamp,
                MAX(timestamp) as last_timestamp
            FROM pulse_nodes
            GROUP BY COALESCE(project_name, project_id, '(Uncategorized)')
            ORDER BY total_prompts DESC
        """).fetchall()
        results = []
        for r in rows:
            results.append({
                "project_name": r[0] or r[1] or "(Uncategorized)",
                "project_path": r[1] or "",
                "source_ides": sorted(set(r[2].split(",") if r[2] else [])),
                "total_prompts": r[3],
                "first_timestamp": r[4],
                "last_timestamp": r[5],
            })
        return results

    def count_nodes(self, project_id: Optional[str] = None) -> int:
        if project_id:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM pulse_nodes WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM pulse_nodes").fetchone()
        return row[0]

    def delete_node(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM pulse_nodes WHERE id = ?", (node_id,))
        self.conn.commit()

    # ── ProjectDNA CRUD ──

    def save_dna(self, dna: ProjectDNA) -> None:
        dna.updated_at = datetime.utcnow()
        self.conn.execute(
            """INSERT OR REPLACE INTO project_dna
            (dna_id, project_name, project_path, source_ide, node_ids, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                dna.dna_id,
                dna.project_name,
                dna.project_path,
                dna.source_ide.value,
                json.dumps(dna.nodes),
                dna.created_at.isoformat(),
                dna.updated_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_dna(self, dna_id: str) -> Optional[ProjectDNA]:
        row = self.conn.execute(
            "SELECT * FROM project_dna WHERE dna_id = ?", (dna_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dna(row)

    def list_dna(self) -> list[ProjectDNA]:
        rows = self.conn.execute(
            "SELECT * FROM project_dna ORDER BY updated_at DESC"
        ).fetchall()
        return [self._row_to_dna(r) for r in rows]

    def get_or_create_dna(
        self, project_name: str, project_path: str, source_ide: SourceIDE
    ) -> ProjectDNA:
        row = self.conn.execute(
            "SELECT * FROM project_dna WHERE project_path = ? AND source_ide = ?",
            (project_path, source_ide.value),
        ).fetchone()
        if row:
            return self._row_to_dna(row)
        dna = ProjectDNA(
            project_name=project_name,
            project_path=project_path,
            source_ide=source_ide,
        )
        self.save_dna(dna)
        return dna

    def append_node_to_dna(self, dna_id: str, node_id: str) -> None:
        dna = self.get_dna(dna_id)
        if dna and node_id not in dna.nodes:
            dna.nodes.append(node_id)
            self.save_dna(dna)

    # ── Project Memos ──

    def list_memos(self, project_key: str, memo_type: Optional[str] = None) -> list[dict]:
        if memo_type:
            rows = self.conn.execute(
                "SELECT * FROM project_memos WHERE project_key = ? AND memo_type = ? ORDER BY pinned DESC, updated_at DESC",
                (project_key, memo_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM project_memos WHERE project_key = ? ORDER BY pinned DESC, updated_at DESC",
                (project_key,),
            ).fetchall()
        return [self._row_to_memo(r) for r in rows]

    def add_memo(self, project_key: str, content: str, memo_type: str = "note",
                 pinned: bool = False, meta: Optional[dict] = None) -> dict:
        now = datetime.utcnow().isoformat()
        meta_json = json.dumps(meta or {})
        cur = self.conn.execute(
            "INSERT INTO project_memos (project_key, content, memo_type, pinned, meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_key, content, memo_type, int(pinned), meta_json, now, now),
        )
        self.conn.commit()
        return {"id": cur.lastrowid, "project_key": project_key, "content": content,
                "memo_type": memo_type, "pinned": pinned, "meta": meta or {},
                "created_at": now, "updated_at": now}

    def update_memo(self, memo_id: int, content: Optional[str] = None,
                    pinned: Optional[bool] = None, meta: Optional[dict] = None) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM project_memos WHERE id = ?", (memo_id,)).fetchone()
        if not row:
            return None
        new_content = content if content is not None else row["content"]
        new_pinned = int(pinned) if pinned is not None else row["pinned"]
        new_meta = json.dumps(meta) if meta is not None else row["meta"]
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            "UPDATE project_memos SET content = ?, pinned = ?, meta = ?, updated_at = ? WHERE id = ?",
            (new_content, new_pinned, new_meta, now, memo_id),
        )
        self.conn.commit()
        return self._row_to_memo(self.conn.execute("SELECT * FROM project_memos WHERE id = ?", (memo_id,)).fetchone())

    def delete_memo(self, memo_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM project_memos WHERE id = ?", (memo_id,))
        self.conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row_to_memo(row: sqlite3.Row) -> dict:
        meta_raw = row["meta"] if "meta" in row.keys() else "{}"
        try:
            meta = json.loads(meta_raw)
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return {
            "id": row["id"],
            "project_key": row["project_key"],
            "content": row["content"],
            "memo_type": row["memo_type"] if "memo_type" in row.keys() else "note",
            "pinned": bool(row["pinned"]),
            "meta": meta,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── Project README ──

    def get_readme(self, project_key: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM project_readme WHERE project_key = ?", (project_key,)
        ).fetchone()
        if not row:
            return None
        return {
            "project_key": row["project_key"],
            "markdown": row["markdown"],
            "blocks": json.loads(row["blocks"]),
            "template_id": row["template_id"],
            "updated_at": row["updated_at"],
        }

    def save_readme(self, project_key: str, markdown: str,
                    blocks: Optional[list] = None, template_id: str = "default") -> dict:
        now = datetime.utcnow().isoformat()
        blocks_json = json.dumps(blocks or [])
        self.conn.execute(
            """INSERT OR REPLACE INTO project_readme
            (project_key, markdown, blocks, template_id, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
            (project_key, markdown, blocks_json, template_id, now),
        )
        self.conn.commit()
        return {"project_key": project_key, "markdown": markdown,
                "blocks": blocks or [], "template_id": template_id, "updated_at": now}

    # ── Helpers ──

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> PulseNode:
        diffs_raw = json.loads(row["diffs"])
        return PulseNode(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            project_id=row["project_id"],
            project_name=row["project_name"],
            source=SourceMeta(
                ide=SourceIDE(row["source_ide"]),
                model_name=row["source_model"],
                session_id=row["source_session"],
            ),
            intent=Intent(
                raw_prompt=row["raw_prompt"],
                clean_title=row["clean_title"],
                context_files=json.loads(row["context_files"]),
            ),
            execution=Execution(
                ai_response=row["ai_response"],
                reasoning=row["reasoning"],
                diffs=[FileDiff(**d) for d in diffs_raw],
                affected_files=json.loads(row["affected_files"]),
            ),
            status=NodeStatus(row["status"]),
            token_usage=row["token_usage"],
        )

    @staticmethod
    def _row_to_dna(row: sqlite3.Row) -> ProjectDNA:
        return ProjectDNA(
            dna_id=row["dna_id"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            source_ide=SourceIDE(row["source_ide"]),
            nodes=json.loads(row["node_ids"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
