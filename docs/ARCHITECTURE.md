# OpenBBox Architecture | 脉络技术架构

> Deep dive into the Shadow Listener engine, Temporal Matching algorithm, and data pipeline.

---

## Overview

OpenBBox operates as a **"Shadow Observer"** — a side-car process that passively reads local AI IDE databases and file systems without modifying them. It never injects code into IDEs or installs plugins.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Your Machine                              │
│                                                                  │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐          │
│  │ Cursor   │  │  Trae   │  │Claude CLI│  │ VS Code │  ...     │
│  │ (SQLite) │  │(SQLite) │  │ (JSONL)  │  │(SQLite) │          │
│  └────┬─────┘  └────┬────┘  └────┬─────┘  └────┬────┘          │
│       │              │            │              │               │
│       └──────────────┴────────────┴──────────────┘               │
│                          │ read-only                             │
│                    ┌─────▼──────┐                                │
│                    │  OpenBBox  │                                │
│                    │  Adapters  │                                │
│                    └─────┬──────┘                                │
│                          │                                       │
│                    ┌─────▼──────┐     ┌──────────────┐          │
│                    │  Temporal  │────▶│ ~/.openbbox/  │          │
│                    │  Matcher   │     │ openbbox.db   │          │
│                    └─────┬──────┘     └──────────────┘          │
│                          │                                       │
│                    ┌─────▼──────┐                                │
│                    │  FastAPI   │                                │
│                    │  Server    │                                │
│                    └─────┬──────┘                                │
│                          │ :9966                                 │
│                    ┌─────▼──────┐                                │
│                    │ Dashboard  │                                │
│                    │ (Browser)  │                                │
│                    └────────────┘                                │
└──────────────────────────────────────────────────────────────────┘
```

---

## 1. Shadow Listener Engine (Adapter Layer)

Each IDE stores AI conversation data differently. OpenBBox uses a **pluggable adapter architecture** to normalize all sources into a common `RawConversation` format.

### Adapter Interface

Every adapter implements `BaseAdapter`:

```python
class BaseAdapter:
    def name(self) -> str: ...
    def detect(self) -> bool: ...
    def get_db_paths(self) -> list[str]: ...
    def get_sniff_strategy(self) -> list[SniffLayer]: ...
    def poll_new(self, since=None) -> list[RawConversation]: ...
