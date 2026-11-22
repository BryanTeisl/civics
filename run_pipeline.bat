@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================================
echo   CivicPulse Full Pipeline Runner
echo ========================================================
echo.

REM Optional flags:
REM   run_pipeline.bat --enrich    (also runs Ballotpedia/socials ^& boundary sync)
REM   run_pipeline.bat --push      (commits and pushes core_civic.db ^& public/ to Git)
set DO_ENRICH=0
set DO_PUSH=0

for %%A in (%*) do (
    if /I "%%A"=="--enrich" set DO_ENRICH=1
    if /I "%%A"=="--push" set DO_PUSH=1
)

echo [1/4] Initializing ^& migrating database schema...
python db.py
if errorlevel 1 goto :error

echo.
echo [2/4] Polling active municipal APIs ^& queuing new documents (watcher.py)...
python watcher.py
if errorlevel 1 goto :error

echo.
echo [3/4] Extracting pending PDF roll-call votes via local LLM (worker.py)...
python worker.py
if errorlevel 1 goto :error

if %DO_ENRICH%==1 (
    echo.
    echo [Optional] Enriching Ballotpedia/social links ^& syncing boundaries...
    if exist enrich_socials.py python enrich_socials.py
    if exist sync_boundaries.py python sync_boundaries.py
    if exist import_us_jurisdictions.py python import_us_jurisdictions.py
)

echo.
echo [4/4] Exporting static JSON files to public\data\ (exporter.py)...
python exporter.py
if errorlevel 1 goto :error

if %DO_PUSH%==1 (
    echo.
    echo [Git] Staging, committing, and pushing updates to origin...
    git add core_civic.db public/
    git diff --staged --quiet
    if errorlevel 1 (
        git commit -m "chore: run civic data ingestion and JSON export pipeline"
        git push
        if errorlevel 1 goto :error
    ) else (
        echo No changes detected to commit.
    )
)

echo.
echo ========================================================
echo   Pipeline completed successfully!
echo ========================================================
pause
exit /b 0

:error
echo.
echo [ERROR] Pipeline halted due to a script failure above.
pause
exit /b 1
