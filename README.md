### IMessage Backup Tool
Currrently there exists no free and easy way to store your iMessages in backup. Oftentimes (certainly in my case), iMessages take up a large amount of storage and often contain important/sentimental data which should not be deleted. This tool is meant to fix that issue through a simple Claude Code authored Python script that can be run from the CLI. 

## Steps to Run                                                               
                  
  ### 1. Grant Full Disk Access to your terminal                                
  iMessage data is protected by macOS. You need to allow your terminal app to   
  read it:
  1. Open **System Settings** → **Privacy & Security** → **Full Disk Access**
  2. Click **+** and add your terminal app (Terminal, iTerm, etc.)
  3. Restart your terminal

  ### 2. Run the export
  ```bash
  # Export everything (raw backup + readable transcripts) to a destination
  python3 imessage_export.py /Volumes/MyDrive/imessage-backup

  # Export only a specific contact
  python3 imessage_export.py /Volumes/MyDrive/imessage-backup --contact
  "+1234567890"

  # Export only human-readable transcripts (skip raw database copy)
  python3 imessage_export.py /Volumes/MyDrive/imessage-backup --readable-only

  # Export only raw database backup (skip transcripts)
  python3 imessage_export.py /Volumes/MyDrive/imessage-backup --backup-only

  3. View your export

  <destination>/
  ├── backup/
  │   ├── chat.db              # Exact copy of iMessage database
  │   └── Attachments/         # Exact copy of all attachments
  ├── readable/
  │   ├── John Smith/
  │   │   ├── chat.txt         # Human-readable transcript
  │   │   └── attachments/     # Attachments for this conversation
  │   ├── Group Chat Name/
  │   │   ├── chat.txt
  │   │   └── attachments/
  │   └── ...
  └── export_info.json          # Export metadata and stats

  Requirements

  - macOS (tested on macOS 15)
  - Python 3.6+
  - No external dependencies — uses only Python standard library
