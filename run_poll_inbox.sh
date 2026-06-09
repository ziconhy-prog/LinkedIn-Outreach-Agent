#!/bin/bash
# Runs poll-inbox. Called by launchd on weekdays at 10AM, 12PM, 4PM MYT.
# Weekday guard is enforced by the launchd plist — this script always runs if called.

PROJECT="/Users/zicong/Desktop/LinkedIn Outreach Agent"
PYTHON="$PROJECT/.venv/bin/python"
LOG="$PROJECT/logs/poll_inbox.log"

mkdir -p "$PROJECT/logs"

echo "---" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting poll-inbox" >> "$LOG"

cd "$PROJECT"
"$PYTHON" -m outreach poll-inbox >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') Done" >> "$LOG"
