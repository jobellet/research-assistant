import os
import json
import logging
import getpass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from extract_module.pdf_utils import extract_text_from_pdf, extract_first_page_as_image
from extract_module.llm_utils import extract_metadata_with_llm, fast_metadata_extract

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_external_pdf_path():
    """Check for external PDF base path in environment variables or default to 'inbox'."""
    project_root = Path(__file__).resolve().parent.parent
    return os.environ.get("EXTERNAL_LIBRARY_PATH", str(project_root / "inbox"))

def process_paper(hash_dir: Path, model: str, overwrite: bool, delete_pdf: bool, skip_llm: bool = False):
    """Processes a single paper: extracts text and verified metadata from databases."""
    txt_path = hash_dir / "full_text.txt"
    metadata_path = hash_dir / "metadata.json"
    
    # Try to find the PDF
    pdf_path = None
    for file in hash_dir.iterdir():
        if file.suffix.lower() == ".pdf":
            pdf_path = file
            break
            
    if not pdf_path:
        # Fallback to external library
        external_pdf_base = Path(get_external_pdf_path())
        source_info_path = hash_dir / "source_info.txt"
        if source_info_path.exists():
            with open(source_info_path, "r") as f:
                first_line = f.readline().strip()
                if first_line.startswith("filename:"):
                    filename = first_line.replace("filename:", "").strip()
                    potential_path = external_pdf_base / filename
                    if potential_path.exists():
                        pdf_path = potential_path

    # FALLBACK: If PDF is missing but text exists, we can still do metadata lookup
    if not pdf_path or not pdf_path.exists():
        if txt_path.exists() and (not metadata_path.exists() or overwrite):
            logger.info(f"PDF missing for {hash_dir.name}, but text exists. Proceeding with metadata extraction.")
            full_text = txt_path.read_text(encoding="utf-8")
            
            # Database Lookup (Crossref)
            metadata = fast_metadata_extract(full_text)
            
            if metadata:
                try:
                    with open(metadata_path, "w") as f:
                        json.dump(metadata, f, indent=4)
                    return f"Successfully extracted verified metadata for {hash_dir.name} (from text)"
                except Exception as e:
                    return f"Failed to save metadata for {hash_dir.name}: {e}"
            return f"No verified metadata found for {hash_dir.name}"
        return f"No PDF or text found for {hash_dir.name}"

    logger.info(f"Processing: {pdf_path.name} in {hash_dir.name}")

    # Step 1: Extract FULL text
    full_text = extract_text_from_pdf(str(pdf_path), max_pages=None)
    if not full_text:
        return f"Failed to extract text from {pdf_path.name}"
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    # Step 2: Extract metadata from online databases (Crossref)
    if skip_llm:
        logger.info(f"Skipping metadata extraction for {pdf_path.name}")
    elif not metadata_path.exists() or overwrite:
        metadata_context = extract_text_from_pdf(str(pdf_path), max_pages=5)

        # Try Database Lookup (Crossref)
        metadata = fast_metadata_extract(metadata_context)
        
        # Smart Retry: Use LLM to find a clue, then verify it
        if not metadata:
            logger.info(f"Fast path failed for {hash_dir.name}. Calling LLM Detective (Text)...")
            metadata = extract_metadata_with_llm(text=metadata_context, model=model)
            
        # Final Fallback: Visual OCR (Multimodal)
        if not metadata and pdf_path:
            logger.info(f"Text-based search failed for {hash_dir.name}. Attempting Visual OCR...")
            image_b64 = extract_first_page_as_image(str(pdf_path))
            if image_b64:
                metadata = extract_metadata_with_llm(image_b64=image_b64, model=model)

        if metadata:
            metadata["pdf_filename"] = pdf_path.name
            try:
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=4)
                logger.info(f"Successfully extracted verified metadata for {hash_dir.name}")
            except Exception as e:
                return f"Failed to save metadata for {hash_dir.name}: {e}"
        else:
            logger.warning(f"No verified metadata found in online databases for {hash_dir.name}")

    # Step 3: Optionally delete PDF (only if it's the local copied one)
    if delete_pdf and pdf_path.parent == hash_dir:
        try:
            os.remove(pdf_path)
            logger.info(f"Deleted local PDF: {pdf_path}")
        except Exception as e:
            logger.error(f"Failed to delete PDF {pdf_path}: {e}")

    return f"Successfully processed {hash_dir.name}"

def main(library_dir: str, model: str, overwrite: bool, delete_pdf: bool, workers: int, skip_llm: bool = False, max_papers: int = None):
    library_path = Path(library_dir)
    if not library_path.exists():
        logger.error(f"Library directory not found: {library_dir}")
        return

    external_pdf_base = get_external_pdf_path()
    logger.info(f"Using external PDF base path: {external_pdf_base}")

    hash_dirs = [d for d in library_path.iterdir() if d.is_dir() and len(d.name) == 64]
    
    if max_papers:
        if not overwrite:
            hash_dirs = [d for d in hash_dirs if not (d / "metadata.json").exists()]
        hash_dirs = hash_dirs[:max_papers]
        
    logger.info(f"Found {len(hash_dirs)} hash directories to process in library.")

    success_count = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_paper, d, model, overwrite, delete_pdf, skip_llm): d for d in hash_dirs}
        
        for future in as_completed(futures):
            hash_dir = futures[future]
            try:
                result = future.result()
                if "Successfully" in result:
                    success_count += 1
                logger.info(result)
            except Exception as e:
                logger.error(f"Exception processing {hash_dir.name}: {e}")

    logger.info(f"Extraction completed. {success_count} papers processed successfully.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract metadata and text from PDFs in the library.")
    parser.add_argument("--library", default="library", help="Path to the library directory.")
    parser.add_argument("--model", default="phi3", help="Ollama model to use (unused in DB mode).")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing metadata.")
    parser.add_argument("--delete-pdf", action="store_true", help="Delete the local PDF after extraction.")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip the metadata extraction step.")
    parser.add_argument("--max-papers", type=int, default=None, help="Maximum number of papers to process in this run.")
    
    args = parser.parse_args()
    main(library_dir=args.library, model=args.model, overwrite=args.overwrite, delete_pdf=args.delete_pdf, workers=args.workers, skip_llm=args.skip_llm, max_papers=args.max_papers)
