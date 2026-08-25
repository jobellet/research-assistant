import json
import os
import logging
from pathlib import Path
from db_module.db_manager import DBManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SemanticSearcher:
    def __init__(self, db_path="./chroma_db", library_dir="./library"):
        """
        Initialize the searcher with access to ChromaDB and the library filesystem.
        """
        self.db_manager = DBManager(db_path=db_path)
        self.library_dir = Path(library_dir)

    def find_all_pdfs(self, hash_id, pdf_filename=None):
        """
        Locate all PDF files associated with this hash_id.
        Returns a list of dictionaries with filename and absolute path.
        """
        found_files = []
        
        # 1. Check local repo library
        # Defend against path traversal
        hash_dir = (self.library_dir / hash_id).resolve()
        safe_library_dir = self.library_dir.resolve()

        if not hash_dir.is_relative_to(safe_library_dir):
            logger.warning(f"Path traversal attempt detected with hash_id: {hash_id}")
            return found_files

        if hash_dir.exists():
            for file in hash_dir.glob("*.pdf"):
                found_files.append({
                    "filename": file.name,
                    "path": str(file),
                    "source": "local"
                })

        # 2. Check external library path
        external_path = os.getenv("EXTERNAL_LIBRARY_PATH")
        if external_path:
            ext_dir = Path(external_path)
            # If we have a specific filename from metadata, check its vicinity for supplements
            if pdf_filename:
                # This is a bit complex. Many users store supplements near the main paper.
                # We'll search for files that start with the same name or are in the same subdir.
                logger.info(f"Searching for supplements of {pdf_filename} in {external_path}...")
                
                # First, find the main file to get its directory
                matches = list(ext_dir.rglob(pdf_filename))
                if matches:
                    parent_dir = matches[0].parent
                    # List all PDFs in that same external directory
                    for file in parent_dir.glob("*.pdf"):
                        # Avoid duplicates if already found in local
                        if not any(f["filename"] == file.name for f in found_files):
                            found_files.append({
                                "filename": file.name,
                                "path": str(file),
                                "source": "external"
                            })
            
            # If nothing found via metadata, and we have a flat folder, we might be out of luck 
            # unless the supplementary contains the hash or DOI in filename.
            # For now, we rely on the primary filename's location.

        return found_files

    def search(self, query_text, n_results=5, where=None):
        """
        Perform semantic search and return matches grouped by DOI.
        """
        # Manually generate the correctly dimensioned (256) embedding for the query
        # Add the search prompt for Gemma if it is being used
        if "embeddinggemma" in self.db_manager.embedding_fn.model_name.lower():
            formatted_query = f"task: search result | query: {query_text}"
        else:
            formatted_query = query_text

        query_embedding = self.db_manager.embedding_fn([formatted_query])[0]
        
        query_kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["metadatas", "distances", "documents"]
        }
        if where:
            query_kwargs["where"] = where

        raw_results = self.db_manager.collection.query(**query_kwargs)
        
        # ChromaDB results format is a dictionary with lists
        ids = raw_results.get("ids", [[]])[0]
        metadatas = raw_results.get("metadatas", [[]])[0]
        distances = raw_results.get("distances", [[]])[0]
        documents = raw_results.get("documents", [[]])[0]
        
        # Temporary storage for grouping by DOI
        grouped_results = {} # {doi or hash: result_dict}
        
        for i in range(len(ids)):
            hash_id = ids[i]
            metadata = metadatas[i] or {}
            doi = metadata.get("doi") or metadata.get("DOI")
            
            # Use DOI as group key if available, otherwise fallback to hash_id
            group_key = f"doi:{doi}" if doi else hash_id
            
            pdf_filename = metadata.get("pdf_filename")
            all_files = self.find_all_pdfs(hash_id, pdf_filename=pdf_filename)
            score = 1.0 - distances[i] if distances[i] is not None else 0.0

            if group_key in grouped_results:
                # Add unique files to the existing group
                existing_files = [f["filename"] for f in grouped_results[group_key]["files"]]
                for new_file in all_files:
                    if new_file["filename"] not in existing_files:
                        grouped_results[group_key]["files"].append(new_file)
                
                # Keep the highest score
                if score > grouped_results[group_key]["score"]:
                    grouped_results[group_key]["score"] = round(score, 4)
            else:
                grouped_results[group_key] = {
                    "hash_id": hash_id,
                    "score": round(score, 4),
                    "metadata": metadata,
                    "summary": documents[i],
                    "files": all_files
                }
            
        # Convert back to sorted list by score
        final_results = list(grouped_results.values())
        final_results.sort(key=lambda x: x["score"], reverse=True)
            
        return final_results

    def search_batch(self, query_texts, n_results=5):
        """
        Perform a batched semantic search for multiple queries at once.
        Returns the raw ChromaDB query response (dictionary with lists).
        """
        if not query_texts:
            return {"ids": [], "distances": []}

        return self.db_manager.collection.query(
            query_texts=query_texts,
            n_results=n_results,
            include=["distances"]
        )

def run_query(query_text):
    """
    Helper function to run a query and print JSON result.
    """
    searcher = SemanticSearcher()
    results = searcher.search(query_text)
    print(json.dumps(results, indent=4))
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        run_query(query)
    else:
        print("Usage: python -m search_module.searcher 'your search query'")
