<p align="center">
  <h1 align="center">🧬 OpenBBox | 脉络</h1>
  <p align="center">
    <strong>Stop Coding in the Dark. Trace the DNA of your AI-Driven Projects.</strong>
  </p>
  <p align="center">
    <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-cyan.svg" alt="License: MIT"></a>
    <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python 3.10+"></a>
    <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
    <a href="./Dockerfile"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker" alt="Docker"></a>
  </p>
  <p align="center">
    <a href="./README.md">English</a> · <a href="./README_zh.md">简体中文</a>
  </p>
</p>

---

<p align="center">
  <img src="./docs/screenshots/dashboard.png" alt="OpenBBox Dashboard — Three-column workspace" width="100%">
  <br>
  <em>The Three-Column Workspace: Prompt list → AI response → Code diff with line numbers</em>
</p>

---

## ⚡️ Why OpenBBox?

AI-assisted coding is fast, but it's a **Black Box**.

1. **The Amnesia Problem** — Can't remember the prompt that fixed that complex bug 2 weeks ago?
2. **The Silo Problem** — Great prompts in Cursor can't be reused in Trae or Claude Code.
3. **The Blackbox Problem** — Looking at a git diff but forgot what instructions led to those changes?

**OpenBBox** is a universal side-car observer. It sniffs your local AI IDE logs and Git diffs to build a permanent, reusable **DNA Sequence** of your project — the complete lineage from intent to code.

> *"Don't just code with AI. Direct it. Trace it. Preserve it."*

---

## ✨ Key Features

| Feature | Description |
|:--------|:------------|
| 🧬 **Prompt Lineage** | Every prompt captured as a clean, searchable "Genetic Code" — no chat noise |
| 📊 **Evolution Mapping** | See the "Cause" (Prompt) and "Effect" (Code Diff) in a unified timeline |
| 🔄 **Multi-IDE Sync** | One dashboard for Cursor, Trae, Claude Code, VS Code, Windsurf, Codex |
| 💾 **Asset Export** | Export your "Director's Scripts" as Markdown or `.pulse` JSON for reuse |
| 🔒 **Privacy First** | 100% local. We sniff local logs. Your data **never** leaves your machine |
| 🌐 **Bilingual UI** | Full Chinese/English toggle with one click |

---

## 📺 Showcase: Intent-to-Code Lineage

Imagine you built a secure auth module in **Project A** using Cursor. With OpenBBox, you don't just copy the code — you export the `.pulse` sequence, the exact prompt flow that guided the AI. Then you "replay" the logic in **Project B** using Trae.

**That is true leverage. Code is the result. The lineage is the asset.**

| # | Intent (The Prompt) | Evolution (The Code) | Impact |
|:--|:--------------------|:---------------------|:-------|
| 01 | "Initialize FastAPI skeleton with WebSocket routing" | `main.py` created, connection pool established | Foundation |
| 02 | "Add AES-256 encryption middleware for end-to-end security" | `security.py` with encrypt/decrypt hooks | Security |
| 03 | "Refactor: move message storage from memory to async Redis" | `db.py`, `config.py` updated | Performance |
| 04 | "Add JWT auth with refresh token rotation" | `auth.py` injected, 12 files updated | Auth |
| 05 | "Write comprehensive test suite for auth flow" | `tests/test_auth.py` with 15 test cases | Quality |

> 💡 Share the `.pulse` file and other developers can instantly see how you directed AI through these 5 architectural decisions.

---

## 🛠 Supported IDEs (2026)

| IDE | Type | Capture Method | Status |
|-----|------|----------------|--------|
| **Cursor** | Native AI IDE | SQLite + JSONL | ✅ Deep Support |
| **VS Code** | Plugin Ecosystem | Extension Storage | ✅ Supported |
| **Trae** | Native AI IDE | SQLite | ✅ Supported |
| **Claude Code** | CLI Agent | File Watch + PTY | ✅ Supported |
| **Cline / Roo Code** | VS Code Extension | Extension Storage | ✅ Supported |
| **Windsurf** | Native AI IDE | SQLite | ✅ Supported |
| **Codex** | CLI | PTY | ✅ Supported |
| **Claude Desktop** | Cloud App | API | ☁️ Cloud |

