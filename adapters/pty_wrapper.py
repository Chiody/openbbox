"""
PTY Terminal Wrapper — Inspired by Asciinema's recording architecture.

Wraps CLI AI tools (Claude Code, Aider, etc.) in a pseudo-terminal,
transparently capturing all input/output while the user interacts normally.

Usage:
    wrapper = PTYWrapper("claude", on_exchange=callback)
    wrapper.start()  # Blocks until the child process exits
"""

from __future__ import annotations

import io
import os
import platform
import re
import select
import signal
import sys
from datetime import datetime
from typing import Callable, Optional

from adapters.base import RawConversation

# PTY is only available on Unix-like systems
IS_UNIX = platform.system() != "Windows"
if IS_UNIX:
    import fcntl
    import pty
    import struct
    import termios
    import tty


class PTYWrapper:
    """
    Wraps a CLI command in a pseudo-terminal for transparent I/O capture.
    Inspired by asciinema's PTY forwarding logic.
    """

    def __init__(
        self,
        command: str = "claude",
        args: Optional[list[str]] = None,
        on_exchange: Optional[Callable[[RawConversation], None]] = None,
        prompt_pattern: str = r"^(Human|User|>)\s*:?\s*",
        response_pattern: str = r"^(Assistant|Claude|AI)\s*:?\s*",
    ):
        self.command = command
        self.args = args or []
        self.on_exchange = on_exchange
        self.prompt_re = re.compile(prompt_pattern, re.MULTILINE | re.IGNORECASE)
        self.response_re = re.compile(response_pattern, re.MULTILINE | re.IGNORECASE)

        self._output_buffer = io.StringIO()
        self._current_prompt = ""
        self._current_response = ""
        self._last_prompt_time: Optional[datetime] = None
        self._child_pid: Optional[int] = None

    def start(self) -> int:
        """
        Start the wrapped process. Blocks until it exits.
        Returns the child's exit code.
        """
        if not IS_UNIX:
            raise RuntimeError("PTY wrapper requires a Unix-like OS (macOS/Linux)")

        # Create a pseudo-terminal pair
        master_fd, slave_fd = pty.openpty()

        pid = os.fork()
        if pid == 0:
            # Child process: run the actual command
            os.close(master_fd)
            os.setsid()

            # Set the slave as the controlling terminal
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            os.dup2(slave_fd, 0)  # stdin
            os.dup2(slave_fd, 1)  # stdout
            os.dup2(slave_fd, 2)  # stderr
            os.close(slave_fd)

            os.execvp(self.command, [self.command] + self.args)
        else:
            # Parent process: relay I/O and capture
            os.close(slave_fd)
            self._child_pid = pid

            # Match terminal size
            self._sync_terminal_size(master_fd)

            try:
                self._relay_loop(master_fd)
            except (OSError, KeyboardInterrupt):
                pass
            finally:
                os.close(master_fd)
                _, status = os.waitpid(pid, 0)
                self._flush_pending()
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1

        return 0

    def _relay_loop(self, master_fd: int):
        """Main I/O relay loop — reads from both stdin and the child's PTY."""
        stdin_fd = sys.stdin.fileno()

        # Put stdin into raw mode so keystrokes pass through immediately
        old_settings = termios.tcgetattr(stdin_fd)
        try:
            tty.setraw(stdin_fd)

            while True:
                readable, _, _ = select.select([stdin_fd, master_fd], [], [], 0.1)

                for fd in readable:
                    if fd == stdin_fd:
                        # User input -> forward to child
                        data = os.read(stdin_fd, 4096)
                        if not data:
                            return
                        os.write(master_fd, data)
                        # Capture user input for prompt detection
                        self._process_input(data)

                    elif fd == master_fd:
                        # Child output -> forward to user's terminal + capture
                        try:
                            data = os.read(master_fd, 4096)
                        except OSError:
                            return
                        if not data:
                            return
                        os.write(sys.stdout.fileno(), data)
                        # Capture output for response detection
                        self._process_output(data)

        finally:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)

    def _process_input(self, data: bytes):
        """Process user input to detect prompt boundaries."""
        try:
            text = data.decode("utf-8", errors="replace")
            # Newline usually means the user submitted a prompt
            if "\r" in text or "\n" in text:
                buf = self._output_buffer.getvalue()
                if buf.strip():
                    self._flush_pending()
                    self._current_prompt = buf.strip()
                    self._last_prompt_time = datetime.utcnow()
                    self._output_buffer = io.StringIO()
        except Exception:
            pass

    def _process_output(self, data: bytes):
        """Process child output to capture AI responses."""
        try:
            text = data.decode("utf-8", errors="replace")
            # Strip ANSI escape codes for clean capture
            clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
            clean = re.sub(r"\x1b\][^\x07]*\x07", "", clean)
            self._output_buffer.write(clean)
        except Exception:
            pass

    def _flush_pending(self):
        """If we have a prompt+response pair, emit it."""
        if self._current_prompt and self._output_buffer.getvalue().strip():
            response = self._output_buffer.getvalue().strip()
            if len(response) > 20:  # Ignore trivial output
                convo = RawConversation(
                    timestamp=self._last_prompt_time or datetime.utcnow(),
                    prompt=self._current_prompt,
                    response=response,
                )
                if self.on_exchange:
                    self.on_exchange(convo)

            self._current_prompt = ""
            self._output_buffer = io.StringIO()

    @staticmethod
    def _sync_terminal_size(master_fd: int):
        """Copy the current terminal size to the PTY."""
        try:
            size = struct.pack("HHHH", 0, 0, 0, 0)
            result = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, size)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, result)
        except (OSError, AttributeError):
            pass

    def stop(self):
        """Send SIGTERM to the child process."""
        if self._child_pid:
            try:
                os.kill(self._child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
