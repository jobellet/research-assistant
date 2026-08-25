import chromadb
from sentence_transformers import SentenceTransformer
import os
import json
import logging
from typing import List, Optional
from config import LIBRARY_DIR

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GemmaMRLSafeEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    Custom embedding function for ChromaDB that handles Matryoshka truncation
    and normalization for the embedding model.
    """
    def __init__(self, model_name: str = "google/embeddinggemma-300m", truncate_dim: int = 256):
        if "google/embeddinggemma-300m" in model_name and not os.environ.get("HF_TOKEN"):
            logger.warning("HF_TOKEN environment variable not set. Access to google/embeddinggemma-300m requires accepting the usage license on Hugging Face.")
        self.model = SentenceTransformer(model_name, truncate_dim=truncate_dim)
        self.model_name = model_name
        self.truncate_dim = truncate_dim

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        # sentence-transformers handles Matryoshka truncation, L2 normalization,
        # and prompt formatting (query vs document) automatically via truncate_dim
        # and the model's config_sentence_transformers.json prompts.
        embeddings = self.model.encode(input, normalize_embeddings=True)
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [list(e) for e in embeddings]

class DBManager:
    def __init__(self, db_path="./chroma_db", collection_name="research_library", truncate_dim: int = 256):
        """
        Initialize ChromaDB client and collection.
        """
        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=db_path)
        
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
        except Exception:
            # Collection does not exist or empty
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Initialized collection '{collection_name}'")
            
        logger.info(f"Initialized ChromaDB at {db_path} with collection '{collection_name}' (truncate_dim={truncate_dim})")

    def index_document(self, hash_id: str, metadata: dict, text_content: Optional[str] = None):
        """
        Upsert a single document into the collection using pre-computed embeddings if available,
        or falling back to the standard text-based embedding pipeline.
        """
        # Format the document text for indexing
        # Gemma expects query: or document: prefixes for asymmetric search, handled by SentenceTransformers
        doc_text = f"Title: {metadata.get('title', '')}\n" \
                   f"Summary: {metadata.get('summary', '')}\n" \
                   f"Keywords: {', '.join(metadata.get('keywords', [])) if isinstance(metadata.get('keywords'), list) else metadata.get('keywords', '')}"
        
        if text_content:
            # Append initial text snippet for richer retrieval
            doc_text += f"\nContent: {text_content[:2000]}"

        # Flatten metadata values to strings/ints/floats for Chroma compatibility
        authors_str = ", ".join(metadata.get("authors", [])) if isinstance(metadata.get("authors"), list) else metadata.get("authors", "")
        keywords_str = ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", "")
        journal_str = metadata.get("journal", "")
        year_val = metadata.get("year", "")
        try:
            year_val = int(year_val)
        except (ValueError, TypeError):
            year_val = 0
            
        clean_metadata = {
            "title": metadata.get("title", ""),
            "authors": authors_str,
            "journal": journal_str,
            "year": year_val,
            "doi": metadata.get("doi", ""),
            "keywords": keywords_str,
            "hash": hash_id,
            "pdf_filename": metadata.get("pdf_filename", "")
        }

        # Check if pre-computed embedding exists
        embedding_file = LIBRARY_DIR / hash_id / "embedding.json"
        precomputed_embedding = None
        
        if embedding_file.exists():
            try:
                with open(embedding_file, "r", encoding="utf-8") as f:
                    emb_data = json.load(f)
                    if isinstance(emb_data, list) and len(emb_data) == self.embedding_fn.truncate_dim:
                        precomputed_embedding = emb_data
            except Exception as e:
                logger.warning(f"Could not read pre-computed embedding from {embedding_file}: {e}")

        if precomputed_embedding:
            self.collection.upsert(
                documents=[doc_text],
                metadatas=[clean_metadata],
                embeddings=[precomputed_embedding],
                ids=[hash_id]
            )
            logger.info(f"Indexed document {hash_id} using pre-computed embedding.")
        else:
            self.collection.upsert(
                documents=[doc_text],
                metadatas=[clean_metadata],
                ids=[hash_id]
            )
            logger.info(f"Indexed document {hash_id} using on-the-fly embedding.")

    def batch_index_documents(self, documents: List[tuple]):
        """
        Batch index a list of tuples: (hash_id, metadata, text_content)
        Optimized to use pre-computed embeddings when available or batch-compute embeddings.
        """
        if not documents:
            return

        doc_texts = []
        metadatas = []
        ids = []
        embeddings = []
        need_embedding_indices = []
        texts_to_embed = []

        for idx, (hash_id, metadata, text_content) in enumerate(documents):
            doc_text = f"Title: {metadata.get('title', '')}\n" \
                       f"Summary: {metadata.get('summary', '')}\n" \
                       f"Keywords: {', '.join(metadata.get('keywords', [])) if isinstance(metadata.get('keywords'), list) else metadata.get('keywords', '')}"
            if text_content:
                doc_text += f"\nContent: {text_content[:2000]}"

            authors_str = ", ".join(metadata.get("authors", [])) if isinstance(metadata.get("authors"), list) else metadata.get("authors", "")
            keywords_str = ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", "")
            journal_str = metadata.get("journal", "")
            year_val = metadata.get("year", "")
            try:
                year_val = int(year_val)
            except (ValueError, TypeError):
                year_val = 0
                
            clean_metadata = {
                "title": metadata.get("title", ""),
                "authors": authors_str,
                "journal": journal_str,
                "year": year_val,
                "doi": metadata.get("doi", ""),
                "keywords": keywords_str,
                "hash": hash_id,
                "pdf_filename": metadata.get("pdf_filename", "")
            }

            doc_texts.append(doc_text)
            metadatas.append(clean_metadata)
            ids.append(hash_id)

            # Check pre-computed embedding
            embedding_file = LIBRARY_DIR / hash_id / "embedding.json"
            loaded = False
            if embedding_file.exists():
                try:
                    with open(embedding_file, "r", encoding="utf-8") as f:
                        emb_data = json.load(f)
                        if isinstance(emb_data, list) and len(emb_data) == self.embedding_fn.truncate_dim:
                            embeddings.append(emb_data)
                            loaded = True
                except Exception:
                    pass

            if not loaded:
                embeddings.append(None)
                need_embedding_indices.append(idx)
                texts_to_embed.append(doc_text)

        # Batch compute missing embeddings
        if texts_to_embed:
            logger.info(f"Computing embeddings for {len(texts_to_embed)} documents in batch...")
            computed_embeddings = self.embedding_fn(texts_to_embed)
            for local_idx, orig_idx in enumerate(need_embedding_indices):
                embeddings[orig_idx] = computed_embeddings[local_idx]

        self.collection.upsert(
            documents=doc_texts,
            metadatas=metadatas,
            embeddings=embeddings,
            ids=ids
        )
        logger.info(f"Successfully batch-indexed {len(documents)} documents into ChromaDB.")

    def query(self, query_text: str, n_results: int = 5, where: Optional[dict] = None) -> dict:
        """
        Query the library using semantic search.
        """
        query_kwargs = {
            "query_texts": [query_text],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        if where:
            query_kwargs["where"] = where
            
        return self.collection.query(**query_kwargs)
