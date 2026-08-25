#!/bin/bash

# Configuration
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${REPO_DIR}/github_sync.log"

cd "${REPO_DIR}"

echo "------------------------------------------------" >> "${LOG_FILE}"
echo "Sync Started: $(date)" >> "${LOG_FILE}"

# 1. Stash any local changes to ensure clean pull
git stash push -m "Auto-sync stash $(date)" >> "${LOG_FILE}" 2>&1

# 2. Pull latest changes
git pull --rebase origin main >> "${LOG_FILE}" 2>&1

# 3. Pop the stash if we stashed anything
if git stash list | grep -q "Auto-sync stash"; then
    git stash pop >> "${LOG_FILE}" 2>&1
fi

echo "Sync Finished: $(date)" >> "${LOG_FILE}"
