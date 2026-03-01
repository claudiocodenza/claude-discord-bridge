#!/usr/bin/env python3
"""
Flask HTTP Bridge - Core of the Discord <-> Claude Code integration

This module is responsible for:
1. Receiving HTTP API requests from the Discord Bot
2. Forwarding messages to Claude Code sessions
3. Monitoring and reporting system status
4. Assisting with session management
5. Providing health check functionality

Extensibility points:
- Adding new API endpoints
- Diversifying message forwarding methods
- Implementing authentication and permission management
- Enhancing logging and monitoring
- Load balancing and scaling support
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

# Add package root to path (for relative imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from flask import Flask, request, jsonify, Response
except ImportError:
    print("Error: Flask is not installed. Run: pip install flask")
    sys.exit(1)

from config.settings import SettingsManager

# Logging configuration (in production, can be loaded from external config file)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TmuxMessageForwarder:
    """
    Message forwarding to tmux sessions

    Future extensions:
    - Non-tmux forwarding methods (WebSocket, gRPC, etc.)
    - Message queuing
    - Retry mechanism on failure
    - Load balancing support
    """

    # Configurable constants (to be moved to config file in the future)
    TMUX_DELAY_SECONDS = 0.2
    SESSION_NAME_PREFIX = "claude-session"

    @classmethod
    def forward_message(cls, message: str, session_num: int) -> Tuple[bool, Optional[str]]:
        """
        Forward a message to the specified session

        Extension points:
        - Forwarding method selection
        - Message encryption
        - Detailed forwarding status logging
        - Batch processing support

        Args:
            message: Message to forward
            session_num: Target session number

        Returns:
            Tuple[bool, Optional[str]]: (success flag, error message)
        """
        try:
            session_name = f"{cls.SESSION_NAME_PREFIX}-{session_num}"

            # Step 1: Send message
            cls._send_tmux_keys(session_name, message)

            # Step 2: Send Enter (execute command)
            time.sleep(cls.TMUX_DELAY_SECONDS)
            cls._send_tmux_keys(session_name, 'C-m')

            logger.info(f"Message forwarded to session {session_num}")
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
        """
        Send key input to a tmux session

        Extension points:
        - Pre-send validation
        - Session existence check
        - Alternative forwarding methods
        """
        subprocess.run(
            ['tmux', 'send-keys', '-t', session_name, keys],
            check=True,
            capture_output=True
        )

class MessageValidator:
    """
    Incoming message validation

    Future extensions:
    - Spam detection
    - Malicious content filtering
    - Rate limiting
    - Permission checks
    """

    @staticmethod
    def validate_discord_message(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate Discord message data

        Extension points:
        - Detailed validation rules
        - Custom validation logic
        - User permission checks

        Args:
            data: Received message data

        Returns:
            Tuple[bool, Optional[str]]: (validity flag, error message)
        """
        if not data:
            return False, "No data provided"

        # Check required fields
        required_fields = ['message', 'session', 'channel_id']
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        # Message length limit check
        message = data.get('message', '')
        if len(message) > 4000:  # Upper limit aligned with Discord limits
            return False, "Message too long"

        return True, None

