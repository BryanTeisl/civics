# CivicPulse

**CivicPulse** is a free, zero-server ($0/month) local government transparency platform built for **everyday residents** and **local businesses** across Colorado (and architected to expand state-by-state). It aggregates agendas, roll-call votes, and plain-English summaries from municipal, county, and school board portals (Legistar, CivicClerk, PrimeGov) and publishes static JSON, quarterly search shards, and RSS feeds to **Cloudflare Pages**.

---

## Architecture & Operating Model (v2)

| Layer | Where It Runs | Role |
| :--- | :--- | :--- |
| **Daily Data Pipeline** | Local Windows PC (`scripts/run_daily.ps1` + Ollama `qwen2.5:3b`) | Backs up `core_civic.db`, runs `civicpulse watch`, extracts PDF/HTML minutes via local Ollama, normalizes data, exports `public/`, validates schemas, and pushes `public/` to GitHub. |
| **GitHub Actions CI** | GitHub (`.github/workflows/ci.yml`) | **CI-only:** Runs `pytest`, verifies `core_civic.db` and `__pycache__/` are never committed, and validates `public/data/` schemas & naming hygiene on every push/PR. *(Legacy v1 cron workflows have been retired.)* |
| **Public Hosting** | Cloudflare Pages (`public/`) | Serves the static frontend, sharded search indices, downloadable scoring formula, and RSS 2.0 feeds at $0/month. |

> **Important:** Keep your active working repository outside live-syncing OneDrive folders (e.g., `C:\Projects\civics`) so OneDrive never locks `core_civic.db` or `.git/index`. `scripts/run_daily.ps1` safely copies daily SQLite snapshots to OneDrive using SQLite's online `.backup()` API.

---

## Daily Routine & Scheduling

### One-Command Daily Run (Local PC)
```powershell
# Run full daily sync (watch -> work -> normalize -> export -> validate)
.\scriptsun_daily.ps1

# Run full sync and automatically commit & push public/ to Cloudflare Pages
.\scriptsun_daily.ps1 -Push

# Fast poll & export without running local Ollama extraction
.\scriptsun_daily.ps1 -SkipWork -Push
```

### Schedule Automatically on Windows (Task Scheduler)
1. Open **Task Scheduler** → **Create Basic Task** → Name: `CivicPulse Daily Sync`.
2. Trigger: **Daily** (e.g., `7:00 AM`).
3. Action: **Start a program**
   - Program/script: `powershell.exe`
   - Arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\Projects\civics\scriptsun_daily.ps1" -Push`
4. Check **"Run task as soon as possible after a scheduled start is missed"** so updates run automatically whenever the PC wakes up.

---

## CLI Quick Reference

```powershell
# Install package and dev tools
pip install -e ".[dev]"

# Initialize / migrate SQLite schema
python -m civicpulse.cli init

# Poll active jurisdictions
python -m civicpulse.cli watch

# Extract pending minutes via local Ollama
python -m civicpulse.cli work --doc-type minutes --limit 10

# Normalize levels, outcomes, topics, committee scores, and QA status
python scripts/normalize_db.py --db core_civic.db --apply

# Export static JSON + quarterly search chunks + RSS feeds + formula docs
python -m civicpulse.cli export
python -m civicpulse.pipeline.export_enhancements --db core_civic.db --public-dir public

# Validate exported data & run full test suite
python scripts/validate_exports.py --data-dir public/data
python -m pytest -v
```

---

## Transparent, Versioned Vote Impactfulness Formula

CivicPulse's 0–100 **Vote Impactfulness** score is 100% deterministic and nonpartisan. The single source of truth lives in `civicpulse/pipeline/scoring_spec.py` and is automatically published on every export to:
- `public/data/scoring_methodology.json` (used by the UI to render the plain-English explanation and alert users if the formula version/checksum changes)
- `public/docs/civicpulse_impact_formula.md` (plain-English downloadable guide with worked examples and changelog)
- `public/docs/civicpulse_impact_formula.json` (machine-readable specification)

---

## Alerts (RSS) & Expanding Beyond Colorado

- **RSS Alerts (`public/feeds/`):** Every export generates `feeds/all.xml`, per-jurisdiction feeds (`feeds/jur_<slug>.xml`), and per-topic feeds (`feeds/topic_<slug>.xml`). Residents can follow in any RSS reader, and businesses can pipe topic feeds (like *Zoning & Land Use* or *Taxes, Fees & Utilities*) directly into Slack, Microsoft Teams, or Zapier.
- **State Expansion:** CivicPulse is currently focused on **Colorado (Front Range)**, with out-of-scope test entries archived cleanly. To expand to a new state, copy `config/jurisdictions/TEMPLATE_state.json` to `config/jurisdictions/<state>.json` and run:
  ```powershell
  python -m civicpulse.cli seed --file config/jurisdictions/<state>.json
  ```
