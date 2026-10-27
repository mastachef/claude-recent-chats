"""Recent Chats: a small panel that sticks to the left edge of the Claude desktop window.

Lists every Code chat, most recently used first, with its sidebar group. Click a chat to open it
(uses the chat's claude:// link, which Windows hands to the Claude app). Read-only: it never
changes chats, groups or the Claude window.

Run:  pythonw recent_chats.pyw          (pythonw = no console window)
      pythonw recent_chats.pyw --demo   (sample chats, for screenshots)
"""
import ctypes, ctypes.wintypes as w, json, os, sys, threading, time
import tkinter as tk

WIDTH = 270           # panel width at 100% display scaling
SHOW = 40             # how many chats to list
APPDATA = os.environ['APPDATA']
SESSIONS = os.path.join(APPDATA, 'Claude', 'claude-code-sessions')
CONFIG = os.path.join(APPDATA, 'Claude', 'claude_desktop_config.json')

BG, ROW_HOVER, TEXT, DIM, ACCENT = '#1f1f1e', '#2c2c2a', '#e8e6e1', '#8f8d88', '#d97757'

u = ctypes.windll.user32
k = ctypes.windll.kernel32
dwm = ctypes.windll.dwmapi
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor: window rects in real pixels
except Exception:
    pass
u.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
u.SetWindowLongPtrW.restype = ctypes.c_ssize_t

# Windows events used to follow the Claude window the moment it moves (no polling lag).
EVENT_MINIMIZESTART, EVENT_MINIMIZEEND, EVENT_LOCATIONCHANGE = 0x0016, 0x0017, 0x800B
WinEventProc = ctypes.WINFUNCTYPE(None, w.HANDLE, w.DWORD, w.HWND, w.LONG, w.LONG, w.DWORD, w.DWORD)
u.SetWinEventHook.restype = w.HANDLE
u.SetWinEventHook.argtypes = [w.DWORD, w.DWORD, w.HMODULE, WinEventProc, w.DWORD, w.DWORD, w.DWORD]


def find_claude():
    """The Claude app's main window (largest claude.exe top-level window) and its process id."""
    best = []

    def cb(h, _):
        if not u.IsWindowVisible(h) and not u.IsIconic(h):
            return True
        pid = w.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        hp = k.OpenProcess(0x1000, False, pid.value)
        exe = ctypes.create_unicode_buffer(260); sz = w.DWORD(260)
        k.QueryFullProcessImageNameW(hp, 0, exe, ctypes.byref(sz)); k.CloseHandle(hp)
        if os.path.basename(exe.value).lower() == 'claude.exe':
            r = w.RECT(); u.GetWindowRect(h, ctypes.byref(r))
            best.append(((r.right - r.left) * (r.bottom - r.top), h, pid.value))
        return True

    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)(cb), 0)
    return max(best)[1:] if best else (None, 0)


def groups_from(cfg):
    """sessionId -> group name, from the app's sidebar settings."""
    out = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        if isinstance(node.get('groups'), list) and isinstance(node.get('order'), dict):
            names = {g.get('id'): g.get('name', '') for g in node['groups'] if isinstance(g, dict)}
            for gid, members in node['order'].items():
                for m in members if isinstance(members, list) else []:
                    out[str(m).split(':', 1)[-1]] = names.get(gid, '')
            return
        for v in node.values():
            walk(v)

    try:
        walk(cfg['preferences']['epitaxyPrefs']['dframe-group-scopes'])
    except Exception:
        pass
    return out


DEMO = [  # (minutes ago, title, group): shown with --demo, for screenshots
    (0, 'Landing page redesign', 'Website'), (2, 'Fix flaky checkout tests', 'Shop backend'),
    (9, 'Boss fight animations', 'Game'), (24, 'Weekly analytics report', 'Data'),
    (51, 'Dark mode for settings', 'Website'), (95, 'Migrate to Postgres 17', 'Shop backend'),
    (180, 'Level 3 lighting pass', 'Game'), (300, 'Onboarding email copy', 'Marketing'),
    (720, 'Rate limiter bug', 'Shop backend'), (1500, 'Trailer shot list', 'Game'),
    (2900, 'Pricing page A/B test', 'Website'), (4400, 'Sales dashboard', 'Data'),
]


