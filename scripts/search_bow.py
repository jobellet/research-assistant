import os
import json
import csv
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Quickly search the Bag of Words index")
    parser.add_argument("query", nargs="+", help="Keywords to search for (e.g. 'fMRI', 'siegel', '2019')")
    parser.add_argument("--top_k", type=int, default=10, help="Number of results to return")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    index_path = base_dir / "library" / "global_bow_index.json"
    inventory_path = base_dir / "papers_inventory.csv"

    if not index_path.exists():
        print(f"Error: Index not found at {index_path}. Has the generate_bow.py script finished running?")
        return

    # Load inventory mapping (hash -> title/authors)
    inventory = {}
    if inventory_path.exists():
        with open(inventory_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                inventory[row["hash"]] = row

    with open(index_path, "r", encoding="utf-8") as f:
        global_index = json.load(f)

    search_terms = [q.lower() for q in args.query]
    paper_scores = {}

    print(f"Searching index for terms: {', '.join(search_terms)}")
    
    for term in search_terms:
        if term in global_index:
            for entry in global_index[term]:
                hash_id = entry[0]
                freq = entry[1]
                
                if hash_id not in paper_scores:
                    paper_scores[hash_id] = 0
                paper_scores[hash_id] += freq

    if not paper_scores:
        print("No papers found containing those terms.")
        return

    # Sort papers by their combined score
    sorted_papers = sorted(paper_scores.items(), key=lambda x: x[1], reverse=True)

    print(f"\nFound {len(sorted_papers)} matching papers. Top {args.top_k} results:\n")
    
    for i, (hash_id, score) in enumerate(sorted_papers[:args.top_k], 1):
        meta = inventory.get(hash_id, {})
        title = meta.get("title", "Unknown Title")
        authors = meta.get("authors", "Unknown Authors")
        year = meta.get("year", "Unknown Year")
        
        # Format the score as a percentage
        pct = score * 100
        
        print(f"{i}. [Score: {pct:.3f}%] {title}")
        print(f"   Authors: {authors}")
        print(f"   Year: {year}")
        print(f"   Hash: {hash_id}\n")

if __name__ == "__main__":
    main()
