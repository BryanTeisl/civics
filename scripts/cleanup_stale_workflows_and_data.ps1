<#
.SYNOPSIS
  Removes broken v1 GitHub Actions workflows and duplicate/stale naming-scheme
  files in public/data/.

.EXAMPLE
  .\scripts\cleanup_stale_workflows_and_data.ps1 -DryRun
  .\scripts\cleanup_stale_workflows_and_data.ps1
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "=== 1. Checking for broken v1 workflows ===" -ForegroundColor Cyan
$BrokenWorkflows = @(
    ".github\workflows\daily_sync.yml",
    ".github\workflows\daily.yml",
    ".github\workflows\monthly_enrichment.yml",
    ".github\workflows\monthly.yml",
    ".github\workflows\boundary_refresh.yml",
    ".github\workflows\boundaries.yml"
)

foreach ($wf in $BrokenWorkflows) {
    if (Test-Path $wf) {
        if ($DryRun) {
            Write-Host "[DRY-RUN] Would remove broken v1 workflow: $wf" -ForegroundColor Yellow
        } else {
            Remove-Item -Force $wf
            Write-Host "[REMOVED] $wf" -ForegroundColor Green
        }
    }
}

Write-Host "`n=== 2. Checking public/data for duplicate/stale naming schemes ===" -ForegroundColor Cyan
# Canonical v2 jurisdiction filename format: country_us__state_co__place_fort_collins.json
# Stale formats to purge:
#   - ocd-division-*.json (old hyphenated v1 scheme)
#   - files containing hyphens in jurisdiction slugs (e.g., fort-collins.json)
#   - duplicate sd_poudre.json when school_district_poudre_r1.json exists
#   - legacy index.json if superseded by directory.json (kept only if explicitly needed)

$DataDir = Join-Path $RepoRoot "public\data"
if (Test-Path $DataDir) {
    $JsonFiles = Get-ChildItem -Path $DataDir -Filter "*.json"
    foreach ($file in $JsonFiles) {
        $name = $file.Name
        $isStale = $false
        $reason = ""

        if ($name -like "ocd-division*") {
            $isStale = $true
            $reason = "Legacy v1 ocd-division-* naming scheme"
        }
        elseif ($name -match "^country_us__.*-.*\.json$") {
            $isStale = $true
            $reason = "Stale hyphenated slug variant"
        }
        elseif ($name -eq "country_us__state_co__sd_poudre.json") {
            $isStale = $true
            $reason = "Duplicate Poudre School District file (use school_district_poudre_r1)"
        }
        elseif ($name -eq "country_us__state_ca__place_san_jose.json") {
            $isStale = $true
            $reason = "Out-of-scope San Jose CA export (Colorado-focused dataset)"
        }
        else {
            # Also detect legacy v1 schema keys ("councilors" / "agenda_items") inside jurisdiction files
            $raw = Get-Content -Path $file.FullName -Raw -ErrorAction SilentlyContinue
            if ($raw -and ($raw -match '"councilors"\s*:' -or $raw -match '"agenda_items"\s*:') -and $raw -notmatch '"representatives"\s*:') {
                $isStale = $true
                $reason = "Legacy v1 JSON payload layout (councilors/agenda_items)"
            }
        }

        if ($isStale) {
            if ($DryRun) {
                Write-Host "[DRY-RUN] Would remove stale file: public\data\$name ($reason)" -ForegroundColor Yellow
            } else {
                Remove-Item -Force $file.FullName
                Write-Host "[REMOVED] public\data\$name ($reason)" -ForegroundColor Green
            }
        }
    }
}

Write-Host "`nDone. Run 'python scripts/validate_exports.py --data-dir public/data' to verify." -ForegroundColor Cyan
