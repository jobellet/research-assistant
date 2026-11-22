# Use your research assistant from Gemini (or any MCP client)

`mcp_module` is a small server that speaks the **Model Context Protocol (MCP)**. An assistant such as
Gemini can then search the literature, and (optionally) your own library, while you chat.

It is a separate program from the web page: a public link exposes **only** these tools, never the
editor, your PDFs, full texts or settings.

| Mode | Tools | What leaves your computer |
|---|---|---|
| `discovery` (default) | `discover_papers` (OpenAlex, arXiv, Crossref, Semantic Scholar) | nothing private: it only queries public databases |
| `library` | adds `search_library`, `get_paper`, `cite` | titles, authors, abstracts, keywords and BibTeX of the papers the assistant asks for. No PDFs, no full text |

## Start

```bash
python -m mcp_module --tunnel                 # discovery only
python -m mcp_module --mode library --tunnel  # also your library
```

`--tunnel` opens a free [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
(install the `cloudflared` program first; no account needed) and prints an `https://….trycloudflare.com/mcp/<secret>` address.
The tunnel and the address exist only while the command runs; the address changes at each start,
the secret does not.

The secret is a long random string stored in `mcp_secret.txt` (git-ignored) or set with `MCP_SECRET` in
`.env`. Anyone who has the whole address can use the tools, so do not share it. To change it, delete the file.

## Connect Gemini

Gemini web (not the phone app), signed in with a **personal** Google account (not a work or school account):
**Settings → Connected apps → Custom → paste the address → Next**. The Gemini page may require
an account in a supported country; if the Custom button is missing, the feature is not available for you.
Once added, the tools also work in the Gemini phone app.

Google's warnings apply: Gemini sends information from your chat to the server, and the server is not reviewed by Google.
`gemini.google.com/devmode` lets you watch the calls (event log, tool schemas).

## Other MCP clients

Any client that supports a remote (streamable HTTP) server takes the same address. For a local client you can skip
the tunnel: `python -m mcp_module` prints `http://127.0.0.1:8765/mcp/<secret>`.

## Safety notes

- Read-only: no tool writes, deletes or downloads anything on your computer.
- Results from the web are data. A paper abstract could contain text that tries to give the assistant instructions;
  the server says so in its `instructions`, but treat the assistant's actions accordingly.
- At most 60 tool calls per minute; requests above 100 KB are refused; wrong paths answer a bare 404.
- Stop the server (Ctrl-C) when you are done, especially in `library` mode.
