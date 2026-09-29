param(
  [Parameter(Mandatory=$true)][string]$Manifest,
  [string]$FeHost = 'localhost',
  [int]$MySqlPort = 9030,
  [string]$User = 'root',
  [string]$MySqlContainer
)
$ErrorActionPreference = 'Stop'
if (-not $env:DORIS_PASSWORD) { throw 'Set DORIS_PASSWORD.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$m = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json

$sqlHost = $FeHost
if ($MySqlContainer) {
  $sqlHost = (& docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $MySqlContainer).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $sqlHost) { throw "Cannot resolve Doris container IP: $MySqlContainer" }
}

function Invoke-DorisSql([string]$Sql, [switch]$Batch, [switch]$SkipColumnNames) {
  $argsCommon = @('-h', $sqlHost, '-P', [string]$MySqlPort, '-u', $User, '--default-character-set=utf8mb4', '--raw')
  if ($Batch) { $argsCommon += '--batch' }
  if ($SkipColumnNames) { $argsCommon += '--skip-column-names' }
  if ($MySqlContainer) {
    $output = $Sql | & docker exec -i -e "MYSQL_PWD=$($env:DORIS_PASSWORD)" $MySqlContainer mysql @argsCommon
  } else {
    $output = $Sql | & mysql @argsCommon
  }
  if ($LASTEXITCODE -ne 0) { throw 'Doris SQL execution failed.' }
  return $output
}

function Expand-ValidationSql([string]$Sql) {
  return $Sql.Replace('__CODE_ROWS__', [string]$m.files.hsj_stock_code_info.rows).
    Replace('__BASIC_ROWS__', [string]$m.files.hsj_stock_hq_basic.rows).
    Replace('__EXT_ROWS__', [string]$m.files.hsj_stock_hq_ext.rows).
    Replace('__BASIC_MIN__', [string]$m.files.hsj_stock_hq_basic.dateMin).
    Replace('__BASIC_MAX__', [string]$m.files.hsj_stock_hq_basic.dateMax).
    Replace('__EXT_MIN__', [string]$m.files.hsj_stock_hq_ext.dateMin).
    Replace('__EXT_MAX__', [string]$m.files.hsj_stock_hq_ext.dateMax)
}

$sql = Expand-ValidationSql (Get-Content -LiteralPath (Join-Path $repo 'data\doris\ddl\003_validate_snapshot.sql') -Raw)
$gateSql = Expand-ValidationSql (Get-Content -LiteralPath (Join-Path $repo 'data\doris\ddl\004_validation_gate.sql') -Raw)
$env:MYSQL_PWD = $env:DORIS_PASSWORD
try {
  $gate = Invoke-DorisSql $gateSql -Batch -SkipColumnNames
  if (($gate -join '').Trim() -ne '1') {
    throw 'Snapshot structural validation gate failed; registry was not updated.'
  }
  Invoke-DorisSql $sql -Batch | Write-Output

  # The full anti join needs more memory than the supported single-node Docker
  # setup.  Date predicates on both sides keep each hash table bounded while
  # preserving exactly the same key-containment check.
  [long]$extWithoutBasic = 0
  $firstYear = [int]([string]$m.files.hsj_stock_hq_ext.dateMin).Substring(0, 4)
  $lastYear = [int]([string]$m.files.hsj_stock_hq_ext.dateMax).Substring(0, 4)
  for ($year = $firstYear; $year -le $lastYear; $year++) {
    $nextYear = $year + 1
    $relationshipSql = @"
USE newzl;
SET exec_mem_limit=1073741824;
SELECT COUNT(*)
FROM hsj_stock_hq_ext e LEFT ANTI JOIN hsj_stock_hq_basic b
ON e.mktcode=b.mktcode AND e.tgtcode=b.tgtcode AND e.bizdate=b.bizdate
AND b.bizdate >= DATE('$year-01-01') AND b.bizdate < DATE('$nextYear-01-01')
WHERE e.bizdate >= DATE('$year-01-01') AND e.bizdate < DATE('$nextYear-01-01');
"@
    $yearResult = (Invoke-DorisSql $relationshipSql -Batch -SkipColumnNames -join '').Trim()
    [long]$yearOrphans = 0
    if (-not [long]::TryParse($yearResult, [ref]$yearOrphans)) {
      throw "Unexpected relationship-check result for year ${year}: $yearResult"
    }
    $extWithoutBasic += $yearOrphans
    Write-Output "relationship_ext_without_basic_${year}`t$yearOrphans"
  }

  # Both tables use UNIQUE KEY(mktcode,tgtcode,bizdate), and the row-count gate
  # above proves that source rows were not collapsed.  Therefore this is the
  # exact reverse-direction count without another large anti join.
  [long]$basicRows = $m.files.hsj_stock_hq_basic.rows
  [long]$extRows = $m.files.hsj_stock_hq_ext.rows
  [long]$basicWithoutExt = $basicRows - ($extRows - $extWithoutBasic)
  Write-Output "relationship_ext_without_basic_total`t$extWithoutBasic"
  Write-Output "relationship_basic_without_ext_total`t$basicWithoutExt"
  if ($extWithoutBasic -ne 0) {
    throw "Relationship validation failed: $extWithoutBasic extension rows have no matching basic key; registry was not updated."
  }

  $manifestHash = (Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash.ToLowerInvariant()
  $snapshotId = ([string]$m.snapshotId).Replace("'", "''")
  $contractVersion = ([string]$m.contractVersion).Replace("'", "''")
  $registerSql = "INSERT INTO newzl.data_snapshot_registry VALUES ('$snapshotId','$contractVersion','$manifestHash','VALIDATED',NOW(),'row/date/key/join gate passed');"
  Invoke-DorisSql $registerSql -Batch | Write-Output
  Write-Host "PASS: snapshot $snapshotId is VALIDATED and registered."
} finally {
  Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}
