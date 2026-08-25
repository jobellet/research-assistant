import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import torch.nn.functional as F
import torch
import logging
from typing import List, Dict, Any, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import os

class VectorDB:
    def __init__(self, db_path: str = "chroma_db", model_name: str = "google/embeddinggemma-300m", truncate_dim: int = 256):
        """
        Initialize the Vector Database.
        
        Args:
            db_path: Path where ChromaDB will persist its data.
            model_name: Name of the SentenceTransformers model to use for embeddings.
            truncate_dim: Dimension to truncate the embedding to (Matryoshka feature). 
                          Set to None or 0 to use full dimensions (768 for embeddinggemma-300m).
        """
        if "google/embeddinggemma-300m" in model_name and not os.environ.get("HF_TOKEN"):
            logger.warning("HF_TOKEN environment variable not set. Access to google/embeddinggemma-300m requires accepting the usage license on Hugging Face.")

        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.truncate_dim = truncate_dim
        
        # Initialize the collection
        try:
            self.collection = self.client.get_collection(name="research_library")
            # Check dimension
            sample = self.collection.get(include=["embeddings"], limit=1)
            if sample["embeddings"] and len(sample["embeddings"][0]) != truncate_dim:
                logger.warning(f"Dimension mismatch in 'research_library'. Recreating collection...")
                self.client.delete_collection(name="research_library")
                self.collection = self.client.create_collection(
                    name="research_library",
                    metadata={"hnsw:space": "cosine"}
                )
            else:
                logger.info(f"Loaded existing collection 'research_library'")
        except:
            self.collection = self.client.create_collection(
                name="research_library",
                metadata={"hnsw:space": "cosine"} # Using cosine similarity
            )
            logger.info(f"Created new collection 'research_library'")
        
        logger.info(f"Initialized VectorDB at {db_path} with model {model_name} (truncate_dim={truncate_dim})")

    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding with Matryoshka truncation and normalization."""
        embedding = self.model.encode(text)
        
        if self.truncate_dim and self.truncate_dim > 0:
            # Truncate to the first N dimensions
            embedding = embedding[:self.truncate_dim]
            # Re-normalize for cosine similarity performance
            embedding_tensor = torch.tensor(embedding)
            embedding = F.normalize(embedding_tensor, p=2, dim=0).tolist()
        else:
            embedding = embedding.tolist()
            
        return embedding

    def upsert_document(self, doc_id: str, text: str, metadata: Dict[str, Any]):
        """
        Generate embedding for the text and upsert it into ChromaDB.
        
        Args:
            doc_id: Primary ID (SHA-256 hash or folder name).
            text: Text content to embed (Title + Summary).
            metadata: Dictionary containing Title, Authors, Keywords, Summary, etc.
        """
        try:
            embedding = self._get_embedding(text)
            
            # Metadata must be simple types for ChromaDB (strings, ints, floats)
            # Ensure keywords (list) is converted to a string or handled
            if "keywords" in metadata and isinstance(metadata["keywords"], list):
                metadata["keywords"] = ", ".join(metadata["keywords"])
            if "Keywords" in metadata and isinstance(metadata["Keywords"], list):
                metadata["Keywords"] = ", ".join(metadata["Keywords"])
            
            self.collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[metadata],
                documents=[text]
            )
            logger.info(f"Successfully upserted document: {doc_id}")
        except Exception as e:
            logger.error(f"Error upserting document {doc_id}: {e}")
            raise

    def query(self, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """
        Query the database for similar documents.
        
        Args:
            query_text: Natural language query.
            n_results: Number of results to return.
        """
        query_embedding = self._get_embedding(query_text)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        return results

if __name__ == "__main__":
    # Quick test
    vdb = VectorDB()
    test_id = "test_hash"
    test_text = "Attention Is All You Need. We propose a new simple network architecture, the Transformer."
    test_metadata = {
        "Title": "Attention Is All You Need",
        "Summary": "Transformers are great.",
        "Keywords": ["deep learning", "nlp"]
    }
    vdb.upsert_document(test_id, test_text, test_metadata)
    print("Test upsert successful.")
    
    results = vdb.query("transformer architecture")
    print("Query results:", results)
