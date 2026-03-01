#!/usr/bin/env python3
"""
Discord Bot implementation - Core functionality of the Claude-Discord Bridge

This module is responsible for:
1. Receiving and processing Discord messages
2. Managing image attachments
3. Forwarding messages to Claude Code
4. Managing user feedback
5. Periodic maintenance tasks

Extensibility points:
- Adding message format strategies
- Supporting new attachment file types
- Adding custom commands
- Extending notification methods
- Enhancing session management
"""

import os
import sys
import json
import asyncio
import logging
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add package root to path (for relative imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import discord
    from discord.ext import commands, tasks
except ImportError:
    print("Error: discord.py is not installed. Run: pip install discord.py")
    sys.exit(1)

from config.settings import SettingsManager
from attachment_manager import AttachmentManager

# Logging configuration (in production, can be loaded from external config file)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MessageProcessor:
    """
    Strategy pattern implementation for message processing

    Future extensions:
    - Support for different message formats
    - Content filtering
    - Message transformation
    """

    @staticmethod
    def format_message_with_attachments(content: str, attachment_paths: List[str], session_num: int) -> str:
        """
        Format a message with attachment file paths

        Extension points:
        - Diversifying attachment file types (video, audio, documents, etc.)
        - Customizing message templates
        - Internationalization support

        Args:
            content: Original message content
            attachment_paths: List of attachment file paths
            session_num: Session number

        Returns:
            str: Formatted message
        """
        # Build attachment path string
        attachment_str = ""
        if attachment_paths:
            attachment_parts = [f"[attached image: {path}]" for path in attachment_paths]
            attachment_str = " " + " ".join(attachment_parts)

        # Branch based on message type
        if content.startswith('/'):
            # Slash command format (direct Claude Code command execution)
            return f"{content}{attachment_str} session={session_num}"
        else:
            # Normal message format (notification to Claude Code)
            return f"Discord notification: {content}{attachment_str} session={session_num}"

class ClaudeCLIBot(commands.Bot):
    """
    Claude CLI integrated Discord Bot

    Architecture features:
    - High responsiveness via asynchronous processing
    - Extensibility through modular design
    - Robust error handling
    - Automatic resource management

    Extensible elements:
    - Adding custom commands
    - Permission management system
    - User session management
    - Statistics and analytics
    - Webhook integration
    """

    # Configurable constants (to be moved to config file in the future)
    CLEANUP_INTERVAL_HOURS = 6
    REQUEST_TIMEOUT_SECONDS = 5
    LOADING_MESSAGE = "`...`"
    SUCCESS_MESSAGE = "> Message sent successfully"

    def __init__(self, settings_manager: SettingsManager):
        """
        Initialize the Bot instance

        Args:
            settings_manager: Settings manager instance
        """
        self.settings = settings_manager
        self.attachment_manager = AttachmentManager()
        self.message_processor = MessageProcessor()

        # Discord Bot configuration
        intents = discord.Intents.default()
        intents.message_content = True  # Permission to access message content

        super().__init__(command_prefix='!', intents=intents)

    async def on_ready(self):
        """
        Initialization when the Bot is ready

        Extension points:
        - Database connection initialization
        - External API connection verification
        - Statistics initialization
        - Starting periodic task processing
        """
        logger.info(f'{self.user} has connected to Discord!')
        print(f'✅ Discord bot is ready as {self.user}')

        # Initial system cleanup
        await self._perform_initial_cleanup()

        # Start periodic maintenance tasks
        await self._start_maintenance_tasks()

    async def _perform_initial_cleanup(self):
        """
        Initial cleanup on Bot startup

        Extension points:
        - Deleting old session data
        - Log file rotation
        - Cache initialization
        """
        cleanup_count = self.attachment_manager.cleanup_old_files()
        if cleanup_count > 0:
            print(f'🧹 Cleaned up {cleanup_count} old attachment files')

    async def _start_maintenance_tasks(self):
        """
        Start periodic maintenance tasks

        Extension points:
        - Database maintenance
        - Statistics aggregation
        - External API health checks
        """
        if not self.cleanup_task.is_running():
            self.cleanup_task.start()
            print(f'⏰ Attachment cleanup task started (runs every {self.CLEANUP_INTERVAL_HOURS} hours)')

    async def on_message(self, message):
        """
        Main handler for incoming messages

        Processing flow:
        1. Pre-validate the message
        2. Verify the session
        3. Provide immediate user feedback
        4. Process attachments
        5. Format the message
        6. Forward to Claude Code
        7. Provide result feedback

        Extension points:
        - Message preprocessing filters
        - Permission checks
        - Rate limiting
        - Logging
        - Statistics collection
        """
        # Basic validation
        if not await self._validate_message(message):
            return

        # Session verification
        session_num = self.settings.channel_to_session(str(message.channel.id))
        if session_num is None:
            return

        # User feedback (immediate loading indicator)
        loading_msg = await self._send_loading_feedback(message.channel)
        if not loading_msg:
            return

        try:
            # Message processing pipeline
            result_text = await self._process_message_pipeline(message, session_num)

        except Exception as e:
            result_text = f"❌ Processing error: {str(e)[:100]}"
            logger.error(f"Message processing error: {e}", exc_info=True)

        # Display final result
        await self._update_feedback(loading_msg, result_text)

    async def _validate_message(self, message) -> bool:
        """
        Basic message validation

        Extension points:
        - Spam detection
        - Permission verification
        - Blacklist checking
        """
        # Ignore messages from the Bot itself
        if message.author == self.user:
            return False

        # Process standard Discord commands
        await self.process_commands(message)

        return True

    async def _send_loading_feedback(self, channel) -> Optional[discord.Message]:
        """
        Send loading feedback

        Extension points:
        - Custom loading messages
        - Animated display
        - Progress bar
        """
        try:
            return await channel.send(self.LOADING_MESSAGE)
        except Exception as e:
            logger.error(f'Feedback send error: {e}')
            return None

    async def _process_message_pipeline(self, message, session_num: int) -> str:
        """
        Message processing pipeline

        Extension points:
        - Adding processing steps
        - Parallelizing async operations
        - Caching
        """
        # Step 1: Process attachments
        attachment_paths = await self._process_attachments(message, session_num)

        # Step 2: Format message
        formatted_message = self.message_processor.format_message_with_attachments(
            message.content, attachment_paths, session_num
        )

        # Step 3: Forward to Claude Code
        return await self._forward_to_claude(formatted_message, message, session_num)

    async def _process_attachments(self, message, session_num: int) -> List[str]:
        """
        Process attachments

        Extension points:
        - Supporting new file formats
        - File conversion
        - Virus scanning
        """
        attachment_paths = []
        if message.attachments:
            try:
                attachment_paths = await self.attachment_manager.process_attachments(message.attachments)
                if attachment_paths:
                    print(f'📎 Processed {len(attachment_paths)} attachment(s) for session {session_num}')
            except Exception as e:
                logger.error(f'Attachment processing error: {e}')

        return attachment_paths

    async def _forward_to_claude(self, formatted_message: str, original_message, session_num: int) -> str:
        """
        Forward a message to Claude Code

        Extension points:
        - Supporting multiple forwarding targets
        - Retry on forwarding failure
        - Load balancing
        """
        try:
            payload = {
                'message': formatted_message,
                'channel_id': str(original_message.channel.id),
                'session': session_num,
                'user_id': str(original_message.author.id),
                'username': str(original_message.author)
            }

            flask_port = self.settings.get_port('flask')
            response = requests.post(
                f'http://localhost:{flask_port}/discord-message',
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS
            )

            return self._format_response_status(response.status_code)

        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to Flask app. Is it running?")
            return "❌ Error: Cannot connect to Flask app"
        except Exception as e:
            logger.error(f"Error forwarding message: {e}")
            return f"❌ Error: {str(e)[:100]}"

    def _format_response_status(self, status_code: int) -> str:
        """
        Format the response status

        Extension points:
        - Detailed status messages
        - Internationalization support
        - Custom messages
        """
        if status_code == 200:
            return self.SUCCESS_MESSAGE
        else:
            return f"⚠️ Status: {status_code}"

    async def _update_feedback(self, loading_msg: discord.Message, result_text: str):
        """
        Update the feedback message

        Extension points:
        - Rich message display
        - Progress status display
        - Interactive elements
        """
        try:
            await loading_msg.edit(content=result_text)
        except Exception as e:
            logger.error(f'Message update failed: {e}')

    @tasks.loop(hours=CLEANUP_INTERVAL_HOURS)
    async def cleanup_task(self):
        """
        Periodic cleanup task

        Extension points:
        - Database cleanup
        - Log file management
        - Statistics aggregation
        - System health checks
        """
        try:
            cleanup_count = self.attachment_manager.cleanup_old_files()
            if cleanup_count > 0:
                logger.info(f'Automatic cleanup: {cleanup_count} files deleted')
        except Exception as e:
            logger.error(f'Error in cleanup task: {e}')

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        """Preparation before starting the cleanup task"""
        await self.wait_until_ready()

def create_bot_commands(bot: ClaudeCLIBot, settings: SettingsManager):
    """
    Register Bot commands

    Extension points:
    - Adding new commands
    - Permission-based commands
    - Dynamic command registration
    """

    @bot.command(name='status')
    async def status_command(ctx):
        """Bot status check command"""
        sessions = settings.list_sessions()
        embed = discord.Embed(
            title="Claude CLI Bot Status",
            description="✅ Bot is running",
            color=discord.Color.green()
        )

        session_list = "\n".join([f"Session {num}: <#{ch_id}>" for num, ch_id in sessions])
        embed.add_field(name="Active Sessions", value=session_list or "No sessions configured", inline=False)

        await ctx.send(embed=embed)

    @bot.command(name='sessions')
    async def sessions_command(ctx):
        """List configured sessions command"""
        sessions = settings.list_sessions()
        if not sessions:
            await ctx.send("No sessions configured.")
            return

        lines = ["**Configured Sessions:**"]
        for num, channel_id in sessions:
            lines.append(f"Session {num}: <#{channel_id}>")

        await ctx.send("\n".join(lines))

def run_bot():
    """
    Main execution function for the Discord Bot

    Extension points:
    - Multi-bot management
    - Sharding support
    - High availability configuration
    """
    settings = SettingsManager()

    # Token verification
    token = settings.get_token()
    if not token or token == 'your_token_here':
        print("❌ Discord bot token not configured!")
        print("Run './install.sh' to set up the token.")
        sys.exit(1)

    # Create Bot instance
    bot = ClaudeCLIBot(settings)

    # Register commands
    create_bot_commands(bot, settings)

    # Run Bot
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Failed to login. Check your Discord bot token.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error running bot: {e}")
        logger.error(f"Bot execution error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_bot()
