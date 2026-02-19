$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $repoRoot "src"
$tmpRoot = Join-Path $repoRoot ".tmp_pytest"
$baseTemp = Join-Path $tmpRoot "basetemp"

if ($env:PYTHONPATH) {
  $env:PYTHONPATH = "$srcDir;$($env:PYTHONPATH)"
}
else {
  $env:PYTHONPATH = $srcDir
}

New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
New-Item -ItemType Directory -Path $baseTemp -Force | Out-Null

$env:TMP = $tmpRoot
$env:TEMP = $tmpRoot
$env:TMPDIR = $tmpRoot

$xdist = @()
if ($env:MMO_PYTEST_N) {
  $xdistCheckExit = 1
  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    & python -c "import xdist" *> $null
    if ($null -ne $LASTEXITCODE) {
      $xdistCheckExit = $LASTEXITCODE
    }
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($xdistCheckExit -ne 0) {
    [Console]::Error.WriteLine("MMO_PYTEST_N is set but pytest-xdist is not installed. Install dev deps.")
    exit 2
  }
  $xdist = @('-n', $env:MMO_PYTEST_N, '--dist', 'loadscope')
}

& python -m pytest @xdist @args --basetemp $baseTemp
exit $LASTEXITCODE
