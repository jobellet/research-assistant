import json
import logging
import re
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

def extract_doi_from_text(text: str) -> list:
    """
    Find DOI strings using regex and rank them based on position and context.
    """
    doi_pattern = r'\b10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+\b'
    matches = re.findall(doi_pattern, text)
    if not matches: return []
        
    candidates = []
    seen = set()
    for match in matches:
        if match in seen: continue
        seen.add(match)
        score = 0
        pos = text.find(match)
        if pos < 2000: score += 50
        context = text[max(0, pos-40):pos].lower()
        if "doi" in context: score += 40
        candidates.append((match, score, pos))
    
    candidates.sort(key=lambda x: (-x[1], x[2]))
    return [(c[0], c[2]) for c in candidates]

def search_crossref(query: str) -> list:
    """
    Search Crossref API with a fuzzy query.
    """
    if not query or len(query) < 15: return []
    try:
        url = "https://api.crossref.org/works"
        # Clean query: remove special chars
        clean_q = " ".join(re.sub(r'[^\w\s]', ' ', query).split())
        params = {"query": clean_q, "rows": 5}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json().get("message", {}).get("items", [])
    except Exception as e:
        logger.warning(f"Crossref search failed for '{query[:30]}...': {e}")
    return []

def calculate_confidence(pdf_text: str, official_meta: dict) -> float:
    """
    Verify metadata against PDF text with high strictness.
    Returns score 0.0 to 1.0.
    """
    title = official_meta.get("title", [None])[0]
    if not title: return 0.0
    
    pdf_text_lower = pdf_text.lower()
    
    # 1. Title Word Overlap (Long words only)
    title_words = set([w for w in re.sub(r'[^\w\s]', '', title.lower()).split() if len(w) > 3])
    if not title_words: return 0.0
    
    # Check first 10k chars of PDF (where title must be)
    pdf_header = pdf_text_lower[:10000]
    found_title_words = sum(1 for w in title_words if w in pdf_header)
    title_score = found_title_words / len(title_words)
    
    # 2. Author Last Name Overlap
    author_score = 0.0
    authors = official_meta.get("author", [])
    if authors:
        last_names = [a.get('family', '').lower() for a in authors if a.get('family') and len(a.get('family')) > 2]
        if last_names:
            found_authors = sum(1 for ln in last_names if ln in pdf_header)
            author_score = found_authors / len(last_names)
    
    # 3. Year Match (Optional but good)
    year_score = 1.0
    issued = official_meta.get("issued", {}).get("date-parts", [[None]])[0][0]
    if issued and str(issued) not in pdf_header:
        year_score = 0.5 # Small penalty if year isn't found at the start

    # STRICT WEIGHTING
    # Title match must be > 70% AND Author match must be > 50% for high confidence
    if title_score < 0.7 or (authors and author_score < 0.5):
        return 0.0
        
    return (title_score * 0.5) + (author_score * 0.5) * year_score

def map_to_metadata(item: dict) -> dict:
    """Map Crossref schema to local schema."""
    abstract = item.get("abstract", "No abstract available.")
    if abstract: abstract = re.sub(r'<[^>]+>', '', abstract).strip()
    
    # Process references/citations
    references = []
    for ref in item.get("reference", []):
        if ref.get("DOI"):
            references.append(ref.get("DOI"))
        elif ref.get("unstructured"):
            references.append(ref.get("unstructured"))
        elif ref.get("article-title"):
            references.append(ref.get("article-title"))
    
    # Extract year
    year = ""
    try:
        # Crossref usually provides 'issued' with 'date-parts'
        date_parts = item.get("issued", {}).get("date-parts", [])
        if date_parts and date_parts[0] and date_parts[0][0]:
            year = str(date_parts[0][0])
        else:
            # Fallback to published-print or published-online
            for pub_type in ["published-print", "published-online", "published"]:
                parts = item.get(pub_type, {}).get("date-parts", [])
                if parts and parts[0] and parts[0][0]:
                    year = str(parts[0][0])
                    break
    except Exception as e:
        logger.warning(f"Failed to extract year: {e}")

    return {
        "title": item.get("title", ["Unknown"])[0],
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get("author", [])],
        "year": year,
        "doi": item.get("DOI"),
        "keywords": item.get("subject", []),
        "summary": abstract[:500] + "..." if len(abstract) > 500 else abstract,
        "references": references,
        "source": "Crossref (Verified)"
    }

