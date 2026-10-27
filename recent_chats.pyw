"""Recent Chats: a small panel that sticks to the left edge of the Claude desktop window.

Lists every Code chat, most recently used first, with its sidebar group. Click a chat to open it
(uses the chat's claude:// link, which Windows hands to the Claude app). Read-only: it never
changes chats, groups or the Claude window.

Run:  pythonw recent_chats.pyw      (pythonw = no console window)
      pythonw recent_chats.pyw --demo   (sample chats, for screenshots)
"""
import ctypes, ctypes.wintypes as w, glob, json, os, sys, time
import tkinter as tk

WIDTH = 270           # panel width in physical pixels (scaled by the monitor's DPI below)
SHOW = 40             # how many chats to list
APPDATA = os.environ['APPDATA']
SESSIONS = os.path.join(APPDATA, 'Claude', 'claude-code-sessions')
CONFIG = os.path.join(APPDATA, 'Claude', 'claude_desktop_config.json')

BG, ROW_HOVER, TEXT, DIM, ACCENT = '#1f1f1e', '#2c2c2a', '#e8e6e1', '#8f8d88', '#d97757'

u = ctypes.windll.user32
k = ctypes.windll.kernel32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor: window rects in real pixels
except Exception:
    pass
u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]


def find_claude():
    """The Claude app's main window (largest visible claude.exe window), or None."""
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
            best.append(((r.right - r.left) * (r.bottom - r.top), h))
        return True

    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)(cb), 0)
    return max(best)[1] if best else None


def load_groups():
    """sessionId -> group name, from the app's sidebar settings."""
    try:
        cfg = json.load(open(CONFIG, encoding='utf-8'))
        scopes = cfg['preferences']['epitaxyPrefs']['dframe-group-scopes']
    except Exception:
        return {}
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

    walk(scopes)
    return out


DEMO = [  # (minutes ago, title, group): shown with --demo, for screenshots
    (0, 'Landing page redesign', 'Website'), (2, 'Fix flaky checkout tests', 'Shop backend'),
    (9, 'Boss fight animations', 'Game'), (24, 'Weekly analytics report', 'Data'),
    (51, 'Dark mode for settings', 'Website'), (95, 'Migrate to Postgres 17', 'Shop backend'),
    (180, 'Level 3 lighting pass', 'Game'), (300, 'Onboarding email copy', 'Marketing'),
    (720, 'Rate limiter bug', 'Shop backend'), (1500, 'Trailer shot list', 'Game'),
    (2900, 'Pricing page A/B test', 'Website'), (4400, 'Sales dashboard', 'Data'),
]


def load_chats():
    if '--demo' in sys.argv:
        now = time.time() * 1000
        return [(now - m * 60000, f'demo-{i}', t, g) for i, (m, t, g) in enumerate(DEMO)]
    groups = load_groups()
    chats = []
    for f in glob.glob(os.path.join(SESSIONS, '*', '*', 'local_*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        if d.get('isArchived') or not d.get('title'):
            continue
        sid = d['sessionId']
        chats.append((d.get('lastActivityAt') or 0, sid, d['title'], groups.get(sid, '')))
    chats.sort(reverse=True)
    return chats[:SHOW]


def ago(ms):
    m = max(0, int((time.time() * 1000 - ms) / 60000))
    if m < 1: return 'now'
    if m < 60: return f'{m}m'
    if m < 1440: return f'{m // 60}h'
    return f'{m // 1440}d'


class Panel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # no title bar: it reads as part of Claude
        self.root.configure(bg=BG)
        self.root.update_idletasks()
        self.hwnd = u.GetAncestor(self.root.winfo_id(), 2)   # GA_ROOT: the real top-level window
        self.owner = None
        self.last_rect = None
        self.signature = None

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill='x', padx=12, pady=(10, 4))
        tk.Label(head, text='Recent', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 11)).pack(side='left')
        close = tk.Label(head, text='✕', bg=BG, fg=DIM, font=('Segoe UI', 10), cursor='hand2')
        close.pack(side='right')
        close.bind('<Button-1>', lambda e: self.root.destroy())

        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.list = tk.Frame(self.canvas, bg=BG)
        self.canvas.create_window((0, 0), window=self.list, anchor='nw', tags='list')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure('list', width=e.width))
        self.list.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.root.bind_all('<MouseWheel>', lambda e: self.canvas.yview_scroll(-e.delta // 120, 'units'))

        self.refresh()
        self.follow()

    def open_chat(self, sid):
        if sid.startswith('demo-'):
            return
        os.startfile(f'claude://claude.ai/epitaxy/{sid}')

    def refresh(self):
        chats = load_chats()
        sig = [(c[1], c[2], c[3], ago(c[0])) for c in chats]
        if sig != self.signature:                 # only redraw when something changed
            self.signature = sig
            for child in self.list.winfo_children():
                child.destroy()
            for _, sid, title, group, when in [(c[0],) + s for c, s in zip(chats, sig)]:
                self.add_row(sid, title, group, when)
        self.root.after(3000, self.refresh)

    def add_row(self, sid, title, group, when):
        row = tk.Frame(self.list, bg=BG, cursor='hand2')
        row.pack(fill='x', padx=6)
        t = tk.Label(row, text=title, bg=BG, fg=TEXT, anchor='w', font=('Segoe UI', 10))
        t.pack(fill='x', padx=8, pady=(5, 0))
        s = tk.Label(row, text=f'{group or "Ungrouped"} · {when}', bg=BG, fg=DIM, anchor='w', font=('Segoe UI', 8))
        s.pack(fill='x', padx=8, pady=(0, 5))
        parts = (row, t, s)
        for p in parts:
            p.bind('<Button-1>', lambda e, i=sid: self.open_chat(i))
            p.bind('<Enter>', lambda e: [q.configure(bg=ROW_HOVER) for q in parts])
            p.bind('<Leave>', lambda e: [q.configure(bg=BG) for q in parts])

    def follow(self):
        """Keep the panel glued to the left edge of the Claude window (only moves itself)."""
        if self.owner is None or not u.IsWindow(self.owner):
            self.owner = find_claude()
            if self.owner:
                # Owned by Claude: stays just above it, hides when it's minimised.
                u.SetWindowLongPtrW(self.hwnd, -8, self.owner)
                dpi = u.GetDpiForWindow(self.owner) or 96
                self.root.tk.call('tk', 'scaling', dpi / 72)
        if not self.owner or u.IsIconic(self.owner):
            self.root.withdraw()
            self.last_rect = None
        else:
            r = w.RECT()
            # The visible edge (DWMWA_EXTENDED_FRAME_BOUNDS = 9), not GetWindowRect, which
            # includes Windows' invisible resize border and leaves a gap.
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(self.owner, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
                u.GetWindowRect(self.owner, ctypes.byref(r))
            rect = (r.left, r.top, r.right, r.bottom)
            if rect != self.last_rect:
                self.last_rect = rect
                dpi = u.GetDpiForWindow(self.owner) or 96
                width = int(WIDTH * dpi / 96)
                self.root.deiconify()
                # SWP_NOACTIVATE (0x10) | SWP_NOZORDER (0x4): never steals focus
                # +1: cover Claude's own 1px left border line so the two read as one window.
                u.SetWindowPos(self.hwnd, 0, r.left - width, r.top, width + 1, r.bottom - r.top, 0x14)
        self.root.after(250, self.follow)


if __name__ == '__main__':
    Panel().root.mainloop()
