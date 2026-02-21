"""
OpenBBox Core Data Models — PulseNode & ProjectDNA

PulseNode is the atomic unit: one prompt-response cycle with its code impact.
ProjectDNA is the lineage: an ordered sequence of PulseNodes forming a project's evolution.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceIDE(str, Enum):
    CURSOR = "Cursor"
    TRAE = "Trae"
    CLAUDECODE = "ClaudeCode"
    VSCODE = "VSCode"
    WINDSURF = "Windsurf"
    CODEX = "Codex"
    KIRO = "Kiro"
    CLINE = "Cline"
    AIDER = "Aider"
    UNKNOWN = "Unknown"


class NodeStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class FileDiff(BaseModel):
    file_path: str
    hunk: str  # standard git diff hunk
    change_type: str = "modified"  # modified / added / deleted


class Intent(BaseModel):
    raw_prompt: str
    clean_title: str = ""
    context_files: list[str] = Field(default_factory=list)


class Execution(BaseModel):
    ai_response: str = ""
    reasoning: str = ""
    diffs: list[FileDiff] = Field(default_factory=list)
    affected_files: list[str] = Field(default_factory=list)


class SourceMeta(BaseModel):
    ide: SourceIDE = SourceIDE.UNKNOWN
    model_name: str = ""
    session_id: str = ""


class PulseNode(BaseModel):
    """The atomic unit of OpenBBox — one prompt/response cycle."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    project_id: str = ""
    project_name: str = ""
    source: SourceMeta = Field(default_factory=SourceMeta)
    intent: Intent
    execution: Execution = Field(default_factory=Execution)
    status: NodeStatus = NodeStatus.COMPLETED
    token_usage: int = 0


class ProjectDNA(BaseModel):
    """Ordered sequence of PulseNodes — the full evolution of a project."""

    dna_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_name: str = ""
    project_path: str = ""
    source_ide: SourceIDE = SourceIDE.UNKNOWN
    nodes: list[str] = Field(default_factory=list)  # ordered list of PulseNode IDs
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_prompts(self) -> int:
        return len(self.nodes)
