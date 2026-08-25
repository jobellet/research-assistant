#!/bin/bash
# Sync script for my-ai-research-assistant

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="${REPO_DIR:-$SCRIPT_DIR}"
LOG_FILE="${LOG_FILE:-$REPO_DIR/sync.log}"

echo "$(date): Starting sync for my-ai-research-assistant" >> "$LOG_FILE"

cd "$REPO_DIR" || exit

# 1. Pull latest changes FIRST
git pull --rebase origin main >> "$LOG_FILE" 2>&1

# 2. Add and Commit
git add . >> "$LOG_FILE" 2>&1

# Commit if there are changes
if ! git diff-index --quiet HEAD --; then
    git commit -m "auto: update research data and inventory" >> "$LOG_FILE" 2>&1
    
    # Push with retries/pulls to ensure it goes through
    git push origin main >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "$(date): Push rejected, trying one more pull/push cycle" >> "$LOG_FILE"
        git pull --rebase origin main >> "$LOG_FILE" 2>&1
        git push origin main >> "$LOG_FILE" 2>&1
    fi
    echo "$(date): Sync operation completed" >> "$LOG_FILE"
fi

if [ $? -eq 0 ]; then
    echo "$(date): Sync successful" >> "$LOG_FILE"
else
    echo "$(date): Sync failed" >> "$LOG_FILE"
fi
