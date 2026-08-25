import os
import re
import sys
import json
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def is_metadata_block(line):
    """
    Check if a line looks like it belongs to a metadata/footnote block.
    """
    l = line.strip()
    if not l: return False
    
    # Common patterns in footnotes/headers
    patterns = [
        r'^\*', # Starts with asterisk (footnote)
        r'Tel\.:', r'Fax:', r'E-mail:',
        r'SSDI \d+', r'ISSN:', r'ISBN:',
        r'^\d{4,}-\d{4,}.*$', # Likely ISSN or similar
        r'http', r'www\.',
        r'^Received \d+', r'^Accepted \d+',
        r'© \d+', r'Published by',
        r'All rights reserved',
    ]
    for p in patterns:
        if re.search(p, l, re.IGNORECASE):
            return True
    return False

def clean_text(text):
    """
    Apply heuristics to clean extracted scientific paper text.
    """
    # 1. Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Heuristic: Remove repetitive headers/footers and artifacts
    lines = text.split('\n')
    cleaned_lines = []
    
    # Common journal-specific noise patterns (more aggressive)
    noise_regexes = [
        r'^ll$', r'^Article$', r'^ll OPEN ACCESS$',
        r'Current Biology \d+', 
        r'Neuron \d+',
        r'Journal of Neuroscience',
        r'Nature Communications',
        r'https?://doi\.org/.+',
        r'© \d+ The Authors',
        r'Published by Elsevier',
        r'All rights reserved',
        r'^\d+ \w+ \d{4} \w+ \w+', # Matches "26 December 2008 Elsevier Inc"
        r'Perspective',
        r'www\.jneurosci\.org',
        r'PNAS | Proceedings of the National Academy',
    ]
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines in this phase
        if not stripped:
            cleaned_lines.append("")
            continue

        # Skip pure line numbers/page numbers
        if re.match(r'^\d+$', stripped):
            if int(stripped) < 3000: # Page numbers usually < 2000, line numbers < 100
                continue
        
        # Skip matched noise
        is_noise = False
        for pattern in noise_regexes:
            if re.search(pattern, stripped, re.IGNORECASE):
                # If it's a very long line, it might be real text that just happens 
                # to contain a keyword, so we check length
                if len(stripped) < 100: 
                    is_noise = True
                    break
        if is_noise:
            continue
            
        cleaned_lines.append(line)
    
    # Filter out the empty lines we might have left, but keep paragraph breaks
    text = '\n'.join(cleaned_lines)
    
    # 3. Heuristic: Fix hyphenation at line breaks
    # Only if the hyphen is preceded by letters and followed by lowercase letters
    # We allow optional space before/after the hyphen
    text = re.sub(r'([a-zA-Z]{2,})-\s*\n\s*([a-z]+)', r'\1\2', text)
    
    # 4. Heuristic: Join lines that seem to be part of a column flow
    lines = text.split('\n')
    final_text = ""
    i = 0
    while i < len(lines):
        curr = lines[i].strip()
        if not curr:
            # Avoid adding multiple blank lines
            if not final_text.endswith("\n\n"):
                final_text += "\n\n"
            i += 1
            continue
        
        # If this line looks like metadata/footnote, don't join it to next
        if is_metadata_block(curr):
            final_text += curr + "\n"
            i += 1
            continue
            
        should_join = False
        if i < len(lines) - 1:
            nxt = lines[i+1].strip()
            if nxt:
                # If next line is metadata, don't join
                if is_metadata_block(nxt):
                    should_join = False
                # Case 1: Column artifact (very short lines)
                elif len(curr) < 25 and len(nxt) < 25:
                    # But don't join if it looks like a list or header
                    if not (curr[0].isdigit() or curr.startswith('d ') or curr.isupper()):
                        should_join = True
                # Case 2: Normal split line
                elif curr[-1] not in '.!?:;-' and nxt[0].islower():
                    should_join = True
                # Case 3: Ends in comma or other mid-sentence punctuation
                elif curr[-1] in ',(':
                    should_join = True
                # Case 4: References/Citations flow
                elif re.search(r'\d{4}\)?$', curr) and nxt[0].islower():
                    should_join = True
                    
        if should_join:
            final_text += curr + " "
        else:
            final_text += curr + "\n"
        i += 1

    # 5. Normalize whitespace and ligatures
    final_text = final_text.replace('ﬁ', 'fi').replace('ﬂ', 'fl').replace('ﬀ', 'ff')
    text = re.sub(r' +', ' ', final_text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def extract_info(text):
    """
    Extract DOI, Title, and potentially References.
    """
    info = {}
    
    # DOI
    doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', text, re.IGNORECASE)
    if doi_match:
        info['doi'] = doi_match.group(0)
        
    # Title - Heuristic: First few lines that are not journal name or "Article"
    lines = text.split('\n')
    for line in lines[:10]:
        l = line.strip()
        if len(l) > 20 and "doi" not in l.lower() and "http" not in l.lower() and "Article" not in l:
            info['title_candidate'] = l
            break
            
    # References - Try to find where references start
    ref_match = re.search(r'\n(REFERENCES|References|LITERATURE CITED|Bibliography)\n', text)
    if ref_match:
        info['references_start_index'] = ref_match.start()
        
    return info

def process_manuscript(input_path, output_path):
    logger.info(f"Processing {input_path}...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            raw_text = f.read()
            
        cleaned = clean_text(raw_text)
        info = extract_info(raw_text)
        
        # Add metadata to the top of the cleaned file (optional)
        header = ""
        if 'doi' in info:
            header += f"DOI: {info['doi']}\n"
        if 'title_candidate' in info:
            header += f"TITLE: {info['title_candidate']}\n"
        header += "-"*20 + "\n\n"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(header + cleaned)
            
        logger.info(f"Saved cleaned text to {output_path}")
        
    except Exception as e:
        logger.error(f"Error processing {input_path}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_manuscript.py <input_file> [output_file]")
        sys.exit(1)
        
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else inp.replace('full_text.txt', 'preprocessed_text.txt')
    
    process_manuscript(inp, out)
