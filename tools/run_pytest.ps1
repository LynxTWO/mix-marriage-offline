$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tmpRoot = Join-Path $repoRoot ".tmp_pytest"
$baseTemp = Join-Path $tmpRoot "basetemp"

New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
New-Item -ItemType Directory -Path $baseTemp -Force | Out-Null

$env:TMP = $tmpRoot
$env:TEMP = $tmpRoot
$env:TMPDIR = $tmpRoot

$xdist = @()
if ($env:MMO_PYTEST_N) {
  $xdist = @('-n', $env:MMO_PYTEST_N, '--dist', 'loadscope')
}

& python -m pytest @xdist @args --basetemp $baseTemp
exit $LASTEXITCODE
