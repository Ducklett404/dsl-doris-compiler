[CmdletBinding()]
param(
  [string]$Scope = 'config/acceptance/stock-slot-phase1-scope-v1.json',
  [string]$Registry = 'src/main/resources/stock-slot-registry-v1.json',
  [string]$Manifest = 'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json',
  [string]$ReportDirectory = 'reports/scope'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Resolve-RepoFile([string]$Path) {
  $candidate = if ([IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path $repo $Path }
  if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Required file not found: $candidate" }
  return (Resolve-Path -LiteralPath $candidate).Path
}

function Assert-Equal([object]$Actual, [object]$Expected, [string]$Label) {
  if ([string]$Actual -cne [string]$Expected) {
    throw "$Label mismatch: actual='$Actual' expected='$Expected'"
  }
}

function Join-Normalized([object[]]$Values) {
  return (@($Values) | ForEach-Object { [string]$_ } | Sort-Object) -join '|'
}

# Signed text uses UTF-8 LF bytes on every checkout; CRLF is the only normalization.
function Get-ContractHash([string]$Path) {
  $bytes = [IO.File]::ReadAllBytes($Path)
  $utf8 = [Text.UTF8Encoding]::new($false, $true)
  $normalized = $utf8.GetString($bytes).Replace("`r`n", "`n")
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $digest = $sha.ComputeHash($utf8.GetBytes($normalized)) } finally { $sha.Dispose() }
  return [BitConverter]::ToString($digest).Replace('-', '').ToLowerInvariant()
}

$scopePath = Resolve-RepoFile $Scope
$registryPath = Resolve-RepoFile $Registry
$manifestPath = Resolve-RepoFile $Manifest
$frozen = Get-Content -LiteralPath $scopePath -Raw | ConvertFrom-Json
$registryJson = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
$manifestJson = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$checks = [Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [string]$Detail) {
  $checks.Add([ordered]@{ name=$Name; status='PASS'; detail=$Detail })
}

if ($frozen.status -ne 'APPROVED') { throw "Unexpected freeze status: $($frozen.status)" }
if ($frozen.changeControl.externalSignoffRequired) { throw 'Approved scope must not require an external signature workflow.' }
if ($frozen.changeControl.approval.mode -ne 'DIRECT_PROJECT_APPROVAL' -or
    [string]::IsNullOrWhiteSpace($frozen.changeControl.approval.approvedAt)) {
  throw 'Direct project approval metadata is incomplete.'
}
Add-Check 'freeze-status' "$($frozen.freezeId) / $($frozen.status)"

Assert-Equal $registryJson.registryVersion $frozen.registryVersion 'registryVersion'
Assert-Equal (Get-ContractHash $registryPath) $frozen.registrySha256 'registry SHA-256'
Add-Check 'registry-lock' "$($frozen.registryVersion) sha256=$($frozen.registrySha256)"

Assert-Equal $manifestJson.snapshotId $frozen.snapshot.snapshotId 'snapshotId'
Assert-Equal $manifestJson.contractVersion $frozen.snapshot.contractVersion 'snapshot contractVersion'
Assert-Equal (Get-ContractHash $manifestPath) $frozen.snapshot.manifestSha256 'manifest SHA-256'
foreach ($table in $frozen.snapshot.tables) {
  $actual = $manifestJson.files.($table.name)
  if ($null -eq $actual) { throw "Snapshot table missing from manifest: $($table.name)" }
  Assert-Equal $actual.rows $table.rows "$($table.name) rows"
  Assert-Equal $actual.dateMin $table.dateMin "$($table.name) dateMin"
  Assert-Equal $actual.dateMax $table.dateMax "$($table.name) dateMax"
  Assert-Equal $actual.sha256 $table.sha256 "$($table.name) file SHA-256"
}
Add-Check 'snapshot-lock' "$($frozen.snapshot.snapshotId), 3 source files verified"

$ddlProperties = @($frozen.ddlHashes.PSObject.Properties)
foreach ($property in $ddlProperties) {
  $ddlPath = Resolve-RepoFile $property.Name
  $actualHash = Get-ContractHash $ddlPath
  Assert-Equal $actualHash $property.Value "DDL hash $($property.Name)"
}
Add-Check 'ddl-lock' "$($ddlProperties.Count) DDL/semantic contracts verified"

$frozenNames = @($frozen.includedIndicators | ForEach-Object { $_.name })
$registryNames = @($registryJson.indicators | ForEach-Object { $_.name })
Assert-Equal (Join-Normalized $frozenNames) (Join-Normalized $registryNames) 'included indicator names'
foreach ($indicator in $frozen.includedIndicators) {
  if (-not $indicator.dataAvailable) { throw "Included indicator is marked unavailable: $($indicator.name)" }
  $registered = @($registryJson.indicators | Where-Object { $_.name -eq $indicator.name })
  if ($registered.Count -ne 1) { throw "Indicator must have exactly one registry definition: $($indicator.name)" }
  $entry = $registered[0]
  Assert-Equal $entry.valueType $indicator.type "$($indicator.name) type"
  Assert-Equal $entry.unit $indicator.unit "$($indicator.name) unit"
  Assert-Equal "$($entry.source.table).$($entry.source.field)" $indicator.source "$($indicator.name) source"
  Assert-Equal $entry.adjustment $indicator.adjustment "$($indicator.name) adjustment"
  Assert-Equal $entry.nullPolicy $indicator.nullPolicy "$($indicator.name) nullPolicy"
  Assert-Equal (Join-Normalized $entry.aliases) (Join-Normalized $indicator.aliases) "$($indicator.name) aliases"
  Assert-Equal (Join-Normalized $entry.allowedAggregations) (Join-Normalized $indicator.aggregations) "$($indicator.name) aggregations"
  Assert-Equal (Join-Normalized $entry.sentinelValues) (Join-Normalized $indicator.sentinels) "$($indicator.name) sentinels"
  if ([string]::IsNullOrWhiteSpace($indicator.rawDefinition) -or [string]::IsNullOrWhiteSpace($indicator.expression)) {
    throw "Indicator lacks a testable formula/expression: $($indicator.name)"
  }
}
Add-Check 'indicator-scope' "$($frozen.includedIndicators.Count) exact indicators have unique definitions"

$frozenPatterns = @($frozen.includedIndicatorPatterns | ForEach-Object { $_.name })
$registryPatterns = @($registryJson.indicatorPatterns | ForEach-Object { $_.name })
Assert-Equal (Join-Normalized $frozenPatterns) (Join-Normalized $registryPatterns) 'indicator patterns'
foreach ($pattern in $frozen.includedIndicatorPatterns) {
  if ($pattern.nMin -lt 1 -or $pattern.nMax -gt 5000 -or $pattern.nMin -gt $pattern.nMax) {
    throw "Invalid parameter range for $($pattern.name)"
  }
}
Add-Check 'pattern-scope' "$($frozen.includedIndicatorPatterns.Count) parameterized indicators verified"

$includedFunctions = @($frozen.includedFunctions | ForEach-Object { $_.name })
$excludedFunctions = @($frozen.excludedFunctions | ForEach-Object { $_.name })
$registryFunctions = @($registryJson.functions | ForEach-Object { $_.name })
$overlap = @($includedFunctions | Where-Object { $excludedFunctions -contains $_ })
if ($overlap.Count -gt 0) { throw "Functions cannot be both included and excluded: $($overlap -join ', ')" }
Assert-Equal (Join-Normalized ($includedFunctions + $excludedFunctions)) (Join-Normalized $registryFunctions) 'function partition'
Add-Check 'function-scope' "$($includedFunctions.Count) included, $($excludedFunctions.Count) explicitly excluded"

foreach ($market in $frozen.markets.included) {
  Assert-Equal $registryJson.markets.($market.name) $market.mktcode "market $($market.name)"
}
foreach ($marketName in $frozen.markets.excluded) {
  if ($null -ne $registryJson.markets.$marketName) { throw "Excluded market has an executable mapping: $marketName" }
}
Add-Check 'market-scope' '沪/深/京 only; all other recognized markets excluded'

if ($frozen.scopeRestrictions.filterScope -ne 'must be empty' -or $frozen.scopeRestrictions.selectType -ne 'must be empty') {
  throw 'Phase-1 filter_scope and select_type must remain empty.'
}
if (@($frozen.excludedCapabilities).Count -lt 8) { throw 'Excluded capability list is incomplete.' }
Add-Check 'negative-scope' "$($frozen.excludedCapabilities.Count) unsupported categories have written reasons"

$reportRoot = if ([IO.Path]::IsPathRooted($ReportDirectory)) { $ReportDirectory } else { Join-Path $repo $ReportDirectory }
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$result = [ordered]@{
  freezeId=$frozen.freezeId; status='PASS'; freezeStatus=$frozen.status
  approval='DIRECT_PROJECT_APPROVAL'; validatedAt=(Get-Date).ToString('o'); checks=$checks
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reportRoot 'phase1-scope-validation.json') -Encoding UTF8
$lines = @('# 首期数据指标范围自动校验','',"- Freeze: ``$($frozen.freezeId)``","- Result: **PASS**",'- Approval: **DIRECT_PROJECT_APPROVAL**（无需签字）','', '| Check | Status | Detail |','|---|---|---|')
foreach ($check in $checks) { $lines += "| $($check.name) | $($check.status) | $($check.detail) |" }
$lines += @('', '> PASS 表示仓库工件与已批准的项目内部冻结范围一致；不表示赛事组织方已认证实现结果。')
$lines | Set-Content -LiteralPath (Join-Path $reportRoot 'phase1-scope-validation.md') -Encoding UTF8
Write-Host "PHASE1_SCOPE_OK freeze=$($frozen.freezeId) status=APPROVED indicators=$($frozen.includedIndicators.Count) functions=$($includedFunctions.Count) approval=DIRECT_PROJECT_APPROVAL"
