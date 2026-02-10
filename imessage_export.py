#!/usr/bin/env python3
"""
iMessage Exporter — Download your iMessage history to an external drive.

Exports in two formats:
  1. Full backup: raw SQLite database + attachments (100% fidelity)
  2. Human-readable: plain text chat transcripts per conversation

Usage:
  python imessage_export.py /Volumes/MyDrive/imessage-backup
  python imessage_export.py ~/Desktop/backup --contact "+1234567890"
  python imessage_export.py ~/Desktop/backup --readable-only
  python imessage_export.py ~/Desktop/backup --backup-only
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys

# iMessage stores dates as nanoseconds since 2001-01-01 00:00:00 UTC.
# This is the offset from the Unix epoch (1970-01-01) to the Apple epoch (2001-01-01).
APPLE_EPOCH_OFFSET = datetime.datetime(2001, 1, 1).timestamp()

# Default iMessage database and attachments paths
DEFAULT_DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")
DEFAULT_ATTACHMENTS_PATH = os.path.expanduser("~/Library/Messages/Attachments")


def apple_timestamp_to_datetime(timestamp):
    """Convert an iMessage timestamp (nanoseconds since 2001-01-01) to a datetime."""
    if timestamp is None or timestamp == 0:
        return None
    # Post-High Sierra timestamps are in nanoseconds
    if timestamp > 1e15:
        timestamp = timestamp / 1e9
    # Pre-High Sierra timestamps are in seconds
    elif timestamp > 1e12:
        timestamp = timestamp / 1e9
    return datetime.datetime.fromtimestamp(timestamp + APPLE_EPOCH_OFFSET)


def sanitize_filename(name):
    """Make a string safe for use as a directory/file name."""
    if not name:
        return "Unknown"
    # Replace characters that are invalid in filenames
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    # Collapse multiple underscores/spaces
    sanitized = re.sub(r'[_\s]+', ' ', sanitized).strip()
    # Truncate to a reasonable length
    if len(sanitized) > 100:
        sanitized = sanitized[:100].strip()
    return sanitized or "Unknown"


def open_db_readonly(db_path):
    """Open the iMessage database in read-only mode."""
    if not os.path.exists(db_path):
        print(f"Error: iMessage database not found at {db_path}")
        print("Make sure you have granted Full Disk Access to Terminal in:")
        print("  System Settings → Privacy & Security → Full Disk Access")
        sys.exit(1)

    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        # Quick test to make sure we can read
        conn.execute("SELECT COUNT(*) FROM message")
        return conn
    except sqlite3.OperationalError as e:
        if "unable to open" in str(e) or "authorization denied" in str(e):
            print(f"Error: Cannot read iMessage database at {db_path}")
            print("You need to grant Full Disk Access to Terminal:")
            print("  System Settings → Privacy & Security → Full Disk Access")
            print("  → Add Terminal (or your terminal app)")
            sys.exit(1)
        raise


def get_chats(conn):
    """Get all chats with their display names and participants."""
    query = """
        SELECT
            c.ROWID as chat_id,
            c.chat_identifier,
            c.display_name,
            c.style as chat_style,
            GROUP_CONCAT(h.id, ', ') as participants
        FROM chat c
        LEFT JOIN chat_handle_join chj ON c.ROWID = chj.chat_id
        LEFT JOIN handle h ON chj.handle_id = h.ROWID
        GROUP BY c.ROWID
        ORDER BY c.ROWID
    """
    return conn.execute(query).fetchall()


def get_chat_display_name(chat):
    """Determine a human-friendly display name for a chat."""
    if chat["display_name"]:
        return chat["display_name"]
    if chat["participants"]:
        return chat["participants"]
    if chat["chat_identifier"]:
        return chat["chat_identifier"]
    return f"Chat {chat['chat_id']}"


def get_messages_for_chat(conn, chat_id):
    """Get all messages for a given chat, ordered by date."""
    query = """
        SELECT
            m.ROWID as message_id,
            m.text,
            m.date as message_date,
            m.is_from_me,
            m.date_delivered,
            m.date_read,
            m.service,
            m.associated_message_type,
            h.id as sender_id
        FROM message m
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
        ORDER BY m.date ASC
    """
    return conn.execute(query, (chat_id,)).fetchall()


def get_attachments_for_message(conn, message_id):
    """Get all attachments for a given message."""
    query = """
        SELECT
            a.ROWID as attachment_id,
            a.filename,
            a.mime_type,
            a.transfer_name,
            a.total_bytes
        FROM attachment a
        JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
        WHERE maj.message_id = ?
    """
    return conn.execute(query, (message_id,)).fetchall()


def format_reaction(associated_message_type):
    """Convert an associated_message_type to a human-readable reaction string."""
    reactions = {
        2000: "Loved",
        2001: "Liked",
        2002: "Disliked",
        2003: "Laughed at",
        2004: "Emphasized",
        2005: "Questioned",
        3000: "Removed love from",
        3001: "Removed like from",
        3002: "Removed dislike from",
        3003: "Removed laugh from",
        3004: "Removed emphasis from",
        3005: "Removed question from",
    }
    return reactions.get(associated_message_type)


def copy_attachment_file(attachment, dest_dir):
    """Copy a single attachment file to the destination directory.

    Returns the basename of the copied file, or None if the copy failed.
    """
    if not attachment["filename"]:
        return None

    source_path = attachment["filename"]
    # iMessage stores paths with ~ prefix
    if source_path.startswith("~"):
        source_path = os.path.expanduser(source_path)

    if not os.path.exists(source_path):
        return None

    dest_name = attachment["transfer_name"] or os.path.basename(source_path)
    dest_path = os.path.join(dest_dir, dest_name)

    # Handle name collisions
    base, ext = os.path.splitext(dest_name)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
        counter += 1

    try:
        shutil.copy2(source_path, dest_path)
        return os.path.basename(dest_path)
    except (OSError, IOError) as e:
        print(f"  Warning: Could not copy attachment {source_path}: {e}")
        return None


def do_raw_backup(db_path, attachments_path, dest_dir):
    """Copy the raw database and attachments folder to the destination."""
    backup_dir = os.path.join(dest_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)

    # Copy database
    print("Copying iMessage database...")
    db_dest = os.path.join(backup_dir, "chat.db")
    shutil.copy2(db_path, db_dest)
    db_size = os.path.getsize(db_dest)
    print(f"  Database copied ({db_size / (1024*1024):.1f} MB)")

    # Copy attachments
    att_dest = os.path.join(backup_dir, "Attachments")
    if os.path.exists(attachments_path):
        print("Copying attachments folder (this may take a while)...")
        if os.path.exists(att_dest):
            print("  Attachments folder already exists at destination, merging...")
        shutil.copytree(attachments_path, att_dest, dirs_exist_ok=True)
        # Calculate total size
        total_size = 0
        file_count = 0
        for dirpath, _, filenames in os.walk(att_dest):
            for f in filenames:
                total_size += os.path.getsize(os.path.join(dirpath, f))
                file_count += 1
        print(f"  Attachments copied: {file_count} files ({total_size / (1024*1024):.1f} MB)")
    else:
        print("  No attachments folder found, skipping.")

    return backup_dir


def do_readable_export(conn, dest_dir, contact_filter=None):
    """Generate human-readable text transcripts per conversation."""
    readable_dir = os.path.join(dest_dir, "readable")
    os.makedirs(readable_dir, exist_ok=True)

    chats = get_chats(conn)
    print(f"\nFound {len(chats)} conversations")

    total_messages = 0
    total_attachments_copied = 0
    exported_chats = 0

    for chat in chats:
        chat_name = get_chat_display_name(chat)

        # Apply contact filter if specified
        if contact_filter:
            identifiers = [
                chat["chat_identifier"] or "",
                chat["participants"] or "",
                chat["display_name"] or "",
            ]
            if not any(contact_filter.lower() in ident.lower() for ident in identifiers):
                continue

        messages = get_messages_for_chat(conn, chat["chat_id"])
        if not messages:
            continue

        exported_chats += 1
        safe_name = sanitize_filename(chat_name)
        chat_dir = os.path.join(readable_dir, safe_name)
        os.makedirs(chat_dir, exist_ok=True)

        # Attachments subdirectory for this chat
        att_dir = os.path.join(chat_dir, "attachments")

        is_group = chat["chat_style"] == 43
        chat_type = "Group Chat" if is_group else "Conversation"

        lines = []
        lines.append(f"{'=' * 60}")
        lines.append(f"{chat_type}: {chat_name}")
        lines.append(f"{'=' * 60}")
        lines.append(f"Messages: {len(messages)}")
        lines.append("")

        for msg in messages:
            total_messages += 1
            dt = apple_timestamp_to_datetime(msg["message_date"])
            timestamp = dt.strftime("%Y-%m-%d %-I:%M %p") if dt else "Unknown date"

            sender = "Me" if msg["is_from_me"] else (msg["sender_id"] or "Unknown")

            # Check if this is a reaction
            reaction = format_reaction(msg["associated_message_type"])
            if reaction:
                target_text = (msg["text"] or "a message")
                # Reaction texts often start with special characters — clean up
                if target_text.startswith("\ufffc"):
                    target_text = "a message"
                lines.append(f"[{timestamp}] {sender} {reaction} {target_text}")
                continue

            # Regular message
            text = msg["text"] or ""

            # Check for attachments
            attachments = get_attachments_for_message(conn, msg["message_id"])
            attachment_notes = []
            for att in attachments:
                att_name = att["transfer_name"] or "file"
                # Copy attachment if possible
                os.makedirs(att_dir, exist_ok=True)
                copied_name = copy_attachment_file(att, att_dir)
                if copied_name:
                    attachment_notes.append(f"<attachment: {copied_name}>")
                    total_attachments_copied += 1
                else:
                    attachment_notes.append(f"<attachment: {att_name} (not available)>")

            # Build the message line
            parts = []
            if text.strip():
                # Remove the object replacement character that appears with attachments
                clean_text = text.replace("\ufffc", "").strip()
                if clean_text:
                    parts.append(clean_text)
            parts.extend(attachment_notes)

            if not parts:
                # Empty message (could be an unsupported message type)
                continue

            content = "\n    ".join(parts) if len(parts) > 1 else parts[0]
            lines.append(f"[{timestamp}] {sender}: {content}")

        # Write transcript
        transcript_path = os.path.join(chat_dir, "chat.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.write("\n")

        # Progress
        if exported_chats % 10 == 0:
            print(f"  Exported {exported_chats} conversations...")

    print(f"  Exported {exported_chats} conversations, {total_messages} messages, "
          f"{total_attachments_copied} attachments")

    return {
        "conversations": exported_chats,
        "messages": total_messages,
        "attachments_copied": total_attachments_copied,
    }


def write_export_info(dest_dir, stats):
    """Write a summary JSON file with export metadata."""
    info = {
        "export_timestamp": datetime.datetime.now().isoformat(),
        "tool": "imessage-exporter",
        "source_db": DEFAULT_DB_PATH,
        **stats,
    }
    info_path = os.path.join(dest_dir, "export_info.json")
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2, default=str)
    print(f"\nExport summary written to {info_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export iMessage history to an external drive.",
        epilog="Example: python imessage_export.py /Volumes/MyDrive/imessage-backup",
    )
    parser.add_argument(
        "destination",
        help="Destination directory for the export (e.g. /Volumes/MyDrive/imessage-backup)",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to iMessage database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--attachments-path",
        default=DEFAULT_ATTACHMENTS_PATH,
        help=f"Path to iMessage attachments (default: {DEFAULT_ATTACHMENTS_PATH})",
    )
    parser.add_argument(
        "--contact",
        help="Export only conversations matching this contact (phone number, email, or name)",
    )
    parser.add_argument(
        "--readable-only",
        action="store_true",
        help="Only export human-readable transcripts (skip raw database backup)",
    )
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Only copy raw database and attachments (skip readable transcripts)",
    )

    args = parser.parse_args()

    if args.readable_only and args.backup_only:
        print("Error: --readable-only and --backup-only are mutually exclusive.")
        sys.exit(1)

    dest = os.path.abspath(args.destination)
    os.makedirs(dest, exist_ok=True)

    print(f"iMessage Exporter")
    print(f"Destination: {dest}")
    print()

    stats = {}

    # Raw backup
    if not args.readable_only:
        print("--- Raw Backup ---")
        do_raw_backup(args.db_path, args.attachments_path, dest)
        print()

    # Readable export
    if not args.backup_only:
        print("--- Readable Transcripts ---")
        conn = open_db_readonly(args.db_path)
        try:
            export_stats = do_readable_export(conn, dest, contact_filter=args.contact)
            stats.update(export_stats)
        finally:
            conn.close()

    # Write summary
    write_export_info(dest, stats)
    print("\nDone!")


if __name__ == "__main__":
    main()
