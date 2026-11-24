# CivicPulse (v2 — Scalable Architecture)

A zero-hosting-cost ($0/month) civic data pipeline and static public-record explorer for municipal, county, and school board governments. Polls structured legislative portals, extracts roll-call votes and plain-English summaries via local Ollama (`qwen2.5:3b`), and publishes sharded Open Civic Data (OCD) JSON to **Cloudflare Pages**.

## Safe Local Setup (Outside OneDrive)

Do **not** keep your active `.git` folder or `core_civic.db` inside a live-syncing OneDrive directory. Clone or extract this repo to a local folder (e.g., `C:\Projects\civics`) and point `ONEDRIVE_BACKUP_DIR` to OneDrive for safe SQLite online backups:

```powershell
setx ONEDRIVE_BACKUP_DIR "C:\Users\YOUR_NAME\OneDrive\CivicCoreBackups"
```

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 1. Initialize or migrate SQLite schema (idempotent)
civicpulse init

# 2. Seed all 21 Front Range corridor cities & activate verified structured APIs
civicpulse seed --file config/jurisdictions/colorado_front_range.json --activate-structured

# 3. Run full pipeline: watch -> work (local Ollama) -> unified export
civicpulse run-all

# 4. Run unit & integration test suite
pytest -v
```

## Unified CLI Commands

| Command | Purpose |
| :--- | :--- |
| `civicpulse init` | Applies versioned SQL migrations (`schema_migrations`) cleanly |
| `civicpulse seed --file <json> [--activate-structured]` | Seeds jurisdictions from declarative config |
| `civicpulse probe --file <json>` | Runs live HTTP health checks across all configured portals |
| `civicpulse watch` | Polls active jurisdictions via the plugin adapter registry |
| `civicpulse work --limit 10` | Extracts votes & summaries via local Ollama (`qwen2.5:3b`) |
| `civicpulse export` | Exports sharded JSON, `directory.json`, lazy `search_index.json`, engagement guides & lifecycles |
| `civicpulse onboard --name "City" --state CO --run-pipeline` | Auto-discovers platform, geocodes, and ingests a new city |
| `civicpulse maintain recalculate-impact` | Recomputes impact scores & vote margins across all events |
| `civicpulse run-all` | Runs `init` → `watch` → `work` → `export` end-to-end |

## Deploying to Cloudflare Pages

* **Build command:** *(leave blank — zero build step, native ES modules)*
* **Build output directory:** `public`
