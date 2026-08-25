#!/usr/bin/env bash
# =============================================================================
#  ResearchAI — Local Launcher
#  Double-click this file in Finder to start the assistant in your browser.
#  Press Ctrl+C in the Terminal window that opens to stop the server.
# =============================================================================

set -euo pipefail

# ── Resolve the project root (the folder containing this script) ──────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Configuration ─────────────────────────────────────────────────────────────
PORT="${PORT:-8000}"
HOST="0.0.0.0"
URL="http://127.0.0.1:${PORT}/ui"
CONDA_ENV="ai_research_assistant"
# Try to find the conda python path dynamically
if command -v conda >/dev/null 2>&1; then
    PYTHON=$(conda info --base)/envs/${CONDA_ENV}/bin/python
else
    # Fallback to a common Mac path if conda is not in PATH
    PYTHON="${HOME}/anaconda3/envs/${CONDA_ENV}/bin/python"
    [[ ! -x "$PYTHON" ]] && PYTHON="/opt/anaconda3/envs/${CONDA_ENV}/bin/python"
    [[ ! -x "$PYTHON" ]] && PYTHON="/usr/local/anaconda3/envs/${CONDA_ENV}/bin/python"
    [[ ! -x "$PYTHON" ]] && PYTHON="${HOME}/opt/miniconda3/envs/${CONDA_ENV}/bin/python"
    [[ ! -x "$PYTHON" ]] && PYTHON="${HOME}/miniconda3/envs/${CONDA_ENV}/bin/python"
fi
PID_FILE="/tmp/research_assistant_${PORT}.pid"
LOG_FILE="${SCRIPT_DIR}/server.log"

# Colour helpers
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       🔬  My AI Research Assistant — Local Launcher       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check Python ──────────────────────────────────────────────────────────────
if [[ ! -x "$PYTHON" ]]; then
    echo -e "${RED}✗ Python not found at: $PYTHON${NC}"
    echo "  Please verify that the '${CONDA_ENV}' conda environment exists."
    echo "  Press Enter to close this window."
    read -r
    exit 1
fi

# ── Kill any stale server on this port ───────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo -e "${YELLOW}⚠  Stopping previous server instance (PID $OLD_PID)…${NC}"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Also free the port if anything else is holding it
EXISTING_PID=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [[ -n "$EXISTING_PID" ]]; then
    echo -e "${YELLOW}⚠  Port $PORT already in use (PID $EXISTING_PID). Releasing…${NC}"
    kill "$EXISTING_PID" 2>/dev/null || true
    sleep 1
fi

# ── Graceful shutdown on exit ─────────────────────────────────────────────────
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down Research Assistant…${NC}"
    if [[ -f "$PID_FILE" ]]; then
        SERVER_PID=$(cat "$PID_FILE")
        if kill -0 "$SERVER_PID" 2>/dev/null; then
            kill "$SERVER_PID"
            echo -e "${GREEN}✓ Server stopped (PID $SERVER_PID).${NC}"
        fi
        rm -f "$PID_FILE"
    fi
    echo ""
    echo "Press Enter to close this window."
    read -r
}
trap cleanup EXIT INT TERM

# ── Start the FastAPI server ──────────────────────────────────────────────────
echo -e "${CYAN}▶  Starting server on port ${PORT}…${NC}"
echo "   Logs → ${LOG_FILE}"
echo ""

# Run from the repo root so all relative paths (library/, projects/, etc.) resolve correctly
PYTHONPATH="$SCRIPT_DIR" \
"$PYTHON" -m uvicorn server_module.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info \
    > "$LOG_FILE" 2>&1 &

SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo -e "   Server PID: ${SERVER_PID}"

# ── Wait for the server to become ready (health check) ───────────────────────
echo ""
echo -n "   Waiting for server to be ready"
MAX_WAIT=300   # seconds (increased for model loading)
ELAPSED=0
READY=false

while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    # Check the process is still alive
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        echo -e "${RED}✗ Server process died unexpectedly. Check ${LOG_FILE} for details.${NC}"
        cat "$LOG_FILE" | tail -20
        echo ""
        echo "Press Enter to close."
        read -r
        exit 1
    fi

    # Try the health endpoint
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        "http://${HOST}:${PORT}/health" \
        --connect-timeout 1 \
        --max-time 2 2>/dev/null || echo "000")

    if [[ "$HTTP_STATUS" == "200" ]]; then
        READY=true
        break
    fi

    echo -n "."
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

echo ""

if [[ "$READY" == false ]]; then
    echo -e "${RED}✗ Server did not become ready within ${MAX_WAIT}s.${NC}"
    echo "   Check ${LOG_FILE} for errors:"
    tail -20 "$LOG_FILE"
    echo ""
    echo "Press Enter to close."
    read -r
    exit 1
fi

echo -e "${GREEN}✓ Server is ready!${NC}"
echo ""
echo -e "   🌐  Opening: ${CYAN}${URL}${NC}"
echo ""
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Press ${YELLOW}Ctrl+C${NC} here (or close this window) to stop the server."
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Open browser
open "$URL"

# ── Keep running, tailing the log so the user can see live output ─────────────
tail -f "$LOG_FILE" &
TAIL_PID=$!

# Wait for server process (blocks until Ctrl+C)
wait "$SERVER_PID" 2>/dev/null || true
kill "$TAIL_PID" 2>/dev/null || true
