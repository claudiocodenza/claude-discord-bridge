#!/usr/bin/env python3
"""
Discord Bot - Claude-Discord Bridge (Channel-per-Session model)

Each Discord channel maps to an independent Claude CLI tmux session with
per-channel configuration (work_dir, claude_options, system_prompt).

Slash commands for channel lifecycle management:
- /new-channel: Create a new channel with a Claude session
- /archive-channel: Archive a channel and kill its tmux session
- /channel-config: View or update config for the current channel
- /list-channels: List all active Claude channels
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
    from discord import app_commands
    from discord.ext import commands, tasks
except ImportError:
    print("Error: discord.py is not installed. Run: pip install discord.py")
    sys.exit(1)

from config.settings import SettingsManager
from attachment_manager import AttachmentManager
from tmux_manager import TmuxManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Category names for Claude session channels
CLAUDE_CATEGORY_NAME = "Claude Sessions"
CLAUDE_ARCHIVE_CATEGORY_NAME = "Archived Sessions"


class MessageProcessor:
    """Format messages for forwarding to Claude CLI."""

    @staticmethod
    def format_message(content: str, attachment_paths: List[str],
                       user_id: str = "", channel_name: str = "") -> str:
        """Format a message with attachments for Claude CLI input."""
        attachment_str = ""
        if attachment_paths:
            attachment_parts = [f"[attached image: {path}]" for path in attachment_paths]
            attachment_str = " " + " ".join(attachment_parts)

        if content.startswith('/'):
            return f"{content}{attachment_str}"
        else:
            return f"Discord notification: {content}{attachment_str}"


class ClaudeCLIBot(commands.Bot):
    """Discord Bot with channel-per-session Claude integration."""

    CLEANUP_INTERVAL_HOURS = 6
    REQUEST_TIMEOUT_SECONDS = 5
    REACT_PROCESSING = "\U0001F440"  # eyes
    REACT_SUCCESS = "\u2705"         # green checkmark
    REACT_ERROR = "\u274C"           # red X

    def __init__(self, settings_manager: SettingsManager):
        self.settings = settings_manager
        self.attachment_manager = AttachmentManager()
        self.message_processor = MessageProcessor()
        self.tmux_manager = TmuxManager()

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix='!', intents=intents)

    async def update_presence(self):
        """Update bot presence to show active session count."""
        channels = self.settings.list_channel_configs()
        count = len(channels) if channels else 0
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{count} session{'s' if count != 1 else ''}",
        )
        await self.change_presence(activity=activity)

    async def setup_hook(self):
        """Called when bot is starting up — register slash commands."""
        register_slash_commands(self, self.settings)
        # Sync commands with Discord
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} slash command(s)")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        print(f'Discord bot is ready as {self.user}')

        # Migrate legacy sessions to channel configs
        self.settings.migrate_sessions_to_channel_configs()

        # Initial cleanup
        cleanup_count = self.attachment_manager.cleanup_old_files()
        if cleanup_count > 0:
            print(f'Cleaned up {cleanup_count} old attachment files')

        # Start periodic maintenance
        if not self.cleanup_task.is_running():
            self.cleanup_task.start()

        # Print active channels and set bot presence
        channels = self.settings.list_channel_configs()
        if channels:
            print(f'Active channels: {len(channels)}')
            for ch_id, cfg in channels:
                print(f'  #{cfg["name"]} -> session {cfg["session_num"]} ({cfg["work_dir"]})')

        await self.update_presence()

    async def on_message(self, message):
        """Route messages from configured channels to their Claude sessions."""
        if message.author == self.user:
            return

        # Process prefix commands (e.g., !status)
        await self.process_commands(message)

        # Check if this channel has a config
        channel_id = str(message.channel.id)
        cfg = self.settings.get_channel_config(channel_id)
        if cfg is None or not cfg.get('active', True):
            return

        session_num = cfg['session_num']

        # React with processing indicator
        try:
            await message.add_reaction(self.REACT_PROCESSING)
        except Exception as e:
            logger.error(f'Reaction add error: {e}')

        try:
            # Process attachments
            attachment_paths = []
            if message.attachments:
                try:
                    attachment_paths = await self.attachment_manager.process_attachments(message.attachments)
                except Exception as e:
                    logger.error(f'Attachment processing error: {e}')

            # Format message
            formatted = self.message_processor.format_message(
                message.content, attachment_paths,
                user_id=str(message.author.id),
                channel_name=cfg.get('name', ''),
            )

            # Forward to Flask bridge
            payload = {
                'message': formatted,
                'channel_id': channel_id,
                'session': session_num,
                'user_id': str(message.author.id),
                'username': str(message.author),
            }

            flask_port = self.settings.get_port('flask')
            response = requests.post(
                f'http://localhost:{flask_port}/discord-message',
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )

            # Replace processing reaction with result
            try:
                await message.remove_reaction(self.REACT_PROCESSING, self.user)
            except Exception:
                pass

            if response.status_code == 200:
                await message.add_reaction(self.REACT_SUCCESS)
            else:
                await message.add_reaction(self.REACT_ERROR)
                await message.channel.send(f"Warning: Status {response.status_code}")

        except requests.exceptions.ConnectionError:
            logger.error("Failed to connect to Flask app")
            try:
                await message.remove_reaction(self.REACT_PROCESSING, self.user)
                await message.add_reaction(self.REACT_ERROR)
            except Exception:
                pass
            await message.channel.send("Error: Cannot connect to Flask app")
        except Exception as e:
            logger.error(f"Message processing error: {e}", exc_info=True)
            try:
                await message.remove_reaction(self.REACT_PROCESSING, self.user)
                await message.add_reaction(self.REACT_ERROR)
            except Exception:
                pass
            await message.channel.send(f"Error: {str(e)[:100]}")

    @tasks.loop(hours=CLEANUP_INTERVAL_HOURS)
    async def cleanup_task(self):
        try:
            cleanup_count = self.attachment_manager.cleanup_old_files()
            if cleanup_count > 0:
                logger.info(f'Automatic cleanup: {cleanup_count} files deleted')
        except Exception as e:
            logger.error(f'Error in cleanup task: {e}')

        # Check for stale sessions (config says active but tmux session is gone)
        try:
            channels = self.settings.list_channel_configs(active_only=True)
            for ch_id, cfg in channels:
                channel_name = cfg.get('name', '')
                if not channel_name:
                    continue
                if not self.tmux_manager.is_claude_session_exists(channel_name):
                    logger.warning(f'Stale session detected: cb-{channel_name} (tmux gone)')
        except Exception as e:
            logger.error(f'Error in session cleanup: {e}')

    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        await self.wait_until_ready()


def register_slash_commands(bot: ClaudeCLIBot, settings: SettingsManager):
    """Register Discord slash commands for channel lifecycle management."""

    @bot.tree.command(name="new-channel", description="Create a new Claude session channel")
    @app_commands.describe(
        name="Channel name (e.g., 'projects', 'knowledge', 'chat')",
        work_dir="Working directory for Claude CLI",
        options="Claude CLI options (e.g., '--dangerously-skip-permissions')",
        system_prompt="Custom system prompt for this channel's Claude session",
    )
    async def new_channel(
        interaction: discord.Interaction,
        name: str,
        work_dir: str = "",
        options: str = "",
        system_prompt: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This command must be used in a server.", ephemeral=True)
            return

        # Find or create the Claude Sessions category
        category = discord.utils.get(guild.categories, name=CLAUDE_CATEGORY_NAME)
        if category is None:
            try:
                category = await guild.create_category(CLAUDE_CATEGORY_NAME)
            except discord.Forbidden:
                await interaction.followup.send("Bot lacks permission to create categories.", ephemeral=True)
                return

        # Create the channel
        try:
            channel = await guild.create_text_channel(name, category=category)
        except discord.Forbidden:
            await interaction.followup.send("Bot lacks permission to create channels.", ephemeral=True)
            return

        # Register in channel configs
        config = settings.add_channel_config(
            channel_id=str(channel.id),
            name=name,
            work_dir=work_dir,
            claude_options=options,
            system_prompt=system_prompt,
        )

        session_num = config['session_num']

        # Start the tmux session via Flask API
        try:
            flask_port = settings.get_port('flask')
            resp = requests.post(
                f'http://localhost:{flask_port}/channels/start',
                json={
                    'channel_id': str(channel.id),
                    'channel_name': name,
                    'session_num': session_num,
                    'work_dir': config['work_dir'],
                    'claude_options': config['claude_options'],
                    'system_prompt': config.get('system_prompt', ''),
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to start tmux session: {resp.text}")
        except Exception as e:
            logger.warning(f"Could not start tmux session via API: {e}")

        await interaction.followup.send(
            f"Created channel <#{channel.id}> with Claude session `cb-{name}`\n"
            f"Work dir: `{config['work_dir']}`\n"
            f"Options: `{config['claude_options'] or '(default)'}`\n"
            f"Attach: `tmux attach -t cb-{name}`",
            ephemeral=True,
        )
        await bot.update_presence()

    @bot.tree.command(name="archive-channel", description="Archive this channel and kill its Claude session")
    async def archive_channel(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel_id = str(interaction.channel.id)
        cfg = settings.get_channel_config(channel_id)

        if cfg is None:
            await interaction.followup.send("This channel is not a Claude session channel.", ephemeral=True)
            return

        session_num = cfg['session_num']

        # Kill tmux session via Flask API
        try:
            flask_port = settings.get_port('flask')
            requests.post(
                f'http://localhost:{flask_port}/channels/stop',
                json={
                    'channel_name': cfg['name'],
                    'session_num': session_num,
                },
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Could not stop tmux session: {e}")

        # Mark as inactive
        settings.remove_channel_config(channel_id)

        # Move channel to Archived Sessions category
        try:
            guild = interaction.guild
            archive_category = discord.utils.get(guild.categories, name=CLAUDE_ARCHIVE_CATEGORY_NAME)
            if archive_category is None:
                archive_category = await guild.create_category(CLAUDE_ARCHIVE_CATEGORY_NAME)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    send_messages=False,
                )
            }
            await interaction.channel.edit(
                name=f"archived-{cfg['name']}",
                category=archive_category,
                overwrites=overwrites,
            )
            await interaction.followup.send(
                f"Archived channel and killed Claude session {session_num}.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"Killed Claude session {session_num} but could not archive channel (missing permissions).",
                ephemeral=True,
            )
        await bot.update_presence()

    @bot.tree.command(name="channel-config", description="View or update this channel's Claude config")
    @app_commands.describe(
        work_dir="New working directory (leave empty to keep current)",
        options="New Claude CLI options (leave empty to keep current)",
        system_prompt="New system prompt (leave empty to keep current)",
    )
    async def channel_config(
        interaction: discord.Interaction,
        work_dir: str = "",
        options: str = "",
        system_prompt: str = "",
    ):
        channel_id = str(interaction.channel.id)
        cfg = settings.get_channel_config(channel_id)

        if cfg is None:
            await interaction.response.send_message(
                "This channel is not a Claude session channel.", ephemeral=True
            )
            return

        # If no args provided, just show current config
        if not work_dir and not options and not system_prompt:
            prompt_preview = cfg.get('system_prompt', '')[:200]
            if len(cfg.get('system_prompt', '')) > 200:
                prompt_preview += '...'

            await interaction.response.send_message(
                f"**Channel config for #{cfg['name']}**\n"
                f"Session: {cfg['session_num']}\n"
                f"Work dir: `{cfg['work_dir']}`\n"
                f"Options: `{cfg['claude_options'] or '(default)'}`\n"
                f"System prompt: `{prompt_preview or '(none)'}`\n"
                f"Active: {cfg.get('active', True)}",
                ephemeral=True,
            )
            return

        # Update config
        await interaction.response.defer(ephemeral=True)

        updates = {}
        if work_dir:
            updates['work_dir'] = work_dir
        if options:
            updates['claude_options'] = options
        if system_prompt:
            updates['system_prompt'] = system_prompt

        updated_cfg = settings.update_channel_config(channel_id, **updates)
        session_num = updated_cfg['session_num']

        # Restart the tmux session with new config
        channel_name = updated_cfg['name']
        try:
            flask_port = settings.get_port('flask')
            # Stop old session
            requests.post(
                f'http://localhost:{flask_port}/channels/stop',
                json={'channel_name': channel_name, 'session_num': session_num},
                timeout=10,
            )
            # Start new session with updated config, resuming previous conversation
            requests.post(
                f'http://localhost:{flask_port}/channels/start',
                json={
                    'channel_id': channel_id,
                    'channel_name': channel_name,
                    'session_num': session_num,
                    'work_dir': updated_cfg['work_dir'],
                    'claude_options': updated_cfg['claude_options'],
                    'system_prompt': updated_cfg.get('system_prompt', ''),
                    'resume': True,
                    'claude_session_id': updated_cfg.get('claude_session_id', ''),
                },
                timeout=10,
            )
            await interaction.followup.send(
                f"Updated config and restarted `cb-{channel_name}`.\n"
                f"Work dir: `{updated_cfg['work_dir']}`\n"
                f"Options: `{updated_cfg['claude_options'] or '(default)'}`",
                ephemeral=True,
            )
        except Exception as e:
            logger.warning(f"Could not restart session: {e}")
            await interaction.followup.send(
                f"Updated config but could not restart session: {e}",
                ephemeral=True,
            )

    @bot.tree.command(name="list-channels", description="List all active Claude session channels")
    async def list_channels(interaction: discord.Interaction):
        channels = settings.list_channel_configs(active_only=True)

        if not channels:
            await interaction.response.send_message("No active Claude channels.", ephemeral=True)
            return

        lines = ["**Active Claude Channels:**"]
        for ch_id, cfg in channels:
            tmux_name = cfg.get('tmux_session', f"cb-{cfg['name']}")
            lines.append(
                f"<#{ch_id}> `{tmux_name}` - "
                f"`{cfg['work_dir']}` - "
                f"`{cfg['claude_options'] or '(default)'}`"
            )

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # Keep legacy prefix commands for backward compat
    @bot.command(name='status')
    async def status_command(ctx):
        """Bot status check command"""
        channels = settings.list_channel_configs()
        embed = discord.Embed(
            title="Claude CLI Bot Status",
            description="Bot is running",
            color=discord.Color.green()
        )

        if channels:
            channel_list = "\n".join(
                [f"<#{ch_id}> (session {cfg['session_num']}, `{cfg['name']}`)" for ch_id, cfg in channels]
            )
        else:
            channel_list = "No channels configured"

        embed.add_field(name="Active Channels", value=channel_list, inline=False)
        await ctx.send(embed=embed)


def run_bot():
    """Main execution function for the Discord Bot."""
    settings = SettingsManager()

    token = settings.get_token()
    if not token or token == 'your_token_here':
        print("Discord bot token not configured!")
        sys.exit(1)

    bot = ClaudeCLIBot(settings)

    try:
        bot.run(token)
    except discord.LoginFailure:
        print("Failed to login. Check your Discord bot token.")
        sys.exit(1)
    except Exception as e:
        print(f"Error running bot: {e}")
        logger.error(f"Bot execution error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run_bot()
