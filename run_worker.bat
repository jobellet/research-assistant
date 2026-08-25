@echo off
setlocal enabledelayedexpansion

:: --- CONFIGURATION ---
set INTERVAL=300
set REPO_DIR=%~dp0
cd /d "%REPO_DIR%"

echo ===================================================
echo   AI Research Assistant - Windows Worker Launcher
echo ===================================================
echo.

:loop
echo [%date% %time%] --- Starting Sync Cycle ---

:: 1. Pull latest changes
echo 1. Pulling latest code and data...
git pull --rebase

:: 2. Run the Worker Pipeline (Preprocess + Embed)
echo 2. Running Worker Pipeline...
python windows_worker.py --single-run

:: 3. Commit and Push new metadata/embeddings
echo 3. Syncing changes back to origin...
git add library/**/metadata.json library/**/embedding.json papers_inventory.csv references.bib
:: Only commit if there are changes
git diff --cached --quiet
if errorlevel 1 (
    echo    New data found. Committing...
    git commit -m "Auto-update: Metadata and embeddings from Windows Worker"
    git push
) else (
    echo    No new data to sync.
)

echo.
echo Cycle complete. Sleeping for %INTERVAL% seconds...
timeout /t %INTERVAL% /nobreak > nul
goto loop
