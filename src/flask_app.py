#!/usr/bin/env python3
"""
Flask HTTP Bridge - Claude-Discord Bridge (Channel-per-Session model)

Routes Discord messages to the correct Claude CLI tmux session based on
channel ID. Provides endpoints for channel session lifecycle management.
"""

import os
import sys
import json
import subprocess
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from flask import Flask, request, jsonify, Response
except ImportError:
    print("Error: Flask is not installed. Run: pip install flask")
    sys.exit(1)

from config.settings import SettingsManager
from tmux_manager import TmuxManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TmuxMessageForwarder:
    """Forward messages to Claude CLI tmux sessions."""

    TMUX_DELAY_SECONDS = 0.2
    SESSION_NAME_PREFIX = "claude-session"

    @classmethod
    def forward_message(cls, message: str, session_num: int,
                        tmux_session: str = "") -> Tuple[bool, Optional[str]]:
        """Forward a message to the specified tmux session."""
        try:
            # Use named session if provided, otherwise fall back to numeric
            session_name = tmux_session or f"{cls.SESSION_NAME_PREFIX}-{session_num}"
            cls._send_tmux_keys(session_name, message)
            time.sleep(cls.TMUX_DELAY_SECONDS)
            cls._send_tmux_keys(session_name, 'C-m')
            logger.info(f"Message forwarded to {session_name}")
            return True, None
        except subprocess.CalledProcessError as e:
            error_msg = f"tmux command failed: {e}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(error_msg)
            return False, error_msg

    @classmethod
    def _send_tmux_keys(cls, session_name: str, keys: str):
        subprocess.run(
            ['tmux', 'send-keys', '-t', session_name, keys],
            check=True,
            capture_output=True,
        )


