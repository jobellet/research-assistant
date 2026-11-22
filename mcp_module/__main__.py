"""Run: python -m mcp_module [--mode discovery|library] [--port 8765] [--tunnel]

Prints the URL to paste into Gemini (Settings > Connectors > Custom). With --tunnel it starts a
free Cloudflare quick tunnel (needs `cloudflared`) and prints the public https URL.
The secret is read from MCP_SECRET in .env, or generated and stored in mcp_secret.txt (git-ignored).
"""
import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import config
from mcp_module.server import create_app


def get_secret() -> str:
    if os.environ.get("MCP_SECRET"):
        return os.environ["MCP_SECRET"]
    f = Path(config.DATA_DIR) / "mcp_secret.txt"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(32))
        f.chmod(0o600)
    return f.read_text().strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["discovery", "library"], default="discovery")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--tunnel", action="store_true", help="open a Cloudflare quick tunnel and print the public URL")
    a = ap.parse_args()
    secret = get_secret()
    app = create_app(secret, a.mode, config.LIBRARY_DIR)
    path = f"/mcp/{secret}"
    print(f"MCP server, mode '{a.mode}', local: http://127.0.0.1:{a.port}{path}", flush=True)
    if a.mode == "library":
        print("WARNING: library mode shares titles, authors and abstracts of your private library with "
              "whoever holds the URL and with the assistant. Stop it when you are done.", flush=True)
    if a.tunnel:
        def run_tunnel():
            p = subprocess.Popen([shutil.which("cloudflared") or str(Path.home() / "bin" / "cloudflared"), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{a.port}"],
                                 stderr=subprocess.PIPE, text=True)
            for line in p.stderr:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    print(f"\nPaste this URL into Gemini (Connectors > Custom):\n  {m.group(0)}{path}\n", flush=True)
        threading.Thread(target=run_tunnel, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
