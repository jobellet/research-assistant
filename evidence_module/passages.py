"""Find the sentences of reference papers that match a claim of a manuscript.

Each paper's PDF is split into sentences (page by page, so every sentence keeps
its page number) and every sentence is embedded once.  The index is stored next
to the paper, in ``library/<hash>/passages.json`` (sentences, pages) and
``passages.npy`` (embeddings).  A claim is then compared with every sentence of
the papers of a project: semantic similarity (cosine of the embeddings) plus a
small bonus for shared distinctive words and numbers.

The embedding model is the library's model (EmbeddingGemma, by default) used at
its full 768 dimensions with its retrieval prompts, which is finer than the
256-dimensional paper-level embeddings of the library search.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np

INDEX_VERSION = 3   # 2: page headers/footers and figure text removed; 3: Methods after the
                    # references kept, statistics sentences kept, compound hyphens and page breaks
QUERY_PROMPT = "task: search result | query: "
DOCUMENT_PROMPT = "title: none | text: "

# An encoder takes texts and returns an (n, d) array of L2-normalised vectors.
Encoder = Callable[[List[str], str], np.ndarray]

# --------------------------------------------------------------------------
# Text cleaning and sentence splitting
# --------------------------------------------------------------------------

_ABBREVIATIONS = {
    "al", "fig", "figs", "eq", "eqs", "ref", "refs", "e.g", "i.e", "vs", "ca", "approx",
    "resp", "cf", "dr", "prof", "no", "vol", "pp", "ed", "eds", "st", "sec", "suppl",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "inc", "ltd", "co", "mr", "mrs", "ms", "jr", "sr", "etc", "viz", "n.b", "tab",
}
_REFERENCES_HEADING = re.compile(
    r"^\s*(\d{1,2}\.?\s*)?((methods\s+)?references?( and notes)?|literature cited|bibliography"
    r"|references cited)\s*:?\s*$", re.I)
# Sections printed after the reference list (Nature 'Methods', Cell 'STAR Methods', ...)
_RESUME_HEADING = re.compile(
    r"^\s*(\d{1,2}\.?\s*)?((online\s+)?methods|star\W{0,3}methods|materials and methods"
    r"|experimental procedures|supplementary (information|materials?|methods)|extended data)\s*:?\s*$", re.I)
# A line-end hyphen after one of these is part of a compound ('self-motion'), not hyphenation.
_COMPOUND_PREFIXES = {
    "self", "non", "eye", "head", "well", "low", "high", "two", "three", "one", "multi", "cross",
    "long", "short", "post", "pre", "anti", "co", "semi", "inter", "intra", "sub", "time", "task",
    "object", "goal", "stimulus", "reward", "saccade", "drift", "trial", "state", "top", "bottom",
}
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "which", "their",
    "these", "those", "have", "has", "had", "been", "but", "not", "its", "into", "than", "then",
    "also", "such", "may", "can", "our", "they", "there", "both", "each", "between", "within",
    "during", "after", "before", "while", "when", "where", "whether", "other", "more", "most",
    "only", "some", "all", "any", "one", "two", "three", "however", "thus", "therefore", "here",
    "show", "shows", "shown", "found", "using", "used", "based", "well", "very", "same", "different",
}


def _hyphenated_words(text: str) -> set:
    """Compounds written with a hyphen inside a line ('drift-corrected'), lower-cased."""
    return {w.lower() for w in re.findall(r"\b[A-Za-z]+-[A-Za-z]+\b", text)}


def _normalise(text: str, hyphenated: Optional[set] = None) -> str:
    text = text.replace("\u00ad", "")                    # soft hyphen
    if hyphenated is None:
        hyphenated = _hyphenated_words(text)

    def join(m):                                         # hyphenation across lines
        a, b = m.group(1), m.group(2)
        keep = (b[0].isupper() or b[0].isdigit() or a.lower() in _COMPOUND_PREFIXES
                or f"{a}-{b}".lower() in hyphenated)
        return f"{a}-{b}" if keep else a + b

    text = re.sub(r"\b(\w+)-[ \t]*\n\s*(\w+)", join, text)
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    return re.sub(r"\s+", " ", text).strip()


def _split_pieces(text: str) -> List[str]:
    """Normalised text cut at sentence ends (no length filter)."""
    pieces, start = [], 0
    for m in re.finditer(r"[.!?](?=[\"'”’)\]]?\s+[\"'“‘(\[]?[A-Z0-9])", text):
        end = m.end()
        before = text[start:end]
        word = re.search(r"([A-Za-z][A-Za-z.]*)\.$", before)
        if word:
            w = word.group(1).lower().rstrip(".")
            if w in _ABBREVIATIONS or len(w) == 1:      # 'et al.', 'Fig.', initials 'J.'
                continue
        if re.search(r"\b\d+\.$", before) and re.match(r"\s*\d", text[end:]):
            continue                                     # decimal numbers split by spaces
        pieces.append(text[start:end].strip())
        start = end
    pieces.append(text[start:].strip())
    return [p for p in pieces if p]


def split_sentences(text: str, min_words: int = 5, max_words: int = 90,
                    hyphenated: Optional[set] = None) -> List[str]:
    """Split prose into sentences, keeping abbreviations such as 'et al.' or 'Fig.' intact."""
    text = _normalise(text, hyphenated)
    if not text:
        return []
    pieces = _split_pieces(text)
    out = []
    for s in pieces:
        words = s.split()
        if len(words) < min_words:
            continue
        # Very long 'sentences' are usually tables or run-together text: cut them up.
        while len(words) > max_words:
            out.append(" ".join(words[:max_words]))
            words = words[max_words - 10:]
        if len(words) >= min_words:
            out.append(" ".join(words))
    return out


_STAMP = re.compile(r"(downloaded from|this content downloaded|for personal use only|all rights reserved"
                    r"|copyright ©|\bIP:\s*\d+\.\d+\.\d+\.\d+)", re.I)


def _strip_page_furniture(pages: List[str]) -> List[str]:
    """Remove running headers/footers (lines repeated on many pages) and download stamps."""
    from collections import Counter
    counts = Counter(line.strip() for page in pages for line in set(page.splitlines())
                     if len(line.strip()) > 3)
    min_pages = max(3, int(0.3 * len(pages)))
    repeated = {line for line, n in counts.items() if n >= min_pages} if len(pages) >= 3 else set()
    out = []
    for page in pages:
        out.append("\n".join(line for line in page.splitlines()
                             if line.strip() not in repeated and not _STAMP.search(line)))
    return out


def _is_figure_text(sentence: str) -> bool:
    """Axis labels and table cells: mostly numbers or one-letter tokens, and few real words.

    A results sentence dense with statistics ('Rates fell from 45.2 ± 3.1 to 21.7 ± 2.4
    spikes/s (p < 0.001, n = 38).') still has real words and is kept."""
    tokens = sentence.split()
    if not tokens:
        return True
    numeric = sum(1 for t in tokens if re.fullmatch(r"[\d.,:;%±+\-–()\[\]°]+|[A-Za-z]", t))
    words = sum(1 for t in tokens if re.fullmatch(r"[(\[]?[A-Za-z][A-Za-z\-/']{2,}[.,;:)\]]*", t))
    return words < 3 or (numeric / len(tokens) > 0.4 and words < 4)


def _cut_references(pages: List[str]) -> List[str]:
    """Drop the reference lists (they match claims for the wrong reason).

    Indexing stops at a 'References' heading found after 40% of the text and resumes at a
    later main-section heading (Methods, STAR Methods, Supplementary ...), whose own
    reference list is dropped too.  The number of pages is kept, so page numbers hold."""
    total = sum(len(p) for p in pages) or 1
    seen, skipping, cut_any = 0, False, False
    out = []
    for page in pages:
        lines = page.splitlines()
        kept = []
        for j, line in enumerate(lines):
            if _REFERENCES_HEADING.match(line) and (
                    cut_any or (seen + len("\n".join(lines[:j]))) / total > 0.4):
                skipping = cut_any = True
                continue
            if skipping and _RESUME_HEADING.match(line):
                skipping = False
            if not skipping:
                kept.append(line)
        out.append("\n".join(kept))
        seen += len(page)
    return out if cut_any else pages


def _sentences_from_pages(pages: List[str]) -> List[Dict]:
    """Clean pages (furniture, reference lists) and split them into sentences {'t', 'p'}.

    A sentence running over a page break (the page does not end a sentence and the next
    page starts in lower case) is joined and kept on the page where it starts."""
    pages = _cut_references(_strip_page_furniture(list(pages)))
    hyphenated = _hyphenated_words("\n".join(pages))
    pages = list(pages)
    for i in range(len(pages) - 1):
        tail = pages[i].rstrip()
        nxt = _split_pieces(_normalise(pages[i + 1], hyphenated))
        if not tail or not nxt or re.search(r"[.!?][\"'”’)\]]?$", tail) or not nxt[0][:1].islower():
            continue
        pages[i] = tail + "\n" + nxt[0]
        pages[i + 1] = " ".join(nxt[1:])
    sentences: List[Dict] = []
    for page_no, page in enumerate(pages, start=1):
        for s in split_sentences(page, hyphenated=hyphenated):
            if not _is_figure_text(s):
                sentences.append({"t": s, "p": page_no})
    return sentences


# Every pattern runs on user selections: none may backtrack exponentially (no repeated
# group around an ambiguous part), so an unclosed '(' cannot freeze the server.
_LEAD_IN = r"(?:see(?: also)?|e\.g\.,?|cf\.|i\.e\.,?|reviewed in)\s+"
_PARTICLES = r"(?:van|von|de|der|den|da|del|della|di|du|le|la|ben|ter|ten)\s+"
_CITATION_PATTERNS = [
    re.compile(r"\\(?:cite|citep|citet|autocite|parencite|textcite)\*?(?:\[[^\]]*\])*\{[^}]*\}"),
    re.compile(r"\[(?:\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]"),                     # [12], [3-5, 9]
    # (Smith et al., 1985; van Dijk and Jones, 2010), (see Smith, 2002), (e.g., Lopez, 2015)
    re.compile(r"\((?:" + _LEAD_IN + r")?(?:" + _PARTICLES + r")*[A-Z][A-Za-z'’\-]+(?![A-Za-z'’\-])"
               r"[^()]{0,400}?\d{4}[a-z]?\)"),
    # Superscripts glued to an acronym, only as a range or a list: 'SC17–21', 'FEF13,14'
    # (a single number is an area name: 'V4', 'CA1', 'MT5'; 'CA1–3', 'PC1,2' are not citations)
    re.compile(r"(?<=[A-Z]{2})(?<!\bCA)(?<!\bPC)(?:\d{1,3}[–-]\d{1,3}|\d{1,3}(?:,\d{1,3})+)"
               r"(?:,\d{1,3}(?:[–-]\d{1,3})?)*(?=\s|$|[,.;:])"),
    # Word superscripts pasted as text: 'fields,32 orbital', 'functions,9,34', 'tasks.15,16'
    # and after an area name 'V1,7'; not the digits of a number: '0.5', '1,250', 'p = 0.39'
    re.compile(r"(?:(?<=[^\d\s][,.;:)\]])|(?<=[A-Z]\d[,.;:])|(?<=[A-Z]\d\d[,.;:]))(?:\d{1,3}(?:[–-]\d{1,3})?)(?:,\d{1,3}(?:[–-]\d{1,3})?)*"
               r"(?=\s|$|[,.;:])"),
    # ... or glued to a lower-case word: 'ocular drift14 and' (not 'V4', 'CA1', '7a')
    re.compile(r"(?<=[a-z]{3})(?:\d{1,3}(?:[–-]\d{1,3})?)(?:,\d{1,3}(?:[–-]\d{1,3})?)*(?=\s|$|[,.;:])"),
]
_LEAD_IN_RE = re.compile(r"^" + _LEAD_IN, re.I)
_TEX_CITE_RE = re.compile(r"\\[a-zA-Z]+\*?(\[[^\]]*\])*\{([^}]*)\}")


def _markers(text: str) -> List[tuple]:
    """(start, end, label) of the citation markers of a text, in order."""
    marks = []
    for pat in _CITATION_PATTERNS:
        for m in pat.finditer(text):
            if not any(m.start() < e and s < m.end() for s, e, _ in marks):
                marks.append((m.start(), m.end(), m.group(0)))
    out = []
    for start, end, raw in sorted(marks):
        raw = raw.strip("[]() ")
        raw = _TEX_CITE_RE.sub(r"\2", raw)
        raw = _LEAD_IN_RE.sub("", raw)                   # '(see Smith, 2002)' -> 'Smith, 2002'
        out.append((start, end, raw))
    return out


def citation_labels(text: str) -> List[str]:
    """The citation markers of a text, e.g. ['32', '9,34', 'smith2010', 'Jones et al., 1985']."""
    return [label for _, _, label in _markers(text)]


def _clause_start(span: str) -> int:
    """Index of the last clause boundary (',', ';', ':' or an open '(') outside parentheses."""
    depth = 0
    for i in range(len(span) - 1, -1, -1):
        c = span[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                return i
            depth -= 1
        elif c in ",;:" and depth == 0:
            return i
    return -1


def _is_claim(text: str) -> bool:
    """Enough words to stand as a claim: two words, one of 3+ letters ('MT activity', not 'V4')."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]*", text)
    return len(words) >= 2 and any(len(w) >= 3 for w in words)


def split_claims(text: str) -> List[Dict]:
    """Split a sentence into the parts that carry their own citation.

    'Area X, with feature alpha,12 feature beta,13 and feature gamma
    functions,4,15 is ...' gives three parts: ('with feature alpha', '12'),
    ('feature beta', '13'), ('feature gamma functions', '4,15').  Returns []
    when the text has fewer than two citation markers (then the whole text is the claim).
    """
    marks = _markers(text)
    if len(marks) < 2:
        return []

    def tidy(clause: str) -> str:
        clause = re.sub(r"^\s*(and|or|as well as|but|whereas|while)\s+", "", clause.strip(" ,;.:"),
                        flags=re.I)
        return clean_claim(clause)

    parts, prev_end = [], 0
    for start, end, label in marks:
        span = text[prev_end:start].rstrip(" ,;.:")
        # the claim attached to a marker starts after the last clause boundary before it
        # (commas inside a parenthesis such as '(<2 mm, i.e., <80 px)' are not boundaries)
        cut = _clause_start(span)
        clause = span[cut + 1:] if cut >= 0 else span
        # a parenthesis closing the clause qualifies it: search without it
        bare = re.sub(r"\s*\([^()]*\)\s*$", "", clause)
        if _is_claim(bare):
            clause = bare
        clause = tidy(clause)
        if not _is_claim(clause):
            clause = tidy(span)
        if not _is_claim(clause):          # 'V4', 'FEF': keep the sentence up to the marker
            clause = tidy(text[:start])
        if not _is_claim(clause):
            clause = clean_claim(text)
        parts.append({"text": clause, "cites": label})
        prev_end = end
    return parts


def clean_claim(text: str) -> str:
    """The claim without citation markers (\\cite{}, [12], (Author, 2001), pasted superscripts)."""
    out = text
    for pat in _CITATION_PATTERNS:
        out = pat.sub(" ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def _terms(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z\-]{2,}", text.lower()) if w not in _STOP}


def _numbers(text: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", text))

# --------------------------------------------------------------------------
# Encoder
# --------------------------------------------------------------------------


def sentence_transformer_encoder(model, dim: Optional[int] = None) -> Encoder:
    """Wrap a SentenceTransformer: 'query' and 'document' texts get the retrieval prompts
    (EmbeddingGemma's), and ``dim`` overrides the model's truncation (None = model default)."""
    gemma = _is_gemma(model)

    def encode(texts: List[str], kind: str) -> np.ndarray:
        kwargs = {"prompt": QUERY_PROMPT if kind == "query" else DOCUMENT_PROMPT} if gemma else {}
        if dim:
            kwargs["truncate_dim"] = dim
        vecs = model.encode(list(texts), batch_size=32, convert_to_numpy=True,
                            show_progress_bar=False, **kwargs)
        vecs = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-12)

    encode.model_id = f"{_model_name(model)}@{dim or 'default'}"
    return encode


def _model_name(model) -> str:
    for attr in ("model_name_or_path", "_model_name"):
        if getattr(model, attr, None):
            return str(getattr(model, attr))
    try:
        return str(model[0].auto_model.config._name_or_path)
    except Exception:
        return type(model).__name__


def _is_gemma(model) -> bool:
    return "gemma" in _model_name(model).lower()

# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------


def _pdf_pages(pdf_path: Path) -> List[str]:
    import fitz  # PyMuPDF
    with fitz.open(str(pdf_path)) as doc:
        return [page.get_text("text") for page in doc]


def build_passage_index(paper_dir: Path, encoder: Encoder, pdf_path: Optional[Path] = None,
                        pages: Optional[List[str]] = None) -> Dict:
    """Split the paper's PDF into sentences, embed them, and save the index in ``paper_dir``."""
    paper_dir = Path(paper_dir)
    if pages is None:
        if pdf_path is None:
            pdfs = sorted(paper_dir.glob("*.pdf"))
            if not pdfs:
                raise FileNotFoundError(f"No PDF in {paper_dir}")
            pdf_path = pdfs[0]
        pages = _pdf_pages(Path(pdf_path))
    sentences = _sentences_from_pages(pages)
    if sentences:
        texts = [s["t"] for s in sentences]
        chunks = [encoder(texts[i:i + 16], "document") for i in range(0, len(texts), 16)]
        vecs = np.vstack(chunks).astype(np.float16)
    else:
        vecs = np.zeros((0, 1), dtype=np.float16)
    meta = {
        "version": INDEX_VERSION,
        "model": getattr(encoder, "model_id", "unknown"),
        "source": Path(pdf_path).name if pdf_path else None,
        "sentences": sentences,
    }
    tmp_json, tmp_npy = paper_dir / "passages.json.tmp", paper_dir / "passages.tmp.npy"
    np.save(tmp_npy, vecs)
    tmp_json.write_text(json.dumps(meta))
    tmp_npy.replace(paper_dir / "passages.npy")
    tmp_json.replace(paper_dir / "passages.json")
    return meta


def load_passage_index(paper_dir: Path):
    """(metadata, embeddings) of a paper's sentence index, or (None, None)."""
    paper_dir = Path(paper_dir)
    try:
        meta = json.loads((paper_dir / "passages.json").read_text())
        vecs = np.load(paper_dir / "passages.npy")
    except (OSError, ValueError):
        return None, None
    if len(meta.get("sentences", [])) != len(vecs):
        return None, None
    return meta, vecs


def passage_index_is_current(paper_dir: Path, model_id: Optional[str] = None) -> bool:
    try:
        meta = json.loads((Path(paper_dir) / "passages.json").read_text())
    except (OSError, ValueError):
        return False
    if meta.get("version") != INDEX_VERSION or not (Path(paper_dir) / "passages.npy").exists():
        return False
    return model_id is None or meta.get("model") == model_id

# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


def _rank(query_vecs: List[np.ndarray], weights: List[float], q_text: str, sentences, vecs,
          per_paper: int, context: int) -> List[Dict]:
    """Best ``per_paper`` sentences: weighted cosine to the query vectors + shared-word bonus."""
    vecs = vecs.astype(np.float32)
    sims = sum(w * (vecs @ q) for q, w in zip(query_vecs, weights)) / sum(weights)
    q_terms, q_nums = _terms(q_text), _numbers(q_text)
    scores = []
    for i, s in enumerate(sentences):
        bonus = 0.0
        if q_terms:
            bonus += 0.12 * len(q_terms & _terms(s["t"])) / len(q_terms)
        if q_nums and q_nums & _numbers(s["t"]):
            bonus += 0.03
        scores.append(float(sims[i]) + bonus)
    order = np.argsort(scores)[::-1]
    picked: List[int] = []
    for i in order:
        if any(abs(int(i) - j) <= context for j in picked):
            continue                   # neighbours are shown as context already
        picked.append(int(i))
        if len(picked) >= per_paper:
            break
    return [{
        "index": i,
        "text": sentences[i]["t"],
        "page": sentences[i].get("p"),
        "score": round(scores[i], 4),
        "similarity": round(float(sims[i]), 4),
        "before": " ".join(sentences[j]["t"] for j in range(max(0, i - context), i)),
        "after": " ".join(sentences[j]["t"] for j in range(i + 1, min(len(sentences), i + 1 + context))),
    } for i in picked]


def find_evidence(claim: str, papers: Sequence[Dict], encoder: Encoder, library_dir: Path,
                  per_paper: int = 3, top_k: int = 10, context: int = 1, split: bool = True) -> Dict:
    """Rank the sentences of ``papers`` (dicts with ``hash_id``, optional title/authors/year)
    by how well they match ``claim``.

    Returns the cleaned claim, the overall best sentences (``top``), and for each paper its
    best ``per_paper`` sentences with the neighbouring sentences as context.  When the claim
    carries several citation markers, ``parts`` holds the same result for each cited part
    (scored on the part and, with a smaller weight, on the whole sentence).
    """
    query = clean_claim(claim)
    if len(query.split()) < 2:
        raise ValueError("Select at least a few words of the claim.")
    parts = split_claims(claim) if split else []
    texts = [query] + [p["text"] for p in parts]
    qvecs = encoder(texts, "query").astype(np.float32)

    indexes, missing = {}, []
    for paper in papers:
        hid = paper["hash_id"]
        meta, vecs = load_passage_index(Path(library_dir) / hid)
        if meta is not None and len(vecs) and vecs.shape[1] != qvecs.shape[1]:
            meta = None                    # built with another model: needs re-indexing
        if meta is None:
            missing.append(hid)
        indexes[hid] = (meta, vecs)

    def run(q_text, q_list, weights):
        results = []
        for paper in papers:
            meta, vecs = indexes[paper["hash_id"]]
            if meta is None:
                fallback = _word_matches(q_text, Path(library_dir) / paper["hash_id"], per_paper, context)
                if fallback is not None:
                    results.append({**_paper_info(paper), **fallback})
                continue
            passages = _rank(q_list, weights, q_text, meta["sentences"], vecs, per_paper, context) \
                if meta["sentences"] else []
            results.append({**_paper_info(paper), "best_score": passages[0]["score"] if passages else 0.0,
                            "passages": passages, "method": "semantic"})
        # word-match scores are on another scale than cosine scores: rank them after
        results.sort(key=lambda r: (r.get("method") != "words", r["best_score"]), reverse=True)
        top = sorted(({**p, "hash_id": r["hash_id"], "title": r.get("title", ""),
                       "method": r.get("method")} for r in results for p in r["passages"]),
                     key=lambda p: (p["method"] != "words", p["score"]), reverse=True)[:top_k]
        return results, top

    results, top = run(query, [qvecs[0]], [1.0])
    out = {"claim": query, "papers": results, "top": top, "not_indexed": missing, "parts": []}
    for n, part in enumerate(parts, start=1):
        p_results, p_top = run(part["text"], [qvecs[n], qvecs[0]], [0.65, 0.35])
        out["parts"].append({"claim": part["text"], "cites": part["cites"], "papers": p_results, "top": p_top})
    return out


def _word_matches(query: str, paper_dir: Path, per_paper: int, context: int) -> Optional[Dict]:
    """Shared-word matching on the extracted text, used until the sentence index is built."""
    try:
        text = (paper_dir / "full_text.txt").read_text(errors="ignore")
    except OSError:
        return None
    # same cleaning as the index: no reference list, page furniture or figure text
    pages = text.split("\f") if "\f" in text else [text]
    found = _sentences_from_pages(pages)
    sentences = [s["t"] for s in found]
    q_terms = _terms(query)
    if not sentences or not q_terms:
        return None
    scores = [len(q_terms & _terms(s)) / len(q_terms) for s in sentences]
    order = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)
    picked: List[int] = []
    for i in order:
        if scores[i] <= 0 or len(picked) >= per_paper:
            break
        if all(abs(i - j) > context for j in picked):
            picked.append(i)
    passages = [{
        "index": i, "text": sentences[i], "page": found[i]["p"] if len(pages) > 1 else None, "score": round(scores[i] * 0.5, 4),
        "similarity": None,
        "before": " ".join(sentences[max(0, i - context):i]),
        "after": " ".join(sentences[i + 1:i + 1 + context]),
    } for i in picked]
    return {"best_score": passages[0]["score"] if passages else 0.0, "passages": passages,
            "method": "words"}


def _paper_info(paper: Dict) -> Dict:
    return {k: paper.get(k) for k in ("hash_id", "title", "authors", "year", "bib_key", "zotero_key")
            if k in paper}
