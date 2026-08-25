import os
import subprocess
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("gdrive_sync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

import sys

def sync_gdrive(folder_id, dest_path):
    """
    Uses gdown to sync a Google Drive folder to a local directory.
    """
    dest_path = Path(dest_path)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting sync for GDrive folder: {folder_id}")
    
    # Construct the gdown command using sys.executable to ensure we use the same environment
    # Use fuzzy matching for better URL/ID detection
    cmd = [
        sys.executable, "-m", "gdown", 
        f"https://drive.google.com/drive/folders/{folder_id}", 
        "-O", str(dest_path), 
        "--folder",
        "--continue",
        "--fuzzy"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("Sync completed successfully.")
        else:
            # Check for common Google Drive errors
            if "Too many requests" in result.stderr or "429" in result.stderr:
                logger.error("Sync failed: Google Drive Rate Limit exceeded. Will retry next cycle.")
            elif "Access denied" in result.stderr:
                logger.error("Sync failed: Access denied. Ensure the folder is public.")
            else:
                logger.error(f"Sync failed with error: {result.stderr}")
    except Exception as e:
        logger.error(f"An error occurred during sync: {e}")

if __name__ == "__main__":
    # The folder ID provided by the user
    FOLDER_ID = "12xY78VsoT7ghfPZfJ8L1591FzUuSdEtv"
    
    # Destination is the 'inbox' folder in the project root
    PROJECT_ROOT = Path(__file__).parent.parent
    DEST_DIR = PROJECT_ROOT / "inbox"
    
    sync_gdrive(FOLDER_ID, DEST_DIR)
