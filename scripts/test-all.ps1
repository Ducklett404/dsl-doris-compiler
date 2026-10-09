[CmdletBinding()]
param(
  [string]$MavenExecutable = 'mvn.cmd',
  [string]$MavenRepository = '',
  [switch]$Offline,
  [string]$TestJvmArgs = '',
  [string]$PythonExecutable = 'python',
  [switch]$WithDoris,
  [switch]$WithProjectDoris,
  [string]$ProjectReportDir = '',
  [string]$ProjectDistribution = 'dsl-doris-official-01a104f9',
  [string]$ProjectDataRoot = '',
  [string]$ProjectReferenceDatabase = '',
  [int]$ProjectRounds = 30,
  [switch]$ProjectRestart,
  [switch]$RunNineteenYearBenchmark,
  [string]$DorisUser = 'dsl_loader',
  [string]$BenchmarkUser = 'dsl_benchmark_reader',
  [string]$DorisContainer = 'doris',
  [int]$MySqlPort = 9030,
  [string]$DockerExecutable = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$reportDir = Join-Path $repo 'reports\automation'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$started = Get-Date
$checks = [ordered]@{}

function Invoke-Checked([string]$Name, [scriptblock]$Action) {
  Write-Host "== $Name =="
  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  $global:LASTEXITCODE = 0
  & $Action
  $powerShellSucceeded = $?
  if (-not $powerShellSucceeded -or ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0)) {
    throw "$Name failed with exit code $LASTEXITCODE"
  }
  $watch.Stop()
  $checks[$Name] = [ordered]@{ status = 'PASS'; elapsedSeconds = [Math]::Round($watch.Elapsed.TotalSeconds, 3) }
}

