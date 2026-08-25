import os
import getpass
import socket
from pathlib import Path

# --- Machine & Environment Configurations ---
USER = getpass.getuser()
HOSTNAME = socket.gethostname()

# Worker Mode (Enabled if this computer runs background embedding/metadata tasks)
# Defaults to True on Windows (the worker) and False otherwise
IS_WINDOWS = os.name == 'nt'
WORKER_MODE = os.environ.get("WORKER_MODE", "true" if IS_WINDOWS else "false").lower() == "true"

# Local Google Drive Path (Optional, for auto-syncing from a cloud folder)
LOCAL_GDRIVE_PATH = os.environ.get("LOCAL_GDRIVE_PATH", "")

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent

# External PDF Library Path (Inbox for new papers)
if LOCAL_GDRIVE_PATH and Path(LOCAL_GDRIVE_PATH).exists():
    EXTERNAL_LIBRARY_PATH = Path(LOCAL_GDRIVE_PATH)
else:
    EXTERNAL_LIBRARY_PATH = PROJECT_ROOT / "inbox"

# Authentication Token for REST API & Frontend
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "vibe-coding-secret")

# Database and Library Directories
CHROMA_DB_PATH = str(PROJECT_ROOT / "chroma_db")
LIBRARY_DIR = PROJECT_ROOT / "library"

def get_config_summary():
    return {
        "user": USER,
        "hostname": HOSTNAME,
        "project_root": str(PROJECT_ROOT),
        "external_library": str(EXTERNAL_LIBRARY_PATH),
        "db_path": CHROMA_DB_PATH
    }

if __name__ == "__main__":
    import json
    print(json.dumps(get_config_summary(), indent=4))
