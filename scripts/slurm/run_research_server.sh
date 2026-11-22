#!/bin/bash
#SBATCH -p cpu-small
#SBATCH -J research_server
#SBATCH -o slurm_logs/research_server_%j.out
#SBATCH -e slurm_logs/research_server_%j.err
#SBATCH --mem=8G
#SBATCH --cpus-per-task=1
#SBATCH --time=5-00:00:00

# Load environment
REPO_DIR="${REPO_DIR:-$HOME/research-assistant}"   # set REPO_DIR to your clone
PYTHON_EXE="${PYTHON_EXE:-python3}"   # or the Python of your environment
export PYTHONPATH="$REPO_DIR:$PYTHONPATH"

echo "$(date): Starting My AI Research Assistant Server..."
cd "$REPO_DIR"

# Run the server
$PYTHON_EXE server_module/main.py
