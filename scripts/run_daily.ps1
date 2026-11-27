<#
.SYNOPSIS
  Official CivicPulse v2 Local Daily Pipeline Runner (Windows / Ollama).

.DESCRIPTION
  Runs database migrations, backs up core_civic.db safely via SQLite's online
  backup API, polls active portals, extracts pending documents via local Ollama,
  normalizes data & recalculates versioned impact scores, generates static JSON,
  chunked search indices, RSS feeds, and downloadable scoring docs, validates
  exports, and optionally commits & pushes ONLY public/ to GitHub.

.EXAMPLE
  .\scripts\run_daily.ps1
  .\scripts\run_daily.ps1 -Push
  .\scripts\run_daily.ps1 -SkipWork -Push
#>

param(
    [switch]$Push,
    [switch]$SkipWork,
    [switch]$ForceWatch,
    [int]$WorkLimit = 10,
    [string]$BackupDir = "$env:USERPROFILE\OneDrive\Backups\CivicPulse"
)

$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "daily_$Stamp.log"

function Write-Step($Msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $LogFile -Value $line
}

try {
    Write-Step "=== CivicPulse Daily Run Started (Repo: $RepoRoot) ==="

    # Guardrail: Warn if running inside OneDrive
    if ($RepoRoot.Path -match "OneDrive") {
        Write-Warning "Working repo is inside OneDrive! Move repo to C:\Projects\civics to prevent SQLite/Git locks."
    }

    # 1. Safe SQLite Snapshot Backup (uses SQLite backup API, safe for OneDrive destination)
    if (Test-Path "core_civic.db") {
        Write-Step "[1/7] Backing up core_civic.db to $BackupDir..."
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        $BackupPath = Join-Path $BackupDir "core_civic_$(Get-Date -Format 'yyyy-MM-dd').db"
        python -c "import sqlite3; src=sqlite3.connect('core_civic.db'); dst=sqlite3.connect(r'$BackupPath'); src.backup(dst); dst.close(); src.close(); print('Backup complete:', r'$BackupPath')" 2>&1 | Tee-Object -FilePath $LogFile -Append
    }

    # 2. Ensure DB schema is migrated
    Write-Step "[2/7] Running schema migrations (civicpulse init)..."
    python -m civicpulse.cli init 2>&1 | Tee-Object -FilePath $LogFile -Append

    # 3. Poll active portals
    Write-Step "[3/7] Polling active municipal/county/school portals..."
    if ($ForceWatch) {
        if (Test-Path "civicpulse\pipeline\autonomous_onboarder.py") {
        python -m civicpulse.pipeline.autonomous_onboarder --db core_civic.db --public-dir public --max-per-run 2 --no-watch 2>&1 | Tee-Object -FilePath $LogFile -Append
    }
    python -m civicpulse.cli watch --force 2>&1 | Tee-Object -FilePath $LogFile -Append
    } else {
        python -m civicpulse.cli watch 2>&1 | Tee-Object -FilePath $LogFile -Append
    }

    # 4. Run local Ollama extraction (unless skipped)
    if (-not $SkipWork) {
        Write-Step "[4/7] Extracting pending minutes via local Ollama (limit=$WorkLimit)..."
        python -m civicpulse.cli work --doc-type minutes --limit $WorkLimit 2>&1 | Tee-Object -FilePath $LogFile -Append
    } else {
        Write-Step "[4/7] Skipping Ollama extraction (-SkipWork set)."
    }

    # 5. Normalize levels, outcomes, topics, committee denominators & versioned scores
    Write-Step "[5/7] Normalizing data & recalculating versioned impact scores..."
    if (Test-Path "scripts\normalize_db.py") {
        python scripts\normalize_db.py --db core_civic.db --apply 2>&1 | Tee-Object -FilePath $LogFile -Append
    if (Test-Path "scripts\calibrate_qa_trust.py") {
        python scripts\calibrate_qa_trust.py --db core_civic.db --apply 2>&1 | Tee-Object -FilePath $LogFile -Append
    }
    }

    # 6. Export static JSON + chunked indices + RSS feeds + scoring methodology docs
    Write-Step "[6/7] Exporting static site assets, RSS feeds & scoring formula docs..."
    python -m civicpulse.cli export 2>&1 | Tee-Object -FilePath $LogFile -Append
    if (Test-Path "civicpulse\pipeline\export_enhancements.py") {
        python -m civicpulse.pipeline.export_enhancements --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append
    }
    if (Test-Path "civicpulse\pipeline\v3_intelligence.py") {
        python -m civicpulse.pipeline.v3_intelligence --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append
    }
    if (Test-Path "civicpulse\pipeline\agenda_preview.py") {
        python -m civicpulse.pipeline.agenda_preview --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append
    }
    if (Test-Path "civicpulse\pipeline\early_warning.py") {
        python -m civicpulse.pipeline.early_warning --db core_civic.db --public-dir public 2>&1 | Tee-Object -FilePath $LogFile -Append
    }

    # 7. Validate exported data before pushing
    Write-Step "[7/7] Validating public/data schema & naming hygiene..."
    if (Test-Path "scripts\validate_exports.py") {
        python scripts\validate_exports.py --data-dir public\data 2>&1 | Tee-Object -FilePath $LogFile -Append
    }

    if ($Push) {
        Write-Step "[Git] Staging public/ (never core_civic.db) and pushing to main..."
        git add public/
        git diff --staged --quiet
        if ($LASTEXITCODE -ne 0) {
            $DateStr = Get-Date -Format "yyyy-MM-dd"
            git commit -m "chore(data): daily civic update ($DateStr)"
            git push
            Write-Step "[Git] Pushed updates to origin/main (Cloudflare Pages will auto-deploy)."
        } else {
            Write-Step "[Git] No changes in public/ to commit."
        }
    }

    Write-Step "=== CivicPulse Daily Run Completed Successfully ==="
}
catch {
    Write-Error "Daily pipeline failed: $_"
    Add-Content -Path $LogFile -Value "ERROR: $_"
    exit 1
}
