"""
Diff Parser — Standardized unified diff parsing and summarization.

Inspired by python-unidiff and what-the-diff projects.
Normalizes diff output from various sources into a clean, structured format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.models import FileDiff


@dataclass
class DiffStats:
    """Statistics for a single file diff."""
    file_path: str
    lines_added: int = 0
    lines_deleted: int = 0
    change_type: str = "modified"

    @property
    def total_changes(self) -> int:
        return self.lines_added + self.lines_deleted

    @property
    def summary(self) -> str:
        parts = []
        if self.lines_added:
            parts.append(f"+{self.lines_added}")
        if self.lines_deleted:
            parts.append(f"-{self.lines_deleted}")
        return f"{self.file_path} ({', '.join(parts)})" if parts else self.file_path


@dataclass
class DiffSummary:
    """Aggregated summary of all diffs in a change set."""
    files: list[DiffStats] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_additions(self) -> int:
        return sum(f.lines_added for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.lines_deleted for f in self.files)

    @property
    def short_summary(self) -> str:
        return f"{self.total_files} file(s), +{self.total_additions} -{self.total_deletions}"

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "files": [
                {
                    "path": f.file_path,
                    "added": f.lines_added,
                    "deleted": f.lines_deleted,
                    "type": f.change_type,
                }
                for f in self.files
            ],
        }


def parse_unified_diff(raw_diff: str) -> list[FileDiff]:
    """
    Parse raw unified diff text into structured FileDiff objects.
    Handles standard git diff output format.
    """
    if not raw_diff or not raw_diff.strip():
        return []

    results: list[FileDiff] = []
    current_file = ""
    current_lines: list[str] = []
    change_type = "modified"

    for line in raw_diff.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_lines:
                results.append(FileDiff(
                    file_path=current_file,
                    hunk="\n".join(current_lines),
                    change_type=change_type,
                ))
            # Extract file path: "diff --git a/path b/path"
            match = re.search(r"b/(.+)$", line)
            current_file = match.group(1) if match else ""
            current_lines = []
            change_type = "modified"
        elif line.startswith("new file"):
            change_type = "added"
        elif line.startswith("deleted file"):
            change_type = "deleted"
        elif line.startswith("rename from"):
            change_type = "renamed"
        elif line.startswith(("@@", "+", "-", " ")) and current_file:
            current_lines.append(line)

    if current_file and current_lines:
        results.append(FileDiff(
            file_path=current_file,
            hunk="\n".join(current_lines),
            change_type=change_type,
        ))

    return results


def calculate_diff_stats(diffs: list[FileDiff]) -> DiffSummary:
    """Calculate statistics for a list of FileDiff objects."""
    summary = DiffSummary()
    for diff in diffs:
        stats = DiffStats(file_path=diff.file_path, change_type=diff.change_type)
        for line in diff.hunk.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                stats.lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                stats.lines_deleted += 1
        summary.files.append(stats)
    return summary


def generate_change_summary(diffs: list[FileDiff]) -> str:
    """
    Generate a human-readable summary of code changes.
    Inspired by what-the-diff's semantic summarization approach.
    """
    if not diffs:
        return "No code changes detected."

    stats = calculate_diff_stats(diffs)
    lines: list[str] = []
    lines.append(f"Changed {stats.total_files} file(s): "
                 f"+{stats.total_additions} additions, -{stats.total_deletions} deletions")
    lines.append("")

    for file_stat in stats.files:
        icon = {"added": "+", "deleted": "-", "modified": "~", "renamed": "→"}.get(
            file_stat.change_type, "~"
        )
        lines.append(f"  {icon} {file_stat.summary}")

    return "\n".join(lines)


def extract_code_blocks_from_response(response: str) -> list[str]:
    """Extract code blocks from an AI response (fenced with ```)."""
    blocks: list[str] = []
    pattern = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(response):
        code = match.group(1).strip()
        if code:
            blocks.append(code)
    return blocks


def diff_to_html(diff: FileDiff) -> str:
    """Convert a FileDiff to syntax-highlighted HTML for the dashboard."""
    lines: list[str] = []
    for line in diff.hunk.split("\n"):
        escaped = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(f'<span class="diff-add">{escaped}</span>')
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f'<span class="diff-del">{escaped}</span>')
        elif line.startswith("@@"):
            lines.append(f'<span class="diff-hunk">{escaped}</span>')
        else:
            lines.append(f'<span class="diff-ctx">{escaped}</span>')
    return "\n".join(lines)
