import os
import json
import logging
from pathlib import Path
from typing import Optional
from db_module.vector_db import VectorDB

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LibraryIndexer:
    def __init__(self, library_dir: str = "library", db_path: str = "chroma_db"):
        """
        Initialize the Library Indexer.
        
        Args:
            library_dir: Path to the research library containing hashed folders.
            db_path: Path to the ChromaDB storage.
        """
        self.library_dir = Path(library_dir)
        self.db = VectorDB(db_path=db_path)
        logger.info(f"Initialized LibraryIndexer for {library_dir}")

    def index_all(self):
        """
        Scan the library directory and index all documents with a metadata.json file.
        """
        if not self.library_dir.exists():
            logger.warning(f"Library directory {self.library_dir} does not exist.")
            return

        count = 0
        for doc_dir in self.library_dir.iterdir():
            if doc_dir.is_dir():
                metadata_path = doc_dir / "metadata.json"
                if metadata_path.exists():
                    self._index_single_directory(doc_dir, metadata_path)
                    count += 1
                else:
                    logger.debug(f"No metadata.json found in {doc_dir}")
        
        logger.info(f"Finished indexing. Processed {count} directories.")

    def _index_single_directory(self, doc_dir: Path, metadata_path: Path):
        """
        Process a single document directory.
        """
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            doc_id = doc_dir.name # Use the hash folder name as the ID
            
            # Construct the text to be embedded
            title = metadata.get("title", metadata.get("Title", "Unknown Title"))
            summary = metadata.get("summary", metadata.get("Summary", ""))
            keywords = metadata.get("keywords", metadata.get("Keywords", []))
            
            # Convert keywords list to string if necessary
            keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
            
            # Embedding text: Title + Summary + Keywords
            embedding_text = f"Title: {title}\nSummary: {summary}\nKeywords: {keywords_str}"
            
            # Add relative PDF path to metadata for front-end retrieval
            pdf_path = self._find_pdf_in_dir(doc_dir)
            if pdf_path:
                metadata["pdf_path"] = str(pdf_path)
            
            # Upsert into VectorDB
            self.db.upsert_document(doc_id, embedding_text, metadata)
            
        except Exception as e:
            logger.error(f"Failed to index directory {doc_dir}: {e}")

    def _find_pdf_in_dir(self, doc_dir: Path) -> Optional[Path]:
        """Find the first PDF file in the given directory."""
        for file in doc_dir.iterdir():
            if file.suffix.lower() == ".pdf":
                # Return relative path from project root
                return file
        return None

if __name__ == "__main__":
    indexer = LibraryIndexer()
    indexer.index_all()
