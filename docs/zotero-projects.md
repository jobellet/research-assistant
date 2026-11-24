# Project references from Zotero, and checking a claim against its sources

Each project can have its **own list of papers**. The simplest way to fill it is to
link a **Zotero collection** (a folder in Zotero): its papers become the project's
references, and every paper you add to that folder later is added to the project
too. The library, the semantic search and the knowledge graph can then show
**only the project's papers**, and when you highlight a sentence of your draft the
app shows **the sentences of those papers that match it**, with their page numbers.

Everything stays on your computer: the PDFs are copied into your private `library/`
folder, the project's list is stored in `projects/<project>/project.json`, and both
are git-ignored, so you can use the public code with your private papers.

## What you need

- Zotero installed, with your papers' PDFs attached (Zotero's normal "storage"
  attachments, or linked files with an absolute path).
- The research-assistant server running (`./launch.command`, see the
  [tutorial](../tutorial.md)).

The app finds Zotero's data folder by itself (`~/Zotero` on macOS, Windows and
Linux, or `~/Documents/Zotero`). If yours is elsewhere, set `ZOTERO_DATA_DIR` in
`.env` to the folder that contains `zotero.sqlite`. Zotero can stay open: the app
reads a copy of its database and **never writes to Zotero**.

## 1. Link a Zotero collection to a project

1. Choose (or create, with **＋**) the project in the left sidebar.
2. Under **REFERENCES**, click **Link Zotero collection…**.
3. Choose the collection. Tick **include subcollections** if the papers are in
   subfolders.
4. Click **Link and sync**.

The sync runs in the background and the sidebar shows its progress. For each
paper of the collection it:

- copies the PDF into the library (a paper already there is not copied twice);
- writes its metadata from Zotero (title, authors, year, journal, DOI, abstract,
  tags). Metadata the library already had is kept, and Zotero only fills the gaps;
