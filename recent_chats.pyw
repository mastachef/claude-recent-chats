"""Recent Chats: a small panel that sticks to the left edge of the Claude desktop window.

Lists every Code chat, most recently used first, with its sidebar group. Click a chat to open it
(uses the chat's claude:// link, which Windows hands to the Claude app). Read-only: it never
changes chats, groups or the Claude window.

Run:  pythonw recent_chats.pyw          (pythonw = no console window)
      pythonw recent_chats.pyw --demo   (sample chats, for screenshots)
"""
import ctypes, ctypes.wintypes as w, glob, json, math, os, sys, threading, time
import tkinter as tk
import tkinter.font as tkfont

WIDTH = 270           # starting panel width at 100% display scaling (drag the left edge to change)
MIN_W, MAX_W = 180, 600
SHOW = 40             # how many chats to list (pinned chats come on top of these)
APPDATA = os.environ['APPDATA']
# Width, condensed view and pins, saved as you change them.
SETTINGS = os.path.join(os.environ.get('LOCALAPPDATA', APPDATA), 'ClaudeRecentChats', 'settings.json')
# Permission prompts live only in the app's memory. Claude Code's Notification hook runs
# `recent_chats.pyw --hook` when one has been open a few seconds; it leaves a marker here.
PROMPTS = os.path.join(os.path.dirname(SETTINGS), 'prompts')
PROMPT_TYPES = ('permission_prompt', 'elicitation_dialog')
CLAUDE_SETTINGS = os.path.join(os.path.expanduser('~'), '.claude', 'settings.json')
SESSIONS = os.path.join(APPDATA, 'Claude', 'claude-code-sessions')
CONFIG = os.path.join(APPDATA, 'Claude', 'claude_desktop_config.json')
APP_CONFIG = os.path.join(APPDATA, 'Claude', 'config.json')   # names the signed-in account
TRANSCRIPTS = os.path.join(os.path.expanduser('~'), '.claude', 'projects')

BG, ROW_HOVER, TEXT, DIM, ACCENT = '#1f1f1e', '#2c2c2a', '#e8e6e1', '#8f8d88', '#d97757'
UNREAD = '#5ea0ff'    # dot: something new you haven't looked at (in progress = pulsing ACCENT)
INPUT = '#f0c043'     # dot: Claude stopped and is waiting on you
STALE_MS = 15 * 60000 # a 'running' chat with no activity this long is treated as stopped
PIN_HOVER = '#5c5a57' # the faint pin shown on the row under the mouse
ICONS = 'Segoe MDL2 Assets'                          # Windows' built-in icon font
PIN, CONDENSE, EXPAND = '', '', ''

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


