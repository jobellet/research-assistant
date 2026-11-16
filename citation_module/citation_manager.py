"""Add library papers to a project's BibTeX file.

Keys look like ``butlin2023consciousness`` (first author's last name, year,
first significant title word) and are made unique with a/b/c suffixes. A paper
already present (same library hash, DOI or arXiv id) is never added twice: its
existing key is returned instead.
"""

import logging
import re
import threading
import unicodedata
from pathlib import Path

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bwriter import BibTexWriter

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_TITLE_STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "and", "to", "towards",
                    "toward", "from", "with", "is", "are", "can", "do", "does", "how", "what", "why"}
_LATEX_ESCAPES = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


def _escape(text: str) -> str:
    text = " ".join((text or "").split())
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in text)


def _author_list(authors) -> list:
    if isinstance(authors, str):
        sep = ";" if ";" in authors else ","
        authors = [a.strip() for a in authors.split(sep)]
    out = []
    for a in authors or []:
        if isinstance(a, dict):
            a = a.get("name") or f"{a.get('given', '')} {a.get('family', '')}"
        a = " ".join(str(a).split())
        if a:
            out.append(a)
    return out


def _last_name(author: str) -> str:
    if "," in author:                      # "Butlin, Patrick"
        return author.split(",", 1)[0].strip()
    return author.split()[-1] if author.split() else ""


def _arxiv_id(metadata: dict) -> str:
    if metadata.get("arxiv_id"):
        return metadata["arxiv_id"]
    doi = metadata.get("doi") or ""
    m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", doi, re.I)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{4}\.\d{4,5})(v\d+)?\.pdf$", metadata.get("pdf_filename") or "")
    return m.group(1) if m else ""


class CitationManager:
    def __init__(self, bib_path: str = "references.bib"):
        self.bib_path = Path(bib_path)

    # -- I/O -----------------------------------------------------------------
    def _load(self) -> BibDatabase:
        if not self.bib_path.exists() or not self.bib_path.read_text().strip():
            return BibDatabase()
        parser = bibtexparser.bparser.BibTexParser(common_strings=True, ignore_nonstandard_types=False)
        with open(self.bib_path) as fh:
            return bibtexparser.load(fh, parser=parser)

    def _save(self, db: BibDatabase):
        writer = BibTexWriter()
        writer.order_entries_by = None   # keep insertion order
        writer.indent = "  "
        tmp = self.bib_path.with_suffix(".bib.tmp")
        tmp.write_text(writer.write(db))
        tmp.replace(self.bib_path)

    # -- keys ----------------------------------------------------------------
    def _generate_bib_key(self, metadata: dict, existing_keys=()) -> str:
        authors = _author_list(metadata.get("authors"))
        last = re.sub(r"[^a-z]", "", _ascii(_last_name(authors[0])).lower()) if authors else ""
        year = str(metadata.get("year") or "")
        year = year if re.fullmatch(r"\d{4}", year) else ""
        words = [w for w in re.findall(r"[a-z]+", _ascii(metadata.get("title", "")).lower())
                 if w not in _TITLE_STOPWORDS and len(w) > 2]
        base = f"{last or 'anon'}{year}{words[0] if words else 'ref'}"
        key, i = base, 0
        while key in existing_keys:
            key = base + "abcdefghijklmnopqrstuvwxyz"[i % 26] * (1 + i // 26)
            i += 1
        return key

    # -- entries -------------------------------------------------------------
    def build_entry(self, metadata: dict, key: str) -> dict:
        authors = _author_list(metadata.get("authors"))
        arxiv = _arxiv_id(metadata)
        journal = metadata.get("journal") or ""
        entry = {"ID": key, "title": "{" + _escape(metadata.get("title") or "Unknown Title") + "}"}
        if authors:
            entry["author"] = " and ".join(_escape(a) for a in authors)
        if re.fullmatch(r"\d{4}", str(metadata.get("year") or "")):
            entry["year"] = str(metadata["year"])
        doi = metadata.get("doi") or ""
        if doi:
            entry["doi"] = doi
        if arxiv and (not journal or journal.lower() == "arxiv"):
            entry["ENTRYTYPE"] = "misc"
            entry["eprint"] = arxiv
            entry["archiveprefix"] = "arXiv"
            entry["howpublished"] = f"arXiv preprint arXiv:{arxiv}"
        else:
            entry["ENTRYTYPE"] = "article"
            if journal:
                entry["journal"] = _escape(journal)
        kws = metadata.get("keywords")
        if kws:
            entry["keywords"] = ", ".join(kws) if isinstance(kws, list) else str(kws)
        if metadata.get("hash"):
            entry["library_hash"] = metadata["hash"]
        return entry

    def find_existing(self, db: BibDatabase, metadata: dict):
        doi = (metadata.get("doi") or "").lower()
        h = metadata.get("hash")
        arxiv = _arxiv_id(metadata)
        for e in db.entries:
            if h and e.get("library_hash") == h:
                return e["ID"]
            if doi and e.get("doi", "").lower() == doi:
                return e["ID"]
            if arxiv and e.get("eprint") == arxiv:
                return e["ID"]
        return None

    def add_entry(self, metadata: dict) -> str:
        """Add a paper (library metadata dict) and return its BibTeX key."""
        with _LOCK:
            db = self._load()
            existing = self.find_existing(db, metadata)
            if existing:
                logger.info(f"Paper already in {self.bib_path} as {existing}")
                return existing
            key = self._generate_bib_key(metadata, {e["ID"] for e in db.entries})
            db.entries.append(self.build_entry(metadata, key))
            self._save(db)
        logger.info(f"Added BibTeX entry: {key}")
        return key


if __name__ == "__main__":
    import sys
    import tempfile
    logging.basicConfig(level=logging.INFO)
    with tempfile.TemporaryDirectory() as d:
        cm = CitationManager(Path(d) / "test.bib")
        cm.add_entry({"title": "A New Study on AI", "authors": ["Ada Lovelace"], "year": "2024"})
        sys.stdout.write((Path(d) / "test.bib").read_text())
