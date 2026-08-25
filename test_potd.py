import sys
import json
from pathlib import Path
from scripts.daily_citation_updater import fetch_cited_by_for_doi

doi = "10.1038/nature14402"
print("Fetching for", doi)
res = fetch_cited_by_for_doi(doi)
print("Found:", len(res))