- adds it to the library's search index;
- splits the PDF into sentences and computes an embedding for each one (see
  [below](#how-the-sentence-search-works));
- adds a BibTeX entry to the project's `references.bib`.

Papers without a PDF in Zotero are listed in the sidebar ("without PDF"). Attach
the PDF in Zotero and sync again.

**Indexing time.** Indexing the sentences takes about 1 to 5 minutes per paper on a
laptop processor, once per paper. Until a paper is indexed, its matches are
word matches only (marked "word match").

## 2. Add more references later

Add the paper to the Zotero collection. The project picks it up:

- when you open the project,
- every 5 minutes while the page is open,
- or right away with the **⟳** button next to REFERENCES.

A paper removed from the Zotero collection leaves the project. It stays in the
library and in `references.bib`.

Papers that are not in Zotero can be added by hand: **Cite** on any library
paper adds it to the active project's references.

## 3. Work on the project's papers only

When the project has papers, the **Library** tab shows two buttons:

- **This project (N)**: the list, the Semantic and Word Frequency searches, the
  **Matches** panel and the **Knowledge Graph** use only the project's papers;
- **Whole library**: everything, as before.

The graph of a project is computed on its papers only, and kept until the list of
papers changes.

## 4. Check a sentence of your manuscript against its references

1. Put the manuscript in the draft: **⇪ Import .docx…** in the sidebar replaces
   the draft with the text of a Word file (paragraphs, including the numbered
   reference list). You can also paste the text, or write LaTeX.
2. **Highlight** a sentence, or the part of it before a citation.
3. The **Matches** tab shows, under **In this project's references**, the best
   sentences of each paper, with the sentence before and after it, a similarity
   score, and buttons to open the **PDF at that page**, copy the sentence, or copy
   its `\cite{}` command. Below them, the papers that match as a whole.

**Citation markers are understood.** If the selection contains citations, the
app knows which paper each part of the sentence cites and checks each part
on its own:

| Draft style | Example | How the paper is found |
|---|---|---|
| Numbered (Word, Cell, Nature…) | `…feature beta,13 and…` or `[13]` | the draft's numbered reference list, matched to the project's papers by DOI, then title |
| LaTeX | `\cite{smith1985tidal}` | the BibTeX key of the project's papers |
| Author–year | `(Smith et al., 1985)` | first author's surname and year |

For example, in *"Area X, with feature alpha,12 feature beta,13 and feature
gamma,4,15 …"*, the three parts are checked
separately, and the cited paper is shown first for each part, with a **cited**
badge. A reference that is not among the project's papers is named
("Reference 4 is not among this project's papers: …").

**Similar does not mean supporting.** The embeddings find sentences on the same
topic. A sentence can match a claim closely and still say the opposite, for
example *"Area X is densely covered"* for a claim of *"sparse coverage of
Area X"*. Read the matched sentences.

**Check with AI (optional).** If an AI provider is set up in **⚙ Settings**, the
**Check with AI** button asks it whether each shown sentence *supports*,
*partly supports*, *contradicts* or is *unrelated to* the claim, with a
one-line reason. This sends the claim and the shown sentences (not the PDFs) to
that provider; nothing is sent unless you click the button.

## 5. Audit all citations of the draft

`POST /api/projects/<project>/citation-audit` (or the MCP tool `audit_citations`)
goes through the whole draft in the background (a few minutes) and saves a report in
`projects/<project>/citation_audit.json`:

- for every sentence that cites something, and every cited part of it, the best
  sentences of each cited paper with their page numbers;
- references that are not among the project's papers (not checkable: add them to
  the Zotero collection with their PDF), citation numbers without a reference
  entry, and references never cited;
- every DOI of the numbered reference list looked up in Crossref: unknown DOIs,
  and DOIs whose Crossref record has another title, first author or year. A DOI
  that differs from the one in your library is flagged too;
- parts where another project paper matches the claim better than the cited one;
- uncited sentences that closely match a project paper (possible missing citations;
  many are false alarms, for example in Methods).

The audit collects evidence; it does not decide. An assistant connected through MCP
(Gemini, Claude…) can read the report and judge each citation: supported,
inaccurate (the paper says something different) or unsupported. The DOI check sends
the DOIs of your reference list to Crossref; nothing else leaves your computer.

## How the sentence search works

- Each PDF is read page by page. Running headers and footers, download stamps,
  figure axis text and the reference list are removed, and the text is split into
  sentences (abbreviations such as *et al.* or *Fig.* do not end a sentence).
- Every sentence is embedded with the library's model (EmbeddingGemma) at its
  full 768 dimensions with its retrieval prompts. This is finer than the
  256-dimension paper-level embeddings used by the library search. The vectors are
  saved next to the paper (`library/<id>/passages.json` and `passages.npy`), so
  a paper used by several projects is indexed once.
- The highlighted text is cleaned of its citation markers and embedded as a
  search query. Each sentence gets its cosine similarity, plus a small bonus
  for distinctive words and numbers it shares with the claim. For a cited part,
  the part counts for 65% and the whole sentence for 35%.

## Use it in Google Docs

The Chrome extension ([docs/browser-extension.md](browser-extension.md)) does the same
checks from a Google Doc: select a claim, press Alt+Shift+K, and the side panel shows the
matching sentences; or audit all citations of the Doc.

## Use it from Gemini or another MCP client

In `full` mode the MCP server ([docs/mcp.md](mcp.md)) has three more tools:
`project_references` (a project's papers), `check_claim` (the matching sentences of
a project's papers for a claim, cited paper first; the assistant then judges
whether they support it) and `sync_project_zotero`.

## Where things are stored

| What | Where | In git? |
|---|---|---|
| The project's list of papers, Zotero link, sync state | `projects/<project>/project.json` | no (ignored) |
| The project's graph | `projects/<project>/graph_cache.json` | no (ignored) |
| PDFs, metadata, sentence index | `library/<sha256>/` | no (ignored) |
| BibTeX entries | `projects/<project>/references.bib` | no (ignored, except the `default` template) |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Zotero library not found" | set `ZOTERO_DATA_DIR` in `.env` to the folder with `zotero.sqlite`, then restart the server |
| A paper is listed "without PDF" | attach the PDF in Zotero (a linked URL or a snapshot is not a PDF) and press ⟳ |
| Linked-file attachments with a relative path ("attachments:…") are not found | set `ZOTERO_BASE_DIR` to Zotero's *Linked Attachment Base Directory* |
| Matches are marked "word match" | the paper's sentences are still being indexed (see the sidebar) |
| A new Zotero item does not appear | press ⟳; Zotero writes its database a few seconds after a change |
