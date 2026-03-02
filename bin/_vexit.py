#!/usr/bin/env python3
"""
vexit - Stop the Claude-Discord Bridge (Python implementation)
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
toolkit_root = Path(os.environ.get('TOOLKIT_ROOT', Path(__file__).parent.parent))
sys.path.insert(0, str(toolkit_root))

from src.tmux_manager import TmuxManager
from lib.utils import stop_service, is_service_running

def main():
    """Main function"""
    print("🛑 Stopping Claude-Discord Bridge...")

    # Stop services
    services_stopped = False

    if is_service_running('discord_bot'):
        print("  Stopping Discord bot...")
        if stop_service('discord_bot'):
            services_stopped = True
        time.sleep(1)

    if is_service_running('flask_app'):
        print("  Stopping Flask app...")
        if stop_service('flask_app'):
            services_stopped = True
        time.sleep(1)

    # Kill Claude Code sessions
    tmux = TmuxManager()
    claude_sessions = tmux.list_claude_sessions()
    if claude_sessions:
        print(f"  Stopping {len(claude_sessions)} Claude Code sessions...")
        tmux.kill_all_claude_sessions()
        services_stopped = True

    # Kill monitoring tmux session
    if tmux.is_session_exists():
        print("  Killing monitoring tmux session...")
        tmux.kill_session()
        services_stopped = True

    if services_stopped:
        print("\n✅ All services stopped successfully!")
    else:
        print("\n⚠️  No services were running")

if __name__ == "__main__":
    main()
