#!/bin/bash
#SBATCH -p cpu-small
#SBATCH -J research_tunnel
#SBATCH -o slurm_logs/res_tunnel_%j.out
#SBATCH -e slurm_logs/res_tunnel_%j.err
#SBATCH --mem=4G
#SBATCH --time=5-00:00:00

# Setup environment for python notification
export PATH="$HOME/envs/assistant_env/bin:$PATH"
export PYTHONPATH="$HOME/assistant:$PYTHONPATH"
NOTIFY_SCRIPT="$HOME/assistant/notify_slack.py"
REPO_DIR="$HOME/my-ai-research-assistant"

echo "Starting dynamic localhost.run tunnel for Research Assistant (Port 8001)..."

# Wait for the research server to be ready
echo "Waiting for research server on port 8001..."
MAX_RETRIES=30
COUNT=0
while ! nc -z 127.0.0.1 8001; do
    sleep 2
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo "Timed out waiting for research server."
        python "$NOTIFY_SCRIPT" "❌ *Research Assistant Tunnel Failure*: Server on port 8001 never started."
        exit 1
    fi
done
echo "Research server is UP!"

# Run localhost.run ssh tunnel and capture the URL
# Use 127.0.0.1 to avoid localhost resolution issues
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -R 80:127.0.0.1:8001 nokey@localhost.run > slurm_logs/lhr_url_$SLURM_JOB_ID.log 2>&1 &
TUNNEL_PID=$!

# Wait for the tunnel to initialize and show the URL
sleep 15

# Extract the dynamic URL
PUBLIC_URL=$(grep -oE "https://[a-zA-Z0-9.-]+\.lhr\.life" slurm_logs/lhr_url_$SLURM_JOB_ID.log | head -n 1)

if [ -n "$PUBLIC_URL" ]; then
    echo "Research Assistant Tunnel: $PUBLIC_URL"
    python "$NOTIFY_SCRIPT" "🔬 *Research Assistant Online*: $PUBLIC_URL/ui (Login: joachim)"

    # Update SERVER_ACCESS.md
    cat << EOL > "$REPO_DIR/SERVER_ACCESS.md"
# 🚀 Research Assistant Access Details
**Last Started:** $(date '+%Y-%m-%d %H:%M:%S')

- **Public URL:** $PUBLIC_URL
- **Access Password:** \`vibe-coding-secret\`
- **Direct Login Link:** [$PUBLIC_URL/ui?token=vibe-coding-secret]($PUBLIC_URL/ui?token=vibe-coding-secret)

### 📎 Multi-File Support Enabled
The system is configured to group supplements and main papers by DOI. You can choose which file to open directly from the search result card.

---
*This file is updated automatically every time the tunnel restarts.*
EOL
else
    echo "Failed to retrieve public URL from localhost.run."
    python "$NOTIFY_SCRIPT" "❌ *Research Assistant Tunnel Failure*: Could not retrieve public URL from localhost.run."
fi

# Keep the script alive
while kill -0 $TUNNEL_PID 2>/dev/null; do
    sleep 60
done
