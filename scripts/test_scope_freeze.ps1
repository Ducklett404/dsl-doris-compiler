[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$fixture = Join-Path $repo ('target/scope-regression-' + [Guid]::NewGuid().ToString('N'))
$scopePath = 'config/acceptance/stock-slot-phase1-scope-v1.json'
$scope = Get-Content -Raw -LiteralPath (Join-Path $repo $scopePath) | ConvertFrom-Json
$files = @($scopePath, 'scripts/ci/verify-phase1-scope.ps1', 'src/main/resources/stock-slot-registry-v1.json',
  'data/doris/snapshots/stock-20060104-20260414-v1/manifest.json') + @($scope.ddlHashes.PSObject.Properties.Name)
$utf8 = [Text.UTF8Encoding]::new($false)
foreach ($ending in @("`n", "`r`n")) {
  foreach ($file in $files) {
    $destination = Join-Path $fixture $file
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    $text = [IO.File]::ReadAllText((Join-Path $repo $file)).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($destination, $text.Replace("`n", $ending), $utf8)
  }
  & (Join-Path $fixture 'scripts/ci/verify-phase1-scope.ps1') -ReportDirectory 'reports/scope'
}
$registryPath = Join-Path $fixture 'src/main/resources/stock-slot-registry-v1.json'
[IO.File]::AppendAllText($registryPath, ' ', $utf8)
$rejected = $false
try { & (Join-Path $fixture 'scripts/ci/verify-phase1-scope.ps1') }
catch {
  if ($_.Exception.Message -notlike '*registry SHA-256 mismatch*') { throw }
  $rejected = $true
}
if (-not $rejected) { throw 'Scope freeze accepted a changed registry' }
Write-Host 'SCOPE_REGRESSIONS_OK: LF and CRLF accepted; altered content rejected'
