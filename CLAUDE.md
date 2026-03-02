## Discord Bridge — Claude Session Instructions

You are running inside a Discord bridge session. Your responses are automatically forwarded to Discord via Claude Code hooks — just respond normally.

### How it works
- A **PostToolUse hook** sends real-time progress updates and intermediate text to the user's Discord channel
- A **Stop hook** sends your final response when you finish
- You do NOT need to manually post to Discord — it's all automatic

### Handling image attachments
When a message contains `[attached image: /path/to/image.png]`:
1. Read the image file using the `Read` tool
2. Analyze the image content and respond appropriately

### Everything else works normally
- You have full tool access (Read, Edit, Write, Bash, Grep, Glob, etc.)
- You have access to MCP servers and skills
- Project CLAUDE.md instructions still apply