class FlaskBridgeApp:
    """Flask HTTP Bridge with channel-per-session routing."""

    def __init__(self, settings_manager: SettingsManager):
        self.settings = settings_manager
        self.app = Flask(__name__)
        self.message_forwarder = TmuxMessageForwarder()
        self.tmux_manager = TmuxManager()
        self._configure_routes()
        self.app.config['DEBUG'] = False
        self.app.config['TESTING'] = False

    def _configure_routes(self):
        self.app.route('/health', methods=['GET'])(self.health_check)
        self.app.route('/discord-message', methods=['POST'])(self.handle_discord_message)
        self.app.route('/channels', methods=['GET'])(self.get_channels)
        self.app.route('/channels/start', methods=['POST'])(self.start_channel_session)
        self.app.route('/channels/stop', methods=['POST'])(self.stop_channel_session)
        self.app.route('/status', methods=['GET'])(self.get_status)
        # Legacy endpoint
        self.app.route('/sessions', methods=['GET'])(self.get_channels)

    def health_check(self) -> Response:
        channels = self.settings.list_channel_configs()
        tmux_sessions = self.tmux_manager.list_claude_sessions()

        channel_details = []
        for ch_id, cfg in channels:
            name = cfg.get('name', '')
            tmux_alive = self.tmux_manager.is_claude_session_exists(name) if name else False
            channel_details.append({
                'channel_id': ch_id,
                'name': name,
                'tmux_alive': tmux_alive,
            })

        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'active_channels': len(channels),
            'tmux_sessions': len(tmux_sessions),
            'channels': channel_details,
        })

    def handle_discord_message(self) -> Response:
        """Route a Discord message to the correct Claude tmux session."""
        try:
            data = request.json
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            message = data.get('message', '')
            channel_id = data.get('channel_id', '')
            session_num = data.get('session')
            tmux_session = ''

            if not message:
                return jsonify({'error': 'Missing message'}), 400

            # Look up tmux session name from channel config
            if channel_id:
                cfg = self.settings.get_channel_config(channel_id)
                if cfg and cfg.get('active', True):
                    session_num = cfg['session_num']
                    tmux_session = cfg.get('tmux_session', '')

            # Fall back to legacy session lookup
            if session_num is None and channel_id:
                sn = self.settings.channel_to_session(channel_id)
                if sn is not None:
                    session_num = sn

            if session_num is None:
                return jsonify({'error': f'No session configured for channel {channel_id}'}), 404

            username = data.get('username', 'Unknown')
            preview = message[:100] + "..." if len(message) > 100 else message
            target = tmux_session or f"session-{session_num}"
            print(f"[{target}] {username}: {preview}")

            success, error_msg = self.message_forwarder.forward_message(
                message, session_num, tmux_session=tmux_session
            )
            if not success:
                return jsonify({'error': error_msg}), 500

            return jsonify({
                'status': 'received',
                'session': session_num,
                'channel_id': channel_id,
                'timestamp': datetime.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500

    def start_channel_session(self) -> Response:
        """Start a tmux session for a channel."""
        try:
            data = request.json
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            channel_id = data.get('channel_id', '')
            session_num = data.get('session_num')
            channel_name = data.get('channel_name', '')
            work_dir = data.get('work_dir', '')
            claude_options = data.get('claude_options', '')
            system_prompt = data.get('system_prompt', '')

            if not channel_id or session_num is None:
                return jsonify({'error': 'Missing channel_id or session_num'}), 400

            resume = data.get('resume', False)
            claude_session_id = data.get('claude_session_id', '')

            result = self.tmux_manager.create_claude_session(
                session_num=session_num,
                work_dir=work_dir,
                options=claude_options,
                channel_id=channel_id,
                system_prompt=system_prompt,
                channel_name=channel_name,
                resume=resume,
                claude_session_id=claude_session_id,
            )

            if result['success']:
                # Persist the claude_session_id back to channel config
                new_id = result.get('claude_session_id', '')
                if new_id and channel_id:
                    self.settings.update_channel_config(channel_id, claude_session_id=new_id)
                return jsonify({
                    'status': 'started',
                    'session_num': session_num,
                    'claude_session_id': new_id,
                })
            else:
                return jsonify({'error': 'Failed to create tmux session'}), 500

        except Exception as e:
            logger.error(f"Error starting channel session: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    def stop_channel_session(self) -> Response:
        """Stop a tmux session for a channel."""
        try:
            data = request.json
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            channel_name = data.get('channel_name', '')
            session_num = data.get('session_num')

            if channel_name:
                success = self.tmux_manager.kill_claude_session(channel_name)
            elif session_num is not None:
                success = self.tmux_manager.kill_claude_session(session_num)
            else:
                return jsonify({'error': 'Missing channel_name or session_num'}), 400

            return jsonify({'status': 'stopped' if success else 'not_found'})

        except Exception as e:
            logger.error(f"Error stopping channel session: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    def get_channels(self) -> Response:
        """List configured channels."""
        channels = self.settings.list_channel_configs()
        return jsonify({
            'channels': [
                {
                    'channel_id': ch_id,
                    'name': cfg['name'],
                    'session_num': cfg['session_num'],
                    'work_dir': cfg['work_dir'],
                    'active': cfg.get('active', True),
                }
                for ch_id, cfg in channels
            ],
            'total_count': len(channels),
        })

    def get_status(self) -> Response:
        return jsonify({
            'status': 'running',
            'configured': self.settings.is_configured(),
            'channels_count': len(self.settings.list_channel_configs()),
            'timestamp': datetime.now().isoformat(),
        })

    def run(self, host: str = '127.0.0.1', port: Optional[int] = None):
        if port is None:
            port = self.settings.get_port('flask')

        print(f"Starting Flask HTTP Bridge on {host}:{port}")

        try:
            self.app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
        except Exception as e:
            print(f"Failed to start Flask app: {e}")
            logger.error(f"Flask startup error: {e}", exc_info=True)
            sys.exit(1)


def run_flask_app(port: Optional[int] = None):
    settings = SettingsManager()

    if not settings.is_configured():
        print("Claude-Discord Bridge is not configured.")
        sys.exit(1)

    app = FlaskBridgeApp(settings)
    app.run(port=port)


if __name__ == "__main__":
    run_flask_app()
