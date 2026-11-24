"""Audit every citation of a draft against the project's own papers.

For each sentence of the draft that cites something, each cited part of the
sentence is matched with the sentences of the cited paper (and of the other
papers of the project, to spot a better-fitting source).  The reference list is
checked too: every DOI is looked up in Crossref and compared with the reference
text, references never cited and citation numbers without a reference are
listed, and sentences without a citation that closely match a project paper are
offered as possibly missing citations.

The audit does not decide whether a claim is true: it collects the evidence a
reader (or an AI assistant) needs to judge each citation quickly.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from evidence_module import passages as ev
from project_module.citations import expand_label, parse_numbered_references

_REF_HEADING = re.compile(r"^\s*(references|bibliography|literature cited|references and notes)\s*:?\s*$", re.I)
# A sentence ends at . ! or ? optionally followed by a pasted superscript citation
# ('...tasks.15,16 Next sentence'), then whitespace and a capital letter or digit.
_SENT_END = re.compile(r"(?<=[a-z0-9)\]%°'’\"”])([.!?])((?:\d{1,3}(?:[–-]\d{1,3})?)(?:,\d{1,3}(?:[–-]\d{1,3})?)*)?"
                       r"(?=\s+[\"“(\[]?[A-Z0-9])")
_ABBREV = re.compile(r"(?:\b(?:et al|e\.g|i\.e|Fig|Figs|Eq|vs|cf|ca|approx|resp|Ref|Refs|No|Vol|Suppl)|\b[A-Z])$")


_FRONT_END = re.compile(r"^\s*(highlights|summary|abstract|introduction|main text|significance)\b.{0,40}$", re.I)


def split_body(draft: str) -> str:
    """The draft without its title block (author names with affiliation numbers look like
    citations) and without its reference list (everything after the last 'References' heading)."""
    lines = draft.splitlines()
    cut = None
    for i, line in enumerate(lines):
        if _REF_HEADING.match(line):
            cut = i
    lines = lines[:cut] if cut is not None else lines
    start = next((i for i, line in enumerate(lines[:80]) if _FRONT_END.match(line)), 0)
    return "\n".join(lines[start:])


def draft_sentences(body: str) -> List[str]:
    """Sentences of the draft, each keeping the superscript citations that follow its full stop."""
    out = []
    for para in re.split(r"\n\s*\n|\n", body):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        start = 0
        for m in _SENT_END.finditer(para):
            head = para[start:m.start()]
            if _ABBREV.search(head):
                continue
            end = m.end()
            out.append(para[start:end].strip())
            start = end
        if para[start:].strip():
            out.append(para[start:].strip())
    return [s for s in out if len(s.split()) >= 4]


# --------------------------------------------------------------------------- DOIs

def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def crossref_lookup(doi: str, timeout: float = 15.0) -> Optional[Dict]:
    """Crossref record of a DOI (title, year, first author), None if the DOI is unknown."""
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/:;()")
    req = urllib.request.Request(url, headers={"User-Agent": "research-assistant citation-audit"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                msg = json.loads(r.read()).get("message", {})
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 503) and attempt < 3:   # rate limited: wait and retry
                time.sleep(2 * (attempt + 1))
                continue
            raise
    issued = (msg.get("issued") or msg.get("published-print") or msg.get("published-online") or {})
    year = ((issued.get("date-parts") or [[None]])[0] or [None])[0]
    authors = msg.get("author") or []
    return {"title": (msg.get("title") or [""])[0], "year": year,
            "first_author": (authors[0].get("family") or authors[0].get("name") or "") if authors else "",
            "journal": (msg.get("container-title") or [""])[0]}


def check_doi(entry: Dict, lookup: Callable[[str], Optional[Dict]] = crossref_lookup) -> Dict:
    """Does the DOI of a reference exist, and does its record match the reference text?"""
    doi = entry.get("doi") or ""
    if not doi:
        return {"status": "no_doi"}
    try:
        rec = lookup(doi)
    except Exception as e:  # network trouble: report, do not guess
        return {"status": "error", "error": str(e)[:200]}
    if rec is None:
        return {"status": "not_found", "note": "Crossref does not know this DOI"}
    ref_words = set(_words(entry.get("text", "")))
    title_words = [w for w in _words(rec["title"]) if len(w) > 2]
    title_match = round(sum(w in ref_words for w in title_words) / len(title_words), 2) if title_words else 0.0
    year_ok = bool(rec["year"]) and str(rec["year"]) in entry.get("text", "")
    author_ok = bool(rec["first_author"]) and set(_words(rec["first_author"])) <= ref_words
    problems = []
    if title_match < 0.7:
        problems.append("title differs")
    if rec["year"] and not year_ok:
        problems.append(f"year differs (Crossref: {rec['year']})")
    if rec["first_author"] and not author_ok:
        problems.append(f"first author differs (Crossref: {rec['first_author']})")
    return {"status": "ok" if not problems else "mismatch", "problems": problems,
            "title_match": title_match, "crossref": rec}


# --------------------------------------------------------------------------- audit

def _passages(block: Dict, hash_id: str, n: int = 2) -> List[Dict]:
    for p in block.get("papers", []):
        if p["hash_id"] == hash_id:
            return [{"text": s["text"], "page": s.get("page"), "similarity": s.get("similarity"),
                     "before": s.get("before", ""), "after": s.get("after", "")}
                    for s in p.get("passages", [])[:n]]
    return []


def _best_other(block: Dict, exclude: List[str]) -> Optional[Dict]:
    best = None
    for p in block.get("papers", []):
        if p["hash_id"] in exclude or not p.get("passages") or p.get("method") == "words":
            continue
        s = p["passages"][0]
        if s.get("similarity") is not None and (best is None or s["similarity"] > best["similarity"]):
            best = {"hash_id": p["hash_id"], "title": p.get("title", ""), "authors": p.get("authors", ""),
                    "year": p.get("year", ""), "text": s["text"], "page": s.get("page"),
                    "similarity": s["similarity"]}
    return best


def run_audit(draft: str, papers: List[Dict], encoder, library_dir: Path, resolver, *,
              check_dois: bool = True, suggest_missing: bool = True,
              doi_lookup: Callable[[str], Optional[Dict]] = crossref_lookup,
              progress: Optional[Callable[[int, int, str], None]] = None,
              missing_threshold: float = 0.66) -> Dict:
    """Audit the citations of ``draft`` (see the module docstring).

    ``papers`` are the project's papers, ``resolver`` a CitationResolver built from them
    and the draft.
    """
    titles = {p["hash_id"]: p for p in papers}
    references = parse_numbered_references(draft)
    sentences = draft_sentences(split_body(draft))
    cited_numbers: Dict[str, List[int]] = {}
    citations, uncited_sentences, unknown = [], [], {}
    total = len(sentences) + (len(references) if check_dois else 0)

    for i, sentence in enumerate(sentences):
        if progress:
            progress(i, total, sentence[:60])
        labels = ev.citation_labels(sentence)
        if not labels:
            uncited_sentences.append((i, sentence))
            continue
        try:
            res = ev.find_evidence(sentence, papers, encoder, library_dir, per_paper=2, top_k=5)
        except ValueError:
            continue
        parts = res["parts"] or [{"claim": res["claim"], "cites": ",".join(labels),
                                  "papers": res["papers"]}]
        out_parts = []
        for part in parts:
            refs = []
            resolved = resolver.resolve(part["cites"])
            for hid in resolved["papers"]:
                info = titles.get(hid, {})
                refs.append({"status": "in_project", "hash_id": hid, "title": info.get("title", ""),
                             "authors": info.get("authors", ""), "year": info.get("year", ""),
                             "best_sentences": _passages(part, hid)})
            for u in resolved["unresolved"]:
                label = u["label"]
                in_list = label in references
                if label.isdigit() and not in_list:
                    unknown.setdefault(label, []).append(i)
                refs.append({"status": "not_in_project" if in_list or not label.isdigit() else "no_reference_entry",
                             "label": label, "reference": u.get("reference", "")})
            for lab in part["cites"] and expand_label(part["cites"]) or []:
                if lab.isdigit():
                    cited_numbers.setdefault(lab, []).append(i)
            other = _best_other(part, resolved["papers"])
            cited_best = max((s["similarity"] for r in refs for s in r.get("best_sentences", [])
                              if s.get("similarity") is not None), default=None)
            entry = {"claim": part["claim"], "cites": part["cites"], "refs": refs}
            if other and (cited_best is None or other["similarity"] > cited_best + 0.05):
                entry["better_match_elsewhere"] = other
            out_parts.append(entry)
        citations.append({"sentence_index": i, "sentence": sentence, "parts": out_parts})

    possibly_missing = []
    if suggest_missing and papers:
        for i, sentence in uncited_sentences:
            if progress:
                progress(i, total, "uncited: " + sentence[:50])
            if len(sentence.split()) < 8:
                continue
            try:
                res = ev.find_evidence(sentence, papers, encoder, library_dir, per_paper=1, top_k=1)
            except ValueError:
                continue
            top = res["top"][0] if res["top"] else None
            if top and top.get("similarity") is not None and top["similarity"] >= missing_threshold:
                possibly_missing.append({"sentence_index": i, "sentence": sentence,
                                         "paper": titles.get(top["hash_id"], {}).get("title", top.get("title", "")),
                                         "hash_id": top["hash_id"], "text": top["text"], "page": top.get("page"),
                                         "similarity": top["similarity"]})
        possibly_missing.sort(key=lambda m: -m["similarity"])

    ref_report = []
    for n, (num, entry) in enumerate(sorted(references.items(), key=lambda kv: int(kv[0]))):
        if progress and check_dois:
            progress(len(sentences) + n, total, f"DOI of reference {num}")
        hid = resolver.resolve_number(num)
        item = {"n": num, "reference": entry["text"][:400], "doi": entry["doi"],
                "in_project": hid, "cited_in": cited_numbers.get(num, [])}
        if hid:
            pdoi = (titles.get(hid, {}).get("doi") or "").lower()
            if pdoi and entry["doi"] and pdoi != entry["doi"].lower():
                item["doi_differs_from_library"] = pdoi
        if check_dois:
            item["doi_check"] = check_doi(entry, doi_lookup)
            time.sleep(0.3)
        ref_report.append(item)

    summary = {
        "sentences": len(sentences),
        "citing_sentences": len(citations),
        "references": len(references),
        "references_in_project": sum(1 for r in ref_report if r["in_project"]),
        "uncited_references": [r["n"] for r in ref_report if not r["cited_in"]],
        "citation_numbers_without_reference": sorted(unknown, key=int),
        "doi_problems": [r["n"] for r in ref_report
                         if r.get("doi_check", {}).get("status") in ("not_found", "mismatch")
                         or r.get("doi_differs_from_library")],
        "better_match_elsewhere": sum(1 for c in citations for p in c["parts"] if "better_match_elsewhere" in p),
        "possibly_missing": len(possibly_missing),
    }
    if progress:
        progress(total, total, "done")
    return {"summary": summary, "references": ref_report, "citations": citations,
            "possibly_missing": possibly_missing[:25],
            "note": ("Similar sentences may support or contradict a claim; read them to judge. "
                     "'better_match_elsewhere' means another project paper matches the claim more closely "
                     "than the cited one.")}
