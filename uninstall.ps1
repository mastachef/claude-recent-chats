# Claude Recent Chats uninstaller (Windows).
#   irm https://raw.githubusercontent.com/mastachef/claude-recent-chats/main/uninstall.ps1 | iex
# Stops the panel, removes it from Windows startup and deletes its folder. Your chats are not touched.

$Dir = Join-Path $env:LOCALAPPDATA 'ClaudeRecentChats'
$Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Claude Recent Chats.lnk'

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*$Dir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
if (Test-Path $Lnk) { Remove-Item $Lnk -Force }
if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
Write-Host 'Claude Recent Chats removed.' -ForegroundColor Green
