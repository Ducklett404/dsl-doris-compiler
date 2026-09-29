param(
  [Parameter(Mandatory=$true)][string]$DataRoot,
  [string]$SnapshotId = 'stock-20060104-20260414-v1',
  [string]$Database = 'newzl',
  [string]$FeHost = 'localhost',
  [int]$MySqlPort = 9030,
  [int]$HttpPort = 8030,
  [string]$User = 'root',
  [string]$MySqlContainer,
  [switch]$NoRebuild
)
$ErrorActionPreference = 'Stop'
if (-not $env:DORIS_PASSWORD) { throw 'Set DORIS_PASSWORD; passwords are never accepted on the command line.' }
if ($Database -ne 'newzl') { throw 'DDL version 1.0.0 is fixed to database newzl; custom database names are not yet supported.' }

$sqlHost = $FeHost
if ($MySqlContainer) {
  $sqlHost = (& docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $MySqlContainer).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $sqlHost) { throw "Cannot resolve Doris container IP: $MySqlContainer" }
}

function Invoke-DorisSql([string]$Sql) {
  $argsCommon = @('-h', $sqlHost, '-P', [string]$MySqlPort, '-u', $User, '--default-character-set=utf8mb4', '--show-warnings')
  if ($MySqlContainer) {
    $output = $Sql | & docker exec -i -e "MYSQL_PWD=$($env:DORIS_PASSWORD)" $MySqlContainer mysql @argsCommon
  } else {
    $output = $Sql | & mysql @argsCommon
  }
  if ($LASTEXITCODE -ne 0) { throw 'Doris SQL execution failed.' }
  return $output
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$manifestPath = Join-Path $repo "data\doris\snapshots\$SnapshotId\manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Snapshot manifest not found: $manifestPath" }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.snapshotId -ne $SnapshotId) { throw 'Snapshot id does not match manifest.' }

function Find-SnapshotCsv([string]$LeafName) {
  if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) { throw "Data root does not exist: $DataRoot" }
  $matches = @(Get-ChildItem -LiteralPath $DataRoot -Recurse -File -Filter $LeafName)
  if ($matches.Count -ne 1) { throw "Expected exactly one $LeafName below data root, found $($matches.Count)." }
  return $matches[0].FullName
}

$files = @{
  hsj_stock_code_info = Find-SnapshotCsv 'hsj_stock_code_info.csv'
  hsj_stock_hq_basic = Find-SnapshotCsv 'hsj_stock_hq_basic.csv'
  hsj_stock_hq_ext = Find-SnapshotCsv 'hsj_stock_hq_ext.csv'
}
foreach ($table in $files.Keys) {
  if (-not (Test-Path -LiteralPath $files[$table] -PathType Leaf)) { throw "CSV not found: $($files[$table])" }
  $actual = (Get-FileHash -LiteralPath $files[$table] -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $manifest.files.$table.sha256) { throw "SHA-256 mismatch: $table" }
}

$runDir = Join-Path $repo ("data\doris\runs\{0}\{1}" -f $SnapshotId, [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$env:MYSQL_PWD = $env:DORIS_PASSWORD
try {
  if (-not $NoRebuild) {
    Invoke-DorisSql (Get-Content -LiteralPath (Join-Path $repo 'data\doris\ddl\001_rebuild_tables.sql') -Raw) | Write-Output
  }
  foreach ($table in @('hsj_stock_code_info','hsj_stock_hq_basic','hsj_stock_hq_ext')) {
    $header = Get-Content -LiteralPath $files[$table] -TotalCount 1
    $normalizedRoot = Join-Path ([System.IO.Path]::GetTempPath()) "dsl-doris-normalized\$SnapshotId"
    New-Item -ItemType Directory -Path $normalizedRoot -Force | Out-Null
    $normalizedFile = Join-Path $normalizedRoot "$table.csv"
    if (Test-Path -LiteralPath $normalizedFile) { Remove-Item -LiteralPath $normalizedFile -Force }
    Write-Host "Normalizing empty fields to Doris NULL token: $table"
    & python (Join-Path $PSScriptRoot 'normalize_csv.py') --input $files[$table] --output $normalizedFile
    if ($LASTEXITCODE -ne 0) { throw "CSV normalization failed: $table" }
    $labelSafe = ($SnapshotId -replace '[^A-Za-z0-9_]', '_')
    $label = "${labelSafe}_${table}_${runId}"
    $responseFile = Join-Path $runDir "$table.response.json"
    & curl.exe --fail-with-body --location-trusted -sS -u "${User}:$($env:DORIS_PASSWORD)" `
      -H 'Expect: 100-continue' -H "label:$label" -H 'format:csv' -H 'skip_lines:1' `
      -H 'column_separator:,' -H 'strict_mode:true' -H 'max_filter_ratio:0' -H 'timeout:3600' `
      -H "columns:$header" -T $normalizedFile `
      "http://${FeHost}:${HttpPort}/api/${Database}/${table}/_stream_load" -o $responseFile
    $curlExitCode = $LASTEXITCODE
    Remove-Item -LiteralPath $normalizedFile -Force -ErrorAction SilentlyContinue
    if ($curlExitCode -ne 0) { Add-Content (Join-Path $runDir 'failed-loads.log') "$table HTTP failure curlExit=$curlExitCode"; throw "Stream Load failed: $table" }
    $response = Get-Content -LiteralPath $responseFile -Raw | ConvertFrom-Json
    if ($response.Status -notin @('Success','Publish Timeout','Label Already Exists') -or [int64]$response.NumberFilteredRows -ne 0) {
      Add-Content (Join-Path $runDir 'failed-loads.log') "$table status=$($response.Status) filtered=$($response.NumberFilteredRows) message=$($response.Message) errorUrl=$($response.ErrorURL)"
      if ($response.ErrorURL) {
        & curl.exe --location -sS -u "${User}:$($env:DORIS_PASSWORD)" $response.ErrorURL -o (Join-Path $runDir "$table.failed_rows.txt")
      }
      throw "Stream Load rejected or filtered rows: $table"
    }
  }
  Invoke-DorisSql (Get-Content -LiteralPath (Join-Path $repo 'data\doris\ddl\002_semantic_view.sql') -Raw) | Write-Output
  Write-Host "Load completed. Run logs: $runDir"
} finally {
  Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}
