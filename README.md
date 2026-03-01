# Claude-Discord Bridge

A bridge that connects Discord to [Claude Code](https://claude.com/claude-code) CLI sessions via tmux. Send messages from Discord, get responses from Claude — with full tool access, per-channel configuration, and conversation persistence.

Each Discord channel maps to an independent Claude CLI session with its own working directory, options, and system prompt. Manage channels with slash commands, and Claude responds back to Discord using the `dp` command.

## How It Works

```
Discord message → Discord Bot → Flask (localhost:5001) → tmux send-keys → Claude CLI
                                                                              ↓
Discord channel ← REST API ← dp command ← Claude calls dp to respond ←───────┘
```

1. You send a message in a Discord channel
2. The bot forwards it to the correct Claude CLI tmux session
3. Claude processes the message with full tool access
4. Claude calls `dp "response"` to post back to Discord

## Prerequisites

- Linux or macOS
- Python 3.8+ with [uv](https://docs.astral.sh/uv/) (recommended) or pip
- tmux
- [Claude Code CLI](https://claude.com/claude-code) installed and authenticated
- A Claude Max or API subscription
- A Discord bot token ([Developer Portal](https://discord.com/developers/applications))

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/claudiocodenza/claude-discord-bridge.git
cd claude-discord-bridge
uv venv && uv pip install -r requirements.txt
```

### 2. Create a Discord bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application, go to **Bot** tab, copy the **Token**
3. Enable **Message Content Intent** under Privileged Gateway Intents
4. Go to **OAuth2 > URL Generator**, select scopes: `bot`, `applications.commands`
5. Select permissions: **Send Messages**, **Read Message History**, **Manage Channels**, **Manage Messages**, **Add Reactions**
6. Use the generated URL to invite the bot to your server

### 3. Configure

Create the config directory and add your bot token:

```bash
mkdir -p ~/.claude-discord-bridge
cat > ~/.claude-discord-bridge/.env << 'EOF'
DISCORD_BOT_TOKEN=your_token_here
FLASK_PORT=5001
CLAUDE_WORK_DIR=/path/to/your/default/workdir
CLAUDE_OPTIONS=
EOF
chmod 600 ~/.claude-discord-bridge/.env
```

### 4. Add bridge bin to PATH

```bash
# Add to your shell config (~/.zshrc or ~/.bashrc)
export PATH="/path/to/claude-discord-bridge/bin:$PATH"
```

### 5. Start the bridge

```bash
vai
```

This starts:
- A tmux monitoring session (`claude-discord-bridge`) with the Discord bot and Flask server
- Claude CLI tmux sessions for each configured channel (`cb-<name>`)

### 6. Create your first channel

In Discord, use the slash command:

```
/new-channel name:my-project work_dir:/path/to/project
```

This creates a Discord channel, starts a Claude CLI session, and links them.

### 7. Add CLAUDE.md instructions

Claude needs to know it should respond via Discord. Add the contents of [CLAUDE.md](./CLAUDE.md) to the CLAUDE.md in your working directory so Claude uses `dp` to send responses.

## Discord Slash Commands

| Command | Description |
|---------|-------------|
| `/new-channel <name> [work_dir] [options] [system_prompt]` | Create a new channel with a Claude session |
| `/archive-channel` | Archive the current channel and kill its session |
| `/channel-config [work_dir] [options] [system_prompt]` | View or update the channel's config (restarts session if changed) |
| `/list-channels` | List all active Claude channels |

## CLI Commands

| Command | Description |
|---------|-------------|
| `vai` | Start all services |
| `vai status` | Check service status |
| `vai doctor` | Run environment diagnostics |
| `vai view` | View all Claude sessions in a single tmux layout |
| `vexit` | Stop all services |
| `dp "message"` | Send a message to the default Discord channel |
| `dp <channel_id> "message"` | Send a message to a specific channel |

## Configuration

### Config directory: `~/.claude-discord-bridge/`

| File | Purpose |
|------|---------|
| `.env` | Bot token, Flask port, default work dir and Claude options |
| `channel_configs.json` | Per-channel config (auto-managed via slash commands) |
| `sessions.json` | Legacy session mapping (backward compatibility) |

### `.env` options

```bash
DISCORD_BOT_TOKEN=       # Required. Your Discord bot token
FLASK_PORT=5001          # HTTP bridge port (default: 5001)
CLAUDE_WORK_DIR=         # Default working directory for new channels
CLAUDE_OPTIONS=          # Default Claude CLI flags for new channels
```

### Per-channel config

Each channel in `channel_configs.json` has:

| Field | Description |
|-------|-------------|
| `name` | Channel name (used for tmux session: `cb-<name>`) |
| `work_dir` | Working directory for Claude CLI |
| `claude_options` | CLI flags (e.g. `--permission-mode plan`) |
| `system_prompt` | Appended to Claude's system prompt via `--append-system-prompt` |
| `claude_session_id` | UUID for conversation persistence across restarts |

You don't edit this file directly — use `/new-channel` and `/channel-config` slash commands instead.

### Session persistence

Each channel gets a stable UUID (`claude_session_id`). When a session restarts (config change, `vai` reboot), it uses `claude --resume <uuid>` to continue the exact conversation. This works correctly even when multiple channels share the same working directory.

## tmux Sessions

The bridge creates named tmux sessions:

```bash
tmux attach -t cb-knowledge     # Attach to a channel's Claude session
tmux attach -t cb-my-project    # Sessions are named cb-<channel_name>
tmux attach -t claude-discord-bridge  # The monitoring session (bot + flask)
```

## systemd Auto-Start

A systemd user service is included for auto-start on boot:

```bash
# Install (one-time)
mkdir -p ~/.config/systemd/user
ln -sf /path/to/claude-discord-bridge/systemd/claude-discord-bridge.service \
    ~/.config/systemd/user/claude-discord-bridge.service
systemctl --user daemon-reload
systemctl --user enable claude-discord-bridge

# Enable linger so it starts without login (requires sudo)
sudo loginctl enable-linger $USER
```

```bash
# Control
systemctl --user start claude-discord-bridge
systemctl --user stop claude-discord-bridge
systemctl --user status claude-discord-bridge
```

## Healthcheck

```bash
curl http://localhost:5001/health
```

Returns JSON with active channel count, per-channel tmux status, and timestamp.

## Architecture

```
claude-discord-bridge/
├── bin/
│   ├── vai             # Start all services
│   ├── vexit           # Stop all services
│   └── dp              # Post message to Discord
├── config/
│   └── settings.py     # Config management
├── src/
│   ├── discord_bot.py  # Discord bot + slash commands
│   ├── flask_app.py    # HTTP bridge + channel routing
│   ├── tmux_manager.py # tmux session lifecycle
│   ├── discord_post.py # Posts to Discord via REST API
│   └── attachment_manager.py  # Discord attachment handling
├── systemd/
│   └── claude-discord-bridge.service
├── CLAUDE.md           # Instructions for Claude sessions
└── requirements.txt
```

## Feedback

The bot uses reaction emojis instead of text messages for acknowledgements:
- 👀 — Processing (message received, forwarding to Claude)
- ✅ — Success (message delivered to Claude session)
- ❌ — Error (posts error details as a text message)

## License

MIT License — see [LICENSE](./LICENSE) for details.

## Credits

Forked from [yamkz/claude-discord-bridge](https://github.com/yamkz/claude-discord-bridge).
