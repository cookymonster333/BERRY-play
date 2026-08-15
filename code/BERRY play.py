#!/usr/bin/env python3
"""
BERRY play Player
==================
Waits for USB stick (RSD) / micro SD card labeled "BERRY play" or root folders 
named "BERRY play" inside Google Drive / OneDrive.

Includes a Windows 11 / Apple-style Dynamic Island with a pitch-black theme.
Collapsed state connects to the screen bezel via angled diagonal lines.
Expanded state forms a clean rectangular box with no rounded corners.

Fully cross-compatible with both Linux (Raspberry Pi OS / Ubuntu) and Windows.
"""

import os
import sys
import string
import random
import re
import socket
import subprocess
import time
import threading
import shutil
import tkinter as tk
from tkinter import messagebox

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes

DRIVE_NAME = "BERRY play"
SEARCH_DIRS = ["/media", "/mnt", "/run/media"]   # Linux/Pi: where drives auto-mount
POLL_SECONDS = 2                                 # how often to check if drives are plugged in
PLAYABLE_EXTENSIONS = (".mp3", ".mp4")

WINDOWS_VLC_PATHS = [
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
]

# ---------------------------------------------------------------------------
# Dark color palette (Pitch Black Island)
# ---------------------------------------------------------------------------
BG = "#1c1c1c"          # main background
BG_PANEL = "#000000"    # pitch black panel matching Apple iPhone Dynamic Island
FG = "#e4e4e4"          # normal text
FG_MUTED = "#8a8a8a"    # secondary / status text
ACCENT = "#4caf82"      # used for toggled-ON state and selection highlight
ACCENT_BG = "#152b20"   # subtle dark background for toggled-ON buttons
DANGER = "#c0524a"      # quit button
BORDER_COLOR = "#2a2a2a"  # modern subtle outline border for main window
FONT = ("Segoe UI", 10) if IS_WINDOWS else ("DejaVu Sans", 10)
FONT_SMALL = ("Segoe UI", 9) if IS_WINDOWS else ("DejaVu Sans", 9)


def flat_button(parent, **kwargs):
    """A tk.Button pre-styled to look flat and minimal."""
    defaults = dict(
        bg=BG_PANEL, fg=FG, activebackground=BG_PANEL, activeforeground=ACCENT,
        relief="flat", bd=0, highlightthickness=0, font=FONT, padx=10, pady=6,
        cursor="hand2",
    )
    defaults.update(kwargs)
    return tk.Button(parent, **defaults)


class ToggleSwitch(tk.Canvas):
    """A small sliding pill-shaped switch, like an iOS toggle."""
    WIDTH, HEIGHT = 38, 20

    def __init__(self, parent, command=None, initial=False, **kwargs):
        defaults = dict(width=self.WIDTH, height=self.HEIGHT, bg=BG_PANEL,
                         highlightthickness=0, bd=0, cursor="hand2")
        defaults.update(kwargs)
        super().__init__(parent, **defaults)
        self.command = command
        self.state = initial
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = self.HEIGHT / 2
        track_color = ACCENT if self.state else "#3a3a3a"
        self.create_oval(0, 0, self.HEIGHT, self.HEIGHT, fill=track_color, outline="")
        self.create_oval(self.WIDTH - self.HEIGHT, 0, self.WIDTH, self.HEIGHT, fill=track_color, outline="")
        self.create_rectangle(r, 0, self.WIDTH - r, self.HEIGHT, fill=track_color, outline="")
        pad = 2
        knob_cx = (self.WIDTH - r) if self.state else r
        self.create_oval(knob_cx - r + pad, pad, knob_cx + r - pad, self.HEIGHT - pad, fill="#ffffff", outline="")

    def _on_click(self, event):
        self.set_state(not self.state)
        if self.command:
            self.command()

    def set_state(self, value):
        self.state = bool(value)
        self._draw()


def detect_drive_hardware_type(drive_path):
    if IS_WINDOWS:
        try:
            cmd = 'wmic diskdrive get InterfaceType,PNPDeviceID'
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            out_lower = out.lower()
            if "sd" in out_lower or "card reader" in out_lower or "sdhc" in out_lower or "mmc" in out_lower:
                return "microSD"
        except Exception:
            pass
        return "microSD" if "sd" in drive_path.lower() else "RSD"
    else:
        try:
            real_path = os.path.realpath(drive_path)
            if "mmcblk" in real_path or "mmc" in real_path:
                return "microSD"
            
            if shutil.which("lsblk"):
                cmd = f"lsblk -no TRAN,TYPE '{real_path}'"
                out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
                out_lower = out.lower()
                if "mmc" in out_lower or "sd" in out_lower:
                    return "microSD"
                elif "usb" in out_lower:
                    return "RSD"
        except Exception:
            pass
            
        path_lower = drive_path.lower()
        if "sd" in path_lower or "mmc" in path_lower:
            return "microSD"
        return "RSD"


def find_all_drive_paths():
    if IS_WINDOWS:
        return _find_drives_windows()
    return _find_drives_linux()


def _find_drives_windows():
    found = []

    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            drive = f"{letter}:\\"
            name_buf = ctypes.create_unicode_buffer(1024)
            kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(drive), name_buf, ctypes.sizeof(name_buf),
                None, None, None, None, 0
            )
            if name_buf.value.upper() == DRIVE_NAME.upper():
                stype = detect_drive_hardware_type(drive)
                found.append((stype, drive))

    user_profile = os.environ.get("USERPROFILE", "")

    onedrive_env = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or os.environ.get("OneDriveCommercial")
    if onedrive_env and os.path.isdir(onedrive_env):
        target = os.path.join(onedrive_env, DRIVE_NAME)
        if os.path.isdir(target):
            found.append(("onedrive", target))

    if user_profile:
        default_onedrive = os.path.join(user_profile, "OneDrive", DRIVE_NAME)
        if os.path.isdir(default_onedrive) and ("onedrive", default_onedrive) not in found:
            found.append(("onedrive", default_onedrive))

        gdrive_folder = os.path.join(user_profile, "Google Drive", DRIVE_NAME)
        if os.path.isdir(gdrive_folder):
            found.append(("googledrive", gdrive_folder))

    for letter in ("G", "H", "I"):
        g_drive_path = f"{letter}:\\My Drive\\{DRIVE_NAME}"
        if os.path.isdir(g_drive_path) and ("googledrive", g_drive_path) not in found:
            found.append(("googledrive", g_drive_path))

    return found


def _find_drives_linux():
    found = []

    user_media = f"/run/media/{os.environ.get('USER', '')}"
    search_paths = list(SEARCH_DIRS)
    if os.path.isdir(user_media):
        search_paths.append(user_media)

    for base in search_paths:
        if not os.path.isdir(base):
            continue
        candidates = [base] + [
            os.path.join(base, d) for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))
        ]
        for folder in candidates:
            try:
                if os.path.basename(folder).upper() == DRIVE_NAME.upper():
                    stype = detect_drive_hardware_type(folder)
                    found.append((stype, folder))
                    continue

                for entry in os.listdir(folder):
                    full = os.path.join(folder, entry)
                    if os.path.isdir(full) and entry.upper() == DRIVE_NAME.upper():
                        stype = detect_drive_hardware_type(full)
                        found.append((stype, full))
            except PermissionError:
                continue

    home = os.path.expanduser("~")
    onedrive_target = os.path.join(home, "OneDrive", DRIVE_NAME)
    if os.path.isdir(onedrive_target):
        found.append(("onedrive", onedrive_target))

    for g_folder in ["Google Drive", "GoogleDrive"]:
        gdrive_target = os.path.join(home, g_folder, DRIVE_NAME)
        if os.path.isdir(gdrive_target):
            found.append(("googledrive", gdrive_target))

    return found


