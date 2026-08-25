#!/bin/bash
# Local Sync Service for AI Research Assistant
# Syncs cloud folders and extracts metadata.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONDA_ENV="ai_research_assistant"
if command -v conda >/dev/null 2>&1; then
    PYTHON="$(conda info --base)/envs/${CONDA_ENV}/bin/python"
else
    PYTHON="${HOME}/opt/miniconda3/envs/${CONDA_ENV}/bin/python"
fi

LOG_FILE="${SCRIPT_DIR}/sync_service.log"

echo "Starting Local Sync Service (Interval: 5 min)..."
echo "Logs -> ${LOG_FILE}"

while true
do
    echo "------------------------------------------------" >> "$LOG_FILE"
    echo "Sync Cycle Started: $(date)" >> "$LOG_FILE"
    
    # 1. Sync from Google Drive (if configured)
    if [ -f scripts/gdrive_sync.py ]; then
        echo "[1/2] Checking sync sources..." >> "$LOG_FILE"
        "$PYTHON" scripts/gdrive_sync.py >> "$LOG_FILE" 2>&1 || true
    fi
    
    # 2. Preprocess (Hashing + Metadata Extraction)
    echo "[2/2] Preprocessing new papers..." >> "$LOG_FILE"
    PYTHONPATH="$SCRIPT_DIR" "$PYTHON" preprocess_library.py >> "$LOG_FILE" 2>&1 || true
    
    echo "Cycle complete: $(date)" >> "$LOG_FILE"
    echo "Sleeping for 5 minutes..." >> "$LOG_FILE"
    sleep 300
done
