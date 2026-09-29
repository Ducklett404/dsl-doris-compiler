[CmdletBinding()]
param(
    [string]$BaseRef,
    [string]$HeadRef = 'HEAD',
    [string]$ChangedFilesFile,
    [ValidateSet('Auto', 'Config', 'Spi')]
    [string]$Mode = 'Auto'
)

$ErrorActionPreference = 'Stop'

if ($ChangedFilesFile) {
    if (-not (Test-Path -LiteralPath $ChangedFilesFile -PathType Leaf)) {
        throw "Changed-files input does not exist: $ChangedFilesFile"
    }
    $changed = @(Get-Content -LiteralPath $ChangedFilesFile -Encoding UTF8)
} else {
    if (-not $BaseRef) { throw 'BaseRef is required unless ChangedFilesFile is supplied.' }
    $changed = @(& git diff --name-only --diff-filter=ACMR "$BaseRef...$HeadRef")
    if ($LASTEXITCODE -ne 0) { throw "git diff failed for $BaseRef...$HeadRef" }
}

$changed = @($changed | ForEach-Object { ($_ -replace '\\', '/').Trim() } | Where-Object { $_ } | Sort-Object -Unique)
$extensionSignal = @($changed | Where-Object {
    $_ -match '^config/extensions/' -or
    $_ -match '^src/test/resources/config-only-extensions/' -or
    $_ -eq 'src/main/resources/rewrite-rules.json' -or
    $_ -match '^plugins/'
})

if ($extensionSignal.Count -eq 0) {
    Write-Host 'No extension change detected; config-only gate is not applicable.'
    exit 0
}

if ($Mode -eq 'Auto') {
    $Mode = if ($changed | Where-Object { $_ -match '^plugins/' }) { 'Spi' } else { 'Config' }
}

$allowedPatterns = @(
    '^config/extensions/[^/]+/(registry-plugin|rules|test-vectors)\.json$',
    '^src/test/resources/config-only-extensions/[^/]+\.json$',
    '^src/main/resources/rewrite-rules\.json$'
)
if ($Mode -eq 'Spi') {
    $allowedPatterns += '^plugins/[^/]+/'
}

$violations = @($changed | Where-Object {
    $path = $_
    -not ($allowedPatterns | Where-Object { $path -match $_ })
})

if ($violations.Count -gt 0) {
    Write-Error ("Core-code zero-change gate failed in {0} mode. Disallowed files:`n - {1}" -f
            $Mode, ($violations -join "`n - "))
    exit 1
}

if ($changed | Where-Object { $_ -match '^src/main/(java|antlr4)/' }) {
    Write-Error 'Compiler core or grammar changed; config-only acceptance is invalid.'
    exit 1
}

Write-Host ("Core-code zero-change gate passed: mode={0}, files={1}, coreChanges=0" -f $Mode, $changed.Count)
exit 0
