#!/usr/bin/env python3
"""
Common utilities
Shared functions used across the Claude-Discord Bridge
"""

import os
import sys
import subprocess
import psutil
from pathlib import Path
from typing import Optional, List, Dict

def find_process_by_name(name: str) -> List[Dict]:
    """Search for running processes by name"""
    processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if name in proc.info['name'] or any(name in arg for arg in (proc.info['cmdline'] or [])):
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': proc.info['cmdline']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        # psutil not installed, use alternative method
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if name in line:
                parts = line.split()
                if len(parts) > 1:
                    processes.append({
                        'pid': int(parts[1]),
                        'name': name,
                        'cmdline': parts[10:]
                    })

    return processes

def is_port_in_use(port: int) -> bool:
    """Check if the specified port is in use"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0

def find_available_port(start_port: int, max_attempts: int = 10) -> Optional[int]:
    """Find an available port"""
    for i in range(max_attempts):
        port = start_port + i
        if not is_port_in_use(port):
            return port
    return None

def get_toolkit_root() -> Path:
    """Get the toolkit root directory"""
    return Path(__file__).parent.parent

def ensure_executable(file_path: Path):
    """Grant execute permission to a file"""
    os.chmod(file_path, 0o755)

def create_pid_file(service_name: str, pid: int) -> Path:
    """Create a PID file"""
    # Support both old and new config directory names for backward compatibility
    old_config_dir = Path.home() / '.claude-cli-toolkit'
    new_config_dir = Path.home() / '.claude-discord-bridge'

    config_dir = new_config_dir if new_config_dir.exists() else old_config_dir
    pid_dir = config_dir / 'run'
    pid_dir.mkdir(parents=True, exist_ok=True)

    pid_file = pid_dir / f"{service_name}.pid"
    pid_file.write_text(str(pid))
    return pid_file

def read_pid_file(service_name: str) -> Optional[int]:
    """Read a PID file"""
    # Support both old and new config directory names for backward compatibility
    old_config_dir = Path.home() / '.claude-cli-toolkit'
    new_config_dir = Path.home() / '.claude-discord-bridge'

    config_dir = new_config_dir if new_config_dir.exists() else old_config_dir
    pid_file = config_dir / 'run' / f"{service_name}.pid"
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except ValueError:
            return None
    return None

def remove_pid_file(service_name: str):
    """Remove a PID file"""
    # Support both old and new config directory names for backward compatibility
    old_config_dir = Path.home() / '.claude-cli-toolkit'
    new_config_dir = Path.home() / '.claude-discord-bridge'

    config_dir = new_config_dir if new_config_dir.exists() else old_config_dir
    pid_file = config_dir / 'run' / f"{service_name}.pid"
    if pid_file.exists():
        pid_file.unlink()

def is_service_running(service_name: str) -> bool:
    """Check if a service is running (process name based)"""
    # Map service names to process names
    process_mapping = {
        'discord_bot': 'discord_bot.py',
        'flask_app': 'flask_app.py'
    }

    process_name = process_mapping.get(service_name, service_name)
    processes = find_process_by_name(process_name)

    # Check if any matching process is running
    return len(processes) > 0

def is_service_running_legacy(service_name: str) -> bool:
    """Check if a service is running (PID file based, legacy)"""
    pid = read_pid_file(service_name)
    if pid is None:
        return False

    try:
        # Check if process exists
        os.kill(pid, 0)
        return True
    except OSError:
        # Process doesn't exist, clean up PID file
        remove_pid_file(service_name)
        return False

def stop_service(service_name: str) -> bool:
    """Stop a service"""
    pid = read_pid_file(service_name)
    if pid is None:
        return False

    try:
        # Send SIGTERM
        os.kill(pid, 15)
        remove_pid_file(service_name)
        return True
    except OSError:
        remove_pid_file(service_name)
        return False

def get_shell_rc_file() -> Optional[Path]:
    """Get the shell RC file"""
    shell = os.environ.get('SHELL', '').split('/')[-1]
    home = Path.home()

    rc_files = {
        'zsh': home / '.zshrc',
        'bash': home / '.bashrc',
        'fish': home / '.config' / 'fish' / 'config.fish'
    }

    rc_file = rc_files.get(shell)
    if rc_file and rc_file.exists():
        return rc_file

    # Try common alternatives
    for shell_name, path in rc_files.items():
        if path.exists():
            return path

    return None

def add_to_path(directory: Path) -> bool:
    """Add a directory to PATH"""
    rc_file = get_shell_rc_file()
    if rc_file is None:
        return False

    export_line = f'\n# Claude-Discord Bridge\nexport PATH="{directory}:$PATH"\n'

    # Check if already added
    content = rc_file.read_text()
    if str(directory) in content:
        return True

    # Add to RC file
    with open(rc_file, 'a') as f:
        f.write(export_line)

    return True

def remove_from_path(directory: Path) -> bool:
    """Remove a directory from PATH"""
    rc_file = get_shell_rc_file()
    if rc_file is None:
        return False

    content = rc_file.read_text()
    lines = content.split('\n')

    # Filter out lines containing the directory
    filtered_lines = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if '# Claude-Discord Bridge' in line or '# Claude CLI Toolkit' in line:
            skip_next = True
            continue
        if str(directory) not in line:
            filtered_lines.append(line)

    # Write back
    rc_file.write_text('\n'.join(filtered_lines))
    return True

def format_session_list(sessions: List[tuple]) -> str:
    """Format a session list for display"""
    if not sessions:
        return "No sessions configured"

    lines = []
    for num, channel_id in sessions:
        lines.append(f"  Session {num}: {channel_id}")

    return '\n'.join(lines)

if __name__ == "__main__":
    # Test utilities
    print(f"Toolkit root: {get_toolkit_root()}")
    print(f"Shell RC file: {get_shell_rc_file()}")
    print(f"Port 5000 in use: {is_port_in_use(5000)}")
