@echo off
rem Tworzy na pulpicie skrot "Go1 Pilot" z ikona lapy.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Go1 Pilot.lnk')); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0go1pilot.ico'; $s.WindowStyle=7; $s.Description='Sterowanie psem Unitree Go1'; $s.Save(); Write-Host ('Skrot utworzony: ' + (Join-Path $d 'Go1 Pilot.lnk'))"