DEMO_STATUS = {0: 'running', 2: 'unread', 3: 'input', 5: 'unread'}   # row -> dot in --demo
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
        self.acct_stamp = None
        self.account = None
        self.transcripts = {}         # CLI session id -> (path, (mtime_ns, size), asking)

    def asking(self, cli_id, marker_ns=None):
        """True while a chat shows you a question, plan or permission prompt.

        Questions and plans are read from the end of its transcript. A permission prompt left a
        marker (see run_hook); it counts until the transcript moves on (you answered)."""
        if not cli_id:
            return False
        path, stamp, result = self.transcripts.get(cli_id) or (None, None, False)
        try:
            if not path:
                path = next(iter(glob.glob(os.path.join(TRANSCRIPTS, '*', glob.escape(cli_id) + '.jsonl'))), None)
                if not path:
                    return False
            st = os.stat(path); new = (st.st_mtime_ns, st.st_size)
        except OSError:
            self.transcripts.pop(cli_id, None)
            return False
        if new != stamp:
            result = _asking(path, st.st_size)
            self.transcripts[cli_id] = (path, new, result)
        if marker_ns is not None:
            if marker_ns >= new[0]:
                return True
            try:
                os.remove(os.path.join(PROMPTS, cli_id + '.json'))   # answered: tidy up
            except OSError:
                pass
        return result

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
        try:
            st = os.stat(APP_CONFIG); stamp = (st.st_mtime_ns, st.st_size)
            if stamp != self.acct_stamp:
                self.acct_stamp = stamp
                with open(APP_CONFIG, encoding='utf-8') as f:
                    self.account = json.load(f).get('lastKnownAccountUuid')
        except Exception:
            pass
        # Only the signed-in account's folder: after an account switch the app copies the chats
        # over and leaves stale copies in the old folder, which it no longer shows.
        mine = os.path.join(SESSIONS, self.account) if self.account else None
        seen = {}
        for org in [mine] if mine and os.path.isdir(mine) else _dirs(SESSIONS):
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
        markers = {}
        try:
            with os.scandir(PROMPTS) as it:
                markers = {e.name[:-5]: e.stat().st_mtime_ns for e in it if e.name.endswith('.json')}
        except OSError:
            pass
        chats = []
        for _, e in seen.values():
            if e:
                st = status(e, now)
                # An open question waits as long as you leave it, and the app stops counting the
                # chat as working meanwhile, so check every chat (cached: re-read only on change).
                if st != 'input' and self.asking(e[7], markers.get(e[7])):
                    st = 'input'
                chats.append((e[0], e[1], e[2], self.groups.get(e[1], ''), st))
        chats.sort(reverse=True)
        return chats


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
    activity = d.get('lastActivityAt') or 0
    # Chats from before the app recorded focus times have none: treat them as read.
    focused = d.get('lastFocusedAt') or activity
    # Waiting on you: the last turn's summary says it needs you (same rule as the app's sidebar).
    summary, wrap = d.get('postTurnSummary') or {}, d.get('turnWrapUp')
    category = summary.get('status_category')
    needs = category == 'failed' or bool(wrap.get('needsUser')) if isinstance(wrap, dict) else \
        category in ('blocked', 'need_input', 'failed')
    needs = needs and summary.get('summarizes_uuid', d.get('lastAssistantUuid')) == d.get('lastAssistantUuid')
    return (activity, d['sessionId'], d['title'],
            d.get('lastTurnEdgeAt') or 0, d.get('latestUserFrameAt') or 0, focused, needs, d.get('cliSessionId'))


ASK_TOOLS = ('AskUserQuestion', 'ExitPlanMode')   # tools that always wait for your answer


def _asking(path, size):
    """True if the transcript's last message is an unanswered question or plan prompt."""
    try:
        with open(path, 'rb') as f:
            for chunk in (1 << 18, 1 << 21, 1 << 23):    # the last message is usually near the end
                f.seek(max(0, size - chunk))
                lines = f.read().splitlines()
                if size > chunk:
                    lines = lines[1:]                     # first line may be cut
                for line in reversed(lines):
                    if b'"type":"assistant"' not in line and b'"type":"user"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get('type') not in ('assistant', 'user') or r.get('isSidechain'):
                        continue
                    content = (r.get('message') or {}).get('content')
                    return r['type'] == 'assistant' and isinstance(content, list) and any(
                        isinstance(x, dict) and x.get('type') == 'tool_use' and x.get('name') in ASK_TOOLS
                        for x in content)
                if size <= chunk:
                    break
    except OSError:
        pass
    return False


def status(entry, now):
    """'running' while Claude works in the chat, 'input' if it stopped to wait on you,
    'unread' if it did something since you last looked.

    A turn is in progress while the last turn edge is the start of your latest message (the edge
    moves past it when the turn ends). Matches the app's own running flag."""
    activity, _, _, edge, user_frame, focused, needs, _ = entry
    if user_frame and edge - user_frame < 2000 and now - activity < STALE_MS:
        return 'running'
    if needs and user_frame <= edge:
        return 'input'
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


def load_settings():
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:
        return {}


def save_settings(s):
    if '--demo' in sys.argv:          # sample data: don't touch your real settings
        return
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(s, f, indent=1)
        os.replace(SETTINGS + '.tmp', SETTINGS)
    except OSError:
        pass


