#!/bin/bash
#SBATCH -p cpu-small
#SBATCH -J research_server
#SBATCH -o slurm_logs/research_server_%j.out
#SBATCH -e slurm_logs/research_server_%j.err
#SBATCH --mem=8G
#SBATCH --cpus-per-task=1
#SBATCH --time=5-00:00:00

# Load environment
REPO_DIR="/gpfs01/siegel/user/jbellet/my-ai-research-assistant"
PYTHON_EXE="/gpfs01/siegel/user/jbellet/envs/ai_research_env/bin/python3"
export PYTHONPATH="$REPO_DIR:$PYTHONPATH"

echo "$(date): Starting My AI Research Assistant Server..."
cd "$REPO_DIR"

# Run the server
$PYTHON_EXE server_module/main.py
