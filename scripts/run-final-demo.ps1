[CmdletBinding()]
param(
  [ValidateSet('Live','HistoricalEvidence')][string]$DorisMode = 'Live',
  [string]$MavenExecutable = 'mvn.cmd',
  [switch]$SkipBuild,
  [switch]$SkipCompilerBenchmark,
  [string]$HostAddress = '127.0.0.1',
  [int]$MySqlPort = 9030,
  [string]$User = 'dsl_runtime_reader',
  [string]$SnapshotId = 'stock-20060104-20260414-v1',
  [int]$BenchmarkIterations = 5,
  [string]$Output = 'reports/demo/latest.md'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$jar = Join-Path $repo 'target\dsl-doris-compiler.jar'
$reportDir = Join-Path $repo 'reports\demo'
$compileJson = Join-Path $reportDir 'formal-complex-compilation.json'
$executionJson = Join-Path $reportDir 'live-execution.json'
$executionMarkdown = Join-Path $reportDir 'live-execution.md'
$benchmarkJson = Join-Path $reportDir 'live-performance.json'
$extensionJson = Join-Path $reportDir 'config-only-compilation.json'
$summaryJson = Join-Path $reportDir 'latest.json'
$changedFiles = Join-Path $reportDir 'config-only-changed-files.txt'

function Invoke-Checked([string]$Program, [string[]]$Arguments, [string]$Label) {
  & $Program @Arguments
  if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

function Get-TextSha256([string]$Text) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
  } finally { $sha.Dispose() }
}

