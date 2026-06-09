#!/bin/bash
# Sends the daily lead report to Telegram at 5PM Mon-Fri.

PROJECT="/Users/zicong/Desktop/LinkedIn Outreach Agent"
PYTHON="$PROJECT/.venv/bin/python"
LOG="$PROJECT/logs/daily_report.log"

mkdir -p "$PROJECT/logs"

echo "---" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') Sending daily report" >> "$LOG"

cd "$PROJECT"
"$PYTHON" -m outreach daily-report >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') Done" >> "$LOG"
