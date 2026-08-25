import os
import time
import logging
import sys
from pathlib import Path

# Add the project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

from config import EXTERNAL_LIBRARY_PATH, LIBRARY_DIR, WORKER_MODE
from preprocess_library import preprocess_google_drive
from batch_indexer import run_batch_indexing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("windows_worker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WindowsWorker")

def run_worker_cycle():
    logger.info("=== Starting Worker Cycle ===")
    
    # 1. Preprocess (Scan GDrive -> Hash -> Extract Metadata)
    # This calls preprocess_library.py logic
    try:
        logger.info(f"Scanning for new papers in: {EXTERNAL_LIBRARY_PATH}")
        preprocess_google_drive(EXTERNAL_LIBRARY_PATH, LIBRARY_DIR)
    except Exception as e:
        logger.error(f"Error during preprocessing: {e}")

    # 2. Index & Embed (Generate embeddings and save to disk)
    try:
        logger.info("Starting batch indexing and embedding...")
        run_batch_indexing(batch_size=20)
    except Exception as e:
        logger.error(f"Error during indexing: {e}")

    logger.info("=== Cycle Complete ===")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Windows Worker for AI Research Assistant")
    parser.add_argument("--single-run", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("SYNC_INTERVAL", 300)), help="Interval between cycles (seconds)")
    args = parser.parse_args()

    if not WORKER_MODE:
        logger.warning("WORKER_MODE is disabled in config.py. Please enable it to run this script.")
        # return # Proceeding anyway for now as requested
    
    logger.info("Windows Worker started.")
    logger.info(f"Local GDrive Path: {EXTERNAL_LIBRARY_PATH}")
    
    if args.single_run:
        run_worker_cycle()
        return

    while True:
        run_worker_cycle()
        logger.info(f"Sleeping for {args.interval}s...")
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
