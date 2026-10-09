param(
  [string]$Url = 'https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz',
  [Parameter(Mandatory=$true)][string]$Output,
  [Parameter(Mandatory=$true)][long]$ExpectedBytes,
  [Parameter(Mandatory=$true)][string]$ExpectedSha256,
  [long]$ChunkBytes = 4194304
)
$ErrorActionPreference='Stop'
if ($ChunkBytes -lt 1024 -or $ExpectedBytes -lt 1 -or $ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid download parameters' }
$taskFile = [System.IO.Path]::GetFullPath($Output)
$taskSize = if (Test-Path -LiteralPath $taskFile) { (Get-Item -LiteralPath $taskFile).Length } else { 0 }
if ($taskSize -gt $ExpectedBytes) { throw 'Existing download exceeds expected size; left untouched' }
$taskPartDirectory = $taskFile + '.ranges'
New-Item -ItemType Directory -Path $taskPartDirectory -Force | Out-Null
while ($taskSize -lt $ExpectedBytes) {
  $taskEnd=[Math]::Min($taskSize+$ChunkBytes-1,$ExpectedBytes-1)
  $taskPart=Join-Path $taskPartDirectory "$taskSize-$taskEnd.bin"
  if (-not (Test-Path -LiteralPath $taskPart)) {
    & curl.exe --silent --show-error --fail --location --retry 2 --connect-timeout 10 --max-time 45 --speed-time 20 --speed-limit 1024 --range "$taskSize-$taskEnd" $Url --output $taskPart
    if ($LASTEXITCODE -ne 0) { throw "Range download failed at $taskSize; files preserved" }
  }
  if ((Get-Item -LiteralPath $taskPart).Length -ne ($taskEnd-$taskSize+1)) { throw 'Invalid range size; files preserved' }
  $taskInput=[System.IO.File]::OpenRead($taskPart)
  $taskOutput=[System.IO.File]::Open($taskFile,[System.IO.FileMode]::Append,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
  try { $taskInput.CopyTo($taskOutput) } finally { $taskInput.Dispose(); $taskOutput.Dispose() }
  $taskSize=$taskEnd+1
  Write-Output "ROOTFS_DOWNLOAD $taskSize / $ExpectedBytes"
}
if ((Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Ubuntu SHA256 mismatch; download preserved' }
Write-Output 'UBUNTU_ROOTFS_SHA256_PASS'
