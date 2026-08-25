import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import LIBRARY_DIR

def get_year_from_crossref(doi):
    if not doi: return None
    try:
        clean_doi = doi.replace('https://doi.org/', '').strip()
        url = f"https://api.crossref.org/works/{clean_doi}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                item = data.get("message", {})
                date_parts = item.get("issued", {}).get("date-parts", [])
                if date_parts and date_parts[0] and date_parts[0][0]:
                    return str(date_parts[0][0])
                for pub_type in ["published-print", "published-online", "published"]:
                    parts = item.get(pub_type, {}).get("date-parts", [])
                    if parts and parts[0] and parts[0][0]:
                        return str(parts[0][0])
    except:
        pass
    return None

def process_file(meta_path):
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        old_year = data.get("year")
        new_year = None
        
        if data.get("doi"):
            new_year = get_year_from_crossref(data["doi"])
            
        if new_year:
            data["year"] = str(new_year)
        else:
            # Enforce strict DOI only
            if "year" in data:
                del data["year"]
                
        if old_year != data.get("year"):
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            return True
            
    except Exception as e:
        print(f"Error on {meta_path}: {e}")
    return False

def main():
    library_dir = LIBRARY_DIR
    meta_files = list(library_dir.glob("*/metadata.json"))
    print(f"Found {len(meta_files)} metadata files to process.")
    
    updated = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_file, p) for p in meta_files]
        for idx, future in enumerate(as_completed(futures)):
            if future.result():
                updated += 1
            if (idx + 1) % 100 == 0:
                print(f"Processed {idx + 1}/{len(meta_files)} files. Updated {updated} files.")
                
    print(f"Done. Modified {updated} metadata files.")

if __name__ == '__main__':
    main()
