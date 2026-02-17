@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "SRC_DIR=%REPO_ROOT%\src"
if defined PYTHONPATH (
  set "PYTHONPATH=%SRC_DIR%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%SRC_DIR%"
)

for /f "usebackq delims=" %%I in (`python -c "import sys; from pathlib import Path; repo = Path(r'%REPO_ROOT%'); sys.path.insert(0, str(repo / 'src')); from mmo.resources import temp_dir; print(temp_dir())"`) do set "TMP_ROOT=%%I"

if not defined TMP_ROOT (
  echo Failed to resolve repo-local temp directory.
  exit /b 1
)

set "BASE_TEMP=%TMP_ROOT%\basetemp"

if not exist "%TMP_ROOT%" mkdir "%TMP_ROOT%"
if not exist "%BASE_TEMP%" mkdir "%BASE_TEMP%"

set "TMP=%TMP_ROOT%"
set "TEMP=%TMP_ROOT%"
set "TMPDIR=%TMP_ROOT%"

python -m pytest %* --basetemp "%BASE_TEMP%"
exit /b %ERRORLEVEL%
