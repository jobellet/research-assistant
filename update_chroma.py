import os
import json
import logging
from pathlib import Path
from config import LIBRARY_DIR
from db_module.db_manager import DBManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_chroma_metadata():
    db = DBManager()
    library_dir = LIBRARY_DIR
    
    # Get all ids in Chroma
    try:
        all_ids = db.collection.get(include=[])["ids"]
    except Exception as e:
        logger.error(f"Failed to query ChromaDB: {e}")
        return
        
    logger.info(f"Found {len(all_ids)} documents in ChromaDB to update.")
    
    batch_ids = []
    batch_metas = []
    
    updated_count = 0
    
    for idx, hash_id in enumerate(all_ids):
        meta_path = library_dir / hash_id / "metadata.json"
        if not meta_path.exists():
            continue
            
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                
            # Keep the same clean_metadata logic
            authors_str = ", ".join(metadata.get("authors", [])) if isinstance(metadata.get("authors"), list) else metadata.get("authors", "")
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
                "keywords": ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", ""),
                "hash": hash_id,
                "pdf_filename": metadata.get("pdf_filename", "")
            }
            
            batch_ids.append(hash_id)
            batch_metas.append(clean_metadata)
            
            if len(batch_ids) >= 100:
                db.collection.update(ids=batch_ids, metadatas=batch_metas)
                updated_count += len(batch_ids)
                logger.info(f"Updated {updated_count} documents in ChromaDB...")
                batch_ids = []
                batch_metas = []
                
        except Exception as e:
            logger.error(f"Error on {hash_id}: {e}")
            
    if batch_ids:
        db.collection.update(ids=batch_ids, metadatas=batch_metas)
        updated_count += len(batch_ids)
        
    logger.info(f"Finished updating {updated_count} documents in ChromaDB with year and doi.")

if __name__ == '__main__':
    update_chroma_metadata()
