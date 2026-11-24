# Daily CivicPulse Runner (safe for manual runs or Windows Task Scheduler)
# - Rosters: synced quarterly (every 90 days)
# - Portals: polled weekly (every 7 days)
# - Extraction: drains up to 25% of pending minutes per day, capped at 8 docs/day
# - Export: runs automatically only when new rosters, docs, or votes were added

$ErrorActionPreference = "Stop"
python -m civicpulse.cli run-all `
    --sync-rosters `
    --roster-max-age-days 90 `
    --watch-interval-days 7 `
    --work-doc-type minutes `
    --work-pct-per-day 25 `
    --work-max-per-day 8
