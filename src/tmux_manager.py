#!/usr/bin/env python3
"""
tmux Manager
Manages tmux sessions
"""

import os
import shlex
import sys
import subprocess
import uuid
from pathlib import Path

class TmuxManager:
    """Class for managing tmux sessions"""

    def __init__(self, session_name="claude-discord-bridge"):
        self.session_name = session_name
        self.claude_session_prefix = "claude-session"

    def is_session_exists(self) -> bool:
        """Check if a tmux session exists"""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", self.session_name],
                capture_output=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            print("Error: tmux is not installed")
            return False

    def create_session(self) -> bool:
        """Create a new tmux session"""
        if self.is_session_exists():
            print(f"tmux session '{self.session_name}' already exists")
            return True

        try:
            # Create new detached session
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", self.session_name],
                check=True
            )
            print(f"✅ Created tmux session: {self.session_name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error creating tmux session: {e}")
            return False

    def kill_session(self) -> bool:
        """Kill a tmux session"""
        if not self.is_session_exists():
            print(f"tmux session '{self.session_name}' does not exist")
            return True

        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", self.session_name],
                check=True
            )
            print(f"✅ Killed tmux session: {self.session_name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error killing tmux session: {e}")
            return False

    def send_command(self, pane: str, command: str) -> bool:
        """Send a command to a tmux pane"""
        if not self.is_session_exists():
            print(f"tmux session '{self.session_name}' does not exist")
            return False

        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"{self.session_name}:{pane}", command, "Enter"],
                check=True
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error sending command to tmux: {e}")
            return False

    def create_panes(self) -> bool:
        """Create the necessary panes"""
        if not self.is_session_exists():
            if not self.create_session():
                return False

        try:
            # Split window horizontally
            subprocess.run(
                ["tmux", "split-window", "-h", "-t", f"{self.session_name}:0"],
                check=True
            )

            # Split the right pane vertically
            subprocess.run(
                ["tmux", "split-window", "-v", "-t", f"{self.session_name}:0.1"],
                check=True
            )

            print("✅ Created tmux panes")
            return True
        except subprocess.CalledProcessError:
            # Panes might already exist
            return True

    def attach(self):
        """Attach to a tmux session"""
        if not self.is_session_exists():
            print(f"tmux session '{self.session_name}' does not exist")
            return

        try:
            subprocess.run(["tmux", "attach-session", "-t", self.session_name])
        except subprocess.CalledProcessError as e:
            print(f"Error attaching to tmux session: {e}")

    def list_panes(self) -> list:
        """Get the list of panes"""
        if not self.is_session_exists():
            return []

        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-t", self.session_name, "-F", "#{pane_index}"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            return []
        except subprocess.CalledProcessError:
            return []

    @staticmethod
    def _make_session_name(name: str) -> str:
        """Build a tmux session name from a channel/session name.

        Sanitizes the name to only contain characters valid for tmux session
        names (alphanumeric, dash, underscore). Prefixes with 'cb-'.
        """
        sanitized = ''.join(c if c.isalnum() or c in '-_' else '-' for c in name)
        return f"cb-{sanitized}"

    def create_claude_session(self, session_num: int, work_dir: str, options: str = "",
                              channel_id: str = "", system_prompt: str = "",
                              channel_name: str = "", resume: bool = False,
                              claude_session_id: str = "") -> dict:
        """Create a tmux session for Claude Code.

        Args:
            session_num: Numeric session ID (used as fallback for naming)
            work_dir: Working directory for Claude CLI
            options: Claude CLI options (e.g. --dangerously-skip-permissions)
            channel_id: Discord channel ID (set as DISCORD_CHANNEL_ID env var for dp)
            system_prompt: Optional system prompt to pass to Claude CLI
            channel_name: Human-readable name for the tmux session (e.g. 'projects')
            resume: If True, resume the conversation identified by claude_session_id
            claude_session_id: UUID of the Claude conversation to resume or pin

        Returns:
            dict with 'success' (bool) and 'claude_session_id' (str, the UUID used)
        """
        if channel_name:
            session_name = self._make_session_name(channel_name)
        else:
            session_name = f"{self.claude_session_prefix}-{session_num}"

        # Check if session already exists
        if self._has_session(session_name):
            print(f"Claude session already exists: {session_name}")
            return {'success': True, 'claude_session_id': claude_session_id}

        # Generate a new session ID if none provided
        if not claude_session_id:
            claude_session_id = str(uuid.uuid4())

        try:
            # Build Claude command with bridge bin in PATH and channel ID
            bridge_bin = str(Path(__file__).parent.parent / 'bin')
            env_exports = f'export PATH="{bridge_bin}:$PATH"'
            if channel_id:
                env_exports += f' && export DISCORD_CHANNEL_ID="{channel_id}"'

            # Build claude command with options
            claude_args = options
            if resume and claude_session_id:
                # Try to resume; if it fails (no prior conversation), start fresh
                resume_args = f'{options} --resume {claude_session_id}'
                fresh_args = f'{options} --session-id {claude_session_id}'
                claude_args = None  # signal to use the retry wrapper below
            else:
                # New conversation — pin it to this session ID
                claude_args = f'{options} --session-id {claude_session_id}'
            prompt_suffix = ''
            if system_prompt:
                escaped_prompt = system_prompt.replace("'", "'\\''")
                prompt_suffix = f" --append-system-prompt '{escaped_prompt}'"

            if claude_args is not None:
                # Simple case: single command
                claude_cmd = f'{env_exports} && cd "{work_dir}" && claude {claude_args}{prompt_suffix}'.strip()
            else:
                # Resume with fallback: try --resume first, fall back to --session-id
                claude_cmd = (
                    f'{env_exports} && cd "{work_dir}" && '
                    f'(claude {resume_args}{prompt_suffix} || claude {fresh_args}{prompt_suffix})'
                ).strip()

            # Wrap in a login shell so ~/.zshenv / ~/.zprofile are sourced,
            # ensuring env vars like LINEAR_API_TOKEN are available.
            shell = os.environ.get('SHELL', '/bin/zsh')
            wrapped_cmd = f'{shell} -l -c {shlex.quote(claude_cmd)}'

            # Create new detached session with Claude Code
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name, wrapped_cmd],
                check=True
            )
            print(f"Created Claude session: {session_name} (channel: {channel_id or 'none'}, claude_id: {claude_session_id[:8]}...)")
            return {'success': True, 'claude_session_id': claude_session_id}
        except subprocess.CalledProcessError as e:
            print(f"Error creating Claude session {session_name}: {e}")
            return {'success': False, 'claude_session_id': claude_session_id}

    def _has_session(self, session_name: str) -> bool:
        """Check if a tmux session exists by exact name."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def is_claude_session_exists(self, session_num_or_name) -> bool:
        """Check if a Claude Code session exists (by number or name)."""
        if isinstance(session_num_or_name, str) and not session_num_or_name.isdigit():
            return self._has_session(self._make_session_name(session_num_or_name))
        session_name = f"{self.claude_session_prefix}-{session_num_or_name}"
        return self._has_session(session_name)

    def kill_claude_session(self, session_num_or_name) -> bool:
        """Kill a Claude Code session (by number or name)."""
        if isinstance(session_num_or_name, str) and not session_num_or_name.isdigit():
            session_name = self._make_session_name(session_num_or_name)
        else:
            session_name = f"{self.claude_session_prefix}-{session_num_or_name}"

        if not self._has_session(session_name):
            return True

        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                check=True
            )
            print(f"Killed Claude session: {session_name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error killing Claude session {session_name}: {e}")
            return False

    def kill_all_claude_sessions(self) -> bool:
        """Kill all Claude Code sessions"""
        try:
            # List all sessions and filter Claude sessions
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                sessions = result.stdout.strip().split('\n')
                claude_sessions = [s for s in sessions
                                   if s.startswith(self.claude_session_prefix) or s.startswith('cb-')]

                for session in claude_sessions:
                    try:
                        subprocess.run(["tmux", "kill-session", "-t", session], check=True)
                        print(f"Killed Claude session: {session}")
                    except subprocess.CalledProcessError:
                        pass

            return True
        except subprocess.CalledProcessError:
            return True

    def list_claude_sessions(self) -> list:
        """Get the list of Claude Code sessions (both legacy and named)."""
        sessions = []
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                all_sessions = result.stdout.strip().split('\n')
                for session in all_sessions:
                    if session.startswith(self.claude_session_prefix):
                        # Legacy: claude-session-N
                        try:
                            num = int(session.split('-')[-1])
                            sessions.append((num, session))
                        except ValueError:
                            sessions.append((0, session))
                    elif session.startswith('cb-'):
                        # Named: cb-{name}
                        sessions.append((0, session))

                sessions.sort(key=lambda x: (x[0], x[1]))

            return sessions
        except subprocess.CalledProcessError:
            return []

def setup_tmux_environment():
    """Set up the tmux environment"""
    manager = TmuxManager()

    # Check if tmux is installed
    if subprocess.run(["which", "tmux"], capture_output=True).returncode != 0:
        print("❌ tmux is not installed. Please install it first.")
        print("  macOS: brew install tmux")
        print("  Ubuntu/Debian: sudo apt-get install tmux")
        return False

    # Create session and panes
    if not manager.create_session():
        return False

    if not manager.create_panes():
        return False

    print("✅ tmux environment is ready")
    print(f"  To attach: tmux attach -t {manager.session_name}")

    return True

if __name__ == "__main__":
    # Test tmux setup
    setup_tmux_environment()
