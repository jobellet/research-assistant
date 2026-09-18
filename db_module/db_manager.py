import chromadb
from sentence_transformers import SentenceTransformer
import os
import json
import logging
from typing import List, Optional
from config import LIBRARY_DIR, CHROMA_DB_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GemmaMRLSafeEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    Custom embedding function for ChromaDB that handles Matryoshka truncation
    and normalization for the embedding model.
    """
    def __init__(self, model_name: str = "google/embeddinggemma-300m", truncate_dim: int = 256):
        self.truncate_dim = truncate_dim
        self.model_name = model_name
        try:
            self.model = SentenceTransformer(model_name, truncate_dim=truncate_dim)
        except Exception as e:
            logger.warning(f"Could not load '{model_name}' ({e}). Falling back to 'all-MiniLM-L6-v2'.")
            self.model_name = "all-MiniLM-L6-v2"
            self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        embeddings = self.model.encode(input, normalize_embeddings=True)
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [e.tolist() for e in embeddings]

def _format_authors(authors_data) -> str:
    if isinstance(authors_data, list):
        formatted = []
        for a in authors_data:
            if isinstance(a, str):
                formatted.append(a)
            elif isinstance(a, dict):
                # E.g. {"given": "John", "family": "Doe"} or {"name": "John Doe"}
                name = a.get("name") or f"{a.get('given', '')} {a.get('family', '')}".strip()
                if name:
                    formatted.append(name)
            else:
                formatted.append(str(a))
        return ", ".join(formatted)
    elif isinstance(authors_data, str):
        return authors_data
    return ""

class DBManager:
    def __init__(self, db_path=None, collection_name="research_library", truncate_dim: int = 256):
        """
        Initialize ChromaDB client and collection.
        """
        self.db_path = db_path or CHROMA_DB_PATH
        self.client = chromadb.PersistentClient(path=self.db_path)
        
        model_name = "google/embeddinggemma-300m"

        # Use custom Gemma MRL embedding function
        self.embedding_fn = GemmaMRLSafeEmbeddingFunction(
            model_name=model_name,
            truncate_dim=truncate_dim
        )
        
        # Check existing dimensions to avoid dimension mismatch errors
        try:
            self.collection = self.client.get_collection(name=collection_name)
            # Sample to check dimension
            sample = self.collection.get(include=["embeddings"], limit=1)
            if sample["embeddings"] and len(sample["embeddings"][0]) != truncate_dim:
                logger.warning(f"Dimension mismatch detected in collection '{collection_name}'. "
                               f"Expected {truncate_dim}, but found {len(sample['embeddings'][0])}. Recreating collection...")
                self.client.delete_collection(name=collection_name)
                self.collection = self.client.create_collection(
                    name=collection_name,
                    embedding_function=self.embedding_fn,
                    metadata={"hnsw:space": "cosine"}
                )
            else:
                self.collection = self.client.get_or_create_collection(
                    name=collection_name,
                    embedding_function=self.embedding_fn,
                    metadata={"hnsw:space": "cosine"}
                )
        except Exception:
            # Collection doesn't exist or other error, create it
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )

        logger.info(f"Initialized collection '{collection_name}'")
        logger.info(f"Initialized ChromaDB at {self.db_path} with collection '{collection_name}' (truncate_dim={truncate_dim})")

    def index_document(self, hash_id, metadata, text_content=None):
        """
        Upsert a document into the vector database.
        
        Args:
            hash_id: Unique SHA-256 hash of the PDF (Primary ID).
            metadata: Dict containing title, authors, keywords, summary.
            text_content: Optional full text or summary to embed. 
                          If None, it defaults to the summary in metadata.
        """
        # We'll embed the summary + keywords for semantic search context
        authors_str = _format_authors(metadata.get("authors", []))
        journal_str = metadata.get("journal", "")
        year_val = metadata.get("year", "")
        try:
            year_val = int(year_val)
        except (ValueError, TypeError):
            year_val = 0

        embedding_text = text_content or f"{metadata.get('title', '')} {authors_str} {journal_str} {metadata.get('summary', '')} {' '.join(metadata.get('keywords', []))}"
        
        # Format metadata for ChromaDB (must be string, int, float, or bool)
        clean_metadata = {
            "title": metadata.get("title", ""),
            "authors": authors_str,
            "journal": journal_str,
            "year": year_val,
            "doi": metadata.get("doi", ""),
            "keywords": ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", ""),
            "hash": hash_id,
            "pdf_filename": metadata.get("pdf_filename", "")
        }
        
        # Check for pre-computed embedding
        embedding = None
        embedding_file = LIBRARY_DIR / hash_id / "embedding.json"
        if embedding_file.exists():
            try:
                embedding = json.loads(embedding_file.read_text())
                logger.info(f"Using pre-computed embedding for {hash_id}")
            except Exception as e:
                logger.error(f"Error reading pre-computed embedding for {hash_id}: {e}")

        upsert_kwargs = {
            "ids": [hash_id],
            "documents": [embedding_text],
            "metadatas": [clean_metadata]
        }
        if embedding:
            upsert_kwargs["embeddings"] = [embedding]
            
        self.collection.upsert(**upsert_kwargs)
        logger.info(f"Indexed document: {hash_id} ({clean_metadata['title']})")

    def batch_index_documents(self, documents: list):
        """
        Upsert a batch of documents.
        documents: list of tuples (hash_id, metadata, text_content)
        """
        ids = []
        texts = []
        metas = []
        embeddings = []
        
        for hash_id, metadata, text_content in documents:
            embedding_text = text_content or f"{metadata.get('title', '')} {metadata.get('summary', '')} {' '.join(metadata.get('keywords', []))}"
            year_val = metadata.get("year", "")
            try:
                year_val = int(year_val)
            except (ValueError, TypeError):
                year_val = 0
                
            clean_metadata = {
                "title": metadata.get("title", ""),
                "authors": _format_authors(metadata.get("authors", [])),
                "keywords": ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", ""),
                "year": year_val,
                "doi": metadata.get("doi", ""),
                "hash": hash_id,
                "pdf_filename": metadata.get("pdf_filename", "")
            }
            ids.append(hash_id)
            texts.append(embedding_text)
            metas.append(clean_metadata)
            
            # Check for pre-computed embedding
            embedding = None
            embedding_file = LIBRARY_DIR / hash_id / "embedding.json"
            if embedding_file.exists():
                try:
                    embedding = json.loads(embedding_file.read_text())
                    logger.info(f"Found pre-computed embedding for {hash_id}")
                except Exception as e:
                    logger.error(f"Error reading pre-computed embedding for {hash_id}: {e}")
            embeddings.append(embedding)
            
        if ids:
            # If ANY embeddings were found, we have to provide the list. 
            # ChromaDB requires the embeddings list to be either None or the same length as ids.
            # If some are None, ChromaDB will compute them for those specific entries.
            # Wait, actually ChromaDB's behavior on mixed embeddings in a single call might be tricky.
            # If we provide a list with some Nones, it might error or ignore.
            # To be safe, if we have pre-computed ones, we'll send them.
            
            if any(embeddings):
                # We have at least one pre-computed embedding.
                # However, for those that are None, we MUST compute them now to provide a complete list,
                # otherwise ChromaDB might fail if the list length matches but contains None.
                # Actually, the most robust way is to split the batch or compute missing ones.
                
                final_embeddings = []
                for i, emb in enumerate(embeddings):
                    if emb is None:
                        # Compute it now
                        logger.info(f"Computing missing embedding for {ids[i]}...")
                        final_embeddings.append(self.embedding_fn([texts[i]])[0])
                    else:
                        final_embeddings.append(emb)
                
                self.collection.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=final_embeddings)
            else:
                # No pre-computed embeddings, let ChromaDB handle it
                self.collection.upsert(ids=ids, documents=texts, metadatas=metas)
                
            logger.info(f"Batch indexed {len(ids)} documents.")
            
    def query(self, query_text, n_results=5):
        """
        Query the collection for top matches.
        """
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["metadatas", "distances", "documents"]
        )
        return results

if __name__ == "__main__":
    # Smoke test
    db = DBManager()
    sample_metadata = {
        "title": "Example Paper",
        "authors": ["Author A", "Author B"],
        "keywords": ["AI", "Search"],
        "summary": "A paper about AI-powered search."
    }
    db.index_document("test_hash_123", sample_metadata)
    res = db.query("AI search")
    print(res)
