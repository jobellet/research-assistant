import os
import getpass
import socket
from pathlib import Path

# --- Machine-Specific Configurations ---
USER = getpass.getuser()
HOSTNAME = socket.gethostname()

# Worker Mode (Enabled if this computer should help with embeddings/metadata)
# Defaults to True on Windows (the worker) and False otherwise (the iMac server)
IS_WINDOWS = os.name == 'nt'
WORKER_MODE = os.environ.get("WORKER_MODE", "true" if IS_WINDOWS else "false").lower() == "true"

# Local Google Drive Path (Bypass gdown on Windows)
# This is specific to your Windows setup. On iMac, this path won't exist.
LOCAL_GDRIVE_PATH = os.environ.get("LOCAL_GDRIVE_PATH", r"G:\Mon Drive\scientific_papers")

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent

# --- Data Directory ---
# The single source of truth for where ALL research data lives.
# Set DATA_DIR in .env to point to an external folder (e.g., Google Drive).
# If not set, falls back to the repo root for backward compatibility.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT)))

# External PDF Library Path (Inbox for new papers)
if LOCAL_GDRIVE_PATH and Path(LOCAL_GDRIVE_PATH).exists():
    EXTERNAL_LIBRARY_PATH = Path(LOCAL_GDRIVE_PATH)
else:
    EXTERNAL_LIBRARY_PATH = DATA_DIR / "inbox"

# Authentication
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "vibe-coding-secret")

# --- All data paths derive from DATA_DIR ---
LIBRARY_DIR = DATA_DIR / "library"
CHROMA_DB_PATH = str(DATA_DIR / "chroma_db")
BOW_INDEX_PATH = DATA_DIR / "library" / "global_bow_index.json"
GRAPH_CACHE_PATH = DATA_DIR / "library" / "graph_cache.json"
CITATION_GRAPH_PATH = DATA_DIR / "library" / "citation_graph.json"
PROCESSED_REGISTRY_PATH = DATA_DIR / ".file_registry.json"

def ensure_data_dirs():
    """Ensure standard data directories exist."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    Path(CHROMA_DB_PATH).mkdir(parents=True, exist_ok=True)

def get_config_summary():
    return {
        "user": USER,
        "hostname": HOSTNAME,
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(DATA_DIR),
        "library_dir": str(LIBRARY_DIR),
        "external_library": str(EXTERNAL_LIBRARY_PATH),
        "db_path": CHROMA_DB_PATH,
        "bow_index": str(BOW_INDEX_PATH),
        "graph_cache": str(GRAPH_CACHE_PATH),
        "citation_graph": str(CITATION_GRAPH_PATH),
        "file_registry": str(PROCESSED_REGISTRY_PATH),
    }

if __name__ == "__main__":
    import json
    print(json.dumps(get_config_summary(), indent=4))
