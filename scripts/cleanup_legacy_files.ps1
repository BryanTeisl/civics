# Safely removes legacy one-off scripts and untracks binary/cache artifacts from Git.
# Run from your repository root AFTER extracting the refactored package.

$LegacyFiles = @(
    "patch_watcher_active_only.py",
    "fix_jurisdictions.py",
    "seed_examples.py",
    "run_au_updates_3_4.py",
    "run_pipeline.bat",
    "exporter.py",
    "sync_json_and_index.py",
    "watcher.py",
    "worker.py",
    "db.py",
    "metrics.py",
    "onboard_city.py",
    "recalculate_impact.py",
    "ai_agents_1_2.py",
    "ai_agent_3_engage.py",
    "ai_agent_4_lifecycle.py",
    "boarddocs_adapter.py",
    "granicus_adapter.py",
    "primegov_adapter.py",
    "test_front_range_corridor.py",
    "test_multiplatform.py",
    "verify_core.py",
    "corridor_batch_sample.json",
    "scout_5_corridor_cities.json"
)

Write-Host "=== Untracking __pycache__ and core_civic.db from Git ==="
git rm -r --cached --ignore-unmatch __pycache__
git rm --cached --ignore-unmatch core_civic.db

foreach ($file in $LegacyFiles) {
    if (Test-Path $file) {
        Write-Host "Removing legacy script: $file"
        Remove-Item -Force $file
    }
}

Write-Host "`nDone! Review 'git status', then run 'pip install -e .[dev]' and 'pytest'."
