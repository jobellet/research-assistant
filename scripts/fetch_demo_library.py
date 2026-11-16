"""Download the demo library used in tutorial.md (AI consciousness, 39 papers).

All papers are open access (38 arXiv preprints + one CC-BY journal article).
They are saved to the inbox; start the server and click "Run Process" in the
Backend Monitor (or POST /api/process/start) to ingest and index them.

    python scripts/fetch_demo_library.py [--inbox PATH]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EXTERNAL_LIBRARY_PATH, LIBRARY_DIR  # noqa: E402
from discovery_module.discover import download_to_inbox, resolve_identifier  # noqa: E402

DEMO_PAPERS = [
    # theories, indicators, methodology
    "2308.08708", "2303.07103", "2410.11407", "2404.15369", "2609.33366", "2610.01002",
    "2309.10063", "2505.19806", "2405.04540", "2306.00915",
    "10.1016/j.neubiorev.2023.105480",  # Fazekas, Cleeremans & Overgaard 2024 (CC BY)
    # global workspace in deep learning
    "1709.08568", "2012.10390", "2103.01197", "2306.15711", "2107.13704", "2204.05133", "2607.15495",
    # integrated information theory
    "2212.14787", "2412.04571", "2601.22786",
    # introspection, metacognition, self-knowledge
    "2207.05221", "2410.13787", "2503.07513", "2506.05068", "2505.13763", "2410.18819",
    "2501.11120", "2309.00667", "2407.04694", "2305.17375",
    # self-reports, interpretation, welfare
    "2311.08576", "2510.24797", "2411.02432", "2212.03551", "2305.16367", "2402.12422",
    "2411.00986", "2501.07290",
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox", default=str(EXTERNAL_LIBRARY_PATH))
    args = ap.parse_args(argv)
    inbox = Path(args.inbox)
    failed = []
    for ident in DEMO_PAPERS:
        cand = resolve_identifier(ident)
        res = download_to_inbox(cand, inbox, LIBRARY_DIR) if cand else {"status": "unresolved"}
        print(f"{res['status']:>11}  {ident}  {(cand or {}).get('title', '')[:70]}")
        if res["status"] in ("failed", "no_pdf", "unresolved"):
            failed.append(ident)
        time.sleep(1)  # be gentle with arXiv
    print(f"\n{len(DEMO_PAPERS) - len(failed)}/{len(DEMO_PAPERS)} papers ready in {inbox}")
    if failed:
        print("Download these manually (open the link, save the PDF into the inbox):")
        for ident in failed:
            print("   ", f"https://doi.org/{ident}" if ident.startswith("10.") else f"https://arxiv.org/abs/{ident}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
