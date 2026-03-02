#!/usr/bin/env python3
"""
Shared utility for extracting unsent text blocks from Claude transcripts.

Used by both progress-hook and stop-hook to avoid duplicate messages.
Tracks how many text blocks have been sent per channel via a temp file.
"""

import json
import os
import sys


def get_turn_texts(transcript_path: str) -> list[str]:
    """Extract all assistant text blocks from the current turn."""
    entries = []
    with open(transcript_path, 'r', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        return []

    # Find the last user message index
    last_user_idx = -1
    for i in range(len(entries) - 1, -1, -1):
        if entries[i].get('type') == 'user':
            last_user_idx = i
            break

    if last_user_idx < 0:
        return []

    # Collect all entries after the last user message
    turn_entries = entries[last_user_idx + 1:]

    # Check if dp was used in this turn (avoid double-posting)
    for entry in turn_entries:
        if entry.get('type') != 'assistant':
            continue
        content = entry.get('message', {}).get('content', [])
        for block in content:
            if block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                cmd = block.get('input', {}).get('command', '')
                if cmd.strip().startswith('dp ') or cmd.strip().startswith('dp"'):
                    return []  # dp was used, skip everything

    # Collect text from assistant messages
    texts = []
    for entry in turn_entries:
        if entry.get('type') != 'assistant':
            continue
        content = entry.get('message', {}).get('content', [])
        for block in content:
            if block.get('type') == 'text':
                text = block.get('text', '').strip()
                if text:
                    texts.append(text)

    return texts


def get_sent_count(channel_id: str) -> int:
    """Get the number of text blocks already sent for this channel's current turn."""
    count_file = f'/tmp/claude-text-sent-{channel_id}.count'
    try:
        with open(count_file, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def update_sent_count(channel_id: str, count: int):
    """Update the sent text block count."""
    count_file = f'/tmp/claude-text-sent-{channel_id}.count'
    with open(count_file, 'w') as f:
        f.write(str(count))


def reset_sent_count(channel_id: str):
    """Reset the sent count (call at start of new turn)."""
    count_file = f'/tmp/claude-text-sent-{channel_id}.count'
    try:
        os.remove(count_file)
    except FileNotFoundError:
        pass


def get_unsent_texts(transcript_path: str, channel_id: str) -> list[str]:
    """Get text blocks that haven't been sent yet."""
    all_texts = get_turn_texts(transcript_path)
    sent_count = get_sent_count(channel_id)
    unsent = all_texts[sent_count:]
    return unsent


def mark_texts_sent(channel_id: str, total_count: int):
    """Mark that we've sent up to total_count text blocks."""
    update_sent_count(channel_id, total_count)


if __name__ == '__main__':
    # CLI interface for hook scripts
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['unsent', 'mark-sent', 'reset', 'all'])
    parser.add_argument('--transcript', required=False)
    parser.add_argument('--channel', required=True)
    parser.add_argument('--count', type=int, required=False)
    args = parser.parse_args()

    if args.action == 'unsent':
        if not args.transcript:
            sys.exit(1)
        texts = get_unsent_texts(args.transcript, args.channel)
        all_texts = get_turn_texts(args.transcript)
        # Output: first line is total count, then each text block separated by NULL
        print(len(all_texts))
        for t in texts:
            sys.stdout.write(t)
            sys.stdout.write('\x00')

    elif args.action == 'mark-sent':
        if args.count is None:
            sys.exit(1)
        mark_texts_sent(args.channel, args.count)

    elif args.action == 'reset':
        reset_sent_count(args.channel)

    elif args.action == 'all':
        if not args.transcript:
            sys.exit(1)
        texts = get_turn_texts(args.transcript)
        for t in texts:
            sys.stdout.write(t)
            sys.stdout.write('\x00')
