"""Literature discovery: search arXiv / Semantic Scholar / OpenAlex / Crossref,
find papers related to the library, and download open-access PDFs into the inbox."""

from discovery_module.sources import (  # noqa: F401
    arxiv_lookup,
    arxiv_search,
    crossref_search,
    openalex_lookup,
    openalex_related,
    openalex_search,
    semantic_scholar_recommendations,
    semantic_scholar_search,
)
from discovery_module.discover import (  # noqa: F401
    download_to_inbox,
    library_index,
    related_to_paper,
    related_to_text,
    search_literature,
)
