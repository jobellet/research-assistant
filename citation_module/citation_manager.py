import re
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class CitationManager:
    def __init__(self, bib_path="references.bib"):
        self.bib_path = Path(bib_path)

    def generate_bib_key(self, metadata: dict) -> str:
        """
        Generate a unique, clean BibTeX citation key (e.g. Author2023KeyConcept).
        """
        authors = metadata.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
            
        first_author = "Unknown"
        if authors:
            first_author = authors[0].split()[-1]
            first_author = re.sub(r'[^a-zA-Z]', '', first_author)
            
        year = str(metadata.get("year", "2024"))
        
        # Pick one keyword or first word from title
        key_term = "Paper"
        if metadata.get("keywords") and isinstance(metadata.get("keywords"), list) and len(metadata["keywords"]) > 0:
            key_term = metadata["keywords"][0]
        elif metadata.get("title"):
            words = [w for w in metadata["title"].split() if len(w) > 3]
            if words:
                key_term = words[0]
                
        key_term = re.sub(r'[^a-zA-Z]', '', key_term).capitalize()
        return f"{first_author}{year}{key_term}"

    def parse_bib_file(self) -> BibDatabase:
        if not self.bib_path.exists():
            return BibDatabase()
            
        with open(self.bib_path, 'r', encoding='utf-8') as bibfile:
            parser = BibTexParser(common_strings=True)
            return bibtexparser.load(bibfile, parser=parser)

    def add_entry(self, metadata: dict) -> str:
        """
        Safely append or merge a BibTeX entry without clobbering existing references.
        """
        db = self.parse_bib_file()
        bib_key = self.generate_bib_key(metadata)

        # Check if already present
        for entry in db.entries:
            if entry.get("ID") == bib_key:
                logger.info(f"Entry {bib_key} already exists in {self.bib_path}")
                return bib_key

        authors = metadata.get("authors", [])
        if isinstance(authors, list):
            author_str = " and ".join(authors)
        else:
            author_str = str(authors)

        new_entry = {
            'ENTRYTYPE': 'article',
            'ID': bib_key,
            'title': metadata.get("title", "Untitled Document"),
            'author': author_str if author_str else "Unknown Author",
            'year': str(metadata.get("year", "2024")),
            'journal': metadata.get("journal", ""),
            'doi': metadata.get("doi", "")
        }
        
        # Clean empty keys
        new_entry = {k: v for k, v in new_entry.items() if v}

        db.entries.append(new_entry)
        
        writer = BibTexWriter()
        with open(self.bib_path, 'w', encoding='utf-8') as bibfile:
            bibfile.write(writer.write(db))
            
        logger.info(f"Added BibTeX entry: {bib_key}")
        return bib_key

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cm = CitationManager("test.bib")
    sample_meta = {
        "title": "A New Study on AI Systems",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "year": "2024",
        "keywords": ["ArtificialIntelligence", "Computing"]
    }
    cm.add_entry(sample_meta)
    print("Generated sample citation entry.")
