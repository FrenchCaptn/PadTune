@echo off
rem Starts PadTune from source (installs what it needs on first run).
setlocal
cd /d "%~dp0"
title PadTune
rem Messages in French if Windows is in French, otherwise in English
set "FR="
for /f %%l in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do if /i "%%l"=="fr" set "FR=1"

if defined FR (
  set "M_NOPY=Aucune version compatible de Python ^(3.10 a 3.14^) n'a ete trouvee."
  set "M_NOPY2=Installe Python 3.14 ^(Windows installer 64-bit^) en cochant 'Add python.exe to PATH', puis relance ce fichier."
  set "M_FIRST=Premiere utilisation : preparation de l'environnement..."
  set "M_VENVERR=Echec de creation de l'environnement Python."
  set "M_DEPS=Verification des dependances..."
  set "M_DEPSERR=Echec d'installation des dependances."
) else (
  set "M_NOPY=No compatible Python version ^(3.10 to 3.14^) was found."
  set "M_NOPY2=Install Python 3.14 ^(Windows installer 64-bit^), tick 'Add python.exe to PATH', then run this file again."
  set "M_FIRST=First run: setting up the environment..."
  set "M_VENVERR=Could not create the Python environment."
  set "M_DEPS=Checking dependencies..."
  set "M_DEPSERR=Could not install the dependencies."
)

set "PY="
rem Bleak (Bluetooth) has no Python 3.15 build yet: prefer 3.14 down to 3.10
for %%v in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined PY py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
)
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo %M_NOPY%
  echo %M_NOPY2%
  start "" https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo %M_FIRST%
  %PY% -m venv .venv || (echo %M_VENVERR% & pause & exit /b 1)
)

echo %M_DEPS%
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (echo %M_DEPSERR% & pause & exit /b 1)

start "" ".venv\Scripts\pythonw.exe" padtune.py %*
exit /b 0