class FlaskBridgeApp:
    """
    Flask HTTP Bridge application

    Architecture features:
    - RESTful API design
    - Robust error handling
    - Structured log output
    - Extensible routing

    Extensible elements:
    - Authentication and authorization system
    - API versioning
    - Rate limiting
    - Metrics collection
    - WebSocket support
    """

    def __init__(self, settings_manager: SettingsManager):
        """
        Initialize the Flask application

        Args:
            settings_manager: Settings manager instance
        """
        self.settings = settings_manager
        self.app = Flask(__name__)
        self.message_forwarder = TmuxMessageForwarder()
        self.message_validator = MessageValidator()
        self.active_processes = {}  # Extension: active process management

        # Route configuration
        self._configure_routes()

        # Application configuration
        self._configure_app()

    def _configure_app(self):
        """
        Configure the Flask application

        Extension points:
        - CORS settings
        - Security headers
        - Middleware additions
        """
        # Production environment settings
        self.app.config['DEBUG'] = False
        self.app.config['TESTING'] = False

    def _configure_routes(self):
        """
        Configure API routing

        Extension points:
        - Adding new endpoints
        - API versioning
        - Permission-based routing
        """
        # Health check endpoint
        self.app.route('/health', methods=['GET'])(self.health_check)

        # Message processing endpoint
        self.app.route('/discord-message', methods=['POST'])(self.handle_discord_message)

        # Session management endpoint
        self.app.route('/sessions', methods=['GET'])(self.get_sessions)

        # Status check endpoint
        self.app.route('/status', methods=['GET'])(self.get_status)

    def health_check(self) -> Response:
        """
        Health check endpoint

        Extension points:
        - Dependent service status checks
        - Detailed health information
        - Alerting
        """
        health_data = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0',  # Extension: version management
            'active_sessions': len(self.active_processes),
            'configured_sessions': len(self.settings.list_sessions())
        }

        return jsonify(health_data)

    def handle_discord_message(self) -> Response:
        """
        Main endpoint for Discord message processing

        Processing flow:
        1. Validate request data
        2. Extract message details
        3. Forward to Claude Code session
        4. Return processing result

        Extension points:
        - Asynchronous processing support
        - Message queuing
        - Priority control
        - Statistics collection
        """
        try:
            # Step 1: Validate data
            data = request.json
            is_valid, error_msg = self.message_validator.validate_discord_message(data)
            if not is_valid:
                logger.warning(f"Invalid message data: {error_msg}")
                return jsonify({'error': error_msg}), 400

            # Step 2: Extract message details
            message_info = self._extract_message_info(data)

            # Step 3: Log
            self._log_message_info(message_info)

            # Step 4: Forward to Claude Code
            success, error_msg = self._forward_to_claude(message_info)
            if not success:
                return jsonify({'error': error_msg}), 500

            # Step 5: Success response
            return jsonify({
                'status': 'received',
                'session': message_info['session_num'],
                'message_length': len(message_info['message']),
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            logger.error(f"Unexpected error in message handling: {e}", exc_info=True)
            return jsonify({'error': 'Internal server error'}), 500

    def _extract_message_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract message information from request data

        Extension points:
        - Additional metadata extraction
        - Data normalization
        - Custom field support
        """
        return {
            'message': data.get('message', ''),
            'channel_id': data.get('channel_id', ''),
            'session_num': data.get('session', 1),
            'user_id': data.get('user_id', ''),
            'username': data.get('username', 'Unknown'),
            'timestamp': datetime.now().isoformat()
        }

    def _log_message_info(self, message_info: Dict[str, Any]):
        """
        Log message information

        Extension points:
        - Structured log output
        - External logging system integration
        - Metrics collection
        """
        session_num = message_info['session_num']
        username = message_info['username']
        message_preview = message_info['message'][:100] + "..." if len(message_info['message']) > 100 else message_info['message']

        print(f"[Session {session_num}] {username}: {message_preview}")
        logger.info(f"Message processed: session={session_num}, user={username}, length={len(message_info['message'])}")

    def _forward_to_claude(self, message_info: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Forward a message to a Claude Code session

        Extension points:
        - Forwarding method selection
        - Retry on failure
        - Load balancing
        """
        session_num = message_info['session_num']
        message = message_info['message']

        success, error_msg = self.message_forwarder.forward_message(message, session_num)

        if success:
            print(f"✅ Forwarded to Claude session {session_num}")
        else:
            print(f"❌ Failed to forward to Claude session {session_num}: {error_msg}")

        return success, error_msg

    def get_sessions(self) -> Response:
        """
        Get the list of configured sessions

        Extension points:
        - Detailed session information
        - Session status checks
        - Filtering
        """
        sessions = self.settings.list_sessions()
        response_data = {
            'sessions': [
                {
                    'number': num,
                    'channel_id': ch_id,
                    'status': 'active'  # Extension: session status check
                }
                for num, ch_id in sessions
            ],
            'default': self.settings.get_default_session(),
            'total_count': len(sessions)
        }

        return jsonify(response_data)

    def get_status(self) -> Response:
        """
        Get application status

        Extension points:
        - Detailed system information
        - Performance metrics
        - Dependent service status
        """
        status_data = {
            'status': 'running',
            'configured': self.settings.is_configured(),
            'sessions_count': len(self.settings.list_sessions()),
            'active_processes': len(self.active_processes),
            'uptime': datetime.now().isoformat(),  # Extension: uptime calculation
            'version': '1.0.0'
        }

        return jsonify(status_data)

    def run(self, host: str = '127.0.0.1', port: Optional[int] = None):
        """
        Run the Flask application

        Extension points:
        - WSGI server support
        - SSL/TLS configuration
        - Load balancing settings
        """
        if port is None:
            port = self.settings.get_port('flask')

        print(f"🌐 Starting Flask HTTP Bridge on {host}:{port}")
        logger.info(f"Flask app starting on {host}:{port}")

        try:
            # Run in production mode
            self.app.run(
                host=host,
                port=port,
                debug=False,
                threaded=True,  # Multi-threaded support
                use_reloader=False
            )
        except Exception as e:
            error_msg = f"Failed to start Flask app: {e}"
            print(f"❌ {error_msg}")
            logger.error(error_msg, exc_info=True)
            sys.exit(1)

def run_flask_app(port: Optional[int] = None):
    """
    Flask application startup function

    Extension points:
    - Loading startup parameters from config files
    - Environment-specific configuration switching
    - Multi-instance management
    """
    settings = SettingsManager()

    # Configuration check
    if not settings.is_configured():
        print("❌ Claude-Discord Bridge is not configured.")
        print("Run './install.sh' first.")
        sys.exit(1)

    # Create and run application
    app = FlaskBridgeApp(settings)
    app.run(port=port)

if __name__ == "__main__":
    run_flask_app()
