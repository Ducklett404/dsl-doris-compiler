param([string]$Distribution='dsl-doris-official-01a104f9')
$ErrorActionPreference='Stop'
if ($Distribution -notmatch '^dsl-doris-official-[a-z0-9]+$') { throw 'Expected the owned project WSL distribution' }
$taskRepo=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if ($taskRepo -notmatch '^([A-Za-z]):\\(.+)$') { throw 'Project must be on a Windows drive mounted in WSL' }
$taskWslRepo='/mnt/'+$Matches[1].ToLower()+'/'+$Matches[2].Replace('\','/')
# Systemd services alone do not keep a WSL distribution alive after commands exit.
$taskKeeper=Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
  $_.CommandLine -like "*-d $Distribution --exec sleep infinity*"
}
if (-not $taskKeeper) {
  Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d',$Distribution,'--exec','sleep','infinity') -WindowStyle Hidden | Out-Null
}
& wsl.exe -d $Distribution --exec env DSL_DORIS_QUERY_PORT=19030 DSL_DORIS_FE_HTTP_PORT=18030 DSL_DORIS_BE_HTTP_PORT=18040 DSL_DORIS_PORT_OFFSET=10000 DSL_DORIS_MEMORY=5g DSL_DORIS_CPUS=4 DSL_DORIS_FE_HEAP=768m DSL_DORIS_BE_HEAP=128m bash "$taskWslRepo/scripts/doris/start-wsl-doris.sh" $taskWslRepo
if ($LASTEXITCODE -ne 0) { throw 'Project Doris readiness failed; existing data is preserved' }
