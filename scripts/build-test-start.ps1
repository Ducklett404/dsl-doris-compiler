[CmdletBinding()]
param(
  [ValidateSet('Http','Docker','VerifyOnly')][string]$Mode = 'Http',
  [string]$MavenExecutable = 'mvn.cmd',
  [string]$HostAddress = '127.0.0.1',
  [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
  & $MavenExecutable '-B' 'test' 'package'
  if ($LASTEXITCODE -ne 0) { throw "Maven test/package failed: $LASTEXITCODE" }
  & java '-jar' 'target/dsl-doris-compiler.jar' 'benchmark-stock-slot-compiler' `
    '--warmup' '1000' '--iterations' '5000' '--p95-threshold-ms' '50'
  if ($LASTEXITCODE -ne 0) { throw "Compiler performance gate failed: $LASTEXITCODE" }

  if ($Mode -eq 'VerifyOnly') {
    Write-Host 'BUILD_TEST_OK (startup intentionally skipped)'
    return
  }
  if ($Mode -eq 'Docker') {
    & docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $LASTEXITCODE" }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
      try {
        $response = Invoke-RestMethod -Uri "http://${HostAddress}:${Port}/health" -TimeoutSec 2
        if ($response.status -eq 'ok') { Write-Host "DOCKER_HTTP_OK http://${HostAddress}:${Port}"; return }
      } catch { Start-Sleep -Seconds 2 }
    }
    throw 'Compiler container did not become healthy within 60 seconds.'
  }
  Write-Host "Starting HTTP server on http://${HostAddress}:${Port}; press Ctrl+C to stop."
  & java '-jar' 'target/dsl-doris-compiler.jar' 'serve' '--host' $HostAddress '--port' "$Port"
  if ($LASTEXITCODE -ne 0) { throw "HTTP server exited with code $LASTEXITCODE" }
} finally {
  Pop-Location
}
