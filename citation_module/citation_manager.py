import os
import logging
import bibtexparser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
from pathlib import Path

logger = logging.getLogger(__name__)

class CitationManager:
    def __init__(self, bib_path: str = "references.bib"):
        self.bib_path = Path(bib_path)
        if not self.bib_path.exists():
            # Create an empty bib file if it doesn't exist
            with open(self.bib_path, "w") as f:
                f.write("")
            logger.info(f"Created new BibTeX file at {self.bib_path}")

    def _generate_bib_key(self, metadata: dict) -> str:
        """Generate a BibTeX key: AuthorYearFirstKeyword."""
        authors = metadata.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",")]
        
        last_name = "Unknown"
        if authors:
            last_name = authors[0].split()[-1].lower()
        
        # We don't have year in metadata explicitly sometimes, 
        # so let's use a generic key if it's missing or use a suffix.
        # For this prototype, we'll use first keyword or 'Ref'.
        keywords = metadata.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",")]
        
        suffix = keywords[0].lower() if keywords else "ref"
        key = f"{last_name}{suffix}"
        
        # Remove special chars
        return "".join(e for e in key if e.isalnum())

    def add_entry(self, metadata: dict) -> str:
        """
        Add a paper's metadata to the BibTeX file.
        Returns the generated BibTeX key.
        """
        bib_key = self._generate_bib_key(metadata)
        
        # Load existing entries to avoid duplicates
        try:
            with open(self.bib_path) as bibtex_file:
                db = bibtexparser.load(bibtex_file)
        except Exception:
            db = BibDatabase()

        # Check if key already exists
        if any(e['ID'] == bib_key for e in db.entries):
            logger.info(f"Entry {bib_key} already exists. Skipping.")
            return bib_key

        # Create new entry
        new_entry = {
            'object_type': 'book', # Defaulting to article/book for simplicity
            'ENTRYTYPE': 'article',
            'ID': bib_key,
            'title': metadata.get("title", "Unknown Title"),
            'author': ", ".join(metadata.get("authors", [])) if isinstance(metadata.get("authors"), list) else metadata.get("authors", "Unknown"),
            'abstract': metadata.get("summary", ""),
            'keywords': ", ".join(metadata.get("keywords", [])) if isinstance(metadata.get("keywords"), list) else metadata.get("keywords", ""),
            'note': f"Source: {metadata.get('hash', 'N/A')}"
        }
        
        db.entries.append(new_entry)
        
        # Write back
        writer = BibTexWriter()
        with open(self.bib_path, 'a') as bibfile:
            bibfile.write("\n" + writer.write(db))
            
        logger.info(f"Added BibTeX entry: {bib_key}")
        return bib_key

if __name__ == "__main__":
    # Smoke test
    logging.basicConfig(level=logging.INFO)
    cm = CitationManager("test.bib")
    sample_meta = {
        "title": "A New Study on AI",
        "authors": ["Joachim Bellet"],
        "keywords": ["Neuroscience", "AI"]
    }
    cm.add_entry(sample_meta)
