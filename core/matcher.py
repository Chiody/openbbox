"""
Temporal Matcher — Enhanced with weighted scoring algorithm.

Links prompts to code changes using:
  1. Temporal proximity (time window)
  2. File-path heuristics (mentioned files vs changed files)
  3. Keyword overlap (prompt terms vs diff content)

Score = α · (1/ΔT) + β · file_overlap + γ · keyword_similarity
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from adapters.base import RawConversation
from adapters.git_observer import FileChangeEvent, GitDiffCapture
from core.models import (
    Execution,
    FileDiff,
    Intent,
    NodeStatus,
    PulseNode,
    SourceIDE,
    SourceMeta,
)

DEFAULT_WINDOW_SECONDS = 90

# Scoring weights
ALPHA_TIME = 0.5
BETA_FILE = 0.3
GAMMA_KEYWORD = 0.2


class TemporalMatcher:
    """
    Matches prompts to code diffs using a multi-signal scoring algorithm.

    Algorithm:
    1. When a new prompt arrives, open a capture window (default 90s).
    2. Collect all file changes within that window.
    3. Score the match using time proximity + file overlap + keyword similarity.
    4. Generate a PulseNode linking the prompt to the best-matching diffs.
    """

    def __init__(self, window_seconds: int = DEFAULT_WINDOW_SECONDS):
        self.window = timedelta(seconds=window_seconds)
        self._pending_prompts: list[tuple[RawConversation, SourceIDE, str, str]] = []
        self._file_changes: list[FileChangeEvent] = []

    def add_prompt(
        self,
        conversation: RawConversation,
        source_ide: SourceIDE,
        project_id: str = "",
        project_name: str = "",
    ) -> None:
        # Prefer project info from the conversation itself (adapter-detected)
        effective_name = conversation.project_name or project_name
        effective_id = conversation.project_path or project_id or effective_name
        self._pending_prompts.append((conversation, source_ide, effective_id, effective_name))

    def add_file_change(self, event: FileChangeEvent) -> None:
        self._file_changes.append(event)

    def flush(self, git_capture: Optional[GitDiffCapture] = None) -> list[PulseNode]:
        """
        Process all pending prompts and return matched PulseNodes.
        Uses the enhanced scoring algorithm for prompt-diff alignment.
        """
        now = datetime.utcnow()
        nodes: list[PulseNode] = []

        for convo, source_ide, project_id, project_name in self._pending_prompts:
            # Step 1: Find file changes in the time window
            matched_changes = self._find_changes_in_window(convo.timestamp)

            # Step 2: Get actual git diffs
            diffs: list[FileDiff] = []
            if git_capture:
                # Prefer combined diff (staged + unstaged)
                diffs = git_capture.get_combined_diff()
                if not diffs:
                    diffs = git_capture.get_unstaged_diff()

            # Step 3: If no git diffs, build from file change events
            if not diffs and matched_changes:
                diffs = [
                    FileDiff(
                        file_path=c.file_path,
                        hunk="",
                        change_type=c.change_type,
                    )
                    for c in matched_changes
                ]

            # Step 4: Score the match
            score = self._calculate_match_score(convo, diffs, matched_changes)

            # Step 5: Build affected files list
            affected_files = list({d.file_path for d in diffs})

            # Step 6: Generate clean title
            clean_title = self._generate_clean_title(convo.prompt)

            # Step 7: Extract reasoning from AI response
            reasoning = self._extract_reasoning(convo.response)

            node = PulseNode(
                timestamp=convo.timestamp,
                project_id=project_id,
                project_name=project_name,
                source=SourceMeta(
                    ide=source_ide,
                    model_name=convo.model_name,
                    session_id=convo.session_id,
                ),
                intent=Intent(
                    raw_prompt=convo.prompt,
                    clean_title=clean_title,
                    context_files=convo.context_files or [],
                ),
                execution=Execution(
                    ai_response=convo.response,
                    reasoning=reasoning,
                    diffs=diffs,
                    affected_files=affected_files,
                ),
                status=NodeStatus.COMPLETED,
            )
            nodes.append(node)

        self._pending_prompts.clear()

        # Prune old file changes (keep 2x window)
        cutoff = now - (self.window * 2)
        self._file_changes = [c for c in self._file_changes if c.timestamp > cutoff]

        return nodes

    def _find_changes_in_window(self, prompt_time: datetime) -> list[FileChangeEvent]:
        """Find file changes within the window after a prompt."""
        window_end = prompt_time + self.window
        return [
            c for c in self._file_changes
            if prompt_time <= c.timestamp <= window_end
        ]

    def _calculate_match_score(
        self,
        convo: RawConversation,
        diffs: list[FileDiff],
        changes: list[FileChangeEvent],
    ) -> float:
        """
        Calculate a weighted match score between a prompt and code changes.
        Score = α · time_score + β · file_score + γ · keyword_score
        """
        if not diffs and not changes:
            return 0.0

        # Time score: inverse of time delta (closer = higher)
        time_score = 0.0
        if changes:
            min_delta = min(
                abs((c.timestamp - convo.timestamp).total_seconds())
                for c in changes
            )
            time_score = 1.0 / (1.0 + min_delta / 10.0)

        # File overlap score: do mentioned files match changed files
        file_score = 0.0
        if convo.context_files and diffs:
            context_set = {Path(f).name for f in convo.context_files if f}
            diff_set = {Path(d.file_path).name for d in diffs if d.file_path}
            if context_set and diff_set:
                overlap = len(context_set & diff_set)
                file_score = overlap / max(len(context_set), 1)

        # Keyword similarity: do prompt words appear in diff content
        keyword_score = 0.0
        prompt_words = self._extract_keywords(convo.prompt)
        if prompt_words and diffs:
            diff_text = " ".join(d.hunk for d in diffs if d.hunk)
            diff_words = self._extract_keywords(diff_text)
            if diff_words:
                overlap = len(prompt_words & diff_words)
                keyword_score = overlap / max(len(prompt_words), 1)

        return (
            ALPHA_TIME * time_score
            + BETA_FILE * file_score
            + GAMMA_KEYWORD * keyword_score
        )

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful keywords from text (variable names, function names, etc.)."""
        # Match identifiers: camelCase, snake_case, PascalCase
        words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text))
        # Filter out common noise words
        noise = {
            "the", "and", "for", "with", "this", "that", "from", "import",
            "def", "class", "return", "self", "None", "True", "False",
            "async", "await", "function", "const", "let", "var",
        }
        return words - noise

    @staticmethod
    def _generate_clean_title(prompt: str) -> str:
        """Generate a short clean title from a raw prompt."""
        clean = prompt.strip()
        # Strip XML-like wrapper tags from Cursor transcripts
        clean = re.sub(r"</?user_query>", "", clean)
        clean = re.sub(r"</?system_reminder>", "", clean)
        clean = re.sub(r"<[^>]{1,30}>", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        # Remove common filler phrases (EN + CN)
        for prefix in ("please ", "help me ", "can you ", "i want to ", "i need to ",
                        "请", "帮我", "你能", "我想", "我需要", "你好 ", "嗨 "):
            if clean.lower().startswith(prefix):
                clean = clean[len(prefix):]
                break
        clean = clean.strip()
        if clean:
            clean = clean[0].upper() + clean[1:]
        if len(clean) > 80:
            clean = clean[:77] + "..."
        return clean

    @staticmethod
    def _extract_reasoning(response: str) -> str:
        """Extract AI reasoning/thinking from the response."""
        if not response:
            return ""
        clean = response.strip()

        # Look for thinking blocks
        thinking_match = re.search(
            r"\[Thinking:?\s*(.*?)\]", clean, re.DOTALL | re.IGNORECASE
        )
        if thinking_match:
            return thinking_match.group(1).strip()[:500]

        # Otherwise take the first meaningful paragraph
        paragraphs = clean.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if len(para) > 30 and not para.startswith(("```", "import ", "from ", "def ", "class ")):
                return para[:500]

        return clean[:500] if len(clean) > 500 else clean


# Import Path for file name extraction
from pathlib import Path
