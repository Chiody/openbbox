"""
Git Observer — Enhanced with patterns from Aider's repo.py.

Watches a local git repository for file changes and captures standardized diffs.
Handles empty repos, encoding issues, and provides combined staged+unstaged diffs.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.models import FileDiff

logger = logging.getLogger("openbbox.git")

# Specific git exceptions to catch (inspired by Aider)
try:
    import git
    import git.exc

    GIT_ERRORS = (
        git.exc.ODBError,
        git.exc.GitError,
        git.exc.InvalidGitRepositoryError,
        git.exc.GitCommandNotFound,
        OSError,
        IndexError,
        BufferError,
        TypeError,
        ValueError,
    )
except ImportError:
    git = None  # type: ignore
    GIT_ERRORS = (Exception,)

# File patterns to ignore during monitoring
IGNORE_PATTERNS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".next",
    ".venv",
    "venv",
    ".DS_Store",
    "*.pyc",
    "*.pyo",
}


class GitDiffCapture:
    """
    Captures git diffs from a local repository.
    Uses repo.git.diff() API (Aider pattern) for reliability with empty repos.
    """

    def __init__(self, repo_path: str, encoding: str = "utf-8"):
        self.repo_path = Path(repo_path).resolve()
        self.encoding = encoding
        self._repo: Optional[git.Repo] = None

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            self._repo = git.Repo(
                str(self.repo_path),
                search_parent_directories=True,
                odbt=git.GitDB,
            )
        return self._repo

    def _has_commits(self) -> bool:
        """Check if the current branch has any commits (handles empty repos)."""
        try:
            active_branch = self.repo.active_branch
            return any(self.repo.iter_commits(active_branch))
        except (TypeError, *GIT_ERRORS):
            return False

    def get_dirty_files(self) -> list[str]:
        """Get all dirty files (staged + unstaged), Aider-style."""
        try:
            dirty = set()
            staged = self.repo.git.diff("--name-only", "--cached").splitlines()
            dirty.update(f for f in staged if f.strip())
            unstaged = self.repo.git.diff("--name-only").splitlines()
            dirty.update(f for f in unstaged if f.strip())
            # Untracked files
            untracked = self.repo.untracked_files
            dirty.update(untracked)
            return sorted(dirty)
        except GIT_ERRORS as e:
            logger.debug("Failed to get dirty files: %s", e)
            return []

    def get_combined_diff(self, file_paths: Optional[list[str]] = None) -> list[FileDiff]:
        """
        Get combined staged + unstaged diffs.
        Handles empty repos gracefully (Aider pattern).
        """
        try:
            fnames = file_paths or []
            raw_diff = ""

            if self._has_commits():
                args = ["HEAD", "--"] + fnames if fnames else ["HEAD"]
                raw_diff = self.repo.git.diff(
                    *args, stdout_as_string=False
                ).decode(self.encoding, errors="replace")
            else:
                # Empty repo: get staged and unstaged separately
                cached_args = ["--cached", "--"] + fnames if fnames else ["--cached"]
                wd_args = ["--"] + fnames if fnames else []

                staged = self.repo.git.diff(
                    *cached_args, stdout_as_string=False
                ).decode(self.encoding, errors="replace")
                unstaged = self.repo.git.diff(
                    *wd_args, stdout_as_string=False
                ).decode(self.encoding, errors="replace") if wd_args else ""
                raw_diff = staged + "\n" + unstaged

            return self._parse_unified_diff(raw_diff)
        except GIT_ERRORS as e:
            logger.debug("Failed to get combined diff: %s", e)
            return []

    def get_unstaged_diff(self) -> list[FileDiff]:
        """Get unstaged diffs (working tree vs index)."""
        try:
            raw = self.repo.git.diff(stdout_as_string=False).decode(
                self.encoding, errors="replace"
            )
            return self._parse_unified_diff(raw)
        except GIT_ERRORS as e:
            logger.debug("Failed to get unstaged diff: %s", e)
            return []

    def get_staged_diff(self) -> list[FileDiff]:
        """Get staged diffs (index vs HEAD)."""
        try:
            raw = self.repo.git.diff(
                "--cached", stdout_as_string=False
            ).decode(self.encoding, errors="replace")
            return self._parse_unified_diff(raw)
        except GIT_ERRORS as e:
            logger.debug("Failed to get staged diff: %s", e)
            return []

    def get_recent_commits(self, count: int = 5) -> list[dict]:
        """Get recent commit info for context."""
        commits = []
        try:
            for commit in self.repo.iter_commits(max_count=count):
                commits.append({
                    "hash": commit.hexsha[:8],
                    "message": commit.message.strip(),
                    "author": str(commit.author),
                    "timestamp": datetime.fromtimestamp(commit.committed_date).isoformat(),
                    "files_changed": len(commit.stats.files),
                })
        except GIT_ERRORS:
            pass
        return commits

    @staticmethod
    def _parse_unified_diff(raw_diff: str) -> list[FileDiff]:
        """Parse raw unified diff output into structured FileDiff objects."""
        if not raw_diff.strip():
            return []

        results: list[FileDiff] = []
        current_file = ""
        current_hunk_lines: list[str] = []
        change_type = "modified"

        for line in raw_diff.split("\n"):
            if line.startswith("diff --git"):
                # Save previous file's diff
                if current_file and current_hunk_lines:
                    results.append(FileDiff(
                        file_path=current_file,
                        hunk="\n".join(current_hunk_lines),
                        change_type=change_type,
                    ))
                # Parse new file path from "diff --git a/path b/path"
                parts = line.split(" b/", 1)
                current_file = parts[1] if len(parts) > 1 else ""
                current_hunk_lines = []
                change_type = "modified"
            elif line.startswith("new file"):
                change_type = "added"
            elif line.startswith("deleted file"):
                change_type = "deleted"
            elif line.startswith("rename"):
                change_type = "renamed"
            elif line.startswith(("@@", "+", "-", " ")) and current_file:
                current_hunk_lines.append(line)

        # Don't forget the last file
        if current_file and current_hunk_lines:
            results.append(FileDiff(
                file_path=current_file,
                hunk="\n".join(current_hunk_lines),
                change_type=change_type,
            ))

        return results


class FileChangeEvent:
    """Represents a detected file change with timestamp and metadata."""

    def __init__(self, file_path: str, change_type: str, timestamp: datetime):
        self.file_path = file_path
        self.change_type = change_type
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"FileChange({self.change_type}: {self.file_path})"


class RepoFileHandler(FileSystemEventHandler):
    """Watches for file changes in a repo, with smart filtering."""

    def __init__(self, callback: Callable[[FileChangeEvent], None]):
        super().__init__()
        self.callback = callback

    def _should_ignore(self, path: str) -> bool:
        for pattern in IGNORE_PATTERNS:
            if pattern in path:
                return True
        return False

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or self._should_ignore(str(event.src_path)):
            return
        self.callback(FileChangeEvent(
            file_path=str(event.src_path),
            change_type="modified",
            timestamp=datetime.utcnow(),
        ))

    def on_created(self, event: FileSystemEvent):
        if event.is_directory or self._should_ignore(str(event.src_path)):
            return
        self.callback(FileChangeEvent(
            file_path=str(event.src_path),
            change_type="added",
            timestamp=datetime.utcnow(),
        ))

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory or self._should_ignore(str(event.src_path)):
            return
        self.callback(FileChangeEvent(
            file_path=str(event.src_path),
            change_type="deleted",
            timestamp=datetime.utcnow(),
        ))


class GitRepoWatcher:
    """Watches a git repository directory for file system changes."""

    def __init__(self, repo_path: str, on_change: Callable[[FileChangeEvent], None]):
        self.repo_path = repo_path
        self.on_change = on_change
        self._observer: Optional[Observer] = None

    def start(self):
        handler = RepoFileHandler(self.on_change)
        self._observer = Observer()
        self._observer.schedule(handler, self.repo_path, recursive=True)
        self._observer.start()
        logger.info("Git watcher started for: %s", self.repo_path)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Git watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
