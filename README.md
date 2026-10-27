# Claude Recent Chats

A small **Recent chats** panel that snaps to the left edge of the Claude desktop app on Windows.

The Code tab's sidebar groups chats into folders, but has no list of the chats you used most recently across all groups. This panel adds one: every chat, newest first, with its sidebar group and how long ago you used it. Click a chat to open it.

- Snaps to the Claude window's left edge, moves and resizes with it, and hides when Claude is minimised
- Lists your 40 most recent chats from every group, updating every few seconds
- Click a chat to open it in Claude
- Read-only: it never changes your chats, groups or the Claude window

## Requirements

- Windows 10 or 11
- The Claude desktop app (Code tab)
- Python 3.9+ with tkinter (included in the python.org installer)

## Run it

```bash
pythonw recent_chats.pyw
```

`pythonw` runs it without a console window. Close it with the ✕ at the top of the panel.

### Start it with Windows

Press `Win + R`, type `shell:startup`, press Enter, and put a shortcut there with:

- Target: `pythonw.exe "C:\path\to\recent_chats.pyw"`
- Start in: the folder that holds `recent_chats.pyw`

## How it works

- Chat titles and last-used times come from the app's session files in `%APPDATA%\Claude\claude-code-sessions`.
- Sidebar groups come from the app's settings in `%APPDATA%\Claude\claude_desktop_config.json`.
- Clicking a chat opens `claude://claude.ai/epitaxy/<session id>`, which Windows hands to the Claude app.
- The panel is owned by the Claude window, so it stays just above it and hides when it does. It snaps to the window's visible edge and covers its 1-pixel border, so the two look like one window.

Nothing is sent anywhere; the panel only reads files on your own computer.

## Settings

At the top of `recent_chats.pyw`:

- `WIDTH`: panel width (at 100% scaling)
- `SHOW`: how many chats to list
- `BG`, `TEXT`, `DIM`, `ROW_HOVER`: colours

## Caveats

This is an unofficial tool, not made by Anthropic. It reads the desktop app's internal files, so an app update that changes them can break it until the panel is updated.

## License

MIT
