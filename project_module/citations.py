"""Which paper of a project does a citation marker point to?

Supports the three ways a draft cites:

* numbered references ('...feature beta,33' or '[33]') resolved through the draft's own
  numbered reference list ('33. Smith, A.B., ... https://doi.org/10.5555/example.0033'),
  matched to the project's papers by DOI, then by title;
* LaTeX keys ('\\cite{smith1985example}') matched to the papers' BibTeX keys;
* author-year ('(Smith et al., 1985)') matched by first-author surname and year.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s;,)\]>]+", re.I)

# Lower-case name particles that may precede a capitalised family name ('van Dijk', 'de Vries').
_PARTICLES = {"van", "von", "de", "der", "den", "da", "del", "della", "di", "du", "dos",
              "le", "la", "ben", "ter", "ten"}
_PARTICLE_RE = "|".join(sorted(_PARTICLES, key=len, reverse=True))
# Lead-ins inside an author-year marker: '(see Smith, 2001)', '(e.g., Smith et al., 2001)'.
_LEAD_IN = re.compile(r"^\s*(?:(?:see(?:\s+also)?|but\s+see|e\.\s?g\.|i\.\s?e\.|cf\.|"
                      r"reviewed\s+in|for\s+(?:a\s+)?reviews?,?\s+see)\s*[,:]?\s*)+", re.I)
_SURNAME = re.compile(r"\b((?:(?:%s)\s+)*[A-ZÀ-Þ][\w'’\-]+(?:\s+[A-ZÀ-Þ][\w'’\-]+)?)" % _PARTICLE_RE)
_YEAR = re.compile(r"(?<![\w/.])(\d{4})([a-z]?)(?![\w/])")
# Words that mark a reference as a commentary/erratum *about* a paper rather than the paper itself.
_DERIVED = re.compile(r"\b(erratum|corrigendum|correction|retraction|retracted|commentary|comment on|"
                      r"reply to)\b", re.I)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _norm_doi(doi: str) -> str:
    """'https://doi.org/10.1/ABC.' -> '10.1/abc'; '' when there is no DOI."""
    doi = (doi or "").strip().lower()
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    m = _DOI.search(doi)
    return m.group(0).rstrip(".,;:)]}>") if m else ""


def _core_surname(name: str) -> str:
    """Normalised family name without leading particles: 'van Dijk' -> 'dijk'."""
    tokens = (name or "").split()
    while len(tokens) > 1 and tokens[0].lower() in _PARTICLES:
        tokens = tokens[1:]
    return _norm(" ".join(tokens))


def parse_numbered_references(text: str, min_entries: int = 3) -> Dict[str, Dict]:
    """``{'33': {'text': ..., 'doi': ...}}`` from a numbered reference list at the end of a text."""
    lines = (text or "").splitlines()
    start = 0
    for i, line in enumerate(lines):
        if re.match(r"^\s*(references|bibliography|literature cited|references and notes)\s*$", line, re.I):
            start = i + 1                      # the last such heading wins
    entries: Dict[str, Dict] = {}
    for line in lines[start:]:
        m = re.match(r"^\s*\[?(\d{1,4})[.\])]\s+(.{20,})$", line.strip())
        if m:
            body = m.group(2)
            doi = _DOI.search(body)
            entries[m.group(1)] = {"text": body.strip(),
                                   "doi": _norm_doi(doi.group(0)) if doi else ""}
    return entries if len(entries) >= min_entries else {}


def expand_label(label: str) -> List[str]:
    """'9,34' -> ['9', '34']; '24–26' -> ['24', '25', '26']; 'a,b' -> ['a', 'b']."""
    out: List[str] = []
    for piece in re.split(r"\s*[,;]\s*", label or ""):
        piece = piece.strip()
        m = re.fullmatch(r"(\d{1,4})\s*[-–—]\s*(\d{1,4})", piece)
        if m and int(m.group(1)) <= int(m.group(2)) <= int(m.group(1)) + 50:
            out += [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif piece:
            out.append(piece)
    return out


class CitationResolver:
    """Resolve citation labels to project papers.

    ``papers``: the project's papers, each a dict with ``hash_id`` and optionally ``doi``,
    ``title``, ``bib_key``, ``first_author`` (surname) and ``year``.
    """

    def __init__(self, papers: List[Dict], draft_text: str = ""):
        self.papers = papers
        self.references = parse_numbered_references(draft_text)
        self.by_doi = {_norm_doi(p.get("doi")): p["hash_id"] for p in papers if _norm_doi(p.get("doi"))}
        self.by_key = {p["bib_key"]: p["hash_id"] for p in papers if p.get("bib_key")}
        self.by_hash = {p["hash_id"]: p for p in papers}
        titles = [(_norm(p.get("title", "")), p["hash_id"]) for p in papers if len(_norm(p.get("title", ""))) > 20]
        self.titles = sorted(titles, key=lambda t: -len(t[0]))     # longest (most specific) title first

    def _title_match_plausible(self, hid: str, text: str) -> bool:
        """A title found inside a reference is only trusted if the reference also carries the paper's year
        or first-author surname, and is not a commentary/erratum about it."""
        p = self.by_hash.get(hid, {})
        if _DERIVED.search(text) and not _DERIVED.search(p.get("title", "") or ""):
            return False
        year = str(p.get("year") or "")[:4]
        first = p.get("first_author") or ""
        if not year and not first:
            return True
        if year and re.search(r"(?<!\d)%s(?!\d)" % re.escape(year), text):
            return True
        words = {_norm(w) for w in re.split(r"[\s,.;:()&]+", text) if w}
        return bool(first) and _core_surname(first) in words

    def resolve_number(self, n: str) -> Optional[str]:
        entry = self.references.get(n)
        if not entry:
            return None
        if entry["doi"] and entry["doi"] in self.by_doi:
            return self.by_doi[entry["doi"]]
        body = _norm(entry["text"])
        for title, hid in self.titles:
            if title in body and self._title_match_plausible(hid, entry["text"]):
                return hid
        return None

    def _match_author_year(self, surname: str, year: str, letter: str) -> List[str]:
        """Hash ids of the papers by ``surname`` in ``year`` (``letter``: the 'a' of '2015a')."""
        same_year = [p for p in self.papers if str(p.get("year") or "")[:4] == year and p.get("first_author")]
        cands = [p for p in same_year if _norm(p["first_author"]) == _norm(surname)]
        if not cands:                                   # 'Dijk' vs 'van Dijk', 'Mar' vs 'Ben Mar'
            core = _core_surname(surname)
            cands = [p for p in same_year if core and _core_surname(p["first_author"]) == core]
        if letter and len(cands) > 1:
            by_key = [p for p in cands if str(p.get("bib_key") or "").lower().endswith(year + letter)]
            if by_key:
                cands = by_key
            else:                                       # 2015a, 2015b, ... follow title order
                ordered = sorted(cands, key=lambda p: (_norm(p.get("title", "")), p["hash_id"]))
                idx = ord(letter) - ord("a")
                cands = [ordered[idx]] if idx < len(ordered) else []
        return [p["hash_id"] for p in cands]

    def _author_year(self, label: str):
        """``(hash ids, unresolved labels)`` for an author-year label; every year of
        'Smith & Jones, 2002, 2004' and every ';' chunk is resolved on its own."""
        found: List[str] = []
        missing: List[str] = []
        surname, authors = "", ""
        for chunk in re.split(r";", label or ""):
            chunk = _LEAD_IN.sub("", chunk).strip()
            years = list(_YEAR.finditer(chunk))
            if not years:
                continue
            head = chunk[:years[0].start()]
            m = _SURNAME.search(head)
            if m:                                       # else: 'Smith, 2002; 2004' reuses the previous name
                surname = m.group(1)
                authors = head.strip().rstrip(",").strip()
            if not surname:
                continue
            for y in years:
                hits = self._match_author_year(surname, y.group(1), y.group(2))
                if hits:
                    found += [h for h in hits if h not in found]
                else:
                    missing.append(f"{authors}, {y.group(0)}")
        return found, missing

    def resolve_author_year(self, label: str) -> List[str]:
        return self._author_year(label)[0]

    def resolve(self, label: str) -> Dict:
        """``{'papers': [hash ids], 'unresolved': [{'label': '9', 'reference': '...'}]}``."""
        label = label or ""
        is_keylist = bool(re.fullmatch(r"[\w:\-]+(,\s*[\w:\-]+)*", label))
        # 'Smith, 2011' looks like a key list, but a piece that is a bare year makes it author-year.
        has_year_piece = any(re.fullmatch(r"\d{4}[a-z]?", piece) for piece in re.split(r"\s*,\s*", label))
        if re.search(r"[A-Za-z]{2,}.*\d{4}", label) and (not is_keylist or has_year_piece):
            found, missing = self._author_year(label)
            ay = {"papers": found,
                  "unresolved": [{"label": m, "reference": ""} for m in missing]
                  or ([] if found else [{"label": label, "reference": ""}])}
            if found or not is_keylist:
                return ay
            keys = self._resolve_items(label)
            return keys if keys["papers"] else ay
        return self._resolve_items(label)

    def _resolve_items(self, label: str) -> Dict:
        papers, unresolved = [], []
        for item in expand_label(label):
            hid = self.resolve_number(item) if item.isdigit() else self.by_key.get(item)
            if hid:
                if hid not in papers:
                    papers.append(hid)
            else:
                ref = self.references.get(item, {}).get("text", "") if item.isdigit() else ""
                unresolved.append({"label": item, "reference": ref[:300]})
        return {"papers": papers, "unresolved": unresolved}
