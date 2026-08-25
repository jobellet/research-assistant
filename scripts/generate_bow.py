import os
import json
import logging
from pathlib import Path
from collections import Counter
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("generate_bow")

def process_text(text):
    # Expanded list of common stopwords to exclude
    STOPWORDS = {
        'the', 'and', 'for', 'with', 'from', 'this', 'that', 'which', 'was', 'were',
        'been', 'have', 'has', 'are', 'not', 'but', 'also', 'their', 'they', 'our',
        'your', 'will', 'can', 'should', 'would', 'could', 'about', 'than', 'then',
        'them', 'these', 'those', 'such', 'into', 'only', 'other', 'some', 'more',
        'most', 'very', 'both', 'each', 'any', 'all', 'anywhere', 'another', 'while',
        'where', 'when', 'who', 'how', 'why', 'what', 'after', 'before', 'during',
        'between', 'under', 'over', 'through', 'above', 'below', 'once', 'here',
        'there', 'mean', 'means', 'using', 'used', 'use', 'using', 'study', 'research',
        'results', 'analysis', 'data', 'methods', 'method', 'paper', 'article',
        'system', 'based', 'approach', 'model', 'provide', 'shown', 'Figure', 'Table'
    }
    
    # Extract words (3 or more chars), lowercase
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    if not words:
        return {}
    
    # Filter stopwords
    filtered_words = [w for w in words if w not in STOPWORDS]
    if not filtered_words:
        return {}
        
    total_words = len(words)
    counts = Counter(filtered_words)
    
    # Only keep words that have at least 0.05% frequency or appear at least twice
    # This prunes noise significantly.
    processed = {}
    for word, count in counts.items():
        freq = count / total_words
        if freq >= 0.0005 or count >= 2:
            processed[word] = round(freq, 6)
            
    return processed

def main(library_dir="library"):
    lib_path = Path(library_dir)
    if not lib_path.exists():
        logger.error(f"Library directory not found: {library_dir}")
        return

    global_index = {}
    papers_processed = 0

    # 1. Process all papers
    for doc_dir in lib_path.iterdir():
        if not doc_dir.is_dir():
            continue
            
        hash_id = doc_dir.name
        text_path = doc_dir / "preprocessed_text.txt"
        if not text_path.exists():
            text_path = doc_dir / "full_text.txt"
            
        if not text_path.exists():
            continue
            
        try:
            text = text_path.read_text(encoding='utf-8', errors='ignore')
            bow = process_text(text)
            
            if not bow:
                continue
                
            # Save local bow.json for the paper
            bow_path = doc_dir / "bow.json"
            with open(bow_path, "w") as f:
                json.dump(bow, f)
                
            # Add to global inverted index
            # Compact format: [hash, freq] instead of {"hash": h, "freq": f}
            for word, freq in bow.items():
                if word not in global_index:
                    global_index[word] = []
                global_index[word].append([hash_id, freq])
                
            papers_processed += 1
            if papers_processed % 100 == 0:
                logger.info(f"Processed {papers_processed} papers...")
        except Exception as e:
            logger.warning(f"Error processing BOW for {hash_id}: {e}")

    # 2. Prune and sort global index
    logger.info("Sorting and pruning global index...")
    pruned_index = {}
    for word, entries in global_index.items():
        # Sort by frequency
        entries.sort(key=lambda x: x[1], reverse=True)
        # Only keep top 100 papers for each word to avoid massive indexing of common technical terms
        pruned_index[word] = entries[:100]

    # 3. Save optimized global inverted index
    index_path = lib_path / "global_bow_index.json"
    try:
        # Using separators for more compact JSON (no spaces)
        with open(index_path, "w") as f:
            json.dump(pruned_index, f, separators=(',', ':'))
        logger.info(f"Successfully generated optimized BOW index for {papers_processed} papers.")
        logger.info(f"Final index size: {index_path.stat().st_size / 1024 / 1024:.2f} MB")
    except Exception as e:
        logger.error(f"Failed to write global index: {e}")

if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    os.chdir(base_dir)
    main()