```

### Sniffing Strategies by IDE

| IDE | Storage Type | Read Method | Key Data Source |
|-----|-------------|-------------|-----------------|
| **Cursor** | SQLite (state.vscdb) + JSONL | WAL-mode read-only | `cursorDiskKV.bubbleId:*` keys → JSON blobs containing conversation trees; `agent-transcripts/*.jsonl` for full session logs; `ItemTable` for workspace-scoped data |
| **Trae** | SQLite (state.vscdb) | WAL-mode read-only | KV table with `aiService.conversations` key; `ItemTable` for deep conversation data |
| **Claude Code** | JSONL files + memory | File system watch | `~/.claude/projects/{encoded-path}/*.jsonl` — each file is a session; `memory/` for persistent context |
| **VS Code** | SQLite (state.vscdb) | WAL-mode read-only | Extension-specific keys: `github.copilot.chat`, `cline.chatHistory`, `roo-cline.chatHistory`, `continue.sessions` |
| **Windsurf** | SQLite (state.vscdb) | WAL-mode read-only | Cascade workspace storage in `~/.codeium/windsurf/` |
| **Codex** | PTY capture | Terminal I/O | Wraps the Codex CLI in a pseudo-terminal to capture stdin/stdout |

### Multi-Layer Scanning

Each adapter defines a **sniff strategy** — an ordered list of scan layers with increasing depth:

```
Layer 1: "kv_quick"     — Fast KV table scan (~100ms)
Layer 2: "item_deep"    — Full ItemTable parse (~500ms)
Layer 3: "transcript"   — JSONL file scan (~2s)
```

The scan engine runs layers sequentially, reporting progress via SSE (Server-Sent Events) to the dashboard.

### SQLite Safety

All database reads use:
- `PRAGMA journal_mode` check (WAL mode preferred)
- `?mode=ro` URI parameter for read-only access
- `PRAGMA query_only = ON` as a safety net
- Connection timeout of 5 seconds to avoid blocking IDE operations

---

## 2. Temporal Matching Algorithm

The core challenge: **"Which code change was caused by which prompt?"**

OpenBBox solves this with a weighted multi-signal scoring algorithm.

### The Formula

```
Score = α · TimeProximity + β · FileOverlap + γ · KeywordSimilarity
```

Where:
- **α = 0.5** — Time proximity (inverse of time delta)
- **β = 0.3** — File overlap between context files and changed files
- **γ = 0.2** — Keyword overlap between prompt text and diff content

### Signal Breakdown

#### Signal 1: Time Proximity (α = 0.5)

When a prompt is detected, a **capture window** (default: 90 seconds) opens. All file changes within this window are candidates.

```
TimeScore = 1 / (1 + ΔT / 10)
```

Where ΔT is the absolute time difference in seconds between the prompt and the closest file change.

#### Signal 2: File Overlap (β = 0.3)

Compares the files referenced in the prompt context against the files actually modified:

```
FileScore = |ContextFiles ∩ ModifiedFiles| / |ContextFiles|
```

This catches cases where a user says "fix the bug in auth.py" and `auth.py` is indeed modified.

#### Signal 3: Keyword Similarity (γ = 0.2)

Extracts identifiers (camelCase, snake_case, PascalCase tokens of 3+ chars) from both the prompt and the diff hunks:

```
KeywordScore = |PromptKeywords ∩ DiffKeywords| / |PromptKeywords|
```

Common noise words (`the`, `and`, `import`, `def`, etc.) are filtered out.

### Clean Title Generation

Raw prompts are cleaned for display:
1. Strip XML wrapper tags (`<user_query>`, `<system_reminder>`)
2. Remove filler phrases ("please", "help me", "帮我", "请")
3. Capitalize first letter
4. Truncate to 80 characters

---

## 3. Data Pipeline

```
IDE Logs → Adapter.poll_new() → RawConversation[]
                                        │
                                        ▼
                              TemporalMatcher.add_prompt()
                                        │
                                        ▼
                              TemporalMatcher.flush()
                                        │
                                        ▼
                                   PulseNode[]
                                        │
                                        ▼
                              PulseStorage.save_node()
                                        │
                                        ▼
                              ~/.openbbox/openbbox.db (SQLite WAL)
```

### PulseNode Structure

The atomic unit of OpenBBox. See [protocol/schema.json](../protocol/schema.json) for the full JSON Schema.

```
PulseNode
├── id (UUID)
├── timestamp (ISO 8601)
├── project_id / project_name
├── source
│   ├── ide (Cursor | Trae | ClaudeCode | VSCode | ...)
│   ├── model_name (claude-3.5-sonnet, gpt-4o, ...)
│   └── session_id
├── intent
│   ├── raw_prompt (original user text)
│   ├── clean_title (auto-generated display title)
│   └── context_files[]
├── execution
│   ├── ai_response (full AI output)
│   ├── reasoning (extracted chain-of-thought)
│   ├── diffs[] (file_path, hunk, change_type)
│   └── affected_files[]
├── status (pending | completed | failed)
└── token_usage
```

### ProjectDNA

An ordered sequence of PulseNode IDs forming a project's complete evolution history. This is the "DNA" — the full lineage from first prompt to current state.

---

## 4. Server Architecture

### FastAPI Application

- **REST API** — CRUD for nodes, projects, memos, README generation
- **WebSocket** — Real-time push of new PulseNodes to connected dashboards
- **SSE** — Streaming scan progress during IDE discovery
- **Static Files** — Serves the dashboard SPA and landing page

### Key Endpoints

| Category | Endpoint | Purpose |
|----------|----------|---------|
| System | `GET /api/health` | Health check |
| Discovery | `GET /api/adapters` | List IDEs with detection status |
| Discovery | `GET /api/scan/discover` | SSE stream of scan progress |
| Import | `POST /api/scan/import` | Import selected projects |
| Data | `GET /api/nodes` | List PulseNodes (paginated) |
| Data | `GET /api/search?q=` | Full-text search |
| Export | `GET /api/export/markdown` | Markdown Director's Script |
| Export | `GET /api/export/json` | .pulse JSON format |
| Realtime | `WS /ws` | Live node push |

### Thread Model

- Scan operations run in a `ThreadPoolExecutor(max_workers=2)` to avoid blocking the async event loop
- Background scanner runs as a daemon thread with 30-second intervals
- WebSocket connections are managed in a simple list with automatic cleanup

---

## 5. Dashboard Architecture

The dashboard is a single-file SPA (`dashboard/index.html`) with zero build dependencies:

- **Three-Column Layout**: Source list → Prompt timeline → AI response + diff viewer
- **Inline i18n**: Full Chinese/English toggle with `localStorage` persistence
- **Custom Tooltip System**: Fixed-position tooltips for IDE status cards
- **SSE Integration**: Real-time scan progress with animated progress bars
- **Diff Renderer**: Syntax-highlighted unified diff display with line numbers

---

## 6. PTY Wrapper (Terminal Capture)

For CLI-based AI tools (Claude Code, Codex, Aider), OpenBBox provides a PTY (pseudo-terminal) wrapper:

```bash
openbbox wrap claude
```

This creates a transparent proxy:
1. Spawns the target CLI in a pseudo-terminal
2. Captures all stdin (user prompts) and stdout (AI responses)
3. Detects conversation boundaries using heuristics (prompt markers, response patterns)
4. Feeds captured exchanges into the standard TemporalMatcher pipeline

> **Note:** PTY wrapper is not available on Windows due to platform limitations.

---

## 7. Security Model

| Aspect | Implementation |
|--------|---------------|
| **Data Locality** | All data stored in `~/.openbbox/`. Zero network calls. |
| **Read-Only Access** | IDE databases opened with `?mode=ro` and `PRAGMA query_only = ON` |
| **No Telemetry** | No analytics, no tracking, no phone-home |
| **No IDE Modification** | No plugins, no extensions, no code injection |
| **User Control** | Delete `~/.openbbox/` to remove all OpenBBox data |
