<#
    Daily price collection.

    Runs from a Windows scheduled task rather than GitHub Actions: both
    retailers refuse datacenter IPs (Woolworths answers 403 to every request
    from a GitHub-hosted runner), while the same script from a residential
    connection collects normally.

    A snapshot cannot be backfilled, so a missed day is gone. Re-running on the
    same day is safe: the fetcher overwrites that date's file, and the commit
    is skipped when nothing changed.

    Manual run:  powershell -ExecutionPolicy Bypass -File scripts\collect.ps1
#>

# Stop applies to cmdlets only. Native calls below run under Continue on
# purpose: Windows PowerShell 5.1 wraps a native command's stderr in ErrorRecord
# objects when you pipe 2>&1, and Python's logging writes INFO to stderr, so
# under Stop the first ordinary progress line aborts the script. Every native
# call here is checked on $LASTEXITCODE instead, which is the honest signal.
$ErrorActionPreference = 'Stop'

$repo   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$logDir = Join-Path $repo 'logs'
$log    = Join-Path $logDir ('collect_{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Output $line
}

Write-Log 'Starting collection.'

if (-not (Test-Path $python)) {
    Write-Log "FAILED: no interpreter at $python. Recreate the venv."
    exit 1
}

Set-Location $repo
$ErrorActionPreference = 'Continue'

# Python logs in UTF-8; without these the console decodes it as the system
# codepage and every em-dash in an error message lands in the log as mojibake,
# exactly when the log is the only thing left to diagnose from.
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Fetch only. The marts and dashboard rebuild from the raw CSVs on demand, and
# running them here would mean committing a ~1.8MB binary warehouse every day.
#
# One retry, well spaced. fetch_prices aborts rather than record a half-empty
# day, which is correct: a snapshot missing one retailer silently skews every
# comparison built on it. But a retailer throttling for a few minutes should not
# cost a day that can never be refetched, and a 10 minute gap is long enough to
# clear a rate limit without turning a failure into hammering.
$attempts = 0
while ($true) {
    $attempts++
    & $python -m ingest.fetch_prices 2>&1 | ForEach-Object { Write-Log ($_ | Out-String).TrimEnd() }
    if ($LASTEXITCODE -eq 0) { break }

    if ($attempts -ge 2) {
        Write-Log "FAILED: fetch exited $LASTEXITCODE on both attempts. No snapshot written."
        exit 1
    }
    Write-Log "Fetch exited $LASTEXITCODE. Waiting 10 minutes for one retry."
    Start-Sleep -Seconds 600
}

& git add data/raw/
& git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Log 'No change to commit (same-day re-run).'
    exit 0
}

$stamp = Get-Date -Format 'yyyy-MM-dd'
& git commit -q -m "data: price snapshot $stamp" 2>&1 | ForEach-Object { Write-Log ($_ | Out-String).TrimEnd() }
if ($LASTEXITCODE -ne 0) {
    Write-Log "FAILED: commit exited $LASTEXITCODE."
    exit 1
}

& git push -q origin master 2>&1 | ForEach-Object { Write-Log ($_ | Out-String).TrimEnd() }
if ($LASTEXITCODE -ne 0) {
    # The snapshot is committed locally either way, so nothing is lost; the
    # next successful run carries both up.
    Write-Log 'WARNING: committed locally but push failed. Will go up next run.'
    exit 0
}

Write-Log "Committed and pushed snapshot $stamp."
