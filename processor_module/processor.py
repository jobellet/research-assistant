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
except ImportError:
    # Handle direct execution or testing scenarios
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from ingest_module.ingestor import process_file
    from extract_module.extractor import main as run_extraction
    from db_module.db_manager import DBManager

logger = logging.getLogger(__name__)

class ManuscriptProcessor:
    def __init__(self, library_dir="library", inbox_dir="inbox", interval=5):
        self.library_dir = Path(library_dir)
        self.inbox_dir = Path(inbox_dir)
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
        
        self.db_manager = DBManager()
        self._lock = threading.Lock()

    def update_config(self, new_config):
        with self._lock:
            self.config.update(new_config)
            logger.info(f"Processor config updated: {self.config}")

    def get_status(self):
        return {
            "running": self.running,
            "config": self.config
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

        # 1. Process New PDFs (Ingestion)
        if current_config.get("process_new_pdfs"):
            for pdf in self.inbox_dir.glob("*.pdf"):
                logger.info(f"Found new PDF in inbox: {pdf.name}")
                process_file(str(pdf), str(self.library_dir))

        # 2. Metadata Extraction (Title, Authors, Keywords)
        if any([current_config.get("add_authors"), 
                current_config.get("add_title"), 
                current_config.get("find_keyword")]):
            # The extractor.py main handles scanning library/ and skipping existing
            # We'll run it with default settings
            run_extraction(library_dir=str(self.library_dir), model="phi3", overwrite=False, delete_pdf=False, workers=4, skip_llm=False)

        # 3. DOI Extraction (Placeholder for now)
        if current_config.get("add_doi"):
            self._handle_doi_extraction()

        # 4. Compute Semantic Embeddings (DB Indexing)
        if current_config.get("compute_semantic_embedding"):
            self._handle_indexing()

    def _handle_doi_extraction(self):
        # Scan library for metadata.json and check if DOI is missing
        for hash_dir in self.library_dir.iterdir():
            if not hash_dir.is_dir(): continue
            metadata_path = hash_dir / "metadata.json"
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    try:
                        metadata = json.load(f)
                    except: continue
                
                if "doi" not in metadata or not metadata["doi"]:
                    # Simple regex search in the PDF text (using existing extract_text_from_pdf logic if available)
                    # For now, we just mark it as "Not Found" to simulate the process
                    # metadata["doi"] = "pending..." 
                    pass

    def _handle_indexing(self):
        # Scan library and index anything with metadata.json but missing from DB

        try:
            existing_data = self.db_manager.collection.get(include=[])
            existing_ids = set(existing_data.get("ids", []))
        except Exception as e:
            logger.error(f"Error fetching existing IDs from DB: {e}")
            existing_ids = set()

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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    proc = ManuscriptProcessor()
    proc.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        proc.stop()
