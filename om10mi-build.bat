@echo off
rem Builds the version 56 card file. Double-click this file.
setlocal
cd /d "%~dp0"
title om10mi build

set "PY="
for %%C in ("py -3" "python" "python3") do (
  if not defined PY (
    %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=%%~C"
  )
)

if not defined PY (
  echo.
  echo Python 3.10 or newer was not found on this computer.
  echo.
  echo Install it, then double-click this file again:
  echo   - download from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  echo   - or run in a terminal:  winget install Python.Python.3.12
  echo.
  echo Or use om10mi-build.exe from the release page, which needs no Python.
  echo.
  pause
  exit /b 1
)

%PY% om10mi.py build --ask-sd
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  if exist "out" start "" explorer "%~dp0out"
)
echo.
pause
exit /b %RC%
