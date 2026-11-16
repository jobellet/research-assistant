import os
import time
import threading
import logging
from pathlib import Path
import json
import subprocess

# Import existing modules
# We assume they are in the python path
try:
    from ingest_module.ingestor import process_file
    from extract_module.extractor import main as run_extraction
    from db_module.db_manager import DBManager
    from config import LIBRARY_DIR, EXTERNAL_LIBRARY_PATH
except ImportError:
    # Handle direct execution or testing scenarios
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from ingest_module.ingestor import process_file
    from extract_module.extractor import main as run_extraction
    from db_module.db_manager import DBManager
    from config import LIBRARY_DIR, EXTERNAL_LIBRARY_PATH

logger = logging.getLogger(__name__)

class ManuscriptProcessor:
    """Background loop: inbox → library → metadata → word index/keywords → embeddings.

    ``on_library_changed`` (optional callable) is invoked after a cycle that
    added or re-indexed papers, so the server can reload the word index and
    rebuild the knowledge graph.
    """

    def __init__(self, library_dir=None, inbox_dir=None, interval=5, db_manager=None,
                 on_library_changed=None):
        self.library_dir = Path(library_dir) if library_dir else LIBRARY_DIR
        self.inbox_dir = Path(inbox_dir) if inbox_dir else EXTERNAL_LIBRARY_PATH
        self.interval = interval
        self.running = False
        self.thread = None
        
        # Configuration flags (toggles)
        self.config = {
            "process_new_pdfs": True,
            "add_doi": True,
            "add_authors": True,
            "add_title": True,
            "find_keyword": True,
            "compute_semantic_embedding": os.getenv("COMPUTE_SEMANTIC_EMBEDDING", "true").lower() == "true"
        }
        
        self.db_manager = db_manager or DBManager()
        self.on_library_changed = on_library_changed
        self.last_cycle = {}
        self._lock = threading.Lock()

    def update_config(self, new_config):
        with self._lock:
            self.config.update(new_config)
            logger.info(f"Processor config updated: {self.config}")

    def get_status(self):
        return {
            "running": self.running,
            "config": self.config,
            "last_cycle": self.last_cycle,
        }

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info("Manuscript Processor started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("Manuscript Processor stopped.")

    def _run_loop(self):
        while self.running:
            try:
                self._process_tasks()
            except Exception as e:
                logger.error(f"Error in processor loop: {e}")
            time.sleep(self.interval)

    def _process_tasks(self):
        with self._lock:
            current_config = self.config.copy()

        changed = False

        # 1. Process New PDFs (Ingestion)
        n_ingested = 0
        if current_config.get("process_new_pdfs") and self.inbox_dir.exists():
            for pdf in sorted(self.inbox_dir.glob("*.pdf")):
                logger.info(f"Found new PDF in inbox: {pdf.name}")
                process_file(str(pdf), str(self.library_dir))
                n_ingested += 1
        changed |= n_ingested > 0

        # 2. Metadata Extraction (Title, Authors, Keywords)
        pending = self._papers_missing_metadata()
        if pending and any([current_config.get("add_authors"),
                current_config.get("add_title"), 
                current_config.get("find_keyword")]):
            # extractor.main scans library/ and skips papers that are already done
            run_extraction(library_dir=str(self.library_dir), model="phi3", overwrite=False, delete_pdf=False, workers=4, skip_llm=False)
            # Only count real progress (avoids rebuilding the graph every cycle
            # when a PDF cannot be parsed)
            changed |= len(self._papers_missing_metadata()) < len(pending)

        # (DOIs are resolved during metadata extraction; the old "add_doi"
        # flag is still accepted for API compatibility but has no separate step.)

        # 4. Word-frequency index + TF-IDF keywords (needed by Word Frequency
        #    search and Quick Graph). Rebuilt only when the library changed.
        keywords_updated = {}
        if changed or not (self.library_dir / "global_bow_index.json").exists():
            try:
                from search_module.bow_builder import build_bow_index
                stats = build_bow_index(self.library_dir, self.library_dir / "global_bow_index.json")
                keywords_updated = stats.get("keywords_updated", {})
            except Exception as e:
                logger.error(f"BOW index build failed: {e}")

        # 5. Compute Semantic Embeddings (DB Indexing)
        n_indexed = 0
        if current_config.get("compute_semantic_embedding"):
            n_indexed = self._handle_indexing()
            self._update_keywords_in_db(keywords_updated)
        changed |= n_indexed > 0

        self.last_cycle = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "ingested": n_ingested,
                           "indexed": n_indexed, "keywords_updated": len(keywords_updated)}
        if changed and self.on_library_changed:
            try:
                self.on_library_changed()
            except Exception as e:
                logger.error(f"on_library_changed callback failed: {e}")

    def _papers_missing_metadata(self):
        if not self.library_dir.exists():
            return []
        return [d for d in self.library_dir.iterdir()
                if d.is_dir() and not ((d / "metadata.json").exists() and (d / "full_text.txt").exists())]

    def _update_keywords_in_db(self, keywords_updated):
        """Push regenerated keywords into ChromaDB metadata of already-indexed papers."""
        if not keywords_updated:
            return
        try:
            ids = list(keywords_updated)
            existing = self.db_manager.collection.get(ids=ids, include=["metadatas"])
            metas = []
            for doc_id, meta in zip(existing["ids"], existing["metadatas"]):
                meta = dict(meta or {})
                meta["keywords"] = ", ".join(keywords_updated[doc_id])
                metas.append(meta)
            if metas:
                self.db_manager.collection.update(ids=existing["ids"], metadatas=metas)
        except Exception as e:
            logger.error(f"Failed to update keywords in DB: {e}")

    def _handle_indexing(self):
        # Scan library and index anything with metadata.json but missing from DB

        try:
            existing_data = self.db_manager.collection.get(include=[])
            existing_ids = set(existing_data.get("ids", []))
        except Exception as e:
            logger.error(f"Error fetching existing IDs from DB: {e}")
            existing_ids = set()

        n_indexed = 0
        for hash_dir in self.library_dir.iterdir():
            if not hash_dir.is_dir(): continue
            
            doc_id = hash_dir.name
            
            # CHECK: Is this document already in the database?
            # If a lab server with a GPU already indexed it, we skip it here.
            if doc_id in existing_ids:
                logger.debug(f"Document {doc_id} already indexed. Skipping.")
                continue

            metadata_path = hash_dir / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    try:
                        metadata = json.load(f)
                    except: continue
                
                # Index document (db_manager handles upsert)
                if "pdf_filename" not in metadata:
                    pdfs = list(hash_dir.glob("*.pdf"))
                    if pdfs:
                        metadata["pdf_filename"] = pdfs[0].name

                self.db_manager.index_document(doc_id, metadata)
                n_indexed += 1
        return n_indexed

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    proc = ManuscriptProcessor()
    proc.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        proc.stop()
