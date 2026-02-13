@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

set "TMP_ROOT=%REPO_ROOT%\.tmp_pytest"
set "BASE_TEMP=%TMP_ROOT%\basetemp"

if not exist "%TMP_ROOT%" mkdir "%TMP_ROOT%"
if not exist "%BASE_TEMP%" mkdir "%BASE_TEMP%"

set "TMP=%TMP_ROOT%"
set "TEMP=%TMP_ROOT%"
set "TMPDIR=%TMP_ROOT%"

python -m pytest %* --basetemp "%BASE_TEMP%"
exit /b %ERRORLEVEL%
