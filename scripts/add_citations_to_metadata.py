import os
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_references_for_doi(doi: str) -> list:
    if not doi: return []
    doi = doi.strip().replace("https://doi.org/", "")
    try:
        url = f"https://api.crossref.org/works/{doi}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            item = response.json().get("message", {})
            references = []
            for ref in item.get("reference", []):
                if ref.get("DOI"):
                    references.append(ref.get("DOI"))
                elif ref.get("unstructured"):
                    references.append(ref.get("unstructured"))
                elif ref.get("article-title"):
                    references.append(ref.get("article-title"))
            return references
    except Exception as e:
        logger.debug(f"Failed to fetch refs for {doi}: {e}")
    return []

def update_paper(metadata_path: Path) -> bool:
    try:
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
            
        if "references" in metadata:
            return False # Already processed
            
        doi = metadata.get("doi")
        if not doi:
            metadata["references"] = []
        else:
            refs = fetch_references_for_doi(doi)
            metadata["references"] = refs
            
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error processing {metadata_path.parent.name}: {e}")
        return False

def main():
    library_dir = Path("library")
    metadata_files = list(library_dir.glob("*/metadata.json"))
    logger.info(f"Found {len(metadata_files)} metadata files to check.")
    
    updated_count = 0
    # 10 workers for Crossref API to avoid rate limits
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(update_paper, p): p for p in metadata_files}
        count = 0
        for future in as_completed(futures):
            if future.result():
                updated_count += 1
            count += 1
            if count % 100 == 0:
                logger.info(f"Checked {count}/{len(metadata_files)} files. Updated {updated_count}.")

    logger.info(f"Finished updating citations. {updated_count} metadata files updated.")

if __name__ == "__main__":
    main()
