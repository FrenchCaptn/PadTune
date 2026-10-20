@echo off
rem Builds PadTune.exe (a single file: end users don't need to install Python).
setlocal
cd /d "%~dp0"
title PadTune.exe
rem Messages in French if Windows is in French, otherwise in English
set "FR="
for /f %%l in ('powershell -NoProfile -Command "(Get-UICulture).TwoLetterISOLanguageName" 2^>nul') do if /i "%%l"=="fr" set "FR=1"

if defined FR (
  set "M_NOPY=Python 3.10 a 3.14 est necessaire pour construire l'exe ^(voir LISEZMOI.md^)."
  set "M_TOOLS=Installation des outils de construction..."
  set "M_BUILD=Construction en cours ^(1 a 3 minutes^)..."
  set "M_CHECK=Verification de l'exe..."
  set "M_DONE=Termine :"
  set "M_ERR=La construction a echoue. Copie les messages ci-dessus pour obtenir de l'aide."
) else (
  set "M_NOPY=Python 3.10 to 3.14 is required to build the exe ^(see README.md^)."
  set "M_TOOLS=Installing the build tools..."
  set "M_BUILD=Building ^(1 to 3 minutes^)..."
  set "M_CHECK=Checking the exe..."
  set "M_DONE=Done:"
  set "M_ERR=The build failed. Copy the messages above to get help."
)

set "PY="
rem Bleak (Bluetooth) has no Python 3.15 build yet: prefer 3.14 down to 3.10
for %%v in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined PY py -%%v -c "import sys" >nul 2>nul && set "PY=py -%%v"
)
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo %M_NOPY%
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
echo %M_TOOLS%
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || goto :failed

echo %M_BUILD%
".venv\Scripts\python.exe" -m PyInstaller padtune.spec --noconfirm --clean || goto :failed

echo %M_CHECK%
if exist selftest.json del selftest.json
start "" /wait "dist\PadTune.exe" --selftest selftest.json
findstr /c:"\"ok\": true" selftest.json >nul || (type selftest.json & goto :failed)
del selftest.json

echo.
echo %M_DONE% dist\PadTune.exe
explorer /select,"%~dp0dist\PadTune.exe"
pause
exit /b 0

:failed
echo.
echo %M_ERR%
pause
exit /b 1
