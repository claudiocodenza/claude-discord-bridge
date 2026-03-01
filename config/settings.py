#!/usr/bin/env python3
"""
Settings management module
Manages configuration for the Claude-Discord Bridge
"""

import os
import json
from pathlib import Path
from typing import Dict, Optional, List
import configparser

class SettingsManager:
    """Class for loading, saving, and managing settings"""

    def __init__(self):
        # Support both old and new config directory names for backward compatibility
        old_config_dir = Path.home() / '.claude-cli-toolkit'
        new_config_dir = Path.home() / '.claude-discord-bridge'

        # Migrate from old to new if old exists and new doesn't
        if old_config_dir.exists() and not new_config_dir.exists():
            try:
                old_config_dir.rename(new_config_dir)
                print(f"Migrated config directory: {old_config_dir} -> {new_config_dir}")
            except Exception as e:
                print(f"Failed to migrate config directory: {e}")
                print(f"Using existing: {old_config_dir}")
                self.config_dir = old_config_dir
                self.env_file = self.config_dir / '.env'
                self.sessions_file = self.config_dir / 'sessions.json'
                self.channel_configs_file = self.config_dir / 'channel_configs.json'
                self.toolkit_root = Path(__file__).parent.parent
                return

        # Use new config directory (either migrated or new installation)
        self.config_dir = new_config_dir if new_config_dir.exists() or not old_config_dir.exists() else old_config_dir
        self.env_file = self.config_dir / '.env'
        self.sessions_file = self.config_dir / 'sessions.json'
        self.channel_configs_file = self.config_dir / 'channel_configs.json'
        self.toolkit_root = Path(__file__).parent.parent

    def ensure_config_dir(self):
        """Create the configuration directory"""
        self.config_dir.mkdir(exist_ok=True)

    def load_env(self) -> Dict[str, str]:
        """Load environment variables"""
        env_vars = {}
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        return env_vars

    def save_env(self, env_vars: Dict[str, str]):
        """Save environment variables"""
        self.ensure_config_dir()
        with open(self.env_file, 'w') as f:
            f.write("# Claude-Discord Bridge Configuration\n")
            f.write("# This file contains sensitive information. Do not share!\n\n")
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")

        # Set permissions to 600 (owner read/write only)
        os.chmod(self.env_file, 0o600)

    def load_sessions(self) -> Dict[str, str]:
        """Load session configuration"""
        if self.sessions_file.exists():
            with open(self.sessions_file, 'r') as f:
                return json.load(f)
        return {}

    def save_sessions(self, sessions: Dict[str, str]):
        """Save session configuration"""
        self.ensure_config_dir()
        with open(self.sessions_file, 'w') as f:
            json.dump(sessions, f, indent=2)

    def get_token(self) -> Optional[str]:
        """Get the Discord bot token"""
        env_vars = self.load_env()
        return env_vars.get('DISCORD_BOT_TOKEN')

    def set_token(self, token: str):
        """Set the Discord bot token"""
        env_vars = self.load_env()
        env_vars['DISCORD_BOT_TOKEN'] = token
        self.save_env(env_vars)

    def get_session_channel(self, session_num: int) -> Optional[str]:
        """Get the channel ID from a session number"""
        sessions = self.load_sessions()
        return sessions.get(str(session_num))

    def add_session(self, channel_id: str) -> int:
        """Add a new session"""
        sessions = self.load_sessions()

        # Find next available session number
        existing_nums = [int(k) for k in sessions.keys() if k.isdigit()]
        next_num = 1
        if existing_nums:
            next_num = max(existing_nums) + 1

        sessions[str(next_num)] = channel_id
        self.save_sessions(sessions)
        return next_num

    def remove_session(self, session_num: int) -> bool:
        """Remove a session"""
        sessions = self.load_sessions()
        if str(session_num) in sessions:
            del sessions[str(session_num)]
            self.save_sessions(sessions)
            return True
        return False

    def list_sessions(self) -> List[tuple]:
        """Get all sessions as a list"""
        sessions = self.load_sessions()
        return [(int(num), channel_id) for num, channel_id in sorted(sessions.items(), key=lambda x: int(x[0]))]

    def get_default_session(self) -> int:
        """Get the default session number"""
        env_vars = self.load_env()
        return int(env_vars.get('DEFAULT_SESSION', '1'))

    def set_default_session(self, session_num: int):
        """Set the default session number"""
        env_vars = self.load_env()
        env_vars['DEFAULT_SESSION'] = str(session_num)
        self.save_env(env_vars)

    def channel_to_session(self, channel_id: str) -> Optional[int]:
        """Reverse lookup: get session number from channel ID"""
        sessions = self.load_sessions()
        for num, ch_id in sessions.items():
            if ch_id == channel_id:
                return int(num)
        return None

    def get_port(self, service: str = 'flask') -> int:
        """Get the port number for a service"""
        env_vars = self.load_env()
        port_map = {
            'flask': int(env_vars.get('FLASK_PORT', '5001'))  # Avoids macOS ControlCenter conflict
        }
        return port_map.get(service, 5000)

    def get_claude_work_dir(self) -> str:
        """Get the Claude Code working directory"""
        env_vars = self.load_env()
        return env_vars.get('CLAUDE_WORK_DIR', os.getcwd())

    def get_claude_options(self) -> str:
        """Get Claude Code startup options"""
        env_vars = self.load_env()
        return env_vars.get('CLAUDE_OPTIONS', '')

    def is_configured(self) -> bool:
        """Check if initial setup is complete"""
        has_token = (self.env_file.exists() and
                     self.get_token() is not None and
                     self.get_token() != 'your_token_here')
        has_channels = len(self.list_channel_configs()) > 0
        has_legacy = len(self.list_sessions()) > 0
        return has_token and (has_channels or has_legacy)

    # --- Channel config methods (channel-per-session model) ---

    def load_channel_configs(self) -> Dict[str, dict]:
        """Load channel configurations. Returns {channel_id: config_dict}."""
        if self.channel_configs_file.exists():
            with open(self.channel_configs_file, 'r') as f:
                return json.load(f)
        return {}

    def save_channel_configs(self, configs: Dict[str, dict]):
        """Save channel configurations."""
        self.ensure_config_dir()
        with open(self.channel_configs_file, 'w') as f:
            json.dump(configs, f, indent=2)

    def get_channel_config(self, channel_id: str) -> Optional[dict]:
        """Get config for a specific channel."""
        configs = self.load_channel_configs()
        return configs.get(channel_id)

    def add_channel_config(self, channel_id: str, name: str,
                           work_dir: str = "", claude_options: str = "",
                           system_prompt: str = "") -> dict:
        """Add a new channel config. Returns the config dict."""
        configs = self.load_channel_configs()
        env_vars = self.load_env()

        # Auto-assign session number (find next available)
        used_nums = {cfg.get('session_num', 0) for cfg in configs.values()}
        session_num = 1
        while session_num in used_nums:
            session_num += 1

        config = {
            'name': name,
            'session_num': session_num,
            'tmux_session': f'cb-{name}',
            'work_dir': work_dir or env_vars.get('CLAUDE_WORK_DIR', os.getcwd()),
            'claude_options': claude_options or env_vars.get('CLAUDE_OPTIONS', ''),
            'system_prompt': system_prompt,
            'active': True,
        }

        configs[channel_id] = config
        self.save_channel_configs(configs)

        # Also sync to legacy sessions.json for backward compat
        sessions = self.load_sessions()
        sessions[str(session_num)] = channel_id
        self.save_sessions(sessions)

        return config

    def update_channel_config(self, channel_id: str, **kwargs) -> Optional[dict]:
        """Update fields on an existing channel config. Returns updated config or None."""
        configs = self.load_channel_configs()
        if channel_id not in configs:
            return None
        for key, value in kwargs.items():
            if key in ('name', 'work_dir', 'claude_options', 'system_prompt', 'active'):
                configs[channel_id][key] = value
        self.save_channel_configs(configs)
        return configs[channel_id]

    def remove_channel_config(self, channel_id: str) -> bool:
        """Remove a channel config (mark inactive). Returns True if found."""
        configs = self.load_channel_configs()
        if channel_id not in configs:
            return False
        session_num = configs[channel_id].get('session_num')
        configs[channel_id]['active'] = False
        self.save_channel_configs(configs)

        # Clean up legacy sessions.json
        if session_num is not None:
            sessions = self.load_sessions()
            sessions.pop(str(session_num), None)
            self.save_sessions(sessions)

        return True

    def list_channel_configs(self, active_only: bool = True) -> List[tuple]:
        """List channel configs as [(channel_id, config_dict), ...] sorted by session_num."""
        configs = self.load_channel_configs()
        items = []
        for ch_id, cfg in configs.items():
            if active_only and not cfg.get('active', True):
                continue
            items.append((ch_id, cfg))
        items.sort(key=lambda x: x[1].get('session_num', 0))
        return items

    def channel_id_to_session_num(self, channel_id: str) -> Optional[int]:
        """Get session number for a channel ID from channel configs."""
        cfg = self.get_channel_config(channel_id)
        if cfg and cfg.get('active', True):
            return cfg.get('session_num')
        return None

    def session_num_to_channel_id(self, session_num: int) -> Optional[str]:
        """Reverse lookup: get channel ID from session number."""
        configs = self.load_channel_configs()
        for ch_id, cfg in configs.items():
            if cfg.get('session_num') == session_num and cfg.get('active', True):
                return ch_id
        return None

    def migrate_sessions_to_channel_configs(self):
        """Migrate legacy sessions.json to channel_configs.json if needed."""
        if self.channel_configs_file.exists():
            return  # Already migrated

        sessions = self.load_sessions()
        if not sessions:
            return

        env_vars = self.load_env()
        configs = {}
        for session_num_str, channel_id in sessions.items():
            configs[channel_id] = {
                'name': f'session-{session_num_str}',
                'session_num': int(session_num_str),
                'work_dir': env_vars.get('CLAUDE_WORK_DIR', os.getcwd()),
                'claude_options': env_vars.get('CLAUDE_OPTIONS', ''),
                'system_prompt': '',
                'active': True,
            }

        if configs:
            self.save_channel_configs(configs)
            print(f"Migrated {len(configs)} session(s) to channel configs")

if __name__ == "__main__":
    # Test settings manager
    manager = SettingsManager()
    print(f"Config directory: {manager.config_dir}")
    print(f"Is configured: {manager.is_configured()}")

    if manager.is_configured():
        print(f"Sessions: {manager.list_sessions()}")
        print(f"Default session: {manager.get_default_session()}")
