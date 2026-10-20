# Creates a "PadTune" shortcut (with its icon) on the Desktop and in the Start menu.
$app = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $app '.venv\Scripts\pythonw.exe'
$script = Join-Path $app 'padtune.py'
$icon = Join-Path $app 'assets\padtune.ico'
$shell = New-Object -ComObject WScript.Shell
$dirs = @([Environment]::GetFolderPath('Desktop'),
          (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))
foreach ($dir in $dirs) {
    $lnk = $shell.CreateShortcut((Join-Path $dir 'PadTune.lnk'))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '"' + $script + '"'
    $lnk.WorkingDirectory = $app
    $lnk.IconLocation = $icon
    $lnk.Description = 'PadTune - controller settings'
    $lnk.Save()
}
