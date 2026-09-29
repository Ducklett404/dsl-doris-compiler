[CmdletBinding()]
param(
  [string]$Dsl = 'examples/registry-smoke.dsl',
  [string]$HistoricalQueryEvidence = 'reports/performance/doris-execution-smoke.json',
  [string]$Output = 'reports/final/compilation-and-query.md'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
  $outputPath = [IO.Path]::GetFullPath((Join-Path $repo $Output))
  $outputDir = Split-Path -Parent $outputPath
  New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
  $artifactPath = Join-Path $outputDir 'compilation.json'
  & java '-jar' 'target/dsl-doris-compiler.jar' 'compile-stock-slot-sql' $Dsl '--format' 'json' '-o' $artifactPath
  if ($LASTEXITCODE -ne 0) { throw "Compilation failed: $LASTEXITCODE" }
  $artifact = Get-Content -LiteralPath $artifactPath -Raw | ConvertFrom-Json
  $normalizedSql = ([string]$artifact.sql -replace '\s+', ' ').Trim()
  $sha = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($normalizedSql))).ToLowerInvariant()
  $plan = (($artifact.logicalPlan | ForEach-Object { $_.kind }) -join ' → ')
  $escapedSql = ([string]$artifact.sql).Replace('```', '`` `')
  $lines = @(
    '# 最终编译和查询结果', '',
    '## 当前编译结果', '',
    '| DSL | DSL version | Status | Logical plan | Bindings | SQL fingerprint |',
    '|---|---|---|---|---:|---|',
    "| ``$Dsl`` | ``$($artifact.dslVersion)`` | PASS | $plan | $($artifact.bindings.Count) | ``sha256:$sha`` |", '',
    '```sql', $escapedSql, '```', '',
    '## 查询结果', ''
  )
  $automation = if (Test-Path 'reports/automation/latest.json') {
    Get-Content -LiteralPath 'reports/automation/latest.json' -Raw | ConvertFrom-Json
  } else { $null }
  $currentStatus = if ($automation) { $automation.checks.'doris-golden-result-differential'.status } else { 'NOT_RUN' }
  $lines += @('| Evidence | Snapshot | Status | Rows | Compile ms | Query ms | Note |',
    '|---|---|---|---:|---:|---:|---|')
  $evidencePath = Join-Path $repo $HistoricalQueryEvidence
  if (Test-Path -LiteralPath $evidencePath) {
    $query = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
    $snapshot = if ($query.snapshotId) { $query.snapshotId } else { 'stock-20060104-20260414-v1' }
    $compileMs = if ($null -ne $query.compileMillis) { $query.compileMillis } elseif ($query.timings) { $query.timings.compileMillis } else { '' }
    $queryMs = if ($null -ne $query.queryMillis) { $query.queryMillis } elseif ($query.timings) { $query.timings.dorisExecutionMillis } else { '' }
    $lines += "| ``$HistoricalQueryEvidence`` | ``$snapshot`` | HISTORICAL_PASS | $($query.rows.Count) | $compileMs | $queryMs | 2026-09-18 固定快照证据；本轮状态为 $currentStatus |"
    $lines += @('', '### 历史查询返回样例', '', '| mktcode | tgtcode |', '|---|---|')
    foreach ($row in @($query.rows | Select-Object -First 20)) { $lines += "| $($row[0]) | $($row[1]) |" }
  } else {
    $lines += "| - | - | $currentStatus | 0 | - | - | No Doris evidence file |"
  }
  $lines += @('', '> 历史证据不会替代本轮复测；当前 Docker/凭据不可用时保持 `NOT_RUN`。')
  $lines | Set-Content -LiteralPath $outputPath -Encoding UTF8
  Write-Host $outputPath
} finally {
  Pop-Location
}
