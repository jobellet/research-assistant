# Tutorial: your own private MCP server for Gemini

Goal: from a Gemini chat, ask "find recent papers on X" (and optionally "what do I have in my library on X?")
and have Gemini call **your** research assistant. Everything runs on your own computer; you need no server,
no hosting and no Cloudflare account.

- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [1. Install `cloudflared`](#1-install-cloudflared)
- [2. Start the server](#2-start-the-server)
- [3. Connect Gemini](#3-connect-gemini)
- [4. Try it](#4-try-it)
- [5. Share your library (optional)](#5-share-your-library-optional)
- [Stop, restart, and what changes each time](#stop-restart-and-what-changes-each-time)
- [Full mode: your whole research assistant in Gemini](#full-mode-your-whole-research-assistant-in-gemini)
- [Privacy and safety](#privacy-and-safety)
- [Troubleshooting](#troubleshooting)
- [Options: permanent address, other clients](#options-permanent-address-other-clients)

## How it works

```
Gemini (Google) ──https──> Cloudflare relay ──tunnel──> cloudflared ──> mcp_module (your computer)
```

- `mcp_module` is a small program that speaks the **Model Context Protocol (MCP)**. It offers a few tools to an assistant.
- Gemini can only reach a public `https://` address, so `cloudflared` opens an outgoing connection from your computer to
  Cloudflare and Cloudflare forwards requests to it. Cloudflare is only a relay: **your code runs on your computer**, not on
  Cloudflare or GitHub.
- A Cloudflare *quick tunnel* is free and needs **no account and no login**. It is meant for testing: the address
  changes at each start and there is no uptime guarantee. Cloudflare's servers see the traffic that passes through.
- The server is separate from the web page, so the public address exposes **only** the tools below, never your editor,
  PDFs, full texts or settings.

| Mode | Tools | What leaves your computer |
|---|---|---|
| `discovery` (default) | `discover_papers` (OpenAlex, arXiv, Crossref, Semantic Scholar) | nothing private: it only queries public databases |
| `library` | adds `search_library`, `get_paper`, `cite`, `check_in_library` | titles, authors, abstracts, keywords and BibTeX of the papers the assistant asks for. No PDFs, no full text |
| `full` | adds the tools of the web app: semantic search, similar papers, full texts, adding papers, projects (see [all tools](#all-tools-full-mode)) | abstracts **and full texts** of the papers it asks for. It can also add papers and write to your projects (never delete) |

## What you need

- this project installed (see the [README](../README.md)), with its Python environment active;
- a **personal Google account** with Gemini on the web. The *Custom* connector is a recent Gemini feature: Google's
  help page ([Connect & manage custom apps](https://support.google.com/gemini/answer/17209137)) lists conditions
  (personal account, English, Gemini history on, and a supported country), which may change. If the **Custom** button is
  missing under Connectors, the feature is not available for your account yet;
- for `library` mode: papers in your library (`library/`, which stays private: it is git-ignored).

## 1. Install `cloudflared`

| System | Command |
|---|---|
| macOS (Homebrew) | `brew install cloudflared` |
| macOS without Homebrew, or Homebrew too slow (Intel Macs may build from source) | download `cloudflared-darwin-amd64.tgz` (Intel) or `cloudflared-darwin-arm64.tgz` (Apple Silicon) from the [releases page](https://github.com/cloudflare/cloudflared/releases/latest), unpack it and put `cloudflared` in `~/bin` (the tutorial's command finds it there) |
| Windows | `winget install --id Cloudflare.cloudflared` |
| Linux | install from your package manager or download the binary from the releases page |

Check it: `cloudflared --version`.

## 2. Start the server

From the project folder:

```bash
python -m mcp_module --tunnel
```

After a few seconds it prints:

```
MCP server, mode 'discovery', local: http://127.0.0.1:8765/mcp/<secret>

Paste this URL into Gemini (Connectors > Custom):
  https://<random-words>.trycloudflare.com/mcp/<secret>
```

Copy the second address (the whole line, including `/mcp/…`). Leave the terminal open: closing it stops the server.

The `<secret>` is a long random string created the first time and kept in `mcp_secret.txt` (git-ignored; or set
`MCP_SECRET` in `.env`). **Anyone who has the full address can use the tools**, so do not share it or paste it in public.
To change it, delete `mcp_secret.txt` and restart.

## 3. Connect Gemini

1. Open [gemini.google.com](https://gemini.google.com) in a browser (connecting is not possible from the phone app, but the
   connected tools then also work in the phone app).
2. Open **Connectors** (Settings & help, or `gemini.google.com/customize/connectors`) and click **+ Custom**.
3. In **Connect to an MCP server**, paste the address (it must start with `https://`) and click **Next**. Leave the
   advanced settings empty: the server needs no login, the secret in the address is the protection.
4. Gemini reads the server and shows **Save your custom app**, with the name *Research Assistant* and the available actions
   (`discover_papers`; in library mode also `search_library`, `get_paper`, `cite`). Click **Connect**.

[Developer Mode](https://gemini.google.com/devmode) shows the calls Gemini makes (event log, tool schemas) and is useful to
debug.

## 4. Try it

In a new Gemini chat:

> Use Research Assistant to find recent papers on neural correlates of consciousness in large language models.

Gemini should call `discover_papers` and answer with titles, authors, years and abstracts. If it answers without the tool,
name it: "Use the discover_papers tool of Research Assistant ...". The tools are read-only: they never download
or change anything on your computer. Gemini also asks for confirmation before any tool that writes (none does here).

## 5. Share your library (optional)

Library mode lets Gemini search the papers **you** collected:

```bash
python -m mcp_module --mode library --tunnel
```

Then ask, for example: "Using Research Assistant, which papers in my library discuss global workspace theory? Give me the
BibTeX of the first one." Re-add the connector if the actions list does not show the three library tools (remove the
custom app, then add the new address).

What Gemini receives is only what it asks for: titles, authors, year, journal, DOI, abstract, keywords, and BibTeX. It never
receives PDFs or full texts. Still, it is your private collection: use library mode only when you need it and stop it
afterwards.

## Full mode: your whole research assistant in Gemini

Full mode connects Gemini to the local web app, so it can do what the web page does. Two programs run on your computer:
the app (it holds the embedding model and the database) and the MCP server, which is the only one exposed through the tunnel
and talks to the app with your `AUTH_TOKEN` (the token never goes to Gemini).

```bash
./launch.command                                  # terminal 1: the web app (or your usual way to start it)
python -m mcp_module --mode full --tunnel         # terminal 2: prints the address for Gemini
```

Then, in Gemini (Connectors → + Custom, address as above; remove an older Research Assistant first), try:

> I give you this paper: https://arxiv.org/abs/2308.08708. Is it already in my library? If not, add it.
> (a minute later) Which papers in my library are the most similar to it? Which ones argue against its position?
> Add the three most relevant to the project "review" and append a short paragraph to the draft.

How "contradict" works: the server finds the semantically closest papers (`similar_papers`, `semantic_search`) and gives
Gemini their abstracts and full texts (`get_paper`, `read_paper_text`); Gemini does the reading and the judgement.

Notes:
- To hand Gemini an article, give a **DOI, an arXiv id or link, or the title**. A PDF attached to the chat is not
  transmitted to the tools. `add_to_library` downloads the *open-access* PDF; if there is none it says so, and you can drop the
  PDF in `inbox/` yourself.
- Indexing a new paper takes about a minute: Gemini can poll `processing_status`.
- Gemini asks for confirmation before tools that write (`add_to_library`, `add_citation`, `create_project`,
  `append_to_draft`). `append_to_draft` only appends; no tool deletes or overwrites anything.

### All tools (full mode)

| Tool | What it does | Writes? |
|---|---|---|
| `discover_papers` | search OpenAlex, arXiv, Crossref, Semantic Scholar | no |
| `check_in_library` | is this paper (DOI / arXiv / title / abstract) in the library? plus the closest ones by meaning | no |
| `add_to_library` | download an open-access paper by arXiv id / URL / DOI and process it | **adds a PDF** |
| `processing_status` | state of the background processing | no |
| `search_library` | word search in titles, authors, abstracts, keywords | no |
| `semantic_search` | search by meaning, with year / author / journal filters | no |
| `similar_papers` | the papers most similar to one library paper | no |
| `get_paper`, `cite` | metadata and abstract; BibTeX | no |
| `read_paper_text` | extracted full text, in chunks | no |
| `related_online` | papers outside the library related to a library paper | no |
| `literature_for_text` | literature relevant to a manuscript passage | no |
| `graph_neighbors` | 50 nearest neighbours by word usage | no |
| `audit_claims` | check manuscript claims against an analysis text | no |
| `library_stats` | size and processing state of the library | no |
| `list_projects`, `get_draft`, `get_bib` | your projects | no |
| `add_citation` | add a library paper to a project's BibTeX | **edits `references.bib`** |
| `create_project` | create a project | **adds a folder** |
| `append_to_draft` | append LaTeX to the end of a draft | **edits `draft.tex`** |
| `project_references` | a project's papers (Zotero collection and papers added by hand) | no |
| `check_claim` | the sentences of a project's papers that match a claim, cited paper first ([details](zotero-projects.md)) | no |
| `sync_project_zotero` | update a project's papers from its Zotero collection | **copies PDFs into the library, edits `references.bib`** |

## Stop, restart, and what changes each time

- **Stop**: `Ctrl-C` in the terminal. The tunnel and the address disappear immediately.
- **Restart**: the `trycloudflare.com` part of the address is new each time, the secret is the same. In Gemini, remove the
  custom app and add the new address (or edit it).
- The server only works while your computer is on, awake and online.

## Privacy and safety

- Public address + secret: anyone holding the complete address can query the tools. Keep it private, stop the server when
  you are done, delete `mcp_secret.txt` to revoke the old address.
- Google's warnings apply: Gemini sends information from your chat to the server, and the server is not reviewed by Google.
- Cloudflare relays the traffic and can technically see it.
- Results from the web are data. A paper abstract could contain text trying to give instructions to the assistant. The server
  says so in its `instructions`, but treat the assistant's actions accordingly.
- Limits: 60 tool calls per minute, requests above 100 KB are refused, a wrong path answers a bare 404, and no tool writes or
  downloads anything.
- **Full mode** gives whoever holds the address the same power as the assistant: reading your library's full texts and
  adding papers or editing your projects (no deletion). Use it only while you work with the assistant, and stop it afterwards.
  If the address leaks, stop the server and delete `mcp_secret.txt`.
- Never commit `mcp_secret.txt` or `.env` (both are in `.gitignore`).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| No **Custom** button | not available for your account or country yet (see the conditions above) |
| "Make sure that your URL starts with https://" | you pasted the local `http://127.0.0.1…` address; use the `trycloudflare.com` one |
| Gemini cannot read the server | the terminal was closed, the computer went to sleep, or the tunnel address changed: restart and re-add |
| `cloudflared: command not found` | install it (step 1) and open a new terminal, or put it in `~/bin` |
| The tunnel prints no address | check your internet connection, and try again in a minute: quick tunnels can be rate limited |
| Gemini does not use the tool | name the app and the tool in your request |
| "Rate limit reached" | more than 60 calls in a minute; wait |
| Library tools missing | start with `--mode library` (or `full`) and re-add the custom app |
| "the research-assistant app is not reachable" (full mode) | start the web app first; if it is not on port 8000, use `--app-url http://127.0.0.1:PORT`; `AUTH_TOKEN` must be set in `.env` |

You can test the server without Gemini:

```bash
curl -s -X POST "<your full address>" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Options: permanent address, other clients

- **Other MCP clients** (Claude, editors, scripts) accept the same address. For a client on the same computer skip the
  tunnel: `python -m mcp_module` prints `http://127.0.0.1:8765/mcp/<secret>`.
- **A fixed address**: a named Cloudflare tunnel (free Cloudflare account and a domain you own) gives a permanent
  `https://mcp.your-domain.org`; see Cloudflare's *Tunnel* documentation, and point it to `http://127.0.0.1:8765`.
  The computer still has to be on.
- **Another port**: `python -m mcp_module --port 9000`.
