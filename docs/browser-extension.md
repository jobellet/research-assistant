# Chrome extension: check citations in Google Docs

The extension in [`browser_extension/`](../browser_extension) adds a side panel to Chrome
(or Edge, Brave, any Chromium browser). In a Google Doc, or any web page, you select a
claim and the panel shows the sentences of your project's papers that match it, with
the cited paper first. It can also audit every citation and DOI of a whole Google Doc.

It talks only to **your own research-assistant server on this computer**
(`http://127.0.0.1:8000` by default): your papers, the document's text and your
password go nowhere else (the password is sent in a request header, never in a URL;
the optional AI check and the DOI check are described below). The server must be running (`./launch.command`), and
the project needs papers (see [Zotero projects](zotero-projects.md)).

## Install (once)

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose the `browser_extension` folder of this repository.
4. Pin the extension: puzzle-piece icon, then the pin next to *Research Assistant*.
5. Click its icon: the side panel opens. In ⚙ Settings enter your server password
   (`SERVER_PASSWORD` in `.env`) and click **Save and connect**.

After a `git pull` that changes the extension, click the ↻ button of the extension
in `chrome://extensions`, then reload the Google Docs tab.

## Check a claim

1. Choose the **project** at the top of the panel. The project is remembered for
   each Google Doc.
2. In the document, **select** the sentence (or the part before a citation).
3. Press <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>K</kbd>, or click **Check selection** in the panel.
   On other web pages (a journal article, a preprint), use the shortcut or right-click the
   selection and choose **Check this claim in my references**: Chrome lets an extension
   read such a page only right after one of these two actions.

The panel shows, for each cited part of the sentence, the best sentences of the cited
paper (with a **cited** badge), the page number (**PDF p. N** opens the PDF at that
page) and the best sentences of up to three other papers of the project. Citation
markers are read as in the app (`,12`, `[12]`, `\cite{key}`, `(Smith, 2001)`). In a
Google Doc, the document's own numbered reference list tells which paper each number
is (typed numbers `12. Author…` and Docs' automatic numbered lists both work).

**Check with AI** (shown when an AI provider is set up in the app) asks that provider
whether each sentence supports, partly supports, contradicts or is unrelated to the claim.

If the selection cannot be read, copy it (<kbd>⌘C</kbd> / <kbd>Ctrl+C</kbd>) and click
**Check copied text**, or paste it under *Type or paste a claim*. The clipboard is read
only when you click **Check copied text**.

**PDF p. N** downloads the PDF from your server and opens it at that page.

## Audit a whole Google Doc

Open the Doc and click **Audit all citations of this Doc**. The panel reads the
document's text and the server checks every citing sentence and every DOI of the
reference list (in Crossref), as described in
[Zotero projects § 5](zotero-projects.md#5-audit-all-citations-of-the-draft). This
takes a few minutes; one audit per project runs at a time. The result lists DOI problems, references that are not in the
project, references never cited, the evidence for each citation and possibly
missing citations. The report is also saved in the project (`citation_audit.json`).

## How it works, and what it can access

- Google Docs draws its text on a canvas, so the selection is not visible to web
  extensions. When you ask for a check, the extension tells the Docs editor to *copy*
  the selection and reads the text from that copy event. As with <kbd>Ctrl+C</kbd>, the
  selection is also left in your clipboard.
- For the document's text, the extension asks the Docs page to fetch the Doc's simple
  HTML version (`/mobilebasic`, with your own Google session) and converts it to text
  in the panel. It only does this when you check a claim or start an audit in that Doc,
  and it uses the Google account the Doc is open in (`/u/1/` links included).
- Permissions: `sidePanel`, `storage` (server address and password, kept in this
  browser only), `scripting` and `activeTab` (read the selection of the tab you are
  using), `contextMenus`, `clipboardWrite` (to ask Google Docs to copy the selection),
  `clipboardRead` (only for *Check copied text*), and access
  to `docs.google.com`, `127.0.0.1` and `localhost`. The extension rejects any server
  that is not on this computer.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Cannot reach the research-assistant server" | start the server (`./launch.command`); check the address in ⚙ Settings |
| "Wrong or missing password" | enter `SERVER_PASSWORD` from `.env` in ⚙ Settings |
| "has no papers yet" | link a Zotero collection to the project in the app (REFERENCES) |
| Numbers like `,12` are not linked to papers | the Doc needs a numbered reference list (`12. Author… https://doi.org/…`) after a *References* heading |
| The shortcut does nothing | set or change it in `chrome://extensions/shortcuts` |
| Google Docs did not hand over the selection | copy it (⌘C / Ctrl+C) and click **Check copied text** |
