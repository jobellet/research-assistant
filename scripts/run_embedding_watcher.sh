#!/bin/bash
#SBATCH -p cpu-small
#SBATCH -J embedding_watcher
#SBATCH --time=5-00:00:00
#SBATCH -o slurm_logs/watcher_%j.out
#SBATCH -e slurm_logs/watcher_%j.err
#SBATCH --mem=2G

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$SCRIPT_DIR/windows_worker.py" --single-run