def fast_metadata_extract(text: str) -> dict:
    """
    The CORE logic: Exclusively uses database lookups and strict verification.
    """
    # 1. Try DOI Regex Path
    candidate_dois = extract_doi_from_text(text)
    for doi, pos in candidate_dois[:5]:
        try:
            resp = requests.get(f"https://api.crossref.org/works/{doi}", timeout=10)
            if resp.status_code == 200:
                meta = resp.json().get("message", {})
                if calculate_confidence(text, meta) > 0.85:
                    logger.info(f"Verified paper via DOI: {doi}")
                    return map_to_metadata(meta)
        except: continue

    # 2. Try Title-Heuristic Path
    # Generate search queries from first few lines
    lines = [l.strip() for l in text[:3000].split('\n') if len(l.strip()) > 25][:3]
    for line in lines:
        results = search_crossref(line)
        for item in results:
            if calculate_confidence(text, item) > 0.9:
                logger.info(f"Verified paper via Title Search: {item.get('DOI')}")
                return map_to_metadata(item)
                
    return None

def get_doi_metadata(doi: str) -> dict:
    """
    Fetch official metadata for a DOI from Crossref.
    """
    if not doi or not isinstance(doi, str):
        return None
    doi = doi.strip().replace("https://doi.org/", "")
    try:
        url = f"https://api.crossref.org/works/{doi}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get("message", {})
    except Exception as e:
        logger.warning(f"Error fetching metadata for DOI {doi}: {e}")
    return None

def extract_metadata_with_llm(text: str = "", image_b64: str = None, model: str = "phi3") -> dict:
    """
    LLM Detective: Finds a DOI or Title clue in text or an image.
    ALWAYS verified against Crossref.
    """
    if image_b64:
        prompt = "Look at this paper image. Extract ONLY the DOI or the Title and First Author as JSON: {\"doi_clue\": \"...\", \"title_clue\": \"...\"}"
        payload = {"prompt": prompt, "images": [image_b64]}
    else:
        prompt = f"""
        You are a library assistant. Find the DOI or EXACT Title/Author from this messy text.
        Text: {text[:5000]}
        Return ONLY JSON: {{"doi_clue": "...", "title_clue": "..."}}
        """
        payload = {"prompt": prompt}
    
    try:
        url_file = Path("library") / ".llm_worker_url"
        if not url_file.exists(): return None
        
        worker_url = url_file.read_text().strip()
        resp = requests.post(f"{worker_url}/generate", json=payload, timeout=90)
        if resp.status_code != 200: return None
        
        json_match = re.search(r'(\{.*\})', resp.text, re.DOTALL)
        if json_match:
            clues = json.loads(json_match.group(1))
            
            # 1. Try DOI clue first
            doi = clues.get("doi_clue")
            if doi and "10." in doi:
                meta = get_doi_metadata(doi)
                if meta and calculate_confidence(text, meta) > 0.8:
                    logger.info(f"LLM Detective found valid DOI: {doi}")
                    return map_to_metadata(meta)
            
            # 2. Try Title/Author clue
            title = clues.get("title_clue")
            if title and len(title) > 20:
                results = search_crossref(title)
                for item in results:
                    if calculate_confidence(text, item) > 0.85:
                        logger.info(f"LLM Detective found valid Title: {item.get('DOI')}")
                        return map_to_metadata(item)
        return None
    except Exception as e:
        logger.error(f"LLM Detective error: {e}")
        return None
