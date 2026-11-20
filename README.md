# Civic Core Aggregator (Starter Kit)

A lightweight, zero-hosting-cost civic data pipeline designed to run on a local PC (RTX 2060 + Ollama) and publish sharded Open Civic Data (OCD) JSON to **Cloudflare Pages**.

## Important: OneDrive + Git + SQLite Setup
**Do NOT place your active `.git` folder or live `core_civic.db` directly inside a live-syncing OneDrive folder.** OneDrive's continuous file-syncing can lock SQLite during writes and corrupt `.git` index files.

Instead, use this safe pattern:
1. Unzip this folder to a local directory on your PC, e.g.: `C:\Projects\civic-core`
2. Set an environment variable pointing to your OneDrive backup folder:
   ```powershell
   setx ONEDRIVE_BACKUP_DIR "C:\Users\YOUR_NAME\OneDrive\CivicCoreBackups"
   ```
3. Every time `exporter.py` runs, it uses SQLite's safe online backup API to copy a clean, timestamped snapshot of `core_civic.db` into your OneDrive folder automatically.

## Quick Start (Windows PowerShell)
```powershell
cd C:\Projects\civic-core
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1. Initialize SQLite DB & seed Fort Collins City Council
python db.py

# 2. Poll Fort Collins CivicClerk for recent Agendas & Minutes (CPU)
python watcher.py

# 3. Extract roll-call votes & compute Vote Impactfulness (RTX 2060 + Ollama)
#    (Make sure Ollama is running: `ollama run llama3.1:8b-instruct-q4_K_M`)
python worker.py

# 4. Export static JSON to public/data/ & backup DB to OneDrive
python exporter.py
```

## Deploying to Cloudflare Pages (Commercial-Friendly Free Tier)
1. Push this repo to GitHub (private or public).
2. In Cloudflare Dashboard -> **Workers & Pages** -> **Create** -> **Pages** -> **Connect to Git**.
3. Set **Build output directory** to `public` (no build command needed).
4. Uncomment `git_publish_if_changed()` in `exporter.py` and schedule `watcher.py` -> `worker.py` -> `exporter.py` via Windows Task Scheduler (e.g., 8:00 AM and 8:00 PM daily, keeping you well under Cloudflare's 500 free builds/month).
