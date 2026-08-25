import os
import json
import logging
import time
from pathlib import Path
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Semantic Scholar API rate limits are strict without an API key (~100 per 5 mins).
# We add a delay between requests to avoid 429 Too Many Requests errors.
REQUEST_DELAY = 1.0 

def fetch_cited_by_for_doi(doi: str) -> list:
    """
    Fetch papers that cite this DOI using Semantic Scholar API.
    """
    if not doi: return []
    doi = doi.strip().replace("https://doi.org/", "")
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
    params = {"fields": "citations.externalIds,citations.title,citations.year"}
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            citations = []
            for cite in data.get("citations", []):
                external_ids = cite.get("externalIds", {})
                cite_doi = external_ids.get("DOI")
                title = cite.get("title")
                year = cite.get("year")
                
                # Build a clean citation object
                citation_obj = {}
                if title: citation_obj["title"] = title
                if year: citation_obj["year"] = year
                if cite_doi: citation_obj["doi"] = cite_doi
                
                if citation_obj:
                    citations.append(citation_obj)
            return citations
        elif response.status_code == 429:
            logger.warning(f"Rate limited by Semantic Scholar. Pausing for 30s...")
            time.sleep(30)
        else:
            logger.debug(f"Semantic Scholar returned {response.status_code} for DOI {doi}")
    except Exception as e:
        logger.debug(f"Failed to fetch incoming citations for {doi}: {e}")
    return []

def update_library_citations():
    library_dir = Path("library")
    metadata_files = list(library_dir.glob("*/metadata.json"))
    logger.info(f"Starting daily citation check for {len(metadata_files)} papers...")
    
    updated_count = 0
    total_new_citations = 0
    
    for meta_path in metadata_files:
        try:
            with open(meta_path, 'r') as f:
                metadata = json.load(f)
                
            doi = metadata.get("doi")
            if not doi:
                continue
                
            # Current citations
            existing_citations = metadata.get("cited_by", [])
            existing_dois = {c.get("doi") for c in existing_citations if c.get("doi")}
            existing_titles = {c.get("title") for c in existing_citations if c.get("title")}
            
            # Fetch new citations
            fresh_citations = fetch_cited_by_for_doi(doi)
            time.sleep(REQUEST_DELAY) # Rate limit safety
            
            # Find new ones
            new_citations = []
            for cite in fresh_citations:
                cite_doi = cite.get("doi")
                cite_title = cite.get("title")
                if cite_doi and cite_doi not in existing_dois:
                    new_citations.append(cite)
                    existing_dois.add(cite_doi)
                elif cite_title and cite_title not in existing_titles and not cite_doi:
                    new_citations.append(cite)
                    existing_titles.add(cite_title)
            
            if new_citations:
                updated_count += 1
                total_new_citations += len(new_citations)
                metadata["cited_by"] = existing_citations + new_citations
                with open(meta_path, 'w') as f:
                    json.dump(metadata, f, indent=4)
                logger.info(f"Added {len(new_citations)} new citations for {doi}")
                
        except Exception as e:
            logger.error(f"Error processing {meta_path.parent.name}: {e}")

    logger.info(f"Daily check complete. Updated {updated_count} papers with {total_new_citations} new incoming citations.")

def run_daily_loop():
    while True:
        try:
            update_library_citations()
        except Exception as e:
            logger.error(f"Error in daily citation loop: {e}")
        
        logger.info("Sleeping for 24 hours before the next citation check...")
        # Sleep for 24 hours (86400 seconds)
        time.sleep(86400)

if __name__ == "__main__":
    run_daily_loop()
