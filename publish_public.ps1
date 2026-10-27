<#
.SYNOPSIS
Publish a clean snapshot of this folder to a separate public repository.

.DESCRIPTION
RPT_Viewer lives inside a private source repository. That repository may
contain non-public material, so it must never be the source of a public repo.

This script exports only the committed contents of this folder into a throwaway
git repo with a single commit and force-pushes that commit to the public
remote. The public repo therefore never inherits any monorepo history, and the
result is byte-identical to what you tested locally.

The working tree must be clean (commit your changes first) unless -AllowDirty
is given. A leak scan runs over the exported tree before anything is pushed and
aborts on a hit.

.PARAMETER Remote
Public repository URL, e.g. https://github.com/<user>/RPT_Viewer.git
Falls back to the "rpt.publicRemote" git config value.

.PARAMETER Message
Commit message for the snapshot (default: "Update public snapshot").

.PARAMETER Branch
Branch to push (default: main).

.PARAMETER DryRun
Build the snapshot and run the checks, but do not push.

.PARAMETER AllowDirty
Publish the committed tree even if the working tree has uncommitted changes.
Uncommitted edits are NOT included in the snapshot.

.EXAMPLE
.\publish_public.ps1 -Remote https://github.com/me/RPT_Viewer.git

.EXAMPLE
git config rpt.publicRemote https://github.com/me/RPT_Viewer.git
.\publish_public.ps1 -Message "Fix CC001 column detection"
#>
[CmdletBinding()]
param(
    [string]$Remote = "",
    [string]$Message = "Update public snapshot",
    [string]$Branch = "main",
    [switch]$DryRun,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

# --------------------------------------------------------------------------
# Locate repo + folder
# --------------------------------------------------------------------------
$projectDir = $PSScriptRoot
$repoRoot = (& git -C $projectDir rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw "Not inside a git repository: $projectDir" }

$prefix = (& git -C $projectDir rev-parse --show-prefix).Trim()
if (-not $prefix) { throw "Run this from inside the RPT_Viewer folder of the monorepo." }
$prefix = $prefix.TrimEnd('/')

# --------------------------------------------------------------------------
# Resolve the public remote
# --------------------------------------------------------------------------
if (-not $Remote) { $Remote = (& git -C $repoRoot config --get rpt.publicRemote) }
if (-not $Remote) {
    throw @"
No public remote configured.

Pass one:   .\publish_public.ps1 -Remote https://github.com/<user>/RPT_Viewer.git
Or store:   git config rpt.publicRemote https://github.com/<user>/RPT_Viewer.git
"@
}

# --------------------------------------------------------------------------
# Refuse to publish half-finished work
# --------------------------------------------------------------------------
$dirty = & git -C $repoRoot status --porcelain -- $prefix
if ($dirty -and -not $AllowDirty) {
    Write-Host "Uncommitted changes under $prefix - commit them first:" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    throw "Working tree is dirty (use -AllowDirty to publish the last commit anyway)."
}

# --------------------------------------------------------------------------
# Export the committed tree to a scratch repo
# --------------------------------------------------------------------------
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("rpt_public_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$archive = Join-Path $tempRoot "snapshot.tar"

try {
    & git -C $repoRoot archive --format=tar -o $archive "HEAD:$prefix"
    if ($LASTEXITCODE -ne 0) { throw "git archive failed." }

    $snapshot = Join-Path $tempRoot "snapshot"
    New-Item -ItemType Directory -Path $snapshot | Out-Null
    & tar -xf $archive -C $snapshot
    if ($LASTEXITCODE -ne 0) { throw "tar extraction failed." }
    Remove-Item $archive -Force

    # ----------------------------------------------------------------------
    # Leak scan - never publish a real identifier.
    # The patterns are kept in a gitignored file (leak_patterns.txt) so this
    # script itself stays publishable.
    # ----------------------------------------------------------------------
    $patternFile = Join-Path $projectDir "leak_patterns.txt"
    if (-not (Test-Path $patternFile)) {
        throw "Leak scan aborted: $patternFile not found. Nothing was pushed."
    }
    $forbidden = Get-Content $patternFile |
        Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith('#') } |
        ForEach-Object { $_.Trim() }
    $files = Get-ChildItem $snapshot -Recurse -File | Select-Object -ExpandProperty FullName
    $leaks = @()
    foreach ($pattern in $forbidden) {
        $hits = Select-String -Path $files -Pattern $pattern -SimpleMatch -ErrorAction SilentlyContinue
        if ($hits) { $leaks += $hits }
    }
    if ($leaks.Count -gt 0) {
        $leaks | Select-Object -First 10 | ForEach-Object { Write-Host ("  {0}:{1}" -f $_.Filename, $_.LineNumber) }
        throw "Leak scan failed - $($leaks.Count) hit(s). Nothing was pushed."
    }
    Write-Host "Leak scan: $($forbidden.Count) patterns, clean" -ForegroundColor Cyan

    # ----------------------------------------------------------------------
    # Fresh single-commit repo
    # ----------------------------------------------------------------------
    Push-Location $snapshot
    try {
        & git init -q -b $Branch
        & git add -A
        & git -c core.autocrlf=false commit -q -m $Message
        if ($LASTEXITCODE -ne 0) { throw "commit failed." }

        $count = (& git ls-files | Measure-Object).Count
        $size = "{0:N0} KB" -f ((Get-ChildItem .git -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
        Write-Host "Snapshot: $count files, $size, 1 commit" -ForegroundColor Cyan

        if ($DryRun) {
            Write-Host "Dry run - snapshot kept at $snapshot" -ForegroundColor Yellow
            return
        }

        & git remote add origin $Remote
        & git push --force origin "${Branch}:${Branch}"
        if ($LASTEXITCODE -ne 0) { throw "push failed." }

        Write-Host "Published to $Remote ($Branch)" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
finally {
    if (-not $DryRun -and (Test-Path $tempRoot)) {
        Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
