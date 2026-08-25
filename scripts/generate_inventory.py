import os
import json
import csv
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("inventory_gen")

def main(library_dir="library", output_file="papers_inventory.csv"):
    lib_path = Path(library_dir)
    if not lib_path.exists():
        logger.error(f"Library directory not found: {library_dir}")
        return

    papers = []
    headers = ["hash", "title", "authors", "year", "doi", "pdf_filename"]

    # Find all subdirectories in library/
    for doc_dir in lib_path.iterdir():
        if not doc_dir.is_dir():
            continue
            
        hash_id = doc_dir.name
        metadata_path = doc_dir / "metadata.json"
        source_info_path = doc_dir / "source_info.txt"
        
        paper_info = {h: "" for h in headers}
        paper_info["hash"] = hash_id
        
        # Load metadata if exists
        if metadata_path.exists():
            try:
                with open(metadata_path, "r") as f:
                    meta = json.load(f)
                    paper_info["title"] = meta.get("title", meta.get("Title", ""))
                    authors = meta.get("authors", meta.get("Authors", ""))
                    paper_info["authors"] = ", ".join(authors) if isinstance(authors, list) else authors
                    paper_info["year"] = meta.get("year", meta.get("Year", ""))
                    paper_info["doi"] = meta.get("doi", meta.get("DOI", ""))
                    paper_info["pdf_filename"] = meta.get("pdf_filename", "")
            except Exception as e:
                logger.warning(f"Error reading metadata for {hash_id}: {e}")
        
        # Fallback to preprocessed_text.txt headers
        prep_path = doc_dir / "preprocessed_text.txt"
        if not paper_info["doi"] and prep_path.exists():
            try:
                content = prep_path.read_text(encoding='utf-8')
                lines = content.split('\n')
                for line in lines[:5]:
                    if line.startswith("DOI: "):
                        paper_info["doi"] = line.replace("DOI: ", "").strip()
                    if line.startswith("TITLE: "):
                        paper_info["title"] = line.replace("TITLE: ", "").strip()
            except:
                pass
        
        # Fallback to source_info for filename
        if not paper_info["pdf_filename"] and source_info_path.exists():
            try:
                content = source_info_path.read_text()
                if "filename: " in content:
                    paper_info["pdf_filename"] = content.split("filename: ")[1].strip()
            except:
                pass
                
        papers.append(paper_info)

    # Write to CSV
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(papers)
        logger.info(f"Successfully generated inventory: {output_file} ({len(papers)} papers)")
    except Exception as e:
        logger.error(f"Failed to write CSV: {e}")

if __name__ == "__main__":
    import sys
    # Add project root to sys.path if needed
    base_dir = Path(__file__).resolve().parent.parent
    os.chdir(base_dir)
    main()
