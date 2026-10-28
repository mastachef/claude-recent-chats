# Claude Recent Chats installer (Windows).
#   irm https://raw.githubusercontent.com/mastachef/claude-recent-chats/main/install.ps1 | iex
# Downloads the panel from the latest release, adds it to Windows startup and starts it.
# Safe to run again: it updates the panel in place.

$ErrorActionPreference = 'Stop'
$Url = 'https://github.com/mastachef/claude-recent-chats/releases/latest/download/recent_chats.pyw'
$Dir = Join-Path $env:LOCALAPPDATA 'ClaudeRecentChats'
$App = Join-Path $Dir 'recent_chats.pyw'
$Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Claude Recent Chats.lnk'

function Fail($msg) { Write-Host "`n[X] $msg" -ForegroundColor Red; throw $msg }

Write-Host 'Installing Claude Recent Chats...' -ForegroundColor Cyan

# 1. Python 3.9+ with tkinter (python.org installs include it).
$python = $null
foreach ($try in 'py -3', 'python') {
    $parts = $try -split ' '
    $extra = @($parts | Select-Object -Skip 1)
    try {
        $exe = & $parts[0] @extra -c "import sys, tkinter; assert sys.version_info >= (3, 9); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $python = $exe.Trim(); break }
    } catch {}
}
if (-not $python) {
    Fail ("Python 3.9+ with tkinter was not found. Install it, then run this again:`n" +
          "    winget install -e --id Python.Python.3.12`n" +
          "or download it from https://www.python.org/downloads/")
}
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { Fail "pythonw.exe not found next to $python" }
Write-Host "[ok] Python: $python"

# 2. Stop a running copy so the file can be replaced.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*recent_chats.pyw*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3. Download the panel.
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Invoke-WebRequest -Uri $Url -OutFile $App -UseBasicParsing
Write-Host "[ok] Installed to $App"

# 4. Hook that tells the panel when a chat shows a permission prompt (the yellow dot).
#    Adds one entry to ~/.claude/settings.json and keeps everything else in it.
& $python $App --install-hook | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host '[ok] Permission-prompt hook added to ~/.claude/settings.json' }
else { Write-Host '[!] Could not add the permission-prompt hook; the panel works without it' -ForegroundColor Yellow }

# 5. Start with Windows.
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($Lnk)
$s.TargetPath = $pythonw
$s.Arguments = "`"$App`""
$s.WorkingDirectory = $Dir
$s.Description = 'Claude Recent Chats panel'
$s.Save()
Write-Host '[ok] Starts with Windows'

# 6. Start it now.
Start-Process -FilePath $pythonw -ArgumentList "`"$App`"" -WorkingDirectory $Dir
Start-Sleep -Seconds 2
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*recent_chats.pyw*' }
if (-not $running) { Fail ("The panel did not start. Run it by hand to see the error: python `"$App`"") }
Write-Host '[ok] Running. Look at the left edge of your Claude window.' -ForegroundColor Green
Write-Host '     Uninstall: irm https://raw.githubusercontent.com/mastachef/claude-recent-chats/main/uninstall.ps1 | iex'
