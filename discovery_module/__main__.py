"""Command-line literature discovery.

Examples::

    # search arXiv + OpenAlex + Semantic Scholar at once
    python -m discovery_module search "global workspace theory language models"

    # papers related to a paper (library hash, arXiv id or DOI)
    python -m discovery_module related 2308.08708

    # literature for a paragraph of your draft
    python -m discovery_module text "LLMs report subjective experience under self-reference"

    # download open-access PDFs into inbox/ (picked up by the processor)
    python -m discovery_module fetch 2308.08708 10.1016/j.neubiorev.2023.105480

    # any command: --json for machine-readable output, --fetch-top N to download hits
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EXTERNAL_LIBRARY_PATH, LIBRARY_DIR, BOW_INDEX_PATH  # noqa: E402
from discovery_module import discover as D  # noqa: E402
from discovery_module import sources as S  # noqa: E402


def _print(results, as_json):
    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    if "per_source" in results:
        print("hits per source:", ", ".join(f"{k}={v}" for k, v in results["per_source"].items()))
    if results.get("terms"):
        print("query terms:", ", ".join(results["terms"]))
    for i, c in enumerate(results.get("results", []), 1):
        authors = c["authors"][0] + (" et al." if len(c["authors"]) > 1 else "") if c["authors"] else "?"
        ident = f"arXiv:{c['arxiv_id']}" if c.get("arxiv_id") else (c.get("doi") or "")
        flag = " [in library]" if c.get("in_library") else ""
        print(f"{i:2d}. {c['title']} — {authors} ({c.get('year') or 'n.d.'}) {ident}{flag}")
        print(f"     sources: {', '.join(c.get('sources', []))}  score={c.get('score')}")


def _seed_from(identifier):
    meta_path = LIBRARY_DIR / identifier / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta.setdefault("arxiv_id", S.find_arxiv_id("", meta.get("pdf_filename", "")))
        return meta
    c = D.resolve_identifier(identifier)
    if not c:
        sys.exit(f"Cannot resolve '{identifier}' (expected a library hash, an arXiv id or a DOI).")
    return c


def _fetch(results, n, inbox):
    for c in [r for r in results.get("results", []) if not r.get("in_library")][:n]:
        res = D.download_to_inbox(c, inbox, LIBRARY_DIR)
        print(f"  {res['status']}: {c['title'][:90]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m discovery_module", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search several databases")
    s.add_argument("query")
    s.add_argument("--sources", default="arxiv,openalex,semantic_scholar",
                   help="comma list among arxiv, openalex, semantic_scholar, crossref")
    s.add_argument("--year", default="", help="e.g. 2024 or 2020-2025 (OpenAlex / Semantic Scholar)")
    r = sub.add_parser("related", help="papers related to a library paper, arXiv id or DOI")
    r.add_argument("identifier")
    t = sub.add_parser("text", help="literature relevant to a piece of text")
    t.add_argument("text")
    f = sub.add_parser("fetch", help="download PDFs (arXiv ids or DOIs) into the inbox")
    f.add_argument("identifiers", nargs="+")
    for p in (s, r, t):
        p.add_argument("-n", "--limit", type=int, default=15)
        p.add_argument("--json", action="store_true")
        p.add_argument("--fetch-top", type=int, default=0, help="download the N best hits not yet in the library")
    ap.add_argument("--inbox", default=str(EXTERNAL_LIBRARY_PATH))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    inbox = Path(args.inbox)

    if args.cmd == "search":
        res = D.search_literature(args.query, sources=args.sources.split(","), limit=args.limit,
                                  year=args.year, library_dir=LIBRARY_DIR)
    elif args.cmd == "related":
        res = D.related_to_paper(_seed_from(args.identifier), limit=args.limit, library_dir=LIBRARY_DIR)
    elif args.cmd == "text":
        bow = json.loads(BOW_INDEX_PATH.read_text()) if BOW_INDEX_PATH.exists() else None
        res = D.related_to_text(args.text, limit=args.limit, library_dir=LIBRARY_DIR, bow_index=bow)
    else:
        for ident in args.identifiers:
            c = D.resolve_identifier(ident)
            if not c:
                print(f"  unresolved: {ident}")
                continue
            res = D.download_to_inbox(c, inbox, LIBRARY_DIR)
            print(f"  {res['status']}: {c.get('title') or ident} {res.get('path', '')}")
        return 0
    _print(res, args.json)
    if args.fetch_top:
        _fetch(res, args.fetch_top, inbox)
    return 0


if __name__ == "__main__":
    sys.exit(main())
