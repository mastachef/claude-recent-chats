# Claude Recent Chats uninstaller (Windows).
#   irm https://raw.githubusercontent.com/mastachef/claude-recent-chats/main/uninstall.ps1 | iex
# Stops the panel, removes it from Windows startup and deletes its folder. Your chats are not touched.

$Dir = Join-Path $env:LOCALAPPDATA 'ClaudeRecentChats'
$Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Claude Recent Chats.lnk'

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*$Dir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# Take the permission-prompt hook back out of ~/.claude/settings.json.
$App = Join-Path $Dir 'recent_chats.pyw'
if (Test-Path $App) {
    foreach ($try in 'py -3', 'python') {
        $parts = $try -split ' '
        try { & $parts[0] @($parts | Select-Object -Skip 1) $App --remove-hook 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } } catch {}
    }
}
if (Test-Path $Lnk) { Remove-Item $Lnk -Force }
if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
Write-Host 'Claude Recent Chats removed.' -ForegroundColor Green
