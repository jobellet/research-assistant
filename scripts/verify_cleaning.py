import os
import re
import difflib
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("verify_cleaning")

def normalize_text(text):
    """
    Standardize text for comparison:
    - Normalize whitespace (all to single spaces)
    - Standardize quotes (“/”/‘‘/’’ -> ")
    - Strip trailing/leading space
    """
    # Standardize various quote forms
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    text = text.replace('‘‘', '"').replace("’’", '"').replace("''", '"')
    
    # Fix common ligature/OCR artifacts
    text = text.replace('ﬁ', 'fi').replace('ﬂ', 'fl').replace('ﬀ', 'ff')
    
    # Standardize dashes
    text = text.replace('—', '-').replace('–', '-')
    
    # Remove any stray newlines or multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    # Final cleanup of any potential remaining odd characters
    text = text.strip()
    return text

def verify_folder(ground_truth_dir, library_dir):
    hash_id = ground_truth_dir.name
    gt_file = ground_truth_dir / "ground_truth.txt"
    prep_file = library_dir / hash_id / "preprocessed_text.txt"
    
    if not gt_file.exists():
        logger.error(f"Ground truth missing for {hash_id}")
        return False
    
    if not prep_file.exists():
        logger.error(f"Preprocessed file missing for {hash_id} at {prep_file}")
        return False
        
    with open(gt_file, 'r', encoding='utf-8') as f:
        gt_content = f.read()
    
    with open(prep_file, 'r', encoding='utf-8') as f:
        prep_content = f.read()
        
    # We want to check if the cleaned snippet (gt) is present in the full cleaned text
    norm_gt = normalize_text(gt_content)
    norm_prep = normalize_text(prep_content)
    
    if norm_gt in norm_prep:
        logger.info(f"✅ PASS: {hash_id}")
        return True
    else:
        logger.error(f"❌ FAIL: {hash_id}")
        # Try to find the closest match to show diff
        # (This is just a basic implementation)
        logger.info("Ground Truth (Normalized):")
        logger.info(norm_gt[:200] + "...")
        return False

def main():
    base_dir = Path(__file__).resolve().parent.parent
    gt_base = base_dir / "tests" / "ground_truth"
    lib_base = base_dir / "library"
    
    if not gt_base.exists():
        logger.error(f"Ground truth base dir not found: {gt_base}")
        return

    success_count = 0
    folders = [d for d in gt_base.iterdir() if d.is_dir()]
    
    for folder in folders:
        if verify_folder(folder, lib_base):
            success_count += 1
            
    logger.info("-" * 20)
    logger.info(f"Verification complete: {success_count}/{len(folders)} passed.")

if __name__ == "__main__":
    main()
