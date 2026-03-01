## Rules for handling notifications via Discord

When you receive a message containing any of the following patterns, treat it as a "Discord notification":
1. Messages starting with "Discord notification:"
2. Messages with `session=NUMBER` at the end
3. Slash commands (e.g., `/project-analyze session=1`)

When a "Discord notification" arrives, follow these rules:
### Basic response rules
1. **Do not respond via CLI output. Always use the `Bash` tool to send messages with the `dp` command.**
2. `dp` command usage examples:
   - `dp "response message"` (default session)
   - `dp 2 "response to session 2"` (specific session)
   - `dp 1234567890 "send directly by channel ID"` (channel ID)

### Mentioning users in Discord replies
- Include the user's mention `<@user_id>` in normal replies
- Place it at the beginning of the message
- Do not include a mention in progress updates using quote format (lines starting with "> ")

### Handling image attachments
When a message contains `[attached image: /path/to/image.png]`:
1. Read the image file using the `Read` tool
2. Analyze the image content and respond appropriately
3. Use it for UI/UX review, code review, document processing, etc.

### Output examples

**Example output (with newlines for longer messages)**
```
dp 1 "<@user_id> {response}\n{response}" (for session=1)
dp 2 "<@user_id> {response}\n{response}" (for session=2)
```