class Chats:
    """Reads chat files, re-parsing only the ones whose size or modified time changed."""

    def __init__(self):
        self.files = {}               # path -> ((mtime_ns, size), entry or None)
        self.cfg_stamp = None
        self.groups = {}

    def load(self):
        if '--demo' in sys.argv:
            now = time.time() * 1000
            return [(now - m * 60000, f'demo-{i}', t, g) for i, (m, t, g) in enumerate(DEMO)]
        try:
            st = os.stat(CONFIG); stamp = (st.st_mtime_ns, st.st_size)
            if stamp != self.cfg_stamp:
                self.cfg_stamp = stamp
                with open(CONFIG, encoding='utf-8') as f:
                    self.groups = groups_from(json.load(f))
        except Exception:
            pass
        seen = {}
        for org in _dirs(SESSIONS):
            for acct in _dirs(org):
                with os.scandir(acct) as it:
                    for e in it:
                        if not (e.name.startswith('local_') and e.name.endswith('.json')):
                            continue
                        st = e.stat(); stamp = (st.st_mtime_ns, st.st_size)
                        old = self.files.get(e.path)
                        seen[e.path] = old if old and old[0] == stamp else (stamp, _parse(e.path))
        self.files = seen
        chats = [(t, sid, title, self.groups.get(sid, '')) for _, entry in seen.values() if entry
                 for t, sid, title in [entry]]
        chats.sort(reverse=True)
        return chats[:SHOW]


def _dirs(path):
    try:
        with os.scandir(path) as it:
            return [e.path for e in it if e.is_dir()]
    except OSError:
        return []


def _parse(path):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return None
    if d.get('isArchived') or not d.get('title'):
        return None
    return (d.get('lastActivityAt') or 0, d['sessionId'], d['title'])


def ago(ms):
    m = max(0, int((time.time() * 1000 - ms) / 60000))
    if m < 1: return 'now'
    if m < 60: return f'{m}m'
    if m < 1440: return f'{m // 60}h'
    return f'{m // 1440}d'


class Row:
    """One list row, created once and reused: refreshes only change its text."""

    def __init__(self, parent, on_click):
        self.sid = None
        self.frame = tk.Frame(parent, bg=BG, cursor='hand2')
        self.title = tk.Label(self.frame, bg=BG, fg=TEXT, anchor='w', font=('Segoe UI', 10))
        self.title.pack(fill='x', padx=8, pady=(5, 0))
        self.sub = tk.Label(self.frame, bg=BG, fg=DIM, anchor='w', font=('Segoe UI', 8))
        self.sub.pack(fill='x', padx=8, pady=(0, 5))
        self.shown = ('', '')
        parts = (self.frame, self.title, self.sub)
        for p in parts:
            p.bind('<Button-1>', lambda e: on_click(self.sid))
            p.bind('<Enter>', lambda e: [q.configure(bg=ROW_HOVER) for q in parts])
            p.bind('<Leave>', lambda e: [q.configure(bg=BG) for q in parts])

    def set(self, sid, title, sub):
        self.sid = sid
        if (title, sub) != self.shown:
            self.shown = (title, sub)
            self.title.configure(text=title)
            self.sub.configure(text=sub)