def run_hook():
    """Run by Claude Code's Notification hook: note that a chat is showing a permission prompt."""
    try:
        data = json.loads(sys.stdin.read() or '{}')
        sid = str(data.get('session_id') or '')
        if data.get('notification_type') in PROMPT_TYPES and sid and all(c.isalnum() or c == '-' for c in sid):
            os.makedirs(PROMPTS, exist_ok=True)
            with open(os.path.join(PROMPTS, sid + '.json'), 'w', encoding='utf-8') as f:
                json.dump({'type': data['notification_type'], 'at': time.time()}, f)
    except Exception:
        pass   # never get in Claude's way


def set_hook(on):
    """Add (on=True) or remove the Notification hook in ~/.claude/settings.json, keeping the rest."""
    try:
        with open(CLAUDE_SETTINGS, encoding='utf-8') as f:
            cfg = json.load(f)
        with open(CLAUDE_SETTINGS + '.recent-chats-backup', 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    except FileNotFoundError:
        cfg = {}
    hooks = cfg.setdefault('hooks', {})
    ours = lambda g: any('recent_chats.pyw' in str(h.get('command', '')) for h in g.get('hooks', []))
    groups = [g for g in hooks.get('Notification', []) if not ours(g)]
    if on:
        pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        exe = pyw if os.path.exists(pyw) else sys.executable
        cmd = '"%s" "%s" --hook' % (exe.replace('\\', '/'), os.path.abspath(__file__).replace('\\', '/'))
        groups.append({'matcher': '|'.join(PROMPT_TYPES), 'hooks': [{'type': 'command', 'command': cmd, 'timeout': 10}]})
    if groups:
        hooks['Notification'] = groups
    else:
        hooks.pop('Notification', None)
    if not hooks:
        cfg.pop('hooks')
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    with open(CLAUDE_SETTINGS + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    os.replace(CLAUDE_SETTINGS + '.tmp', CLAUDE_SETTINGS)
    print('hook added' if on else 'hook removed')


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
        self.dismissed = None   # the Claude window you closed the panel on (hidden until Claude reopens)
        self.chats = Chats()
        self.settings = load_settings()
        try:
            self.width = min(MAX_W, max(MIN_W, int(self.settings.get('width', WIDTH))))
        except (TypeError, ValueError):
            self.width = WIDTH
        self.compact = self.settings.get('compact') is True
        pins = self.settings.get('pins')
        self.pins = [p for p in pins if isinstance(p, str)] if isinstance(pins, list) else []

        head = tk.Frame(self.root, bg=BG)
        head.pack(fill='x', padx=12, pady=(10, 4))
        tk.Label(head, text='Recent', bg=BG, fg=TEXT, font=('Segoe UI Semibold', 11)).pack(side='left')
        self.icon_font = tkfont.Font(family=ICONS, size=9)
        close = tk.Label(head, text='✕', bg=BG, fg=DIM, font=('Segoe UI', 10), cursor='hand2')
        close.pack(side='right')
        close.bind('<Button-1>', lambda e: self.dismiss())
        self.view_btn = tk.Label(head, bg=BG, fg=DIM, font=self.icon_font, cursor='hand2')
        self.view_btn.pack(side='right', padx=(0, 12))
        self.view_btn.bind('<Button-1>', lambda e: self.toggle_view())
        for b in (close, self.view_btn):
            b.bind('<Enter>', lambda e: e.widget.configure(fg=TEXT))
            b.bind('<Leave>', lambda e: e.widget.configure(fg=DIM))

        # Rows are drawn straight onto one canvas (no widget per row), so fast scrolling stays smooth.
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0, yscrollincrement=8)
        self.canvas.pack(fill='both', expand=True)
        self.title_font = tkfont.Font(family='Segoe UI', size=10)
        self.sub_font = tkfont.Font(family='Segoe UI', size=8)
        # One highlight rectangle that moves to the hovered row (40 row backgrounds doubled redraw time).
        self.highlight = self.canvas.create_rectangle(0, 0, 0, 0, fill=ROW_HOVER, width=0, state='hidden')
        self.hover_pin = self.canvas.create_text(0, 0, anchor='e', text=PIN, fill=PIN_HOVER,
                                                 font=self.icon_font, state='hidden')
        self.divider = self.canvas.create_line(0, 0, 0, 0, fill=ROW_HOVER, state='hidden')
        self.items = []         # (title, sub, dot, pin) canvas items per row, made as needed
        self.data = []          # (sid, title, sub, status, pinned) per drawn row
        self.n_pinned = 0
        self.running_dots = []
        self.hover = -1
        self.wheel_pending, self.wheel_job = 0.0, None
        self.row_h, self.pad, self.t_h, self.r = 1, 0, 0, 0
        self.canvas.bind('<Configure>', lambda e: self.layout())
        self.canvas.bind('<Motion>', self._motion)
        self.canvas.bind('<Leave>', lambda e: self._set_hover(-1))
        self.canvas.bind('<Button-1>', lambda e: self._click(e))
        self.root.bind_all('<MouseWheel>', self._wheel)

        # Drag the left edge to change the width (the right edge stays stuck to Claude).
        grip = tk.Frame(self.root, bg=BG, cursor='sb_h_double_arrow')
        grip.place(x=0, y=0, relheight=1, width=5)
        grip.bind('<B1-Motion>', self._resize)
        grip.bind('<ButtonRelease-1>', lambda e: self.save())

        self.on_event = WinEventProc(self._event)   # kept on self so it isn't garbage-collected
        self.update_view_button()
        self.refresh()
        self.watch()
        self.pulse()

    def dismiss(self):
        """✕: hide until Claude is next opened. The panel keeps running, so it comes back by itself."""
        self.dismissed = self.owner
        self.place()

    def save(self):
        self.settings.update(width=self.width, compact=self.compact, pins=self.pins)
        save_settings(self.settings)

    def toggle_view(self):
        self.compact = not self.compact
        self.update_view_button()
        self.save()
        self.layout()

    def update_view_button(self):
        self.view_btn.configure(text=EXPAND if self.compact else CONDENSE)

    def toggle_pin(self, sid):
        if sid in self.pins:
            self.pins.remove(sid)
        else:
            self.pins.append(sid)      # newest pin goes to the bottom of the pinned group
        self.save()
        self.update_list()

    def _resize(self, event):
        if not self.last_rect:
            return
        scale = (u.GetDpiForWindow(self.owner) or 96) / 96
        width = min(MAX_W, max(MIN_W, round((self.last_rect[0] - event.x_root) / scale)))
        if width != self.width:
            self.width = width
            self.last_rect = None      # make place() apply the new width
            self.place()

    def open_chat(self, sid):
        if not sid or sid.startswith('demo-'):
            return
        # Off the UI thread: opening the link can take a moment and must not freeze the panel.
        threading.Thread(target=os.startfile, args=(f'claude://claude.ai/epitaxy/{sid}',), daemon=True).start()

    def refresh(self):
        self.update_list()
        self.root.after(2000, self.refresh)

    def update_list(self):
        chats = self.chats.load()
        by_id = {c[1]: c for c in chats}
        pinned = [by_id[p] for p in self.pins if p in by_id]
        rest = [c for c in chats if c[1] not in self.pins][:SHOW]
        data = [(sid, title, f'{group or "Ungrouped"} · {ago(t)}', st, i < len(pinned))
                for i, (t, sid, title, group, st) in enumerate(pinned + rest)]
        if data != self.data:
            self.data, self.n_pinned = data, len(pinned)
            self.draw_text()

    def layout(self):
        """Position every row for the current width, font size and view (when any of them change)."""
        self.t_h = self.title_font.metrics('linespace')
        s_h = self.sub_font.metrics('linespace')
        self.pad = max(3, self.t_h // 5) if self.compact else max(4, self.t_h // 3)
        self.row_h = self.pad + self.t_h + (0 if self.compact else s_h) + self.pad
        self.r = max(4, self.t_h // 5)
        for i in range(len(self.items)):
            self._place_row(i)
        self.hover = -2
        self._set_hover(-1)
        self.draw_text()

    def _place_row(self, i):
        title, sub, dot, pin = self.items[i]
        y = i * self.row_h
        cy = y + self.pad + self.t_h // 2
        self.canvas.coords(title, 24, y + self.pad)
        self.canvas.coords(sub, 24, y + self.pad + self.t_h)
        self.canvas.coords(dot, 12 - self.r, cy - self.r, 12 + self.r, cy + self.r)
        self.canvas.coords(pin, self.canvas.winfo_width() - 10, cy)

    def draw_text(self):
        while len(self.items) < len(self.data):
            self.items.append((self.canvas.create_text(0, 0, anchor='nw', fill=TEXT, font=self.title_font),
                               self.canvas.create_text(0, 0, anchor='nw', fill=DIM, font=self.sub_font),
                               self.canvas.create_oval(0, 0, 0, 0, width=0, state='hidden'),
                               self.canvas.create_text(0, 0, anchor='e', text=PIN, fill=DIM,
                                                       font=self.icon_font, state='hidden')))
            self._place_row(len(self.items) - 1)
        width = self.canvas.winfo_width()
        room = max(20, width - 24 - 28)     # leave the right edge for the pin
        self.running_dots = []
        for i, (title, sub, dot, pin) in enumerate(self.items):
            if i < len(self.data):
                _, t, s, st, pinned = self.data[i]
                self.canvas.itemconfigure(title, text=fit(self.title_font, t, room), state='normal')
                self.canvas.itemconfigure(sub, text=fit(self.sub_font, s, room),
                                          state='hidden' if self.compact else 'normal')
                if st == 'running':
                    self.running_dots.append(dot)
                self.canvas.itemconfigure(dot, state='normal' if st else 'hidden',
                                          fill={'running': ACCENT, 'input': INPUT}.get(st, UNREAD))
                self.canvas.itemconfigure(pin, state='normal' if pinned else 'hidden')
            else:
                for item in (title, sub, dot, pin):
                    self.canvas.itemconfigure(item, state='hidden')
        if 0 < self.n_pinned < len(self.data):     # a thin line under the pinned chats
            y = self.n_pinned * self.row_h
            self.canvas.coords(self.divider, 12, y, width - 12, y)
            self.canvas.itemconfigure(self.divider, state='normal')
        else:
            self.canvas.itemconfigure(self.divider, state='hidden')
        self.canvas.configure(scrollregion=(0, 0, width, len(self.data) * self.row_h))
        self.hover, i = -2, self.hover
        self._set_hover(i if i < len(self.data) else -1)

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
            # A faint pin on the hovered row: click it to pin the chat to the top.
            self.canvas.coords(self.hover_pin, self.canvas.winfo_width() - 10, y + self.pad + self.t_h // 2)
            self.canvas.itemconfigure(self.hover_pin, state='hidden' if self.data[i][4] else 'normal')
            self.canvas.tag_raise(self.hover_pin)
        else:
            self.canvas.itemconfigure(self.highlight, state='hidden')
            self.canvas.itemconfigure(self.hover_pin, state='hidden')
        self.hover = i
        self.canvas.configure(cursor='hand2' if i >= 0 else '')

    def _motion(self, event):
        self._set_hover(self._row_at(event))

    def _click(self, event):
        i = self._row_at(event)
        if i < 0:
            return
        if event.x >= self.canvas.winfo_width() - 28:   # the pin area at the right edge
            self.toggle_pin(self.data[i][0])
        else:
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
        if not self.owner or self.owner == self.dismissed or u.IsIconic(self.owner) or not u.IsWindowVisible(self.owner):
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
        width = int(self.width * (u.GetDpiForWindow(self.owner) or 96) / 96)
        # +1 covers Claude's own 1px border so the two read as one window.
        # SWP_NOACTIVATE | SWP_NOZORDER: never steals focus or changes stacking.
        u.SetWindowPos(self.hwnd, 0, r.left - width, r.top, width + 1, r.bottom - r.top, 0x14)


if __name__ == '__main__':
    if '--hook' in sys.argv:
        run_hook()
    elif '--install-hook' in sys.argv or '--remove-hook' in sys.argv:
        set_hook('--install-hook' in sys.argv)
    else:
        Panel().root.mainloop()
