"""Tiny HTTP client for the local research-assistant web app (the MCP server never exposes the app itself)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


class AppError(Exception):
    pass


class AppClient:
    def __init__(self, base_url: str, token: str, timeout: float = 120):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[Dict] = None, params: Optional[Dict] = None) -> Any:
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"X-Auth-Token": self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode()).get("detail", "")
            except Exception:
                detail = ""
            raise AppError(f"the app answered {e.code}: {detail}".strip())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise AppError("the research-assistant app is not reachable: start it (launch.command) "
                           f"and check the address and AUTH_TOKEN ({getattr(e, 'reason', e)})")

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body):
        return self.request("POST", path, body)

    def put(self, path, body):
        return self.request("PUT", path, body)
