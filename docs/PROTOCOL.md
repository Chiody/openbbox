# OpenPulse Protocol v1.0

> The standard data format for AI development evolution tracking.

---

## Overview

The **OpenPulse Protocol** defines how AI-driven development interactions are structured, stored, and exchanged. Every adapter in OpenBBox normalizes its output to this format.

The canonical schema is defined in [`protocol/schema.json`](../protocol/schema.json).

---

## PulseNode

A **PulseNode** is the atomic unit — one prompt-response cycle with its code impact.

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | UUID string | Unique identifier |
| `timestamp` | ISO 8601 datetime | When the interaction occurred |
| `source.ide` | Enum string | The AI IDE that generated this interaction |
| `intent.raw_prompt` | String | The user's original instruction |

### Full Structure

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-02-20T14:30:00Z",
  "project": {
    "id": "/Users/dev/my-project",
    "name": "my-project",
    "path": "/Users/dev/my-project"
  },
  "source": {
    "ide": "Cursor",
    "model_name": "claude-3.5-sonnet",
    "session_id": "abc123"
  },
  "intent": {
    "raw_prompt": "Add JWT authentication middleware to the Express server",
    "clean_title": "Add JWT authentication middleware",
    "context_files": ["src/server.ts", "src/middleware/auth.ts"],
    "tags": ["Feature", "Security"]
  },
  "execution": {
    "ai_response": "I'll add JWT authentication...",
    "reasoning": "The server needs token-based auth for the API endpoints...",
    "diffs": [
      {
        "file_path": "src/middleware/auth.ts",
        "hunk": "@@ -0,0 +1,25 @@\n+import jwt from 'jsonwebtoken';\n+...",
        "change_type": "added"
      }
    ],
    "affected_files": ["src/middleware/auth.ts", "src/server.ts"],
    "commits": [
      {
        "hash": "a1b2c3d",
        "message": "feat: add JWT auth middleware",
        "timestamp": "2026-02-20T14:31:00Z"
      }
    ]
  },
  "metadata": {
    "status": "completed",
    "token_usage": { "input": 1200, "output": 3500 },
    "match_score": 0.87,
    "is_manual_marked": false
  }
}
```

---

## Source IDE Enum

| Value | IDE | Capture Method |
|-------|-----|----------------|
| `Cursor` | Cursor IDE | SQLite + JSONL |
| `Trae` | Trae IDE | SQLite |
| `ClaudeCode` | Claude Code CLI | JSONL file watch |
| `VSCode` | VS Code + extensions | SQLite |
| `Windsurf` | Windsurf IDE | SQLite |
| `Codex` | OpenAI Codex CLI | PTY capture |
| `Cline` | Cline / Roo Code | VS Code extension storage |
| `Aider` | Aider CLI | PTY capture |
| `Unknown` | Unidentified source | — |

---

## Change Types

| Value | Meaning |
|-------|---------|
| `added` | New file created |
| `modified` | Existing file changed |
| `deleted` | File removed |
| `renamed` | File moved or renamed |

---

## Node Status

| Value | Meaning |
|-------|---------|
| `pending` | Prompt captured, waiting for code changes |
| `completed` | Prompt matched with code changes |
| `failed` | Prompt could not be matched |

---

## ProjectDNA

A **ProjectDNA** is an ordered sequence of PulseNode IDs representing a project's complete evolution.

```json
{
  "dna_id": "660e8400-e29b-41d4-a716-446655440001",
  "project_name": "my-project",
  "project_path": "/Users/dev/my-project",
  "source_ide": "Cursor",
  "nodes": [
    "550e8400-e29b-41d4-a716-446655440000",
    "550e8400-e29b-41d4-a716-446655440001",
    "550e8400-e29b-41d4-a716-446655440002"
  ],
  "created_at": "2026-02-01T10:00:00Z",
  "updated_at": "2026-02-20T14:30:00Z"
}
```

---

## Export Formats

### Markdown Director's Script

Human-readable export for documentation and sharing:

```markdown
# Project Evolution: my-project

## #01 — Add JWT authentication middleware
- **IDE**: Cursor (claude-3.5-sonnet)
- **Time**: 2026-02-20 14:30
- **Files**: src/middleware/auth.ts (+25), src/server.ts (+3 -1)

> Add JWT authentication middleware to the Express server

---
```

### .pulse JSON

Machine-readable export following the full PulseNode schema. Can be imported into other OpenBBox instances.

### Prompt List

Clean, copy-paste-ready list of prompts for replication:

```
1. Add JWT authentication middleware to the Express server
2. Add rate limiting to the auth endpoint
3. Write unit tests for the auth middleware
```

---

## Versioning

The protocol follows semantic versioning. The current version is **v1.0**.

Breaking changes will increment the major version. New optional fields will increment the minor version.

| Version | Changes |
|---------|---------|
| v1.0 | Initial release — PulseNode, ProjectDNA, export formats |
