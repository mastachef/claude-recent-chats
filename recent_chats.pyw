"""Recent Chats: a small panel that sticks to the left edge of the Claude desktop window.

Lists every Code chat, most recently used first, with its sidebar group. Click a chat to open it
(uses the chat's claude:// link, which Windows hands to the Claude app). Read-only: it never
changes chats, groups or the Claude window.

Run:  pythonw recent_chats.pyw          (pythonw = no console window)
      pythonw recent_chats.pyw --demo   (sample chats, for screenshots)
"""
import ctypes, ctypes.wintypes as w, json, math, os, sys, threading, time
import tkinter as tk
import tkinter.font as tkfont

WIDTH = 270           # panel width at 100% display scaling
SHOW = 40             # how many chats to list
APPDATA = os.environ['APPDATA']
SESSIONS = os.path.join(APPDATA, 'Claude', 'claude-code-sessions')
CONFIG = os.path.join(APPDATA, 'Claude', 'claude_desktop_config.json')

BG, ROW_HOVER, TEXT, DIM, ACCENT = '#1f1f1e', '#2c2c2a', '#e8e6e1', '#8f8d88', '#d97757'
UNREAD = '#5ea0ff'    # dot: something new you haven't looked at (in progress = pulsing ACCENT)
STALE_MS = 15 * 60000 # a 'running' chat with no activity this long is treated as stopped

u = ctypes.windll.user32
k = ctypes.windll.kernel32
dwm = ctypes.windll.dwmapi
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor: window rects in real pixels
except Exception:
    pass
u.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u.GetWindow.restype = w.HWND

# Windows events used to follow the Claude window the moment it moves (no polling lag).
EVENT_FOREGROUND, EVENT_MINIMIZESTART, EVENT_MINIMIZEEND, EVENT_LOCATIONCHANGE = 0x0003, 0x0016, 0x0017, 0x800B
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


DEMO_STATUS = {0: 'running', 2: 'unread', 5: 'unread'}   # row -> dot in --demo
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
            return [(now - m * 60000, f'demo-{i}', t, g, DEMO_STATUS.get(i, '')) for i, (m, t, g) in enumerate(DEMO)]
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
        now = time.time() * 1000
        chats = [(e[0], e[1], e[2], self.groups.get(e[1], ''), status(e, now)) for _, e in seen.values() if e]
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
    return (d.get('lastActivityAt') or 0, d['sessionId'], d['title'],
            d.get('lastTurnEdgeAt') or 0, d.get('latestUserFrameAt') or 0, d.get('lastFocusedAt') or 0)


def status(entry, now):
    """'running' while Claude works in the chat, 'unread' if it did something since you last looked.

    A turn is in progress while the last turn edge is the start of your latest message (the edge
    moves past it when the turn ends). Matches the app's own running flag."""
    activity, _, _, edge, user_frame, focused = entry
    if user_frame and edge - user_frame < 2000 and now - activity < STALE_MS:
        return 'running'
    if activity > focused + 1000:
        return 'unread'
    return ''