try {
  Push-Location $repo
  Invoke-Checked 'phase1-scope-freeze' { & '.\scripts\ci\verify-phase1-scope.ps1' }
  Invoke-Checked 'scope-line-ending-regressions' { & '.\scripts\test_scope_freeze.ps1' }
  $mavenArgs = @('-B', '--no-transfer-progress')
  if ($MavenRepository) {
    $cachePath = [IO.Path]::GetFullPath((Join-Path $repo $MavenRepository))
    if ([IO.Path]::IsPathRooted($MavenRepository)) { $cachePath = $MavenRepository }
    $mavenArgs += "-Dmaven.repo.local=$cachePath"
  }
  if ($Offline) { $mavenArgs += '-o' }
  if ($TestJvmArgs) { $mavenArgs += "-Dtest.jvm.args=$TestJvmArgs" }
  Invoke-Checked 'maven-all-tests' { & $MavenExecutable @mavenArgs 'test' 'package' }
  Invoke-Checked 'executor-module-tests' { & $MavenExecutable @mavenArgs '-f' 'executor-doris/pom.xml' 'test' }
  Invoke-Checked 'corpus-python-tests' { & $PythonExecutable 'scripts/test_prepare_competition_corpus.py' }
  Invoke-Checked 'doris-data-contract-tests' { & $PythonExecutable 'scripts/doris/self-test.py' }
  Invoke-Checked 'raw-csv-audit-regressions' { & $PythonExecutable 'scripts/doris/test_data_audit.py' }
  Invoke-Checked 'independent-reference-rebuild-contracts' { & $PythonExecutable 'scripts/doris/test_reference_rebuild.py' }
  Invoke-Checked 'exact-eight-junit-report-contracts' { & $PythonExecutable 'scripts/doris/test_wsl_integration_reports.py' }
  Invoke-Checked 'review-sql-result-regressions' { & $PythonExecutable 'scripts/test_review_regressions.py' }
  Invoke-Checked 'versioned-golden-contract-tests' { & $PythonExecutable 'scripts/accuracy/test_contract_revision.py' }
  Invoke-Checked 'project-matrix-reference-tests' { & $PythonExecutable 'scripts/doris/test_project_matrix_reference.py' }
  Invoke-Checked 'project-field-reference-tests' { & $PythonExecutable 'scripts/doris/test_project_field_reference.py' }
  Invoke-Checked 'project-reference-loading-regressions' { & $PythonExecutable 'scripts/doris/test_project_reference_loading.py' }
  Invoke-Checked 'project-combination-reference-tests' { & $PythonExecutable 'scripts/doris/test_project_combination_reference.py' }
  Invoke-Checked 'project-numeric-comparison-contract-tests' { & $PythonExecutable 'scripts/doris/test_project_numeric_comparisons.py' }
  Invoke-Checked 'project-portable-decimal-adapter-tests' { & $PythonExecutable 'scripts/doris/test_project_portable_decimal.py' }
  Invoke-Checked 'project-be-memory-configuration-tests' { & $PythonExecutable 'scripts/doris/test_project_be_memory.py' }
  Invoke-Checked 'project-be-bounded-runtime-tests' { & $PythonExecutable 'scripts/doris/test_project_be_runtime.py' }
  Invoke-Checked 'project-runtime-evidence-tests' { & $PythonExecutable 'scripts/doris/test_project_runtime_evidence.py' }
  Invoke-Checked 'project-ma-precision-tests' { & $PythonExecutable 'scripts/doris/test_project_ma_precision.py' }
  Invoke-Checked 'project-rsi-precision-tests' { & $PythonExecutable 'scripts/doris/test_project_rsi_precision.py' }
  Invoke-Checked 'project-rank-reference-tests' { & $PythonExecutable 'scripts/doris/test_project_rank_reference.py' }
  Invoke-Checked 'project-acceptance-contract-tests' { & $PythonExecutable 'scripts/doris/test_project_acceptance.py' }
  Invoke-Checked 'project-performance-evidence-tests' { & $PythonExecutable 'scripts/doris/test_project_performance_evidence.py' }
  Invoke-Checked 'project-resource-stability-contract-tests' { & $PythonExecutable 'scripts/doris/test_project_resource_stability.py' }
  Invoke-Checked 'project-delivery-integrity-tests' { & $PythonExecutable 'scripts/doris/test_package_project_delivery.py' }
  $projectWindowOutput = Join-Path $repo ('target/project-window-boundaries-' + [Guid]::NewGuid().ToString('N') + '.json')
  $projectJava = (Get-Command java -ErrorAction Stop).Source
  Invoke-Checked 'project-window-boundaries' {
    & $PythonExecutable 'scripts/doris/check_project_window_boundaries.py' '--output' $projectWindowOutput '--java' $projectJava
  }
  $checks['project-window-boundaries']['outputPath'] = $projectWindowOutput
  $projectRsiOutput = Join-Path $repo ('target/project-rsi-boundaries-' + [Guid]::NewGuid().ToString('N') + '.json')
  Invoke-Checked 'project-rsi-tail-boundaries' {
    & $PythonExecutable 'scripts/doris/check_project_rsi_tail.py' '--output' $projectRsiOutput '--java' $projectJava
  }
  $checks['project-rsi-tail-boundaries']['outputPath'] = $projectRsiOutput
  $projectAvailabilityOutput = Join-Path $repo ('target/project-availability-' + [Guid]::NewGuid().ToString('N') + '.json')
  Invoke-Checked 'project-availability-explanations' {
    & $PythonExecutable 'scripts/doris/check_project_availability.py' '--output' $projectAvailabilityOutput '--java' $projectJava
  }
  $checks['project-availability-explanations']['outputPath'] = $projectAvailabilityOutput
  $projectFieldsOutput = Join-Path $repo ('target/project-fields-' + [Guid]::NewGuid().ToString('N') + '.json')
  Invoke-Checked 'project-field-boundaries' {
    & $PythonExecutable 'scripts/doris/check_project_fields.py' '--output' $projectFieldsOutput '--java' $projectJava
  }
  $checks['project-field-boundaries']['outputPath'] = $projectFieldsOutput
  $projectCombinationsOutput = Join-Path $repo ('target/project-combinations-' + [Guid]::NewGuid().ToString('N') + '.json')
  Invoke-Checked 'project-combination-boundaries' {
    & $PythonExecutable 'scripts/doris/check_project_combinations.py' '--output' $projectCombinationsOutput '--java' $projectJava
  }
  $checks['project-combination-boundaries']['outputPath'] = $projectCombinationsOutput
  $projectRankOutput = Join-Path $repo ('target/project-rank-combinations-' + [Guid]::NewGuid().ToString('N') + '.json')
  Invoke-Checked 'project-rank-combination-boundaries' {
    & $PythonExecutable 'scripts/doris/check_project_rank_combinations.py' '--output' $projectRankOutput '--java' $projectJava
  }
  $checks['project-rank-combination-boundaries']['outputPath'] = $projectRankOutput
  Invoke-Checked 'sentinel-window-boundaries' { & $PythonExecutable 'scripts/accuracy/check_contract_boundaries.py' }
  Invoke-Checked 'historical-extrema-boundaries' { & $PythonExecutable 'scripts/accuracy/check_historical_extrema.py' }
  Invoke-Checked 'rolling-average-boundaries' { & $PythonExecutable 'scripts/accuracy/check_rolling_averages.py' }
  Invoke-Checked 'formal-compiler-p95' {
    & java '-jar' 'target/dsl-doris-compiler.jar' 'benchmark-stock-slot-compiler' `
      '--corpus' 'benchmarks/compiler/stock-slot-complex-v1.json' '--warmup' '1000' `
      '--iterations' '5000' '--p95-threshold-ms' '50' `
      '--json-output' 'reports/compiler-performance/latest.json' `
      '--markdown-output' 'reports/compiler-performance/latest.md'
  }

  if ($WithDoris -or $RunNineteenYearBenchmark) {
    if ([string]::IsNullOrWhiteSpace($env:DORIS_PASSWORD)) { throw 'DORIS_PASSWORD is required for Doris tests' }
    Invoke-Checked 'doris-golden-result-differential' {
      & $PythonExecutable 'scripts/accuracy/run_correctness.py' '--container' $DorisContainer `
        '--docker' $DockerExecutable '--user' $DorisUser '--mysql-port' "$MySqlPort"
    }
    Invoke-Checked 'doris-12-function-smoke' {
      & $PythonExecutable 'scripts/accuracy/run_function_smoke.py' '--container' $DorisContainer `
        '--docker' $DockerExecutable '--user' $DorisUser '--mysql-port' "$MySqlPort"
    }
  } else {
    $checks['doris-golden-result-differential'] = [ordered]@{ status = 'NOT_RUN'; reason = 'Use -WithDoris and set DORIS_PASSWORD' }
    $checks['doris-12-function-smoke'] = [ordered]@{ status = 'NOT_RUN'; reason = 'Use -WithDoris and set DORIS_PASSWORD' }
  }

  if ($RunNineteenYearBenchmark) {
    Invoke-Checked 'doris-19-year-matrix' {
      & java '-jar' 'target/dsl-doris-compiler.jar' 'benchmark-matrix' `
        '--matrix' 'benchmarks/doris-matrix-v1.json' '--user' $BenchmarkUser `
        '--iterations' '30' '--cold-restart-container' $DorisContainer `
        '--evidence-dir' 'reports/benchmark-matrix/evidence' `
        '--json-output' 'reports/benchmark-matrix/report.json' `
        '--markdown-output' 'reports/benchmark-matrix/report.md'
    }
  } else {
    $checks['doris-19-year-matrix'] = [ordered]@{ status = 'NOT_RUN'; reason = 'Use -RunNineteenYearBenchmark (long-running: 720 container restarts)' }
  }

  if ($WithProjectDoris) {
    $projectTransportOutput = Join-Path $repo ('target/wsl-transport-' + [Guid]::NewGuid().ToString('N') + '.json')
    Invoke-Checked 'wsl-authentication-and-be-memory-shell-tests' {
      & $PythonExecutable 'scripts/doris/test_wsl_transport.py' '--shell-distribution' $ProjectDistribution '--output' $projectTransportOutput
    }
    $checks['wsl-authentication-and-be-memory-shell-tests']['outputPath'] = $projectTransportOutput
    if (-not $ProjectReportDir) {
      $ProjectReportDir = Join-Path $repo ('reports/project-acceptance/selftest-' + [Guid]::NewGuid().ToString('N'))
    }
    $projectArgs = @('scripts/doris/run_project_acceptance.py', '--with-doris', '--report-dir', $ProjectReportDir,
      '--distribution', $ProjectDistribution, '--java', $projectJava, '--rounds', "$ProjectRounds")
    if ($ProjectDataRoot) { $projectArgs += @('--data-root', $ProjectDataRoot) }
    if ($ProjectReferenceDatabase) { $projectArgs += @('--reference-database', $ProjectReferenceDatabase) }
    if ($ProjectRestart) { $projectArgs += '--restart' }
    & $PythonExecutable @projectArgs
    $projectExit = $LASTEXITCODE
    $projectSummaryPath = Join-Path $ProjectReportDir 'project-summary.json'
    if (-not (Test-Path -LiteralPath $projectSummaryPath)) { throw 'Project acceptance did not publish its machine summary' }
    $projectSummary = Get-Content -LiteralPath $projectSummaryPath -Raw | ConvertFrom-Json
    if ($projectExit -eq 2 -and $projectSummary.status -eq 'NOT_RUN') {
      $checks['project-real-acceptance'] = [ordered]@{ status = 'NOT_RUN'; reason = 'Explicit project environment precheck failed; see retained summary'; outputPath = $projectSummaryPath }
    } elseif ($projectExit -eq 0 -and $projectSummary.status -eq 'PROJECT_PASS_FORMAL_BLOCKED') {
      $checks['project-real-acceptance'] = [ordered]@{ status = 'PASS'; reason = 'Project scope passed; formal acceptance remains BLOCKED'; outputPath = $projectSummaryPath }
    } else {
      throw "Project acceptance exit/status mismatch or failure: exit=$projectExit status=$($projectSummary.status)"
    }
    $global:LASTEXITCODE = 0
  } else {
    $checks['project-real-acceptance'] = [ordered]@{ status = 'NOT_RUN'; reason = 'Use -WithProjectDoris with immutable source files, raw reference database and the explicit WSL/Doris environment' }
  }
} catch {
  $checks['failure'] = [ordered]@{ status = 'FAIL'; message = $_.Exception.Message }
  throw
} finally {
  Pop-Location
  $summary = [ordered]@{
    suiteVersion = 'automated-acceptance-v2-project-combinations'
    startedAt = $started.ToString('o')
    completedAt = (Get-Date).ToString('o')
    checks = $checks
  }
  $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reportDir 'latest.json') -Encoding UTF8
  $lines = @(
    '# 自动化验收结果', '',
    "- Suite: ``$($summary.suiteVersion)``",
    "- Started: ``$($summary.startedAt)``",
    "- Completed: ``$($summary.completedAt)``", '',
    '| Check | Status | Detail |', '|---|---|---|'
  )
  foreach ($entry in $checks.GetEnumerator()) {
    $detail = if ($entry.Value.Contains('elapsedSeconds')) { "$($entry.Value.elapsedSeconds) s" }
      elseif ($entry.Value.Contains('reason')) { $entry.Value.reason }
      elseif ($entry.Value.Contains('message')) { $entry.Value.message } else { '' }
    $detail = ([string]$detail).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
    $lines += "| $($entry.Key) | $($entry.Value.status) | $detail |"
  }
  $lines += @('', '> `NOT_RUN` 表示缺少明确要求的外部环境或未启用长耗时模式，不计为通过。')
  $lines | Set-Content -LiteralPath (Join-Path $reportDir 'latest.md') -Encoding UTF8
}

Write-Host "AUTOMATED_TESTS_OK: $(Join-Path $reportDir 'latest.json')"
