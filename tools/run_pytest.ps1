$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $repoRoot "src"
$tmpRoot = Join-Path $repoRoot ".tmp_pytest"
$baseTemp = Join-Path $tmpRoot "basetemp"
$pythonBin = $env:MMO_PYTHON_BIN

if (-not $pythonBin) {
  $repoVenvPython = Join-Path $repoRoot ".venv/bin/python"
  $repoVenvPythonWin = Join-Path $repoRoot ".venv/Scripts/python.exe"
  if (Test-Path $repoVenvPython) {
    $pythonBin = $repoVenvPython
  }
  elseif (Test-Path $repoVenvPythonWin) {
    $pythonBin = $repoVenvPythonWin
  }
  else {
    $pythonBin = "python"
  }
}

if ($env:PYTHONPATH) {
  $env:PYTHONPATH = "$srcDir;$($env:PYTHONPATH)"
}
else {
  $env:PYTHONPATH = $srcDir
}

# Mirror the shell runners by forcing repo-local temp roots. That keeps pytest
# artifacts easy to inspect and avoids user-global temp drift.
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
    & $pythonBin -c "import xdist" *> $null
    if ($null -ne $LASTEXITCODE) {
      $xdistCheckExit = $LASTEXITCODE
    }
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($xdistCheckExit -ne 0) {
    # Keep the requested validation mode explicit. Silent serial fallback would
    # hide the missing xdist dependency.
    [Console]::Error.WriteLine("MMO_PYTEST_N is set but pytest-xdist is not installed. Install dev deps.")
    exit 2
  }
  $xdist = @('-n', $env:MMO_PYTEST_N, '--dist', 'loadscope')
}

& $pythonBin -m pytest @xdist @args --basetemp $baseTemp
exit $LASTEXITCODE
