[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$DataRoot,
  [string]$SnapshotId = 'stock-20060104-20260414-v1',
  [string]$FeHost = '127.0.0.1',
  [int]$MySqlPort = 9030,
  [int]$HttpPort = 8040,
  [string]$User = 'dsl_loader',
  [string]$MySqlContainer = 'doris',
  [switch]$NoRebuild,
  [switch]$BuildPerformanceFeatures
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($env:DORIS_PASSWORD)) {
  throw 'Set DORIS_PASSWORD. The password is never accepted as a command-line argument.'
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$manifest = Join-Path $repo "data\doris\snapshots\$SnapshotId\manifest.json"
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw "Snapshot manifest not found: $manifest" }

$loadArgs = @{
  DataRoot = $DataRoot; SnapshotId = $SnapshotId; FeHost = $FeHost
  MySqlPort = $MySqlPort; HttpPort = $HttpPort; User = $User
}
if ($MySqlContainer) { $loadArgs.MySqlContainer = $MySqlContainer }
if ($NoRebuild) { $loadArgs.NoRebuild = $true }
& (Join-Path $PSScriptRoot 'load-csv.ps1') @loadArgs

$validateArgs = @{ Manifest = $manifest; FeHost = $FeHost; MySqlPort = $MySqlPort; User = $User }
if ($MySqlContainer) { $validateArgs.MySqlContainer = $MySqlContainer }
& (Join-Path $PSScriptRoot 'validate-snapshot.ps1') @validateArgs

if ($BuildPerformanceFeatures) {
  $sql = Get-Content -LiteralPath (Join-Path $repo 'data\doris\ddl\005_performance_features.sql') -Raw
  $sqlHost = $FeHost
  if ($MySqlContainer) {
    $sqlHost = (& docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $MySqlContainer).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $sqlHost) { throw "Cannot resolve Doris container IP: $MySqlContainer" }
    $sql | & docker exec -i -e "MYSQL_PWD=$($env:DORIS_PASSWORD)" $MySqlContainer mysql `
      -h $sqlHost -P $MySqlPort -u $User --default-character-set=utf8mb4
  } else {
    $env:MYSQL_PWD = $env:DORIS_PASSWORD
    try { $sql | & mysql -h $sqlHost -P $MySqlPort -u $User --default-character-set=utf8mb4 }
    finally { Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue }
  }
  if ($LASTEXITCODE -ne 0) { throw 'Performance feature build failed.' }
}

Write-Host "SETUP_LOAD_VALIDATE_OK snapshot=$SnapshotId manifest=$manifest"
