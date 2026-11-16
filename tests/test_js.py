"""Run the browser-side unit tests (node:test) when Node is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_frontend_js_units():
    files = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
    proc = subprocess.run(["node", "--test", *files], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
