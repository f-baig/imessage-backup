# iMessage Downloader — Implementation Plan

## Overview
Python CLI tool that exports iMessage data to an external drive in two formats:
1. **Full backup** — Raw SQLite database copy + attachments (100% fidelity)
2. **Human-readable** — Plain text chat transcripts per conversation

## Output Structure
```
<destination>/
├── backup/
│   ├── chat.db                    # Exact copy of iMessage database
│   └── Attachments/               # Exact copy of attachments folder
├── readable/
│   ├── John Smith (+1234567890)/
│   │   ├── chat.txt               # Human-readable transcript
│   │   └── attachments/           # Copied attachments for this chat
│   ├── Group Chat Name/
│   │   ├── chat.txt
│   │   └── attachments/
│   └── ...
└── export_info.json               # Metadata: timestamp, message count, etc.
```

## Human-Readable Format (chat.txt)
```
=== Conversation with John Smith (+1234567890) ===
Exported: 2026-02-10

[2025-01-15 3:42 PM] John Smith: Hey what's up
[2025-01-15 3:43 PM] Me: Not much, you?
[2025-01-15 3:44 PM] John Smith: <attachment: photo.jpg>
[2025-01-15 3:45 PM] Me: Nice!
```

## CLI Usage
```bash
# Export everything to a destination
python imessage_export.py /Volumes/MyDrive/imessage-backup

# Export only specific contact
python imessage_export.py /Volumes/MyDrive/imessage-backup --contact "+1234567890"

# Export only readable transcripts (skip raw backup)
python imessage_export.py /Volumes/MyDrive/imessage-backup --readable-only

# Export only raw backup (skip transcripts)
python imessage_export.py /Volumes/MyDrive/imessage-backup --backup-only
```

## Files to Create
1. **imessage_export.py** — Single-file CLI tool, all logic in one file. Sections:
   - Argument parsing (argparse)
   - Database reading (sqlite3, read-only connection)
   - Raw backup (shutil.copy2 for db, shutil.copytree for attachments)
   - Transcript generation (iterate chats → messages → write text files)
   - Attachment copying per conversation
   - Export summary/metadata

## Key Design Decisions
- **Read-only** — Opens chat.db with `?mode=ro` URI, never modifies source data
- **Single file** — No dependencies beyond Python stdlib (sqlite3, shutil, argparse, json)
- **macOS date handling** — iMessage stores dates as nanoseconds since 2001-01-01; we convert to readable timestamps
- **Safe filenames** — Sanitize contact names for use as directory names
- **Progress output** — Print progress to terminal as it exports

## Database Queries Needed
- List all chats with display names: `chat` + `chat_handle_join` + `handle`
- Get messages per chat: `chat_message_join` + `message` + `handle`
- Get attachments per message: `message_attachment_join` + `attachment`
