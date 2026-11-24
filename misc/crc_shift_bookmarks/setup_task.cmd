@echo off
rem Double-click to install, validate or uninstall the CRC Shift Bookmarks scheduled task.
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0setup_task.ps1" %*
if errorlevel 1 pause
