import json
import logging
from pathlib import Path
from config import LIBRARY_DIR, CHROMA_DB_PATH, WORKER_MODE
from db_module.db_manager import DBManager
import itertools

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_single_paper(hash_id):
    hash_dir = LIBRARY_DIR / hash_id
    if not hash_dir.is_dir():
        return None
    
    metadata_path = hash_dir / "metadata.json"
    
    metadata = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text())
        except Exception as e:
            logger.error(f"Error reading metadata for {hash_id}: {e}")
            pass

    if not metadata or not metadata.get("title") or metadata.get("title") == "Unknown Title":
        return None
    
    return hash_id, metadata, None

def run_batch_indexing(batch_size=100):
    db_manager = DBManager()
    
    hash_ids = [d.name for d in LIBRARY_DIR.iterdir() if d.is_dir() and len(d.name) == 64]
    logger.info(f"Found {len(hash_ids)} folders in library.")
    
    existing_ids = set(db_manager.collection.get(include=[])["ids"])
    to_process = [h for h in hash_ids if h not in existing_ids]
    logger.info(f"{len(to_process)} papers need indexing.")
    
    if not to_process:
        logger.info("Everything is already indexed.")
        return

    success_count = 0
    
    # Process in batches
    def batched(iterable, n):
        it = iter(iterable)
        while batch := list(itertools.islice(it, n)):
            yield batch
            
    for i, hash_batch in enumerate(batched(to_process, batch_size)):
        docs = []
        for h in hash_batch:
            res = process_single_paper(h)
            if res:
                docs.append(res)
        
        if docs:
            # If in worker mode, we want to save the embeddings to disk
            if WORKER_MODE:
                logger.info(f"Worker mode: Computing and saving embeddings for batch {i+1}...")
                # We need to compute the embeddings ourselves to save them
                texts_to_embed = []
                for hash_id, metadata, text_content in docs:
                    # Logic same as in DBManager
                    embedding_text = text_content or f"{metadata.get('title', '')} {metadata.get('summary', '')} {' '.join(metadata.get('keywords', []))}"
                    texts_to_embed.append(embedding_text)
                
                # Use the db_manager's embedding function
                embeddings = db_manager.embedding_fn(texts_to_embed)
                
                for j, (hash_id, metadata, text_content) in enumerate(docs):
                    emb_path = LIBRARY_DIR / hash_id / "embedding.json"
                    try:
                        emb_data = embeddings[j].tolist() if hasattr(embeddings[j], "tolist") else embeddings[j]
                        with open(emb_path, "w") as f:
                            json.dump(emb_data, f)
                        logger.debug(f"Saved embedding for {hash_id}")
                    except Exception as e:
                        logger.error(f"Failed to save embedding for {hash_id}: {e}")

            db_manager.batch_index_documents(docs)
            success_count += len(docs)
        
        logger.info(f"Batch {i+1} processed. Indexed {success_count} papers so far.")

    logger.info(f"Batch indexing complete. Indexed {success_count} verified papers into ChromaDB.")

if __name__ == "__main__":
    run_batch_indexing(batch_size=50)