class Panel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # no title bar: it reads as part of Claude
        self.root.configure(bg=BG)
        self.root.update_idletasks()
        self.hwnd = u.GetAncestor(self.root.winfo_id(), 2)   # GA_ROOT: the real top-level window
        self.owner, self.owner_pid, self.hooks = None, 0, []
        self.last_rect = None
        self.hidden = False
        self.chats = Chats()

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill='x', padx=12, pady=(10, 4))
        tk.Label(head, text='Recent', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 11)).pack(side='left')
        close = tk.Label(head, text='✕', bg=BG, fg=DIM, font=('Segoe UI', 10), cursor='hand2')
        close.pack(side='right')
        close.bind('<Button-1>', lambda e: self.root.destroy())

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0, yscrollincrement=24)
        self.canvas.pack(fill='both', expand=True)
        self.list = tk.Frame(self.canvas, bg=BG)
        self.canvas.create_window((0, 0), window=self.list, anchor='nw', tags='list')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure('list', width=e.width))
        self.list.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.root.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(-e.delta // 40, 'units'))
        self.rows = [Row(self.list, self.open_chat) for _ in range(SHOW)]
        self.packed = 0

        self.on_event = WinEventProc(self._event)   # kept on self so it isn't garbage-collected
        self.refresh()
        self.watch()

    def open_chat(self, sid):
        if not sid or sid.startswith('demo-'):
            return
        # Off the UI thread: opening the link can take a moment and must not freeze the panel.
        threading.Thread(target=os.startfile, args=(f'claude://claude.ai/epitaxy/{sid}',), daemon=True).start()

    def refresh(self):
        chats = self.chats.load()
        for row, (t, sid, title, group) in zip(self.rows, chats):
            row.set(sid, title, f'{group or "Ungrouped"} · {ago(t)}')
        n = len(chats)
        for i in range(self.packed, n):
            self.rows[i].frame.pack(fill='x', padx=6)
        for i in range(n, self.packed):
            self.rows[i].frame.pack_forget()
        self.packed = n
        self.root.after(2000, self.refresh)

    def _event(self, hook, event, hwnd, id_object, id_child, thread, ms):
        if hwnd == self.owner and id_object == 0:   # OBJID_WINDOW: the Claude window itself
            self.place()

    def watch(self):
        """Find the Claude window (again, if it was closed or restarted) and hook its moves."""
        if self.owner is None or not u.IsWindow(self.owner):
            for h in self.hooks:
                u.UnhookWinEvent(h)
            self.hooks = []
            self.owner, self.owner_pid = find_claude()
            if self.owner:
                # Owned by Claude: stays just above it, hides when it's minimised.
                u.SetWindowLongPtrW(self.hwnd, -8, self.owner)
                self.root.tk.call('tk', 'scaling', (u.GetDpiForWindow(self.owner) or 96) / 72)
                for lo, hi in ((EVENT_LOCATIONCHANGE, EVENT_LOCATIONCHANGE), (EVENT_MINIMIZESTART, EVENT_MINIMIZEEND)):
                    self.hooks.append(u.SetWinEventHook(lo, hi, None, self.on_event, self.owner_pid, 0, 0))
                self.last_rect = None
        self.place()   # safety net in case an event was missed
        self.root.after(1000 if self.owner else 2000, self.watch)

    def place(self):
        """Snap to the left edge of the Claude window (only ever moves this panel)."""
        if not self.owner or u.IsIconic(self.owner) or not u.IsWindowVisible(self.owner):
            if not self.hidden:
                self.root.withdraw(); self.hidden = True
            self.last_rect = None
            return
        r = w.RECT()
        # The visible edge (DWMWA_EXTENDED_FRAME_BOUNDS = 9), not GetWindowRect, which
        # includes Windows' invisible resize border and leaves a gap.
        if dwm.DwmGetWindowAttribute(self.owner, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            u.GetWindowRect(self.owner, ctypes.byref(r))
        rect = (r.left, r.top, r.right, r.bottom)
        if rect == self.last_rect and not self.hidden:
            return
        self.last_rect = rect
        if self.hidden:
            self.root.deiconify(); self.hidden = False
        width = int(WIDTH * (u.GetDpiForWindow(self.owner) or 96) / 96)
        # +1 covers Claude's own 1px border so the two read as one window.
        # SWP_NOACTIVATE | SWP_NOZORDER: never steals focus or changes stacking.
        u.SetWindowPos(self.hwnd, 0, r.left - width, r.top, width + 1, r.bottom - r.top, 0x14)


if __name__ == '__main__':
    Panel().root.mainloop()
