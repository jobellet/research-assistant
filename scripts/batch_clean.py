import os
import logging
from pathlib import Path
from clean_manuscript import process_manuscript

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("batch_clean")

def main(library_dir="library"):
    lib_path = Path(library_dir)
    if not lib_path.exists():
        logger.error(f"Library directory not found: {library_dir}")
        return

    full_text_files = list(lib_path.glob("**/full_text.txt"))
    logger.info(f"Found {len(full_text_files)} manuscripts to process.")

    count = 0
    for file_path in full_text_files:
        output_path = file_path.parent / "preprocessed_text.txt"
        process_manuscript(str(file_path), str(output_path))
        count += 1

    logger.info(f"Successfully processed {count} manuscripts.")

if __name__ == "__main__":
    import sys
    library = "library"
    if len(sys.argv) > 1:
        library = sys.argv[1]
    
    # We assume we are in the repo root or scripts dir
    if not os.path.exists(library) and os.path.exists("../library"):
        library = "../library"
        
    main(library)
