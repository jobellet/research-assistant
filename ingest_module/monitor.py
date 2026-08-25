import time
import os
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Try relative import, fall back to direct import if run as script
try:
    from .ingestor import process_file
except ImportError:
    from ingestor import process_file

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class InboxHandler(FileSystemEventHandler):
    """Handles file system events in the inbox directory."""
    def __init__(self, inbox_dir: str, library_dir: str):
        self.inbox_dir = inbox_dir
        self.library_dir = library_dir

    def on_created(self, event):
        if not event.is_directory:
            logger.info(f"New file detected: {event.src_path}")
            # Small delay to ensure file is fully written
            time.sleep(0.5)
            process_file(event.src_path, self.library_dir)

    def on_moved(self, event):
        # Handle files moved into the inbox (e.g., from another folder on the same disk)
        if not event.is_directory:
            dest_path = Path(event.dest_path)
            # Check if it was moved INTO the inbox
            if dest_path.parent.resolve() == Path(self.inbox_dir).resolve():
                logger.info(f"File moved into inbox: {dest_path}")
                time.sleep(0.5)
                process_file(str(dest_path), self.library_dir)

def start_monitoring(inbox_dir: str, library_dir: str):
    """Starts the monitoring service."""
    inbox_path = Path(inbox_dir).resolve()
    library_path = Path(library_dir).resolve()

    # Ensure directories exist
    inbox_path.mkdir(parents=True, exist_ok=True)
    library_path.mkdir(parents=True, exist_ok=True)

    # 1. Initial scan of existing files
    logger.info(f"Performing initial scan of {inbox_path}...")
    for item in inbox_path.iterdir():
        if item.is_file():
            process_file(str(item), str(library_path))

    # 2. Setup Watchdog Observer
    event_handler = InboxHandler(str(inbox_path), str(library_path))
    observer = Observer()
    observer.schedule(event_handler, str(inbox_path), recursive=False)
    observer.start()
    
    logger.info(f"Monitoring {inbox_path} for new PDFs...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping monitor...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    # Default paths for independent testing from root
    # To run: python3 ingest_module/monitor.py
    ROOT_DIR = Path(__file__).parent.parent
    INBOX = ROOT_DIR / "inbox"
    LIBRARY = ROOT_DIR / "library"
    
    start_monitoring(str(INBOX), str(LIBRARY))