> Want to add a new IDE? See the [Contributing Guide](./CONTRIBUTING.md#how-to-add-a-new-ide-adapter).

<p align="center">
  <img src="./docs/screenshots/scan-panel.png" alt="IDE Scanner — Auto-detect installed AI IDEs" width="680">
  <br>
  <em>IDE Scanner: Auto-detects Cursor, VS Code, Trae, Codex and more on your machine</em>
</p>

---

## 🚀 Quick Start

### One-Line Install

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/Chiody/openbbox/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/Chiody/openbbox/main/install.ps1 | iex
```

### Manual Install

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
openbbox start
# Open http://localhost:9966
```

### Docker

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox
docker compose up -d
# Open http://localhost:9966
```

### Makefile Shortcuts

```bash
make install    # Set up venv + install
make start      # Start the server
make dev        # Dev mode with auto-reload
make scan       # One-time scan
make status     # Show detected IDEs
make help       # Show all commands
```

---

## 📂 Project Structure

```text
openbbox/
├── adapters/           # IDE-specific data readers (Cursor, Trae, Claude, VS Code...)
├── core/               # Engine: matching algorithm, data models, storage, export
├── server/             # FastAPI + WebSocket + REST API
├── cli/                # Click CLI with Rich output
├── protocol/           # OpenPulse JSON Schema specification
├── dashboard/          # Three-column SPA (zero build dependencies)
├── docs/               # Landing page + technical documentation
├── .github/            # Issue templates
├── Dockerfile          # Container support
├── docker-compose.yml  # One-command deployment
├── pyproject.toml      # pip install support
├── Makefile            # Developer shortcuts
├── install.sh          # macOS/Linux one-line installer
└── install.ps1         # Windows one-line installer
```

> 💡 For the full directory breakdown, see [CONTRIBUTING.md](./CONTRIBUTING.md#project-structure).

---

## 🧠 How It Works

OpenBBox operates as a **Shadow Observer** — a side-car process that passively reads local IDE databases without modifying them.

```
IDE Logs (SQLite/JSONL) ──▶ Adapters ──▶ Temporal Matcher ──▶ PulseNodes ──▶ Dashboard
                                              │
                                    Score = α·(1/ΔT) + β·FileOverlap + γ·Keywords
```

1. **Sniff** — Read-only access to IDE conversation databases
2. **Match** — Pair prompts with Git diffs using weighted temporal alignment
3. **Store** — Save structured PulseNodes to `~/.openbbox/openbbox.db`
4. **Visualize** — Three-column dashboard with search, export, and real-time updates

> 📖 For the full algorithm breakdown, see [Technical Architecture](./docs/ARCHITECTURE.md).

---

## 🔌 API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/adapters` | List IDEs with detection status |
| GET | `/api/nodes` | List PulseNodes (paginated) |
| GET | `/api/search?q=` | Search prompts by keyword |
| GET | `/api/export/markdown` | Export as Markdown |
| GET | `/api/export/json` | Export as .pulse JSON |
| WS | `/ws` | Real-time node push |

Full interactive docs at `http://localhost:9966/docs` after starting the server.

---

## 🔒 Privacy & Security

- **100% Local** — All data stored in `~/.openbbox/openbbox.db` on your machine
- **No Telemetry** — Zero network calls, no analytics, no tracking
- **Read-Only Sniffing** — IDE databases opened with `?mode=ro` and `PRAGMA query_only = ON`
- **No IDE Modification** — No plugins, no extensions, no code injection
- **Your Data, Your Control** — Delete `~/.openbbox/` to remove everything

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Technical Architecture](./docs/ARCHITECTURE.md) | Shadow Listener engine, Temporal Matching algorithm, data pipeline |
| [Contributing Guide](./CONTRIBUTING.md) | How to add new IDE adapters, code style, PR process |
| [OpenPulse Protocol](./docs/PROTOCOL.md) | PulseNode JSON Schema, export formats, versioning |

---

## 🤝 Contributing

OpenBBox is built for the community. Whether you use Cursor, Trae, or raw CLI, we need your help.

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox && make install && source .venv/bin/activate
make dev  # starts with auto-reload
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full guide.

---

## 🗺 Roadmap

- [x] Core Python sniffer engine with multi-adapter architecture
- [x] Temporal matching algorithm (Prompt → Git Diff)
- [x] Three-column web dashboard with bilingual UI
- [x] Multi-IDE support (Cursor, Trae, Claude Code, VS Code, Windsurf, Codex)
- [x] PTY terminal wrapper for CLI tools
- [x] Asset export (Markdown / JSON / prompt list)
- [ ] Community "Pulse Hub" for sharing prompt sequences
- [ ] GitHub Actions integration for automated lineage tracking
- [ ] VS Code extension for in-editor lineage view

---

## 🙏 Acknowledgments

- [Aider](https://github.com/paul-gauthier/aider) — Git monitoring patterns
- [Continue](https://github.com/continuedev/continue) — SQLite ChatHistory structure
- [Asciinema](https://github.com/asciinema/asciinema) — PTY terminal recording architecture
- [python-unidiff](https://github.com/btimby/python-unidiff) — Unified diff parsing

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](./LICENSE) for details.

---

<p align="center">
  Built with ❤️ for the AI Director era.<br>
  <strong>Open the Box. Trace the Pulse.</strong>
</p>