function Get-CoreFingerprint {
  $roots = @((Join-Path $repo 'src\main\java'), (Join-Path $repo 'src\main\antlr4'))
  $entries = foreach ($root in $roots) {
    Get-ChildItem -LiteralPath $root -Recurse -File | Sort-Object FullName | ForEach-Object {
      $relative = $_.FullName.Substring($repo.Length + 1).Replace('\', '/')
      "$relative|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
    }
  }
  return Get-TextSha256 ($entries -join "`n")
}

function Escape-Markdown([object]$Value) {
  if ($null -eq $Value) { return '' }
  return ([string]$Value).Replace('|', '\|').Replace("`r", '').Replace("`n", '<br>')
}

function Add-CodeBlock([Collections.Generic.List[string]]$Lines, [string]$Language, [string]$Content) {
  $Lines.Add("``````$Language")
  foreach ($line in ($Content -split "`r?`n")) { $Lines.Add($line) }
  $Lines.Add('```')
  $Lines.Add('')
}

New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
Push-Location $repo
try {
  if (-not $SkipBuild) {
    Invoke-Checked $MavenExecutable @('-B','test','package') 'Maven build/test'
  }
  if (-not (Test-Path -LiteralPath $jar -PathType Leaf)) {
    throw "Missing executable JAR: $jar. Run without -SkipBuild or provide -MavenExecutable."
  }

  Write-Host '[1/7] Compile the formal complex DSL'
  Invoke-Checked 'java' @('-jar',$jar,'compile-stock-slot-sql','examples/final-demo-complex.dsl',
    '--format','json','-o',$compileJson) 'formal DSL compilation'
  $artifact = Get-Content -LiteralPath $compileJson -Raw | ConvertFrom-Json
  if ($artifact.dslVersion -ne 'stock-slot-v1' -or -not $artifact.sql -or $artifact.bindings.Count -lt 1) {
    throw 'Formal compilation artifact is incomplete.'
  }

  Write-Host '[2/7] Collect AST, rule trace, logical plan and parameterized SQL'
  $accessNode = @($artifact.logicalPlan | Where-Object { $_.kind -in @('FeatureScan','HistoryScan','Scan') } | Select-Object -First 1)
  $accessDetail = if ($accessNode.Count -gt 0) { "$($accessNode[0].kind): $($accessNode[0].detail)" } else { 'not reported' }
  $ruleTrace = @(
    [ordered]@{ phase='PARSE'; input='stock-slot-v1 source'; output='Typed AST'; action='ANTLR parse with source spans' },
    [ordered]@{ phase='NORMALIZE'; input='SemanticModel'; output='SemanticModel'; action='stable normalization hook; identity for an already canonical typed tree' },
    [ordered]@{ phase='LOWER'; input='typed indicator/rank calls'; output='registered expressions'; action='registry mapping, scale and sentinel policy' },
    [ordered]@{ phase='ACCESS_PATH'; input='registered expressions'; output='logical scan path'; action=$accessDetail },
    [ordered]@{ phase='PARAMETERIZE'; input='typed literals'; output='JDBC placeholders'; action="$($artifact.bindings.Count) bound values; no user literal concatenation" }
  )

  Write-Host '[3/7] Execute on Doris and return securities'
  $evidenceKind = $DorisMode
  if ($DorisMode -eq 'Live') {
    if ([string]::IsNullOrWhiteSpace($env:DORIS_PASSWORD)) {
      throw 'Live mode requires DORIS_PASSWORD in this PowerShell process.'
    }
    Invoke-Checked 'java' @('-jar',$jar,'execute-stock-slot-sql','examples/final-demo-complex.dsl',
      '--host',$HostAddress,'--port',"$MySqlPort",'--user',$User,'--snapshot-id',$SnapshotId,
      '--timeout-seconds','10','--max-rows','20','--format','json','-o',$executionJson) 'live Doris execution'
    Invoke-Checked 'java' @('-jar',$jar,'execute-stock-slot-sql','examples/final-demo-complex.dsl',
      '--host',$HostAddress,'--port',"$MySqlPort",'--user',$User,'--snapshot-id',$SnapshotId,
      '--timeout-seconds','10','--max-rows','20','--format','markdown','-o',$executionMarkdown) 'live Doris Markdown execution'
    $execution = Get-Content -LiteralPath $executionJson -Raw | ConvertFrom-Json
  } else {
    $historicalExecution = Join-Path $repo 'reports\performance\doris-execution-smoke.json'
    if (-not (Test-Path -LiteralPath $historicalExecution)) { throw "Missing historical execution evidence: $historicalExecution" }
    $execution = Get-Content -LiteralPath $historicalExecution -Raw | ConvertFrom-Json
  }

  Write-Host '[4/7] Compare full scan and optimized path with identical results'
  if ($DorisMode -eq 'Live') {
    Invoke-Checked 'java' @('-jar',$jar,'benchmark-doris','examples/performance-long-cycle.dsl',
      '--host',$HostAddress,'--port',"$MySqlPort",'--user',$User,'--snapshot-id',$SnapshotId,
      '--warmup','1','--iterations',"$BenchmarkIterations",'--timeout-seconds','10',
      '--baseline-timeout-seconds','120','-o',$benchmarkJson) 'live Doris benchmark'
    $benchmark = Get-Content -LiteralPath $benchmarkJson -Raw | ConvertFrom-Json
  } else {
    $historicalBenchmark = Join-Path $repo 'reports\performance\doris-benchmark-long-cycle-v1.json'
    if (-not (Test-Path -LiteralPath $historicalBenchmark)) { throw "Missing historical benchmark evidence: $historicalBenchmark" }
    $benchmark = Get-Content -LiteralPath $historicalBenchmark -Raw | ConvertFrom-Json
  }
  if (-not $benchmark.passed) { throw 'Doris benchmark did not pass all equality, latency and speedup gates.' }

  Write-Host '[5/7] Enforce 19-year speedup and latency gates'
  if (-not $benchmark.fullScanSpeedupAtLeastTen -or -not $benchmark.queryP95AtMost10Seconds) {
    throw "Performance gate failed: speedup=$($benchmark.fullScanSpeedup), queryP95=$($benchmark.query.p95Millis) ms"
  }

  Write-Host '[6/7] Compile one config-only indicator and prove core hash is unchanged'
  $coreBefore = Get-CoreFingerprint
  $pluginPath = 'config/extensions/direct-field/registry-plugin.json'
  $plugin = Get-Content -LiteralPath $pluginPath -Raw | ConvertFrom-Json
  $functionCount = if ($null -eq $plugin.functions) { 0 } else { @($plugin.functions).Count }
  if (@($plugin.fields).Count -ne 1 -or $functionCount -ne 0) {
    throw 'The demo plugin must contain exactly one field indicator and no function implementation.'
  }
  Set-Content -LiteralPath $changedFiles -Value $pluginPath -Encoding UTF8
  Invoke-Checked 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',
    (Join-Path $repo 'scripts\ci\verify-config-only-extension.ps1'),'-ChangedFilesFile',$changedFiles,'-Mode','Config') 'zero-core gate'
  Invoke-Checked 'java' @('-jar',$jar,'compile','examples/final-demo-config-only.dsl','--plugin',$pluginPath,
    '--format','json','-o',$extensionJson) 'config-only indicator compilation'
  $coreAfter = Get-CoreFingerprint
  if ($coreBefore -ne $coreAfter) { throw 'Core source fingerprint changed during the config-only demonstration.' }

  Write-Host '[7/7] Refresh and display accuracy/compiler P95 reports'
  if (-not $SkipCompilerBenchmark) {
    Invoke-Checked 'java' @('-jar',$jar,'benchmark-stock-slot-compiler','--warmup','1000','--iterations','5000',
      '--p95-threshold-ms','50') 'compiler P95 benchmark'
  }
  $compilerReport = Get-Content -LiteralPath 'reports\compiler-performance\latest.json' -Raw | ConvertFrom-Json
  $accuracyReport = Get-Content -LiteralPath 'reports\accuracy\stock-slot-executable-v1\result.json' -Raw | ConvertFrom-Json
  if (-not $compilerReport.passed -or $accuracyReport.overall.accuracy -lt 0.95) {
    throw 'Accuracy or compiler P95 report does not meet the acceptance threshold.'
  }

  $lines = [Collections.Generic.List[string]]::new()
  $lines.Add('# 最终七步演示报告'); $lines.Add('')
  $lines.Add("- Generated: $(Get-Date -Format o)")
  $lines.Add("- Doris evidence mode: **$evidenceKind**")
  if ($DorisMode -eq 'HistoricalEvidence') {
    $lines.Add('- **警告：本报告的 Doris 查询与性能数字来自 2026-09-18 固定快照历史证据，不是本轮实时执行。正式演示必须使用 `-DorisMode Live`。**')
  }
  $lines.Add('')
  $lines.Add('## 1. 正式复杂 DSL'); $lines.Add('')
  Add-CodeBlock $lines 'text' (Get-Content -LiteralPath 'examples\final-demo-complex.dsl' -Raw)
  $lines.Add('## 2. Typed AST、规则轨迹、逻辑计划和参数化 SQL'); $lines.Add('')
  $lines.Add('### Typed AST / Semantic Model'); $lines.Add('')
  Add-CodeBlock $lines 'json' ($artifact.semanticModel | ConvertTo-Json -Depth 30)
  $lines.Add('### 规则与转换轨迹'); $lines.Add('')
  $lines.Add('| Phase | Input | Output | Action |'); $lines.Add('|---|---|---|---|')
  foreach ($trace in $ruleTrace) {
    $lines.Add("| $($trace.phase) | $(Escape-Markdown $trace.input) | $(Escape-Markdown $trace.output) | $(Escape-Markdown $trace.action) |")
  }
  $lines.Add(''); $lines.Add('> `NORMALIZE` 是正式 DSL 当前真实的稳定规则钩子；输入已经规范化时保持恒等，不虚构未执行的重写。'); $lines.Add('')
  $lines.Add('### 逻辑计划'); $lines.Add(''); $lines.Add('| # | Node | Detail |'); $lines.Add('|---:|---|---|')
  $index = 1
  foreach ($node in $artifact.logicalPlan) { $lines.Add("| $index | $($node.kind) | $(Escape-Markdown $node.detail) |"); $index++ }
  $lines.Add(''); $lines.Add('### 参数绑定'); $lines.Add('')
  $lines.Add('| Index | Value |'); $lines.Add('|---:|---|')
  for ($i=0; $i -lt $artifact.bindings.Count; $i++) { $lines.Add("| $($i+1) | ``$(Escape-Markdown $artifact.bindings[$i])`` |") }
  $lines.Add(''); $lines.Add('### SQL'); $lines.Add(''); Add-CodeBlock $lines 'sql' ([string]$artifact.sql)

  $step3Title = if ($DorisMode -eq 'Live') { '## 3. Doris 股票结果' } else { '## 3. Doris 股票结果（实时步骤 NOT_RUN）' }
  $lines.Add($step3Title); $lines.Add('')
  if ($DorisMode -eq 'HistoricalEvidence') {
    $lines.Add('> 以下行为历史 `registry-smoke.dsl` 冒烟证据，仅验证结果展示格式；它不是第 1 步复杂 DSL 的执行结果，不能作为实时演示通过证据。')
    $lines.Add('')
  }
  $lines.Add("| Evidence | Status | Snapshot | Rows shown | Query ms |")
  $lines.Add('|---|---|---|---:|---:|')
  $queryMillis = if ($null -ne $execution.queryMillis) { $execution.queryMillis } elseif ($execution.timings) { $execution.timings.dorisExecutionMillis } else { '' }
  $executionStatus = if ($DorisMode -eq 'Live') { 'PASS' } else { 'HISTORICAL_REFERENCE_ONLY' }
  $lines.Add("| $evidenceKind | $executionStatus | ``$SnapshotId`` | $(@($execution.rows).Count) | $queryMillis |")
  $lines.Add(''); $lines.Add('| mktcode | tgtcode |'); $lines.Add('|---|---|')
  foreach ($row in @($execution.rows | Select-Object -First 20)) { $lines.Add("| $($row[0]) | $($row[1]) |") }
  $lines.Add('')

  $lines.Add('## 4–5. 同结果基线、优化路径与19年性能'); $lines.Add('')
  $lines.Add('| Check | Value | Gate | Result |'); $lines.Add('|---|---:|---:|---|')
  $lines.Add("| Optimized P95 | $($benchmark.query.p95Millis) ms | ≤ 10000 ms | PASS |")
  $lines.Add("| Full-scan P95 | $($benchmark.fullScanBaseline.p95Millis) ms | reference | PASS |")
  $lines.Add("| Speedup | $([math]::Round([double]$benchmark.fullScanSpeedup,4))x | ≥ 10x | PASS |")
  $lines.Add("| Result equality | enforced for $($benchmark.iterations) iteration(s) | identical rows/order | PASS |")
  $lines.Add('')

  $lines.Add('## 6. 单指标配置扩展，核心代码 0 行改动'); $lines.Add('')
  $lines.Add('| Item | Value |'); $lines.Add('|---|---|')
  $lines.Add("| Added config | ``$pluginPath`` |")
  $lines.Add("| Indicator | ``$($plugin.fields[0].name)`` |")
  $lines.Add('| Compile | PASS |')
  $lines.Add('| CI allow-list gate | PASS |')
  $lines.Add("| Core fingerprint before | ``sha256:$coreBefore`` |")
  $lines.Add("| Core fingerprint after | ``sha256:$coreAfter`` |")
  $lines.Add('| Core code changes during demo | **0** |'); $lines.Add('')

  $lines.Add('## 7. 正确率与编译 P95'); $lines.Add('')
  $lines.Add('| Report | Value | Gate | Result |'); $lines.Add('|---|---:|---:|---|')
  $lines.Add("| Golden accuracy | $([math]::Round(100*[double]$accuracyReport.overall.accuracy,2))% ($($accuracyReport.overall.correct)/$($accuracyReport.overall.total)) | ≥ 95% | PASS |")
  $lines.Add("| Uncached compiler P95 | $($compilerReport.uncachedPipeline.stages.total.p95) ms | < 50 ms | PASS |")
  $lines.Add("| Compiler iterations | $($compilerReport.uncachedPipeline.iterations) | ≥ 5000 | PASS |")
  $lines.Add('')
  $lines.Add('## 总结'); $lines.Add('')
  $overall = if ($DorisMode -eq 'Live') { 'PASS（本轮实时 Doris）' } else { 'PARTIAL_PASS（脚本/编译器通过；实时 Doris 步骤 NOT_RUN）' }
  $lines.Add("**$overall**")

  $outputPath = [IO.Path]::GetFullPath((Join-Path $repo $Output))
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
  $lines | Set-Content -LiteralPath $outputPath -Encoding UTF8
  [ordered]@{
    generatedAt=(Get-Date -Format o); dorisMode=$DorisMode; overall=$overall
    liveDorisExecution=($(if ($DorisMode -eq 'Live') { 'PASS' } else { 'NOT_RUN' }))
    formalCompilation='PASS'; resultRows=@($execution.rows).Count
    optimizedP95Millis=$benchmark.query.p95Millis; baselineP95Millis=$benchmark.fullScanBaseline.p95Millis
    speedup=$benchmark.fullScanSpeedup; resultEquality='PASS'
    configOnlyCompile='PASS'; coreChanges=0; coreFingerprint=$coreAfter
    accuracy=$accuracyReport.overall.accuracy; compilerP95Millis=$compilerReport.uncachedPipeline.stages.total.p95
    markdown=$outputPath
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryJson -Encoding UTF8
  Write-Host "FINAL_DEMO_OK mode=$DorisMode report=$outputPath"
} finally {
  Pop-Location
}
