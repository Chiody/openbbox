# Contributing to OpenBBox | 贡献指南

Thank you for your interest in contributing to OpenBBox! Whether it's a bug fix, new adapter, or documentation improvement, every contribution matters.

感谢你对 OpenBBox 的关注！无论是修复 Bug、添加新适配器还是改进文档，每一份贡献都很重要。

---

## Quick Start for Contributors

```bash
git clone https://github.com/Chiody/openbbox.git
cd openbbox
make install
source .venv/bin/activate
make dev  # starts server with auto-reload at http://localhost:9966
```

---

## Project Structure

```text
openbbox/
├── adapters/                # IDE-specific data readers
│   ├── base.py              # BaseAdapter interface + RawConversation model
│   ├── cursor_adapter.py    # Cursor: SQLite + JSONL + ItemTable
│   ├── trae_adapter.py      # Trae: SQLite KV + ItemTable
│   ├── claudecode_adapter.py # Claude Code: JSONL file watch
│   ├── vscode_adapter.py    # VS Code: Copilot/Cline/Roo Code/Continue
│   ├── windsurf_adapter.py  # Windsurf: Cascade SQLite
│   ├── codex_adapter.py     # Codex: CLI PTY capture
│   ├── claude_desktop_adapter.py # Claude Desktop (cloud-only)
│   ├── git_observer.py      # Git diff capture via GitPython
│   ├── pty_wrapper.py       # PTY terminal wrapper for CLI tools
│   └── registry.py          # Auto-detection & adapter management
├── core/                    # Core engine
│   ├── models.py            # PulseNode, ProjectDNA, SourceIDE (Pydantic)
│   ├── storage.py           # SQLite persistence (WAL mode)
│   ├── matcher.py           # Weighted temporal matching algorithm
│   ├── diff_parser.py       # Unified diff parsing & statistics
│   └── exporter.py          # Markdown / JSON / prompt-list export
├── server/
│   └── app.py               # FastAPI + WebSocket + REST API + SSE
├── cli/
│   └── main.py              # Click CLI with Rich output
├── protocol/
│   └── schema.json          # PulseNode JSON Schema v1.0
├── dashboard/
│   └── index.html           # Three-column SPA (zero build deps)
├── docs/
│   ├── index.html           # Landing page (bilingual)
│   ├── ARCHITECTURE.md       # Technical deep dive
│   └── PROTOCOL.md          # OpenPulse data protocol
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── install.sh               # macOS/Linux installer
├── install.ps1              # Windows installer
└── requirements.txt
```

---

## How to Add a New IDE Adapter

This is the most common contribution. Follow these steps:

### 1. Create the adapter file

Create `adapters/your_ide_adapter.py`:

```python
from adapters.base import BaseAdapter, RawConversation, SniffLayer

class YourIdeAdapter(BaseAdapter):
    def name(self) -> str:
        return "YourIDE"

    def detect(self) -> bool:
        """Return True if this IDE is installed on the current machine."""
        # Check for config directories, CLI commands, or app bundles
        return Path("~/.your-ide").expanduser().exists()

    def get_db_paths(self) -> list[str]:
        """Return paths to data files this adapter can read."""
        return [str(p) for p in self._find_db_files()]

    def get_sniff_strategy(self) -> list[SniffLayer]:
        """Define scanning layers (fast → deep)."""
        return [
            SniffLayer(name="quick_scan", description="Fast KV lookup", speed="fast"),
            SniffLayer(name="deep_scan", description="Full conversation parse", speed="medium"),
        ]

    def poll_new(self, since=None) -> list[RawConversation]:
        """Read conversations from the IDE's data store."""
        conversations = []
        # ... your parsing logic ...
        return conversations
```

### 2. Register the adapter

In `adapters/registry.py`, import and add your adapter:

```python
from adapters.your_ide_adapter import YourIdeAdapter

ALL_ADAPTERS = [
    # ... existing adapters ...
    YourIdeAdapter(),
]
```

### 3. Add the IDE to the data model

In `core/models.py`, add the enum value:

```python
class SourceIDE(str, Enum):
    # ... existing ...
    YOURIDE = "YourIDE"
```

### 4. Update the dashboard

In `dashboard/index.html`, add the IDE icon SVG to the `renderIdeGrid` function.

### 5. Test

```bash
make start
# Open http://localhost:9966
# Click the scan button — your new IDE should appear
```

---

## Code Style Guidelines

- **Python**: Follow PEP 8. Use type hints. Prefer `pathlib.Path` over `os.path`.
- **Imports**: Use `from __future__ import annotations` in all Python files.
- **Error Handling**: Catch specific exceptions. Never silently swallow errors in adapters — log them.
- **SQLite Safety**: Always open IDE databases in read-only mode (`?mode=ro`). Never write to IDE databases.
- **HTML/CSS/JS**: The dashboard is a single-file SPA. Keep it that way — no build tools, no npm.
- **i18n**: All user-facing strings must have both English and Chinese translations.

---

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Windsurf adapter with SQLite sniffing
fix: handle empty conversation in Trae adapter
docs: update architecture diagram
refactor: extract common SQLite logic to base adapter
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`

---

## Pull Request Process

1. **Fork** the repository and create a feature branch
2. **Write** your changes following the code style guidelines
3. **Test** locally with `make start` — verify the dashboard works
4. **Commit** with a clear conventional commit message
5. **Open a PR** with:
   - A clear description of what changed and why
   - Screenshots if UI changes are involved
   - Which IDEs you tested with

---

## Reporting Issues

Use the [GitHub Issue templates](.github/ISSUE_TEMPLATE/) to report:

- **Bug Reports**: Include your OS, Python version, IDE version, and error logs
- **Feature Requests**: Describe the use case and expected behavior
- **New IDE Support**: Tell us which IDE and where it stores conversation data

---

## Development Tips

### Inspecting IDE databases

```bash
# Find Cursor's database
ls ~/Library/Application\ Support/Cursor/User/globalStorage/state.vscdb

# Open in read-only mode
sqlite3 "file:path/to/state.vscdb?mode=ro" ".tables"

# Dump KV keys
sqlite3 "file:path/to/state.vscdb?mode=ro" "SELECT key FROM ItemTable LIMIT 20"
```

### Running the API docs

```bash
make start
# Open http://localhost:9966/docs for interactive Swagger UI
```

### Checking adapter detection

```bash
python -m cli.main status
```

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