def find_vlc():
    if IS_WINDOWS:
        for path in WINDOWS_VLC_PATHS:
            if os.path.isfile(path):
                return [path]
        vlc_in_path = shutil.which("vlc.exe") or shutil.which("vlc")
        if vlc_in_path:
            return [vlc_in_path]
        return None
    else:
        # Native binary (apt/dnf/etc installed VLC)
        native = shutil.which("cvlc") or shutil.which("vlc")
        if native:
            return [native]
        # Fall back to a Flatpak install of VLC (common on atomic/immutable
        # distros, where VLC usually isn't installed natively and doesn't
        # expose a "vlc" binary on PATH)
        if shutil.which("flatpak"):
            try:
                check = subprocess.run(
                    ["flatpak", "list", "--app", "--columns=application"],
                    capture_output=True, text=True
                )
                if "org.videolan.VLC" in check.stdout:
                    return ["flatpak", "run", "org.videolan.VLC"]
            except Exception:
                pass
        return None


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


SW_HIDE = 0
SW_MINIMIZE = 6
SW_RESTORE = 9
CONSOLE_HWND = None


def _find_windows_for_pid(pid):
    if not IS_WINDOWS:
        return []
    hwnds = []
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def enum_handler(hwnd, lparam):
        wnd_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wnd_pid))
        if wnd_pid.value == pid and user32.IsWindowVisible(hwnd):
            hwnds.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(enum_handler), 0)
    return hwnds


def set_process_window_state(pid, minimize=True, hide=False):
    """Hide/show or minimize/restore all visible windows belonging to a process."""
    if not IS_WINDOWS or not pid:
        return
    user32 = ctypes.windll.user32
    if hide:
        command = SW_HIDE
    else:
        command = SW_MINIMIZE if minimize else SW_RESTORE
    for hwnd in _find_windows_for_pid(pid):
        user32.ShowWindow(hwnd, command)


def wait_and_minimize_process_window(pid, find_attempts=20, find_delay=0.15,
                                      reinforce_attempts=6, reinforce_delay=0.15):
    if not IS_WINDOWS or not pid:
        return
    found = False
    for _ in range(find_attempts):
        if _find_windows_for_pid(pid):
            found = True
            break
        time.sleep(find_delay)
    if not found:
        return
    for _ in range(reinforce_attempts):
        set_process_window_state(pid, minimize=True, hide=True)
        time.sleep(reinforce_delay)


def hide_console_window():
    if not IS_WINDOWS:
        return
    global CONSOLE_HWND
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        CONSOLE_HWND = hwnd
        ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)


class PlayerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BERRY play Player")
        self.overrideredirect(True)
        self.configure(bg=BORDER_COLOR)

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True, padx=1, pady=1)

        width, height = 640, 420
        self.update_idletasks()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)

        self.bind("<Escape>", lambda e: self.handle_escape())
        self.bind("<FocusOut>", self.on_focus_out)

        # Arrow-key navigation bound at the window level (bind_all) so it
        # works no matter which child widget currently has focus (e.g. the
        # search entry). This also helps on Linux, where WM focus handling
        # for override-redirect windows can be inconsistent.
        self.bind_all("<Up>", lambda e: self._move_selection(-1))
        self.bind_all("<Down>", lambda e: self._move_selection(1))
        self.bind_all("<Return>", lambda e: self.open_selected())

        self.status_label = tk.Label(self.container, text="Looking for BERRY play drive.",
                                      bg=BG, fg=FG_MUTED, font=FONT_SMALL, anchor="w")

        self._dots_job = None
        self._dots_count = 0

        nav_frame = tk.Frame(self.container, bg=BG)
        nav_frame.pack(fill="x", padx=14, pady=(10, 0))
        self.path_label = tk.Label(nav_frame, text="Select Source", bg=BG, fg=FG_MUTED, font=FONT_SMALL, anchor="w")
        self.path_label.pack(side="left", padx=2)
        self.queue_button = flat_button(
            nav_frame, text="Queue", command=self.toggle_queue_view, font=FONT_SMALL, padx=6, pady=3,
        )
        self.queue_button.pack(side="right")

        search_frame = tk.Frame(self.container, bg=BG)
        search_frame.pack(fill="x", padx=14, pady=(10, 0))
        self.search_icon = tk.Label(search_frame, text="\u2315", bg=BG, fg=FG_MUTED, font=FONT)
        self.search_icon.pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.apply_filter())
        self.search_entry = tk.Entry(
            search_frame, textvariable=self.search_var, bg=BG_PANEL, fg=FG,
            insertbackground=FG, relief="flat", font=FONT,
            highlightthickness=1, highlightbackground=BG_PANEL, highlightcolor=ACCENT,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=4)

        # Queue-editing toolbar - lives in the same row/parent as the search
        # box so toggling between them never reshuffles the window layout.
        # Hidden until Queue mode is turned on.
        self.queue_toolbar = tk.Frame(search_frame, bg=BG)
        self.queue_up_btn = flat_button(
            self.queue_toolbar, text="\u25b2", command=lambda: self.queue_move(-1),
            font=FONT_SMALL, width=2, padx=4, pady=2,
        )
        self.queue_up_btn.pack(side="left", padx=1)
        self.queue_down_btn = flat_button(
            self.queue_toolbar, text="\u25bc", command=lambda: self.queue_move(1),
            font=FONT_SMALL, width=2, padx=4, pady=2,
        )
        self.queue_down_btn.pack(side="left", padx=1)
        self.queue_remove_btn = flat_button(
            self.queue_toolbar, text="Remove", command=self.queue_remove_selected,
            font=FONT_SMALL, padx=6, pady=2,
        )
        self.queue_remove_btn.pack(side="left", padx=(8, 1))
        self.queue_play_btn = flat_button(
            self.queue_toolbar, text="\u25b6 Play", command=self.queue_play_selected,
            font=FONT_SMALL, padx=6, pady=2,
        )
        self.queue_play_btn.pack(side="left", padx=1)

        self.listbox = tk.Listbox(
            self.container, bg=BG_PANEL, fg=FG, font=FONT, bd=0, highlightthickness=0,
            selectbackground=ACCENT_BG, selectforeground=ACCENT, activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=14, pady=12)
        self.listbox.bind("<Double-Button-1>", self.on_double_click)
        self.listbox.bind("<Return>", self.on_enter_key)

        self.detected_locations = []
        self.root_path = None
        self.drive_type = "microSD"
        self.current_path = None
        self.entries = []
        self.all_entries = []

        self.original_order = []
        self.playlist = []
        self.play_index = -1
        self.current_proc = None
        self.current_rc_port = None
        self.is_paused = False
        self.autoplay_enabled = True
        self.shuffle_enabled = False
        self.play_session = 0
        self._advance_requested = None
        self.is_minimized = False
        self.vlc_windows_hidden = False
        self.volume = 100      # 0-100, applied to VLC via the rc interface
        self.queue_mode = False

        self._suppress_dismiss_until = 0.0
        self._topmost_guard_job = None

        self.island = ControlIsland(self)

        self.withdraw()

        self._start_loading_dots()
        threading.Thread(target=self._drive_poll_loop, daemon=True).start()

    def _animate_loading_dots(self):
        if not self.detected_locations:
            dots = "." * ((self._dots_count % 3) + 1)
            self.status_label.config(text=f"Looking for BERRY play drive{dots}")
            self._dots_count += 1
            self._dots_job = self.after(400, self._animate_loading_dots)

    def _start_loading_dots(self):
        if self._dots_job is not None:
            return
        self.status_label.pack(fill="x", padx=14, pady=(12, 4), before=self.path_label.master)
        self._dots_count = 0
        self._animate_loading_dots()

    def _stop_loading_dots(self):
        if self._dots_job is not None:
            self.after_cancel(self._dots_job)
            self._dots_job = None
        self.status_label.pack_forget()

    def _drive_poll_loop(self):
        while True:
            locations = find_all_drive_paths()
            if locations != self.detected_locations:
                self.detected_locations = locations
                self.after(0, self.on_sources_updated)

            time.sleep(POLL_SECONDS)

    def on_sources_updated(self):
        if not self.detected_locations:
            self.root_path = None
            self.current_path = None
            self._start_loading_dots()
            self.refresh_listing()
        else:
            self._stop_loading_dots()
            if self.root_path and not any(p == self.root_path for _, p in self.detected_locations):
                self.root_path = None
                self.current_path = None

            self.refresh_listing()

    def format_display_location(self, target_path=None):
        target = target_path or self.current_path
        if not target or not self.root_path:
            return "BERRY play Sources"

        rel = os.path.relpath(target, self.root_path)
        if rel in ("", "."):
            return f"BERRY play: {self.drive_type}"

        formatted_rel = rel.replace(os.sep, " / ")
        return f"BERRY play: {self.drive_type} / {formatted_rel}"

    def refresh_listing(self):
        if self.current_path is None:
            self.path_label.config(text="Select BERRY play Source:")
            self.all_entries = []

            for stype, path in self.detected_locations:
                display_title = f"BERRY play: {stype}"
                self.all_entries.append(("source", path, stype, display_title))

            if self.search_var.get():
                self.search_var.set("")
            else:
                self.apply_filter()
            return

        if not os.path.exists(self.current_path):
            self.go_to_sources()
            return

        self.path_label.config(text=self.format_display_location(self.current_path))

        try:
            items = sorted(os.listdir(self.current_path))
        except OSError as e:
            messagebox.showerror("Error", f"Could not read folder:\n{e}")
            return

        self.all_entries = []
        for name in items:
            full_path = os.path.join(self.current_path, name)
            if name.lower().endswith(PLAYABLE_EXTENSIONS) and not os.path.isdir(full_path):
                self.all_entries.append(("media", full_path))
            elif os.path.isdir(full_path):
                self.all_entries.append(("folder", full_path))

        if self.search_var.get():
            self.search_var.set("")
        else:
            self.apply_filter()

    def apply_filter(self):
        raw_query = self.search_var.get().strip()
        query_lower = raw_query.lower()
        self.listbox.delete(0, tk.END)
        self.entries = []

        if self.current_path is None:
            for item in self.all_entries:
                _, path, stype, title = item
                if query_lower and query_lower not in title.lower():
                    continue
                self.listbox.insert(tk.END, f"  \u25b8  {title}")
                self.entries.append(item)
            return

        if query_lower.startswith("@all"):
            search_term = query_lower[5:].strip()
            drive_files = self.build_drive_index()
            for path in drive_files:
                filename = os.path.basename(path)
                display_name = os.path.splitext(filename)[0]
                if search_term and search_term not in display_name.lower():
                    continue

                parent = os.path.dirname(path)
                rel = os.path.relpath(parent, self.root_path) if self.root_path else ""
                origin = self.drive_type if rel in ("", ".") else rel.replace(os.sep, " / ")

                self.listbox.insert(tk.END, f"  \u266a  {display_name}   \u2014  ({origin})")
                self.entries.append(("media", path))
        else:
            for kind, path in self.all_entries:
                name = os.path.basename(path)
                display_name = os.path.splitext(name)[0] if kind == "media" else name
                if query_lower and query_lower not in display_name.lower():
                    continue
                marker = "\u266a" if kind == "media" else "\u25b8"
                self.listbox.insert(tk.END, f"  {marker}  {display_name}")
                self.entries.append((kind, path))

    def on_double_click(self, event):
        self.open_selected()

    def on_enter_key(self, event):
        self.open_selected()

    def _move_selection(self, delta):
        """Moves the listbox selection up/down by `delta`, regardless of
        which widget currently has keyboard focus."""
        if not self.entries:
            return
        current = self.listbox.curselection()
        idx = current[0] if current else -1
        new_idx = max(0, min(len(self.entries) - 1, idx + delta))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(new_idx)
        self.listbox.activate(new_idx)
        self.listbox.see(new_idx)

    def open_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return

        if self.queue_mode:
            self.control_jump(selection[0])
            self.render_queue()
            return

        selected_item = self.entries[selection[0]]

        if self.current_path is None:
            _, path, stype, _ = selected_item
            self.root_path = path
            self.drive_type = stype
            self.current_path = path
            self.refresh_listing()
            return

        kind, path = selected_item
        if kind == "folder":
            self.current_path = path
            self.refresh_listing()
        else:
            folder = os.path.dirname(path)
            if self.root_path and os.path.normpath(folder) != os.path.normpath(self.current_path or ""):
                self.current_path = folder
                self.refresh_listing()
            self.start_playback(path)

    def go_up(self):
        if self.current_path is None:
            return

        if os.path.normpath(self.current_path) == os.path.normpath(self.root_path):
            self.go_to_sources()
            return

        parent = os.path.dirname(self.current_path)
        if os.path.normpath(parent).startswith(os.path.normpath(self.root_path)) or IS_WINDOWS:
            if parent and parent != self.current_path:
                self.current_path = parent
                self.refresh_listing()

    def go_to_sources(self):
        self.root_path = None
        self.current_path = None
        self.refresh_listing()

    def handle_escape(self):
        if self.search_var.get():
            self.search_var.set("")
        elif self.current_path is not None:
            self.go_up()
        else:
            self.hide_main_window_under_island()

    def on_focus_out(self, event=None):
        self.after(150, self._check_external_click)

    def _suppress_dismiss(self, duration=0.8):
        self._suppress_dismiss_until = time.monotonic() + duration

    def _foreground_is_this_app(self):
        if not IS_WINDOWS:
            return True
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            fg_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
            return fg_pid.value == os.getpid()
        except Exception:
            return False

    def _focus_is_on_vlc(self):
        if not IS_WINDOWS or not self.current_proc or self.current_proc.poll() is not None:
            return False
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False
            fg_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
            return fg_pid.value == self.current_proc.pid
        except Exception:
            return False

    def _check_external_click(self):
        if time.monotonic() < self._suppress_dismiss_until:
            return

        focused = self.focus_get()
        if focused is not None:
            try:
                top = focused.winfo_toplevel()
                if top in (self, self.island):
                    return
            except Exception:
                pass
        elif self._focus_is_on_vlc():
            return

        def collapse_island_if_expanded():
            if hasattr(self, "island") and self.island.is_expanded:
                self.island.toggle_expand()

        if self.state() != "withdrawn" and not self.is_minimized:
            self.hide_main_window_under_island(on_complete=collapse_island_if_expanded)
        else:
            collapse_island_if_expanded()

    def start_playback(self, path):
        playlist = [p for kind, p in self.all_entries if kind == "media"]
        if path not in playlist:
            return

        self.original_order = playlist

        if self.shuffle_enabled:
            remaining = [p for p in playlist if p != path]
            random.shuffle(remaining)
            playlist = [path] + remaining
            index = 0
        else:
            index = playlist.index(path)

        self.playlist = playlist
        self.play_index = index

        self.play_session += 1
        session = self.play_session

        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.terminate()
            except OSError:
                pass

        threading.Thread(target=self.playback_loop, args=(session,), daemon=True).start()

    def playback_loop(self, session):
        vlc_cmd = find_vlc()
        if vlc_cmd is None:
            self.after(0, lambda: messagebox.showerror(
                "VLC not found", "Couldn't find VLC.\n\nWindows: videolan.org\nLinux: sudo apt install vlc"
            ))
            return

        while True:
            if session != self.play_session:
                return
            if not (0 <= self.play_index < len(self.playlist)):
                self.after(0, lambda: self.status_label.config(text="Playlist finished"))
                self.after(0, self.island.set_stopped_state)
                return

            path = self.playlist[self.play_index]
            filename = os.path.basename(path)
            display_name = os.path.splitext(filename)[0]

            folder = os.path.dirname(path)
            rel = os.path.relpath(folder, self.root_path) if self.root_path else ""
            location = self.drive_type if rel in ("", ".") else rel.replace(os.sep, " / ")

            self.after(0, lambda n=filename: self.status_label.config(text=f"Playing: {n}"))
            self.after(0, lambda n=display_name, l=location: self.island.set_now_playing(n, l))
            self.after(0, self.render_queue_if_active)
            self.after(0, self.island._stop_progress)
            self.after(0, lambda: self.island._set_progress(0.0))
            self.is_paused = False
            self._advance_requested = None
            self.after(0, self.island.set_playing_state)

            rc_port = get_free_port()
            vlc_args = [
                *vlc_cmd,
                "--fullscreen",
                "--play-and-exit",
                "--extraintf", "rc",
                "--rc-host", f"127.0.0.1:{rc_port}",
                "--rc-quiet",
            ]
            if self.vlc_windows_hidden:
                vlc_args.append("--qt-start-minimized")
            vlc_args.append(path)

            try:
                creationflags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                proc = subprocess.Popen(
                    vlc_args, creationflags=creationflags,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                self.after(0, lambda: messagebox.showerror("VLC not found", "Couldn't launch VLC."))
                return

            self.current_proc = proc
            self.current_rc_port = rc_port
            self.after(0, self.island._start_progress)

            if self.volume != 100:
                threading.Thread(target=self._apply_saved_volume, args=(rc_port,), daemon=True).start()

            if self.vlc_windows_hidden and IS_WINDOWS:
                time.sleep(0.25)
                wait_and_minimize_process_window(proc.pid)
            else:
                self.after(200, self._bring_main_above_vlc)

            proc.wait()

            if self.current_proc is proc:
                self.current_proc = None
                self.current_rc_port = None

            if session != self.play_session:
                return

            if self._advance_requested == "back":
                self.play_index = max(0, self.play_index - 1)
            elif self._advance_requested == "next":
                self.play_index += 1
            elif self._advance_requested == "jump":
                pass  # play_index was already set directly by control_jump()
            else:
                if not self.autoplay_enabled:
                    self.after(0, lambda: self.status_label.config(text="Stopped (autoplay off)"))
                    self.after(0, self.island.set_stopped_state)
                    return
                self.play_index += 1

    def send_rc_command(self, port, command, reply=False):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
                s.sendall((command + "\n").encode())
                if reply:
                    return s.recv(256).decode(errors="ignore")
        except OSError:
            pass
        return None

    def set_volume(self, value):
        """Called by the settings panel's volume slider. value is 0-100;
        VLC's rc interface uses a 0-256 scale (256 = 100%)."""
        try:
            self.volume = int(float(value))
        except (TypeError, ValueError):
            return
        if self.current_proc and self.current_proc.poll() is None and self.current_rc_port:
            vlc_level = round(self.volume / 100 * 256)
            self.send_rc_command(self.current_rc_port, f"volume {vlc_level}")

    def _apply_saved_volume(self, port):
        # Give VLC's rc interface a brief moment to come up before we talk to it.
        time.sleep(0.3)
        vlc_level = round(self.volume / 100 * 256)
        self.send_rc_command(port, f"volume {vlc_level}")

    def query_volume(self):
        """
        Ask VLC for its actual current volume (0-256 scale) and return
        it as 0-100, or None if nothing is playing / no reply. Used to
        keep the settings panel honest, since volume can also change
        via keyboard media keys, VLC's own window, etc.
        """
        if not (self.current_proc and self.current_proc.poll() is None and self.current_rc_port):
            return None
        reply = self.send_rc_command(self.current_rc_port, "volume", reply=True)
        if not reply:
            return None
        match = re.search(r"\d+", reply)
        if not match:
            return None
        vlc_level = int(match.group())
        return round(vlc_level / 256 * 100)

    def control_toggle_playpause(self):
        if not self.current_proc or self.current_proc.poll() is not None:
            return
        self.send_rc_command(self.current_rc_port, "pause")
        self.is_paused = not self.is_paused
        if self.is_paused:
            self.island.set_paused_state()
            self.status_label.config(text=self.status_label.cget("text").replace("Playing:", "Paused:"))
        else:
            self.island.set_playing_state()
            self.status_label.config(text=self.status_label.cget("text").replace("Paused:", "Playing:"))

    def control_next(self):
        if self.current_proc and self.current_proc.poll() is None:
            self._advance_requested = "next"
            self.current_proc.terminate()

    def control_back(self):
        if self.current_proc and self.current_proc.poll() is None:
            self._advance_requested = "back"
            self.current_proc.terminate()

    def control_jump(self, index):
        """Jump playback straight to a specific position in the queue."""
        if not (0 <= index < len(self.playlist)):
            return
        self.play_index = index
        if self.current_proc and self.current_proc.poll() is None:
            self._advance_requested = "jump"
            self.current_proc.terminate()
        elif self.playlist:
            self.play_session += 1
            session = self.play_session
            threading.Thread(target=self.playback_loop, args=(session,), daemon=True).start()

    def queue_move(self, direction):
        """Swap the selected queue row with its neighbor (Up/Down buttons)."""
        if not self.queue_mode:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        i = selection[0]
        j = i + direction
        if not (0 <= j < len(self.playlist)):
            return
        self.playlist[i], self.playlist[j] = self.playlist[j], self.playlist[i]
        if self.play_index == i:
            self.play_index = j
        elif self.play_index == j:
            self.play_index = i
        self.render_queue()
        self.listbox.selection_set(j)

    def queue_remove(self, index):
        """Remove a track from the queue. If it's the one currently
        playing, skip forward to whatever now takes its place."""
        if not (0 <= index < len(self.playlist)):
            return
        was_current = (index == self.play_index)
        del self.playlist[index]
        if index < self.play_index:
            self.play_index -= 1
        elif was_current and self.current_proc and self.current_proc.poll() is None:
            # the list shifted left, so play_index already points at
            # what used to be the next track - just interrupt playback
            # of the (now-removed) file so that track starts.
            self._advance_requested = "jump"
            self.current_proc.terminate()

    def queue_remove_selected(self):
        if not self.queue_mode:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        self.queue_remove(selection[0])
        self.render_queue()

    def queue_play_selected(self):
        if not self.queue_mode:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        self.control_jump(selection[0])
        self.render_queue()

    def toggle_queue_view(self):
        self.queue_mode = not self.queue_mode
        if self.queue_mode:
            self.search_icon.pack_forget()
            self.search_entry.pack_forget()
            self.queue_toolbar.pack(side="left", fill="x", expand=True)
            self.queue_button.config(fg=ACCENT, bg=ACCENT_BG, activebackground=ACCENT_BG)
            self.render_queue()
        else:
            self.queue_toolbar.pack_forget()
            self.search_icon.pack(side="left", padx=(0, 6))
            self.search_entry.pack(side="left", fill="x", expand=True, ipady=4)
            self.queue_button.config(fg=FG, bg=BG_PANEL, activebackground=BG_PANEL)
            self.refresh_listing()

    def render_queue_if_active(self):
        if self.queue_mode:
            self.render_queue()

    def render_queue(self):
        """Draw the current playback queue into the listbox, marking
        whichever track is currently playing."""
        self.listbox.delete(0, tk.END)
        self.path_label.config(text=f"Queue \u00b7 {len(self.playlist)} tracks")
        for i, path in enumerate(self.playlist):
            name = os.path.splitext(os.path.basename(path))[0]
            marker = "\u25b6" if i == self.play_index else "   "
            self.listbox.insert(tk.END, f" {marker}  {name}")

    def toggle_autoplay(self):
        self.autoplay_enabled = not self.autoplay_enabled
        self.island.update_autoplay_button()

    def toggle_shuffle(self):
        self.shuffle_enabled = not self.shuffle_enabled
        self.island.update_shuffle_button()

        if not self.playlist or not (0 <= self.play_index < len(self.playlist)):
            return

        already_played = self.playlist[: self.play_index + 1]
        if self.shuffle_enabled:
            remaining = self.playlist[self.play_index + 1:]
            random.shuffle(remaining)
        else:
            played_set = set(already_played)
            remaining = [p for p in self.original_order if p not in played_set]
        self.playlist = already_played + remaining

    def build_drive_index(self):
        index = []
        if not self.root_path:
            return index
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            for fname in filenames:
                if fname.lower().endswith(PLAYABLE_EXTENSIONS):
                    index.append(os.path.join(dirpath, fname))
        return index

    def toggle_search(self):
        self._suppress_dismiss(0.5)
        if self.state() != "withdrawn" and not self.is_minimized:
            self.hide_main_window_under_island()
        else:
            self.show_main_window_under_island()

    def show_main_window_under_island(self):
        if not self.island.is_expanded:
            self.island.toggle_expand()

        self.island.update_search_button(True)
        self.update_idletasks()
        self.island.update_idletasks()

        island_x = self.island.winfo_x()
        island_y = self.island.winfo_y()
        island_w = self.island.winfo_width()
        island_h = self.island.winfo_height()

        target_w, target_h = 640, 420
        target_x = island_x + (island_w - target_w) // 2
        screen_w = self.winfo_screenwidth()
        target_x = max(10, min(screen_w - target_w - 10, target_x))
        target_y = island_y + island_h + 8

        start_y = target_y - 30

        self.geometry(f"{target_w}x{target_h}+{target_x}+{start_y}")
        self.deiconify()
        self.is_minimized = False

        # Explicitly request window-manager focus, then grab all keyboard
        # input. On Linux (especially Wayland compositors), WMs frequently
        # refuse to hand keyboard focus to override-redirect windows, so
        # without this, keys like arrows/Escape/typing can silently pass
        # through to whatever window was focused before this one appeared.
        self.lift()
        self.focus_force()
        try:
            self.grab_set_global()
        except tk.TclError:
            pass

        self._suppress_dismiss(0.8)
        self._bring_main_above_vlc()
        self._start_topmost_guard()

        steps = 12
        def animate_slide_down(step):
            if step > steps:
                self.geometry(f"{target_w}x{target_h}+{target_x}+{target_y}")
                self.search_entry.focus_set()
                return

            t = step / float(steps)
            ease = 1.0 - (1.0 - t) ** 3
            curr_y = int(start_y + (target_y - start_y) * ease)
            self.geometry(f"{target_w}x{target_h}+{target_x}+{curr_y}")
            self.after(10, lambda: animate_slide_down(step + 1))

        animate_slide_down(1)

    def hide_main_window_under_island(self, on_complete=None):
        if self.state() == "withdrawn":
            if on_complete:
                on_complete()
            return

        self._stop_topmost_guard()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.island.update_search_button(False)
        self.update_idletasks()
        self.island.update_idletasks()

        island_y = self.island.winfo_y()
        island_h = self.island.winfo_height()

        target_w = self.winfo_width()
        target_h = self.winfo_height()
        current_x = self.winfo_x()
        current_y = self.winfo_y()

        end_y = (island_y + island_h + 8) - 30

        steps = 12
        def animate_slide_up(step):
            if step > steps:
                self.withdraw()
                if on_complete:
                    on_complete()
                return

            t = step / float(steps)
            ease = t ** 3
            curr_y = int(current_y + (end_y - current_y) * ease)
            self.geometry(f"{target_w}x{target_h}+{current_x}+{curr_y}")
            self.after(10, lambda: animate_slide_up(step + 1))

        animate_slide_up(1)

    def _bring_main_above_vlc(self):
        if self.state() == "withdrawn":
            return
        self.attributes("-topmost", True)
        self.lift()
        self.attributes("-topmost", False)

    def _start_topmost_guard(self):
        if self._topmost_guard_job is not None:
            return
        self._topmost_guard_tick()

    def _topmost_guard_tick(self):
        if self.state() == "withdrawn":
            self._topmost_guard_job = None
            return

        # If Windows says another application's window is in the foreground,
        # treat that as a click outside BERRY play. Collapse every expanded
        # island/settings/search view back to the small island.
        if not self._foreground_is_this_app():
            if hasattr(self, "island") and self.island.is_expanded and not self.island._animating:
                self.island.toggle_expand()
            if self.search_panel is not None and self.search_panel.winfo_exists():
                self.search_panel.destroy()
                self.search_panel = None
                self.island.update_search_button(False)
            self._suppress_dismiss(0.5)
            self._topmost_guard_job = self.after(250, self._topmost_guard_tick)
            return

        if self._focus_is_on_vlc():
            self._suppress_dismiss(0.5)
            self._bring_main_above_vlc()
        self._topmost_guard_job = self.after(250, self._topmost_guard_tick)

    def _stop_topmost_guard(self):
        if self._topmost_guard_job is not None:
            self.after_cancel(self._topmost_guard_job)
            self._topmost_guard_job = None

    def toggle_player_visibility(self):
        self._suppress_dismiss(0.8)
        self.vlc_windows_hidden = not self.vlc_windows_hidden

        if IS_WINDOWS and CONSOLE_HWND:
            ctypes.windll.user32.ShowWindow(CONSOLE_HWND, SW_HIDE)

        if self.vlc_windows_hidden:
            if self.current_proc and self.current_proc.poll() is None:
                set_process_window_state(self.current_proc.pid, minimize=True, hide=True)
        else:
            if self.current_proc and self.current_proc.poll() is None:
                set_process_window_state(self.current_proc.pid, minimize=False, hide=False)
                self._bring_main_above_vlc()

        self.island.update_vlc_button()

    def control_quit(self):
        self._stop_loading_dots()
        self._stop_topmost_guard()
        self.play_session += 1
        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.terminate()
            except OSError:
                pass
        self.island.destroy()
        self.destroy()


class ControlIsland(tk.Toplevel):
    # Dimensions
    COLLAPSED_W, COLLAPSED_H = 170, 28
    EXPANDED_W, EXPANDED_H = 460, 68
    SETTINGS_EXTRA_H = 76   # extra height added when the settings panel is open

    COLLAPSED_Y = 0   # Attached flush to screen top bezel
    EXPANDED_Y = 14   # Floating detached island

    FLARE_X = 50      # Horizontal flare offset for angled diagonal connection to bezel

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        # Transparent canvas background for dynamic edges
        self.trans_color = "#000001"
        self.configure(bg=self.trans_color)
        if IS_WINDOWS:
            try:
                self.attributes("-transparentcolor", self.trans_color)
            except tk.TclError:
                pass

        self.bg_canvas = tk.Canvas(self, bg=self.trans_color, highlightthickness=0, bd=0)
        self.bg_canvas.pack(fill="both", expand=True)

        self.bind("<FocusOut>", app.on_focus_out)

        self.is_expanded = False
        self._animating = False

        self._marquee_job = None
        self._marquee_text = ""
        self._marquee_pos = 0
        self._progress_job = None
        self._progress_length = 0.0

        # Collapsed UI view
        self.collapsed_frame = tk.Frame(self.bg_canvas, bg=BG_PANEL, cursor="hand2")
        self.collapsed_label = tk.Label(
            self.collapsed_frame, text="\u2022 BERRY play \u2022", fg=ACCENT, bg=BG_PANEL,
            font=("Segoe UI" if IS_WINDOWS else "DejaVu Sans", 10, "bold")
        )
        self.collapsed_label.pack(expand=True)
        self.collapsed_frame.bind("<Button-1>", lambda e: self.toggle_expand())
        self.collapsed_label.bind("<Button-1>", lambda e: self.toggle_expand())

        # Expanded UI view
        self.expanded_container = tk.Frame(self.bg_canvas, bg=BG_PANEL, padx=8, pady=6)

        now_playing_row = tk.Frame(self.expanded_container, bg=BG_PANEL, cursor="hand2")
        now_playing_row.pack(fill="x", pady=(0, 4))
        now_playing_row.bind("<Button-1>", lambda e: self.toggle_expand())

        self.now_playing_label = tk.Label(
            now_playing_row, text="Nothing playing", fg=FG, bg=BG_PANEL,
            font=FONT_SMALL, anchor="e", cursor="hand2"
        )
        self.now_playing_label.pack(side="left", expand=True, fill="x")
        self.now_playing_label.bind("<Button-1>", lambda e: self.toggle_expand())

        self.location_label = tk.Label(
            now_playing_row, text="", fg=FG_MUTED, bg=BG_PANEL,
            font=FONT_SMALL, anchor="w", cursor="hand2"
        )
        self.location_label.pack(side="right", expand=True, fill="x")
        self.location_label.bind("<Button-1>", lambda e: self.toggle_expand())

        frame = tk.Frame(self.expanded_container, bg=BG_PANEL)
        frame.pack()

        self.settings_button = flat_button(
            frame, text="\u2699", command=self.toggle_settings,
            font=FONT_SMALL, width=2, padx=5, pady=3,
        )
        self.settings_button.pack(side="left", padx=(0, 5))

        self.back_button = flat_button(
            frame, text="\u2039\u2039", command=app.control_back,
            font=FONT_SMALL, width=2, padx=5, pady=3,
        )
        self.back_button.pack(side="left", padx=1)

        self.playpause_button = flat_button(
            frame, text="\u23f8", command=app.control_toggle_playpause,
            font=FONT_SMALL, width=2, padx=5, pady=3,
        )
        self.playpause_button.pack(side="left", padx=1)

        self.next_button = flat_button(
            frame, text="\u203a\u203a", command=app.control_next,
            font=FONT_SMALL, width=2, padx=5, pady=3,
        )
        self.next_button.pack(side="left", padx=1)

        self.autoplay_button = flat_button(
            frame, text="Auto", command=app.toggle_autoplay, font=FONT_SMALL, padx=6, pady=3,
        )
        self.autoplay_button.pack(side="left", padx=(8, 1))

        self.shuffle_button = flat_button(
            frame, text="Shuffle", command=app.toggle_shuffle, font=FONT_SMALL, padx=6, pady=3,
        )
        self.shuffle_button.pack(side="left", padx=1)

        self.search_button = flat_button(
            frame, text="Search", command=app.toggle_search, font=FONT_SMALL, padx=6, pady=3,
        )
        self.search_button.pack(side="left", padx=(8, 1))

        self.quit_button = flat_button(
            frame, text="\u2715", command=app.control_quit, width=2,
            font=FONT_SMALL, padx=5, pady=3,
            fg=DANGER, activeforeground=DANGER,
        )
        self.quit_button.pack(side="left", padx=(8, 0))

        # --- Settings panel: hidden until the gear button is pressed,
        # then the island grows taller to reveal it (see toggle_settings). ---
        self.settings_open = False
        self.settings_frame = tk.Frame(self.expanded_container, bg=BG_PANEL)

        vlc_row = tk.Frame(self.settings_frame, bg=BG_PANEL)
        vlc_row.pack(fill="x", pady=(8, 4))
        tk.Label(
            vlc_row, text="Hide VLC window", fg=FG, bg=BG_PANEL, font=FONT_SMALL, anchor="w",
        ).pack(side="left")
        self.vlc_toggle = ToggleSwitch(
            vlc_row, command=app.toggle_player_visibility,
            initial=app.vlc_windows_hidden, bg=BG_PANEL,
        )
        self.vlc_toggle.pack(side="right")

        volume_row = tk.Frame(self.settings_frame, bg=BG_PANEL)
        volume_row.pack(fill="x", pady=(0, 4))
        tk.Label(
            volume_row, text="Volume", fg=FG, bg=BG_PANEL, font=FONT_SMALL, anchor="w",
        ).pack(side="left")

        self._volume_editing = False
        self.volume_value_label = tk.Label(
            volume_row, text=f"{app.volume}%", fg=FG_MUTED, bg=BG_PANEL, font=FONT_SMALL,
            width=4, anchor="e", cursor="xterm",
        )
        self.volume_value_label.pack(side="right", padx=(6, 0))
        self.volume_value_label.bind("<Button-1>", self._start_volume_text_edit)

        self.volume_slider = tk.Scale(
            volume_row, from_=0, to=100, orient="horizontal", command=self._on_volume_change,
            bg=BG_PANEL, fg=FG, troughcolor="#3a3a3a", highlightthickness=0, bd=0,
            font=FONT_SMALL, showvalue=False, sliderlength=14, length=200,
            activebackground=ACCENT,
        )
        self.volume_slider.set(app.volume)
        self.volume_slider.pack(side="right", fill="x", expand=True, padx=(10, 0))
        # Override the default "click jumps one page toward the click" trough
        # behavior so a click anywhere on the bar moves the knob straight
        # to that spot instead.
        self.volume_slider.bind("<Button-1>", self._on_volume_bar_click)
        self.volume_slider.bind("<B1-Motion>", self._on_volume_bar_click)

        self.update_autoplay_button()
        self.update_shuffle_button()

        self.progress_window = tk.Toplevel(self)
        self.progress_window.overrideredirect(True)
        self.progress_window.attributes("-topmost", True)
        self.progress_window.configure(bg=BG_PANEL)
        if IS_WINDOWS:
            try:
                self.progress_window.attributes("-transparentcolor", BG_PANEL)
            except tk.TclError:
                pass

        self.progress_canvas = tk.Canvas(
            self.progress_window, height=5, bg=BG_PANEL, highlightthickness=0, bd=0, cursor="hand2"
        )
        self.progress_canvas.pack(fill="x")
        self.progress_fill = self.progress_canvas.create_rectangle(
            0, 0, 0, 5, fill="#3b82f6", outline=""
        )

        self.progress_canvas.bind("<Button-1>", self._on_progress_click)
        self.progress_canvas.bind("<B1-Motion>", self._on_progress_click)

        screen_w = self.winfo_screenwidth()
        self.center_x = (screen_w - self.COLLAPSED_W) // 2
        self.curr_y = self.COLLAPSED_Y
        self.curr_w, self.curr_h = float(self.COLLAPSED_W), float(self.COLLAPSED_H)
        
        # Position initial window with extra margin for diagonal flares
        win_w = self.COLLAPSED_W + (self.FLARE_X * 2)
        win_x = self.center_x - self.FLARE_X
        self.geometry(f"{win_w}x{self.COLLAPSED_H}+{win_x}+{self.curr_y}")

        self._draw_island_shape(is_attached=True)
        self.collapsed_window = self.bg_canvas.create_window(
            win_w // 2, self.COLLAPSED_H // 2, window=self.collapsed_frame,
            width=self.COLLAPSED_W - 20, height=self.COLLAPSED_H - 4
        )

        self._position_progress_bar()

    def _draw_island_shape(self, is_attached=True):
        """Draws the island canvas shape."""
        self.bg_canvas.delete("bg_shape")
        w, h = int(self.curr_w), int(self.curr_h)

        if is_attached:
            # Collapsed / Bezel State:
            # Trapezoid shape forming angled diagonal connections to top bezel
            flare = self.FLARE_X
            points = [
                0, 0,             # Top-left attached to bezel
                w + (flare * 2), 0,  # Top-right attached to bezel
                w + flare, h,     # Bottom-right corner
                flare, h          # Bottom-left corner
            ]
            self.bg_canvas.create_polygon(
                points, fill=BG_PANEL, outline="", tags="bg_shape"
            )
        else:
            # Expanded State:
            # Clean rectangular box shape
            self.bg_canvas.create_rectangle(
                0, 0, w, h,
                fill=BG_PANEL, outline="", tags="bg_shape"
            )

    def _on_progress_click(self, event):
        width = max(1, self.progress_canvas.winfo_width())
        fraction = max(0.0, min(1.0, event.x / width))
        self._set_progress(fraction)

        if self._progress_length > 0 and self.app.current_rc_port:
            target_sec = int(fraction * self._progress_length)
            self.app.send_rc_command(self.app.current_rc_port, f"seek {target_sec}")

    def toggle_expand(self):
        if self._animating:
            return
        self.is_expanded = not self.is_expanded

        if not self.is_expanded and self.settings_open:
            # Collapsing while settings is open - close it without a separate
            # animation; the collapse animation below already shrinks
            # smoothly from whatever height we're currently at.
            self.settings_open = False
            self.settings_frame.pack_forget()
            self.update_settings_button(False)

        target_w = self.EXPANDED_W if self.is_expanded else self.COLLAPSED_W
        target_h = self.EXPANDED_H if self.is_expanded else self.COLLAPSED_H
        target_y = self.EXPANDED_Y if self.is_expanded else self.COLLAPSED_Y

        if self.is_expanded:
            self.bg_canvas.delete(self.collapsed_window)
            self.expanded_window = self.bg_canvas.create_window(
                self.EXPANDED_W // 2, self.EXPANDED_H // 2, window=self.expanded_container,
                width=self.EXPANDED_W - 12, height=self.EXPANDED_H - 12
            )

        self._animate_resize(target_w, target_h, target_y, steps=18)

    def _animate_resize(self, target_w, target_h, target_y, steps=18):
        self._animating = True
        start_w, start_h = self.curr_w, self.curr_h
        start_y = self.curr_y
        center_x = self.center_x + (self.COLLAPSED_W / 2.0)

        def step(i):
            if i > steps:
                self.curr_w, self.curr_h = float(target_w), float(target_h)
                self.curr_y = target_y
                
                if self.is_expanded:
                    final_x = round(center_x - (target_w / 2.0))
                    self.geometry(f"{target_w}x{target_h}+{final_x}+{self.curr_y}")
                else:
                    win_w = target_w + (self.FLARE_X * 2)
                    win_x = round(center_x - (target_w / 2.0) - self.FLARE_X)
                    self.geometry(f"{win_w}x{target_h}+{win_x}+{self.curr_y}")

                self._draw_island_shape(is_attached=not self.is_expanded)

                if not self.is_expanded:
                    self.bg_canvas.delete(self.expanded_window)
                    win_w = self.COLLAPSED_W + (self.FLARE_X * 2)
                    self.collapsed_window = self.bg_canvas.create_window(
                        win_w // 2, self.COLLAPSED_H // 2, window=self.collapsed_frame,
                        width=self.COLLAPSED_W - 20, height=self.COLLAPSED_H - 4
                    )
                self._position_progress_bar()
                self._animating = False
                return

            t = i / float(steps)
            ease = 1.0 - (1.0 - t) ** 3

            curr_w = start_w + (target_w - start_w) * ease
            curr_h = start_h + (target_h - start_h) * ease
            curr_y = round(start_y + (target_y - start_y) * ease)

            self.curr_w, self.curr_h = curr_w, curr_h
            self.curr_y = curr_y

            is_attached = (curr_y < 5)
            if is_attached:
                win_w = round(curr_w + (self.FLARE_X * 2))
                curr_x = round(center_x - (curr_w / 2.0) - self.FLARE_X)
                self.geometry(f"{win_w}x{round(curr_h)}+{curr_x}+{curr_y}")
            else:
                curr_x = round(center_x - (curr_w / 2.0))
                self.geometry(f"{round(curr_w)}x{round(curr_h)}+{curr_x}+{curr_y}")

            self._draw_island_shape(is_attached=is_attached)

            if self.is_expanded:
                self.bg_canvas.coords(self.expanded_window, curr_w / 2, curr_h / 2)
                self.bg_canvas.itemconfig(self.expanded_window, width=curr_w - 12, height=curr_h - 12)

            self._position_progress_bar()

            self.after(10, lambda: step(i + 1))

        step(1)

    def toggle_settings(self):
        """Grows/shrinks the island vertically to reveal the settings
        panel. Only works while already expanded (the settings button
        lives inside the expanded view)."""
        if self._animating or not self.is_expanded:
            return
        self.settings_open = not self.settings_open
        self.update_settings_button(self.settings_open)

        if self.settings_open:
            self.settings_frame.pack(fill="x")
            self.vlc_toggle.set_state(self.app.vlc_windows_hidden)
            threading.Thread(target=self._sync_volume_from_vlc, daemon=True).start()
        else:
            self._end_volume_text_edit()

        target_h = self.EXPANDED_H + self.SETTINGS_EXTRA_H if self.settings_open else self.EXPANDED_H
        self._animate_settings_height(target_h)

    def _sync_volume_from_vlc(self):
        """Runs on a background thread: asks VLC for its actual current
        volume so the slider reflects reality even if it was changed
        some other way (VLC's own UI, media keys, etc.)."""
        vol = self.app.query_volume()
        if vol is not None:
            self.after(0, lambda v=vol: self.volume_slider.set(v))

    def _on_volume_change(self, value):
        """Fires whenever the slider's value changes, from a drag, a
        click, or a programmatic .set() call (including the sync above
        and the text-entry commit below)."""
        self.volume_value_label.config(text=f"{int(float(value))}%")
        self.app.set_volume(value)

    def _on_volume_bar_click(self, event):
        """Jump the knob straight to wherever the mouse is, instead of
        the default Tk behavior of nudging one page toward the click."""
        width = self.volume_slider.winfo_width()
        if width <= 1:
            return "break"
        fraction = max(0.0, min(1.0, event.x / width))
        self.volume_slider.set(round(fraction * 100))
        return "break"

    def _start_volume_text_edit(self, event):
        if self._volume_editing:
            return
        self._volume_editing = True
        current_val = int(self.volume_slider.get())

        self.volume_value_label.pack_forget()
        self.volume_edit_entry = tk.Entry(
            self.volume_value_label.master, width=4, font=FONT_SMALL,
            bg=BG_PANEL, fg=FG, insertbackground=FG, relief="flat",
            highlightthickness=1, highlightbackground="#3a3a3a", highlightcolor=ACCENT,
        )
        self.volume_edit_entry.insert(0, str(current_val))
        self.volume_edit_entry.pack(side="right", padx=(6, 0))
        self.volume_edit_entry.focus_set()
        self.volume_edit_entry.select_range(0, tk.END)
        self.volume_edit_entry.bind("<Return>", self._commit_volume_text_edit)
        self.volume_edit_entry.bind("<FocusOut>", self._commit_volume_text_edit)
        self.volume_edit_entry.bind("<Escape>", self._cancel_volume_text_edit)

    def _commit_volume_text_edit(self, event=None):
        if not self._volume_editing:
            return
        text = self.volume_edit_entry.get().strip()
        try:
            value = max(0, min(100, int(text)))
        except ValueError:
            value = int(self.volume_slider.get())
        self._end_volume_text_edit()
        self.volume_slider.set(value)

    def _cancel_volume_text_edit(self, event=None):
        self._end_volume_text_edit()

    def _end_volume_text_edit(self):
        if not self._volume_editing:
            return
        self._volume_editing = False
        if hasattr(self, "volume_edit_entry") and self.volume_edit_entry.winfo_exists():
            self.volume_edit_entry.destroy()
        self.volume_value_label.pack(side="right", padx=(6, 0))

    def _animate_settings_height(self, target_h, steps=14):
        self._animating = True
        start_h = self.curr_h
        x = self.winfo_x()

        def step(i):
            if i > steps:
                self.curr_h = float(target_h)
                self.geometry(f"{int(self.curr_w)}x{target_h}+{x}+{self.curr_y}")
                self._draw_island_shape(is_attached=False)
                self.bg_canvas.itemconfig(self.expanded_window, height=self.curr_h - 12)
                self._position_progress_bar()
                self._animating = False
                if not self.settings_open:
                    self.settings_frame.pack_forget()
                return

            t = i / float(steps)
            ease = 1.0 - (1.0 - t) ** 3
            curr_h = start_h + (target_h - start_h) * ease
            self.curr_h = curr_h

            self.geometry(f"{int(self.curr_w)}x{round(curr_h)}+{x}+{self.curr_y}")
            self._draw_island_shape(is_attached=False)
            self.bg_canvas.coords(self.expanded_window, self.curr_w / 2, curr_h / 2)
            self.bg_canvas.itemconfig(self.expanded_window, width=self.curr_w - 12, height=curr_h - 12)
            self._position_progress_bar()

            self.after(10, lambda: step(i + 1))

        step(1)

    def _position_progress_bar(self):
        if not self.winfo_exists() or not self.progress_window.winfo_exists():
            return
        self.update_idletasks()
        if not self.is_expanded:
            width = self.COLLAPSED_W
            x = self.center_x
        else:
            width = max(1, self.winfo_width())
            x = self.winfo_x()

        y = self.winfo_y() + self.winfo_height()
        self.progress_window.geometry(f"{width}x5+{x}+{y}")
        self.progress_canvas.config(width=width)
        self._set_progress(getattr(self, "_progress_fraction", 0.0))

    def update_autoplay_button(self):
        if self.app.autoplay_enabled:
            self.autoplay_button.config(fg=ACCENT, bg=ACCENT_BG, activebackground=ACCENT_BG)
        else:
            self.autoplay_button.config(fg=FG, bg=BG_PANEL, activebackground=BG_PANEL)

    def update_shuffle_button(self):
        if self.app.shuffle_enabled:
            self.shuffle_button.config(fg=ACCENT, bg=ACCENT_BG, activebackground=ACCENT_BG)
        else:
            self.shuffle_button.config(fg=FG, bg=BG_PANEL, activebackground=BG_PANEL)

    def update_search_button(self, active):
        if active:
            self.search_button.config(fg=ACCENT, bg=ACCENT_BG, activebackground=ACCENT_BG)
        else:
            self.search_button.config(fg=FG, bg=BG_PANEL, activebackground=BG_PANEL)

    def update_vlc_button(self):
        if hasattr(self, "vlc_toggle"):
            self.vlc_toggle.set_state(self.app.vlc_windows_hidden)

    def update_settings_button(self, active):
        if active:
            self.settings_button.config(fg=ACCENT, bg=ACCENT_BG, activebackground=ACCENT_BG)
        else:
            self.settings_button.config(fg=FG, bg=BG_PANEL, activebackground=BG_PANEL)

    def set_playing_state(self):
        self.playpause_button.config(text="\u23f8")
        self._start_progress()

    def set_paused_state(self):
        self.playpause_button.config(text="\u25b6")

    def set_stopped_state(self):
        self.playpause_button.config(text="\u25b6")
        self._stop_marquee()
        self._stop_progress()
        self._set_progress(0.0)
        self.now_playing_label.config(text="Nothing playing")
        self.collapsed_label.config(text="\u2022 BERRY play \u2022")
        self.location_label.config(text="")

    def set_now_playing(self, name, location=None):
        self._stop_marquee()
        self._marquee_text = name
        self._marquee_pos = 0

        if location:
            display_loc = location if len(location) <= 18 else location[:16] + "\u2026"
            self.location_label.config(text=f" \u00b7 {display_loc}")
        else:
            self.location_label.config(text="")

        if len(name) > 12:
            self._animate_marquee()
        else:
            self.collapsed_label.config(text=f"\u25b6 {name}")
            self.now_playing_label.config(text=name)

    def _animate_marquee(self):
        text = self._marquee_text + "   \u2022   "

        if len(self._marquee_text) > 12:
            col_display = (text[self._marquee_pos:] + text[:self._marquee_pos])[:16]
            self.collapsed_label.config(text=f"\u25b6 {col_display}")
        else:
            self.collapsed_label.config(text=f"\u25b6 {self._marquee_text}")

        if len(self._marquee_text) > 22:
            exp_display = (text[self._marquee_pos:] + text[:self._marquee_pos])[:22]
            self.now_playing_label.config(text=exp_display)
        else:
            self.now_playing_label.config(text=self._marquee_text)

        self._marquee_pos = (self._marquee_pos + 1) % len(text)
        self._marquee_job = self.after(300, self._animate_marquee)

    def _stop_marquee(self):
        if self._marquee_job is not None:
            self.after_cancel(self._marquee_job)
            self._marquee_job = None

    def _set_progress(self, fraction):
        fraction = max(0.0, min(1.0, fraction))
        self._progress_fraction = fraction
        if not self.progress_window.winfo_exists():
            return
        width = max(1, self.progress_canvas.winfo_width())
        self.progress_canvas.coords(self.progress_fill, 0, 0, width * fraction, 5)
        if fraction <= 0.0:
            self.progress_window.withdraw()
        else:
            self.progress_window.deiconify()

    def _start_progress(self):
        self._stop_progress()
        self._progress_last_time = None
        self._progress_last_timestamp = None
        self._progress_length = 0.0
        self._progress_job = self.after(33, self._update_progress)

    def _stop_progress(self):
        if self._progress_job is not None:
            self.after_cancel(self._progress_job)
            self._progress_job = None

    def _update_progress(self):
        proc = self.app.current_proc
        port = self.app.current_rc_port

        if proc is None or proc.poll() is not None or port is None:
            self._progress_job = None
            return

        now = time.monotonic()

        try:
            reply = self.app.send_rc_command(port, "get_time", reply=True)
            length_reply = self.app.send_rc_command(port, "get_length", reply=True)
            current = float(reply.strip())
            length = float(length_reply.strip())

            if length > 0:
                self._progress_length = length
                self._progress_last_time = current
                self._progress_last_timestamp = now
        except (ValueError, TypeError, AttributeError):
            pass

        if self._progress_last_time is not None and self._progress_last_timestamp is not None:
            estimated = self._progress_last_time + ((now - self._progress_last_timestamp))
            self._set_progress(estimated / self._progress_length)

        self._progress_job = self.after(33, self._update_progress)

    def destroy(self):
        self._stop_marquee()
        self._stop_progress()
        if hasattr(self, "progress_window") and self.progress_window.winfo_exists():
            self.progress_window.destroy()
        super().destroy()


if __name__ == "__main__":
    hide_console_window()
    app = PlayerApp()
    app.mainloop()