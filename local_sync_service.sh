#!/bin/bash
# Local Sync Service for AI Research Assistant
# This script handles GDrive sync and metadata extraction.

# Resolve the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
CONDA_ENV="ai_research_assistant"
PYTHON=$(conda info --base)/envs/${CONDA_ENV}/bin/python
LOG_FILE="${SCRIPT_DIR}/sync_service.log"

echo "Starting Local Sync Service (Interval: 5 min)..."
echo "Logs → ${LOG_FILE}"

while true
do
    echo "------------------------------------------------" >> "$LOG_FILE"
    echo "Sync Cycle Started: $(date)" >> "$LOG_FILE"
    
    # 1. Sync from Google Drive
    echo "[1/2] Syncing from Google Drive..." >> "$LOG_FILE"
    "$PYTHON" scripts/gdrive_sync.py >> "$LOG_FILE" 2>&1
    
    # 2. Preprocess (Hashing + Metadata Extraction)
    echo "[2/2] Preprocessing new papers..." >> "$LOG_FILE"
    # Ensure PYTHONPATH is set so internal modules are found
    PYTHONPATH="$SCRIPT_DIR" "$PYTHON" preprocess_library.py >> "$LOG_FILE" 2>&1
    
    echo "Cycle complete. $(date)" >> "$LOG_FILE"
    echo "Sleeping for 5 minutes..." >> "$LOG_FILE"
    sleep 300
done
