@echo off
rem Creates a "PadTune" shortcut (with its icon) on the Desktop and in the Start menu.
setlocal
cd /d "%~dp0"
rem Messages in French if Windows is in French, otherwise in English
set "FR="
for /f %%l in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do if /i "%%l"=="fr" set "FR=1"

if defined FR (
  set "M_FIRST=Lance d'abord Launch.bat une fois pour installer l'application."
  set "M_ERR=La creation du raccourci a echoue."
  set "M_OK=Raccourci PadTune cree sur le Bureau et dans le menu Demarrer."
) else (
  set "M_FIRST=Run Launch.bat once first to install the app."
  set "M_ERR=Could not create the shortcut."
  set "M_OK=PadTune shortcut created on the Desktop and in the Start menu."
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo %M_FIRST%
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0assets\create_shortcut.ps1"
if errorlevel 1 (
  echo %M_ERR%
) else (
  echo %M_OK%
)
pause