def fit(font, text, room):
    """Cut text to fit `room` pixels, ending in an ellipsis."""
    if font.measure(text) <= room:
        return text
    while text and font.measure(text + '…') > room:
        text = text[:-1]
    return text.rstrip() + '…'


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
        # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW: clicks never take focus from Claude, no taskbar button.
        u.SetWindowLongPtrW(self.hwnd, -20, u.GetWindowLongPtrW(self.hwnd, -20) | 0x08000000 | 0x80)
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

        # Rows are drawn straight onto one canvas (no widget per row), so fast scrolling stays smooth.
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0, yscrollincrement=8)
        self.canvas.pack(fill='both', expand=True)
        self.title_font = tkfont.Font(family='Segoe UI', size=10)
        self.sub_font = tkfont.Font(family='Segoe UI', size=8)
        # One highlight rectangle that moves to the hovered row (40 row backgrounds doubled redraw time).
        self.highlight = self.canvas.create_rectangle(0, 0, 0, 0, fill=ROW_HOVER, width=0, state='hidden')
        self.items = [(self.canvas.create_text(0, 0, anchor='nw', fill=TEXT, font=self.title_font),
                       self.canvas.create_text(0, 0, anchor='nw', fill=DIM, font=self.sub_font),
                       self.canvas.create_oval(0, 0, 0, 0, width=0, state='hidden'))
                      for _ in range(SHOW)]
        self.data = []          # (sid, title, sub, status) per drawn row
        self.running_dots = []
        self.hover = -1
        self.wheel_pending, self.wheel_job = 0.0, None
        self.row_h = 1
        self.canvas.bind('<Configure>', lambda e: self.layout())
        self.canvas.bind('<Motion>', self._motion)
        self.canvas.bind('<Leave>', lambda e: self._set_hover(-1))
        self.canvas.bind('<Button-1>', lambda e: self._click(e))
        self.root.bind_all('<MouseWheel>', self._wheel)

        self.on_event = WinEventProc(self._event)   # kept on self so it isn't garbage-collected
        self.refresh()
        self.watch()
        self.pulse()

    def open_chat(self, sid):
        if not sid or sid.startswith('demo-'):
            return
        # Off the UI thread: opening the link can take a moment and must not freeze the panel.
        threading.Thread(target=os.startfile, args=(f'claude://claude.ai/epitaxy/{sid}',), daemon=True).start()

    def refresh(self):
        chats = self.chats.load()
        data = [(sid, title, f'{group or "Ungrouped"} · {ago(t)}', st) for t, sid, title, group, st in chats]
        if data != self.data:
            self.data = data
            self.draw_text()
        self.root.after(2000, self.refresh)

    def layout(self):
        """Position every row for the current width and font size (on resize or DPI change)."""
        w_ = self.canvas.winfo_width()
        t_h, s_h = self.title_font.metrics('linespace'), self.sub_font.metrics('linespace')
        pad = max(4, t_h // 3)
        self.row_h = pad + t_h + s_h + pad
        r = max(4, t_h // 5)
        for i, (title, sub, dot) in enumerate(self.items):
            y = i * self.row_h
            self.canvas.coords(title, 24, y + pad)
            self.canvas.coords(sub, 24, y + pad + t_h)
            cy = y + pad + t_h // 2
            self.canvas.coords(dot, 12 - r, cy - r, 12 + r, cy + r)
        self.hover = -2
        self._set_hover(-1)
        self.draw_text()

    def draw_text(self):
        room = max(20, self.canvas.winfo_width() - 38)
        self.running_dots = []
        for i, (title, sub, dot) in enumerate(self.items):
            if i < len(self.data):
                _, t, s, st = self.data[i]
                self.canvas.itemconfigure(title, text=fit(self.title_font, t, room), state='normal')
                self.canvas.itemconfigure(sub, text=fit(self.sub_font, s, room), state='normal')
                if st == 'running':
                    self.running_dots.append(dot)
                self.canvas.itemconfigure(dot, state='normal' if st else 'hidden',
                                          fill=ACCENT if st == 'running' else UNREAD)
            else:
                for item in (title, sub, dot):
                    self.canvas.itemconfigure(item, state='hidden')
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), len(self.data) * self.row_h))

    def pulse(self):
        """Gently pulse the in-progress dots (only those few items are touched)."""
        if self.running_dots and not self.hidden:
            k = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(time.time() * 4))
            colour = '#%02x%02x%02x' % tuple(int(b + (a - b) * k) for a, b in ((0xd9, 0x1f), (0x77, 0x1f), (0x57, 0x1e)))
            for dot in self.running_dots:
                self.canvas.itemconfigure(dot, fill=colour)
        self.root.after(80, self.pulse)

    def _row_at(self, event):
        i = int(self.canvas.canvasy(event.y) // self.row_h)
        return i if 0 <= i < len(self.data) else -1

    def _set_hover(self, i):
        if i == self.hover:
            return
        if i >= 0:
            y = i * self.row_h
            self.canvas.coords(self.highlight, 6, y, self.canvas.winfo_width() - 6, y + self.row_h)
            self.canvas.itemconfigure(self.highlight, state='normal')
        else:
            self.canvas.itemconfigure(self.highlight, state='hidden')
        self.hover = i
        self.canvas.configure(cursor='hand2' if i >= 0 else '')

    def _motion(self, event):
        self._set_hover(self._row_at(event))

    def _click(self, event):
        i = self._row_at(event)
        if i >= 0:
            self.open_chat(self.data[i][0])

    def _wheel(self, event):
        # Add the wheel movement up and scroll once per screen frame: a fast spin sends events
        # faster than a redraw takes, and scrolling on each one queued redraws (laggy catch-up).
        self.wheel_pending += -event.delta / 40
        if self.wheel_job is None:
            self.wheel_job = self.root.after(16, self._apply_wheel)

    def _apply_wheel(self):
        self.wheel_job = None
        steps = int(self.wheel_pending)
        self.wheel_pending -= steps
        top, bottom = self.canvas.yview()
        if steps and not (top <= 0 and bottom >= 1):
            self.canvas.yview_scroll(steps, 'units')
            y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            self._set_hover(self._row_at(type('E', (), {'y': y})))

    def _event(self, hook, event, hwnd, id_object, id_child, thread, ms):
        if event == EVENT_FOREGROUND:
            self.stack()
        elif hwnd == self.owner and id_object == 0:   # OBJID_WINDOW: the Claude window itself
            self.place()

    def stack(self):
        """Sit directly above the Claude window in the window stack.

        Not an "owned" window: owning a window from another program ties the two programs'
        input together, so Claude had to wait on this panel while being dragged."""
        if not self.owner or self.hidden:
            return
        prev = u.GetWindow(self.owner, 3)          # GW_HWNDPREV: the window just above Claude
        if prev == self.hwnd:
            return
        # SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE; after `prev` = just above Claude (0 = HWND_TOP)
        u.SetWindowPos(self.hwnd, prev or 0, 0, 0, 0, 0, 0x13)

    def watch(self):
        """Find the Claude window (again, if it was closed or restarted) and hook its moves."""
        if self.owner is None or not u.IsWindow(self.owner):
            for h in self.hooks:
                u.UnhookWinEvent(h)
            self.hooks = []
            self.owner, self.owner_pid = find_claude()
            if self.owner:
                self.root.tk.call('tk', 'scaling', (u.GetDpiForWindow(self.owner) or 96) / 72)
                self.root.after_idle(self.layout)   # fonts changed size with the scaling
                for lo, hi in ((EVENT_LOCATIONCHANGE, EVENT_LOCATIONCHANGE), (EVENT_MINIMIZESTART, EVENT_MINIMIZEEND)):
                    self.hooks.append(u.SetWinEventHook(lo, hi, None, self.on_event, self.owner_pid, 0, 0))
                # Any program coming to the front: re-stack above Claude when Claude is involved.
                self.hooks.append(u.SetWinEventHook(EVENT_FOREGROUND, EVENT_FOREGROUND, None, self.on_event, 0, 0, 2))
                self.last_rect = None
        self.place()   # safety net in case an event was missed
        self.stack()
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
            self.stack()
        width = int(WIDTH * (u.GetDpiForWindow(self.owner) or 96) / 96)
        # +1 covers Claude's own 1px border so the two read as one window.
        # SWP_NOACTIVATE | SWP_NOZORDER: never steals focus or changes stacking.
        u.SetWindowPos(self.hwnd, 0, r.left - width, r.top, width + 1, r.bottom - r.top, 0x14)


if __name__ == '__main__':
    Panel().root.mainloop()
