#!/usr/bin/env python3
"""
Discord Post implementation
Posts messages to Discord
"""

import os
import sys
import json
import requests
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import SettingsManager

def post_to_discord(channel_id: str, message: str):
    """Post a message to Discord channel"""
    settings = SettingsManager()
    
    # Get bot token
    token = settings.get_token()
    if not token:
        print("Error: Discord bot token not configured")
        sys.exit(1)
    
    # Discord API endpoint
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    
    # Headers
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json"
    }
    
    # Payload
    payload = {
        "content": message
    }
    
    try:
        # Send request
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            return True
        else:
            print(f"Error: Discord API returned status {response.status_code}")
            if response.status_code == 401:
                print("Invalid bot token")
            elif response.status_code == 403:
                print("Bot doesn't have permission to send messages in this channel")
            elif response.status_code == 404:
                print("Channel not found")
            else:
                print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("Error: Failed to connect to Discord API")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    """Main function for command line usage"""
    settings = SettingsManager()
    
    # Check if stdin has data
    if not sys.stdin.isatty():
        message = sys.stdin.read().strip()
        
        # Check if channel ID is provided as argument
        if len(sys.argv) > 1:
            channel_arg = sys.argv[1]
        else:
            # Use default session
            channel_arg = str(settings.get_default_session())
        
        # Determine if it's a session number or channel ID
        if channel_arg.isdigit() and len(channel_arg) < 5:
            # It's a session number
            channel_id = settings.get_session_channel(int(channel_arg))
            if not channel_id:
                print(f"Error: Session {channel_arg} not configured")
                sys.exit(1)
        else:
            # It's a channel ID
            channel_id = channel_arg
        
        # Post message
        if post_to_discord(channel_id, message):
            # Success - no output
            pass
        else:
            sys.exit(1)
    else:
        print("Usage: echo 'message' | discord_post.py [session_number or channel_id]")
        sys.exit(1)

if __name__ == "__main__":
    main()