@echo off
title Omnipuls setup
cd /d "%~dp0"

rem ---- find Python (installs it with winget if missing) ----
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python is not installed. Installing Python 3.12 now...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo Could not install Python automatically.
    echo Download it from https://www.python.org/downloads/ and tick "Add Python to PATH".
    pause
    exit /b 1
  )
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

rem ---- private environment for the app, created once ----
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Omnipuls for the first time...
  %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Could not create the app environment. Starting with the system Python instead.
  %PY% app.py
  pause
  exit /b
)

rem ---- install anything missing (shows progress here) and add the desktop shortcut ----
".venv\Scripts\python.exe" app.py --install-only
if errorlevel 1 (
  pause
  exit /b 1
)

rem ---- start the app in its own window; this console closes ----
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0
