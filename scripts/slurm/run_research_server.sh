#!/bin/bash
#SBATCH -p cpu-small
#SBATCH -J research_server
#SBATCH -o slurm_logs/research_server_%j.out
#SBATCH -e slurm_logs/research_server_%j.err
#SBATCH --mem=8G
#SBATCH --cpus-per-task=1
#SBATCH --time=5-00:00:00

# Set paths relative to user directory or script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_DIR="${REPO_DIR:-$SCRIPT_DIR}"
PYTHON_EXE="${PYTHON_EXE:-python3}"

export PYTHONPATH="$REPO_DIR:$PYTHONPATH"

echo "$(date): Starting My AI Research Assistant Server in $REPO_DIR..."
cd "$REPO_DIR"

# Run the server
$PYTHON_EXE -m server_module.main
