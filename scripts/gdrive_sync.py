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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def sync_gdrive(folder_id, dest_path):
    """Download a publicly shared Google Drive folder into ``dest_path`` (resumable).

    Uses gdown's Python API: the ``--fuzzy`` command-line flag previously used
    here was removed from recent gdown versions, which made every sync fail.
    """
    import gdown

    dest_path = Path(dest_path)
    dest_path.mkdir(parents=True, exist_ok=True)
    url = folder_id if folder_id.startswith("http") else f"https://drive.google.com/drive/folders/{folder_id}"
    logger.info(f"Starting sync for GDrive folder: {url}")
    kwargs = dict(url=url, output=str(dest_path), quiet=False)
    try:
        try:
            files = gdown.download_folder(resume=True, **kwargs)
        except TypeError:  # gdown < 5 has no resume argument
            files = gdown.download_folder(**kwargs)
    except Exception as e:
        msg = str(e)
        if "Too many" in msg or "429" in msg:
            logger.error("Sync failed: Google Drive rate limit exceeded. Try again later.")
        elif "Access denied" in msg or "permission" in msg.lower():
            logger.error("Sync failed: access denied. Share the folder as 'Anyone with the link'.")
        else:
            logger.error(f"Sync failed: {msg}")
        return []
    files = files or []
    logger.info(f"Sync completed: {len(files)} files in {dest_path}")
    return files


if __name__ == "__main__":
    import argparse
    from config import EXTERNAL_LIBRARY_PATH

    parser = argparse.ArgumentParser(description="Mirror a public Google Drive folder into the inbox.")
    parser.add_argument("folder", nargs="?", default=os.getenv("GDRIVE_FOLDER_ID"),
                        help="folder id or URL (default: $GDRIVE_FOLDER_ID)")
    parser.add_argument("--dest", default=str(EXTERNAL_LIBRARY_PATH), help="destination (default: the inbox)")
    args = parser.parse_args()
    if not args.folder:
        parser.error("give a folder id/URL or set GDRIVE_FOLDER_ID")
    sync_gdrive(args.folder, args.dest)
