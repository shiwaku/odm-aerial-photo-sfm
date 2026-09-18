<#
.SYNOPSIS
  [D] Run ODM (GPU) on datasets/<Project>.

.EXAMPLE
  .\scripts\04_run_odm.ps1 -Project suzu_0102
  .\scripts\04_run_odm.ps1 -Project suzu_0102 -FeatureQuality medium -Rerun
  .\scripts\04_run_odm.ps1 -Project suzu_0102 -Extra @('--3d-tiles') -RerunFrom odm_dem

.NOTES
  - Expects datasets/<Project>/images/ and geo.txt from 03_prepare_odm_inputs.py.
  - Log is tee'd to datasets/<Project>/odm_log.txt (appended per run).
  - Image tag can be pinned with -Image opendronemap/odm:<version>-gpu.
#>
param(
  [Parameter(Mandatory)] [string] $Project,
  [string] $Image = "opendronemap/odm:gpu",
  [string] $DatasetsDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "datasets"),
  [ValidateSet("ultra","high","medium","low","lowest")] [string] $FeatureQuality = "high",
  [ValidateSet("ultra","high","medium","low","lowest")] [string] $PcQuality = "high",
  [int] $DemResolutionCm = 100,
  [int] $OrthoResolutionCm = 100,
  [int] $GpsAccuracy = 30,
  [int] $MinNumFeatures = 12000,
  [int] $MatcherNeighbors = 12,
  [int] $MaxConcurrency = 14,
  [switch] $Dtm,          # also build a DTM (needs -PcClassify). Off by default: on the Suzu qv set
  [switch] $PcClassify,   # SMRF found no ground points and renderdem died (exit 137) on an empty cloud
  [switch] $Rerun,
  [string] $RerunFrom = "",
  [string[]] $Extra = @()
)

$ErrorActionPreference = "Stop"
$projDir = Join-Path $DatasetsDir $Project
if (-not (Test-Path (Join-Path $projDir "images"))) { throw "images/ not found under $projDir" }
$hasGeo = Test-Path (Join-Path $projDir "geo.txt")

# docker on Windows wants a Windows path for the host side of -v
$hostDatasets = (Resolve-Path $DatasetsDir).Path

$odmArgs = @(
  "--project-path", "/datasets", $Project,
  "--feature-type", "sift",
  "--feature-quality", $FeatureQuality,
  "--min-num-features", "$MinNumFeatures",
  "--matcher-type", "flann",
  "--matcher-neighbors", "$MatcherNeighbors",
  "--camera-lens", "brown",
  "--gps-accuracy", "$GpsAccuracy",
  "--pc-quality", $PcQuality,
  "--dsm",
  "--dem-resolution", "$DemResolutionCm",
  "--orthophoto-resolution", "$OrthoResolutionCm",
  "--cog",
  "--auto-boundary",
  "--max-concurrency", "$MaxConcurrency"
)
if ($hasGeo) { $odmArgs += @("--geo", "/datasets/$Project/geo.txt") }
if ($PcClassify -or $Dtm) { $odmArgs += "--pc-classify" }
if ($Dtm) { $odmArgs += "--dtm" }
if ($Rerun) { $odmArgs += "--rerun-all" }
if ($RerunFrom) { $odmArgs += @("--rerun-from", $RerunFrom) }
$odmArgs += $Extra

$log = Join-Path $projDir "odm_log.txt"
$imageId = docker image inspect $Image --format '{{.Id}} {{index .RepoDigests 0}}' 2>$null
$header = @(
  "==== $(Get-Date -Format s) ODM run ====",
  "image: $Image  $imageId",
  "args : $($odmArgs -join ' ')"
)
$header | Tee-Object -FilePath $log -Append | Write-Host

$sw = [Diagnostics.Stopwatch]::StartNew()
# Windows PowerShell 5.1 wraps native stderr lines in NativeCommandError records; with
# ErrorActionPreference=Stop the first stderr line would abort this script (the container
# keeps running detached). Relax it around the docker call and stringify every record.
$ErrorActionPreference = "Continue"
docker run --rm --gpus all `
  -v "${hostDatasets}:/datasets" `
  $Image @odmArgs 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $log -Append
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
$sw.Stop()
"==== exit $code after $($sw.Elapsed.ToString('hh\:mm\:ss')) ====" | Tee-Object -FilePath $log -Append | Write-Host
exit $code
