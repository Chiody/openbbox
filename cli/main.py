"""
OpenBBox CLI — Enhanced with PTY wrapper, rich status, and search.

Commands:
  start     Start the server + background scanner
  scan      One-time scan of all detected IDE logs
  status    Show detected IDEs, DB stats, and system health
  export    Export prompts in various formats
  wrap      Launch an AI CLI tool inside the PTY wrapper
  search    Search captured prompts by keyword
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


@click.group()
@click.version_option(version="0.2.0", prog_name="openbbox")
def cli():
    """OpenBBox (脉络) — The DNA of AI-Driven Development"""
    pass


@cli.command()
@click.option("--port", default=9966, help="Server port")
@click.option("--host", default="0.0.0.0", help="Server host")
@click.option("--no-scan", is_flag=True, help="Don't run background scanner")
def start(port: int, host: str, no_scan: bool):
    """Start the OpenBBox server and background scanner."""
    console.print(Panel.fit(
        "[bold cyan]OpenBBox[/bold cyan] | [bold magenta]脉络[/bold magenta]\n"
        "[dim]The DNA of AI-Driven Development[/dim]",
        border_style="cyan",
    ))

    if not no_scan:
        scan_thread = threading.Thread(target=_background_scan, daemon=True)
        scan_thread.start()
        console.print("[green]✓[/green] Background scanner started")

    console.print(f"[green]✓[/green] Server starting at http://{host}:{port}")
    console.print(f"[dim]  Dashboard: http://localhost:{port}/[/dim]")
    console.print(f"[dim]  Landing:   http://localhost:{port}/landing[/dim]")
    console.print(f"[dim]  API docs:  http://localhost:{port}/docs[/dim]")

    try:
        import uvicorn
        uvicorn.run("server.app:app", host=host, port=port, log_level="info")
    except Exception as e:
        console.print(f"\n[red]Server failed to start: {e}[/red]")
        console.print()
        console.print("[cyan]💡 Paste this to your AI assistant to fix it:[/cyan]")
        console.print(f'[dim]  "The OpenBBox server failed with: {e}')
        console.print(f'   Entry point: PYTHONPATH=. python3 cli/main.py start --port {port}')
        console.print('   Diagnose and fix the issue."[/dim]')
        raise


@cli.command()
@click.option("--since", default=None, help="Only scan since this ISO datetime")
def scan(since: str | None):
    """One-time scan of all detected IDE conversation logs."""
    from adapters.registry import get_available_adapters
    from core.matcher import TemporalMatcher
    from core.models import SourceIDE
    from core.storage import PulseStorage

    since_dt = datetime.fromisoformat(since) if since else None

    adapters = get_available_adapters()
    if not adapters:
        console.print("[yellow]No AI IDEs detected on this machine.[/yellow]")
        console.print()
        console.print("[cyan]💡 Ask your AI assistant to help debug:[/cyan]")
        console.print('[dim]  "OpenBBox detected no IDEs. I use [Cursor/VS Code/Kiro/Trae].')
        console.print('   Check if the adapter paths exist on my system and run a manual scan."[/dim]')
        return

    storage = PulseStorage()
    matcher = TemporalMatcher()
    total_found = 0

    for adapter in adapters:
        console.print(f"\n[cyan]Scanning {adapter.name()}...[/cyan]")
        try:
            conversations = adapter.poll_new(since=since_dt)
            console.print(f"  Found [bold]{len(conversations)}[/bold] conversations")
            total_found += len(conversations)

            ide_enum = _name_to_ide(adapter.name())
            for convo in conversations:
                matcher.add_prompt(convo, ide_enum)

            nodes = matcher.flush()
            for node in nodes:
                storage.save_node(node)

            console.print(f"  Saved [green]{len(nodes)}[/green] PulseNodes")
        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")

    console.print(f"\n[bold green]Scan complete:[/bold green] {total_found} conversations processed")


@cli.command()
def status():
    """Show detected IDEs, database stats, and system health."""
    from adapters.registry import get_all_adapters
    from core.storage import PulseStorage

    console.print(Panel.fit(
        "[bold cyan]OpenBBox System Status[/bold cyan]",
        border_style="cyan",
    ))

    # Adapter detection
    table = Table(title="IDE Detection", show_header=True, header_style="bold cyan")
    table.add_column("IDE", style="bold")
    table.add_column("Status")
    table.add_column("DB Files")
    table.add_column("Data Sources")

    for adapter in get_all_adapters():
        detected = adapter.detect()
        status_text = "[green]✓ Detected[/green]" if detected else "[dim]Not found[/dim]"
        db_count = len(adapter.get_db_paths()) if detected else 0
        sources = ", ".join(Path(p).name for p in adapter.get_db_paths()[:3]) if detected else "—"
        table.add_row(adapter.name(), status_text, str(db_count), sources or "—")

    console.print(table)

    # Storage stats
    storage = PulseStorage()
    node_count = storage.count_nodes()
    dna_count = len(storage.list_dna())

    stats_table = Table(title="Storage", show_header=True, header_style="bold magenta")
    stats_table.add_column("Metric")
    stats_table.add_column("Value", justify="right")
    stats_table.add_row("Total PulseNodes", str(node_count))
    stats_table.add_row("Total Projects (DNA)", str(dna_count))

    db_path = Path.home() / ".openbbox" / "openbbox.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        stats_table.add_row("Database Size", f"{size_mb:.1f} MB")
    else:
        stats_table.add_row("Database Size", "0 MB (not created)")

    console.print(stats_table)


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["markdown", "json", "prompts"]), default="prompts")
@click.option("--project", default=None, help="Filter by project ID")
@click.option("--output", "-o", default=None, help="Output file path")
def export(fmt: str, project: str | None, output: str | None):
    """Export captured prompts and interactions."""
    from core.exporter import PromptExporter
    from core.storage import PulseStorage

    storage = PulseStorage()
    nodes = storage.list_nodes(project_id=project, limit=10000)

    if not nodes:
        console.print("[yellow]No data to export.[/yellow]")
        return

    if fmt == "markdown":
        content = PromptExporter.to_markdown(nodes, "OpenBBox Export")
    elif fmt == "json":
        content = PromptExporter.to_json(nodes, "OpenBBox Export")
    else:
        content = PromptExporter.to_prompt_list(nodes)

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


@cli.command()
@click.argument("query")
@click.option("--limit", default=20, help="Max results")
def search(query: str, limit: int):
    """Search captured prompts by keyword."""
    from core.storage import PulseStorage

    storage = PulseStorage()
    all_nodes = storage.list_nodes(limit=10000)
    q = query.lower()

    matched = [
        n for n in all_nodes
        if q in n.intent.raw_prompt.lower()
        or q in n.intent.clean_title.lower()
        or q in n.execution.ai_response.lower()
    ]

    if not matched:
        console.print(f"[yellow]No results for '{query}'[/yellow]")
        return

    table = Table(title=f"Search: '{query}' ({len(matched)} results)", show_header=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("IDE", width=10)
    table.add_column("Prompt", max_width=60)
    table.add_column("Files Changed", width=12, justify="right")

    for i, node in enumerate(matched[:limit], 1):
        table.add_row(
            str(i),
            node.source.ide.value,
            node.intent.clean_title or node.intent.raw_prompt[:50],
            str(len(node.execution.affected_files)),
        )

    console.print(table)


@cli.command()
@click.argument("command", default="claude")
@click.argument("args", nargs=-1)
def wrap(command: str, args: tuple):
    """Launch an AI CLI tool inside the PTY wrapper for capture.

    Example: openbbox wrap claude
    """
    import platform
    if platform.system() == "Windows":
        console.print("[red]PTY wrapper is not supported on Windows.[/red]")
        return

    from adapters.pty_wrapper import PTYWrapper
    from core.matcher import TemporalMatcher
    from core.models import SourceIDE
    from core.storage import PulseStorage

    storage = PulseStorage()
    matcher = TemporalMatcher()

    def on_exchange(convo):
        console.print(f"\n[cyan]Captured:[/cyan] {convo.prompt[:60]}...")
        matcher.add_prompt(convo, SourceIDE.CLAUDECODE)
        nodes = matcher.flush()
        for node in nodes:
            storage.save_node(node)

    console.print(Panel.fit(
        f"[bold cyan]PTY Wrapper[/bold cyan]\n"
        f"[dim]Wrapping: {command} {' '.join(args)}[/dim]\n"
        f"[dim]All interactions will be captured by OpenBBox.[/dim]",
        border_style="cyan",
    ))

    wrapper = PTYWrapper(
        command=command,
        args=list(args),
        on_exchange=on_exchange,
    )
    exit_code = wrapper.start()
    console.print(f"\n[dim]Process exited with code {exit_code}[/dim]")


# ── Helpers ──

def _name_to_ide(name: str):
    from core.models import SourceIDE
    mapping = {
        "cursor": SourceIDE.CURSOR,
        "trae": SourceIDE.TRAE,
        "claudecode": SourceIDE.CLAUDECODE,
        "vscode": SourceIDE.VSCODE,
        "codex": SourceIDE.CODEX,
        "kiro": SourceIDE.KIRO,
    }
    return mapping.get(name.lower(), SourceIDE.UNKNOWN)


def _background_scan():
    """Background thread that periodically scans IDE logs."""
    import logging
    bg_logger = logging.getLogger("openbbox.bg_scan")

    from adapters.registry import get_available_adapters
    from core.matcher import TemporalMatcher
    from core.storage import PulseStorage

    storage = PulseStorage()
    last_scan = datetime.utcnow() - timedelta(hours=24)

    while True:
        try:
            adapters = get_available_adapters()
            matcher = TemporalMatcher()

            for adapter in adapters:
                try:
                    conversations = adapter.poll_new(since=last_scan)
                    ide_enum = _name_to_ide(adapter.name())
                    for convo in conversations:
                        matcher.add_prompt(convo, ide_enum)
                    if conversations:
                        bg_logger.info("%s: %d conversations", adapter.name(), len(conversations))
                except Exception as e:
                    bg_logger.warning("%s scan failed: %s", adapter.name(), e)

            nodes = matcher.flush()
            for node in nodes:
                storage.save_node(node)
            if nodes:
                bg_logger.info("Saved %d new nodes", len(nodes))

            last_scan = datetime.utcnow()
        except Exception as e:
            bg_logger.error("Background scan error: %s", e)

        time.sleep(30)


if __name__ == "__main__":
    cli()
