from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    X,
    Y,
    BooleanVar,
    StringVar,
    Text,
    TclError,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
)
from tkinter import ttk

from core import (
    APP_NAME,
    FILE_PREFIX,
    POSTPROCESS_PREFIX,
    TITLE_PREFIX,
    DownloadOptions,
    ToolPaths,
    build_analyze_command,
    build_download_command,
    detect_tools,
    executable_version,
    friendly_error,
    hidden_subprocess_kwargs,
    invalid_urls,
    normalize_urls,
    parse_progress_line,
    prepared_cookie_command,
    redact_log_line,
    validate_cookie_file,
)


APP_VERSION = "1.0.1"
SMOKE_RESULT_ENV = "YTDLP_GUI_SMOKE_RESULT"
ACCENT = "#2563EB"
ACCENT_ACTIVE = "#1D4ED8"
BG = "#F4F6FA"
CARD = "#FFFFFF"
TEXT = "#172033"
MUTED = "#667085"
SUCCESS = "#16803C"
DANGER = "#C43232"
BORDER = "#D8DEE9"


def enable_high_dpi() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def settings_file() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    return base / "settings.json"


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home()


class YTDLPApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=5000)
        self.process: subprocess.Popen[str] | None = None
        self.analysis_process: subprocess.Popen[str] | None = None
        self.worker: threading.Thread | None = None
        self.operation: str | None = None
        self.closing = False
        self.cancel_event = threading.Event()
        self.tools: ToolPaths = detect_tools()
        self.log_lines: deque[str] = deque(maxlen=2500)
        self.downloaded_files: list[Path] = []
        self.analysis_info: dict[str, object] | None = None
        self.active_format_mode: str | None = None
        self.log_dialog: Toplevel | None = None
        self.log_text: Text | None = None
        self.download_started_at = 0.0
        self.settings = self._load_settings()

        self.output_var = StringVar(
            value=str(self.settings.get("output_dir", default_download_dir()))
        )
        self.media_type_var = StringVar(value=str(self.settings.get("media_type", "video")))
        self.quality_var = StringVar(value=str(self.settings.get("quality", "best")))
        self.audio_format_var = StringVar(value=str(self.settings.get("audio_format", "mp3")))
        self.video_container_var = StringVar(value=str(self.settings.get("video_container", "mkv")))
        self.playlist_var = BooleanVar(value=bool(self.settings.get("playlist", False)))
        self.subtitles_var = BooleanVar(value=bool(self.settings.get("subtitles", False)))
        self.metadata_var = BooleanVar(value=bool(self.settings.get("metadata", True)))
        self.cookie_browser_var = StringVar(
            value=str(self.settings.get("cookie_browser", "none"))
        )
        self.cookie_file_var = StringVar(value=str(self.settings.get("cookie_file", "")))
        self.cookie_hint_var = StringVar()
        self.status_var = StringVar(value="准备就绪")
        self.detail_var = StringVar(value="粘贴一个或多个视频链接即可开始")
        self.progress_text_var = StringVar(value="0%")
        self.speed_var = StringVar(value="速度 —")
        self.eta_var = StringVar(value="剩余 —")
        self.tool_status_var = StringVar()
        self.advanced_open = BooleanVar(value=False)

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self.cookie_file_var.trace_add("write", self._invalidate_cookie_analysis)
        self._refresh_tool_status()
        self._on_media_type_changed()
        self._fit_initial_window()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self) -> None:
        self.root.title(f"{APP_NAME}  {APP_VERSION}")
        self.root.configure(bg=BG)
        self.root.geometry("920x730")
        self.root.minsize(820, 690)
        self.root.option_add("*Font", "{Microsoft YaHei UI} 10")

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("CardTitle.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Body.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("Status.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Success.TLabel", background=CARD, foreground=SUCCESS)
        style.configure("Tool.TLabel", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 8))
        style.configure(
            "Accent.TButton",
            foreground=ACCENT,
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=(18, 9),
        )
        style.map(
            "Accent.TButton",
            foreground=[("disabled", "#A4ADC0"), ("active", ACCENT_ACTIVE), ("!disabled", ACCENT)],
        )
        style.configure("Secondary.TButton", padding=(13, 8))
        style.configure("Danger.TButton", padding=(13, 8))
        style.configure("Link.TButton", padding=(4, 2))
        style.configure("Horizontal.TProgressbar", thickness=10, troughcolor="#E7ECF4", background=ACCENT)

    def _fit_initial_window(self) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        max_width = max(820, screen_width - 80)
        max_height = max(690, screen_height - 80)
        width = min(max(920, self.root.winfo_reqwidth()), max_width)
        height = min(max(780, self.root.winfo_reqheight()), max_height)
        self.root.minsize(min(820, max_width), min(690, max_height))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(24, 16, 24, 10))
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill=X, pady=(0, 12))
        logo = self._make_logo(header)
        logo.pack(side=LEFT, padx=(0, 13))
        title_wrap = ttk.Frame(header, style="App.TFrame")
        title_wrap.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(title_wrap, text=APP_NAME, style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_wrap, text="清爽、直接的 yt-dlp Windows 图形界面", style="Subtitle.TLabel").pack(anchor="w")
        self.tool_button = ttk.Button(header, text="检查工具", style="Secondary.TButton", command=self._show_tool_dialog)
        self.tool_button.pack(side=RIGHT)

        link_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        link_card.pack(fill=X, pady=(0, 10))
        link_head = ttk.Frame(link_card, style="Card.TFrame")
        link_head.pack(fill=X, pady=(0, 8))
        ttk.Label(link_head, text="视频链接", style="CardTitle.TLabel").pack(side=LEFT)
        ttk.Label(link_head, text="支持一行一个，也可一次粘贴多个", style="Muted.TLabel").pack(side=LEFT, padx=(10, 0))
        ttk.Button(link_head, text="清空", style="Link.TButton", command=self._clear_urls).pack(side=RIGHT)
        ttk.Button(link_head, text="粘贴", style="Link.TButton", command=self._paste_urls).pack(side=RIGHT, padx=(0, 6))

        self.url_text = Text(
            link_card,
            height=2,
            wrap="word",
            relief="solid",
            bd=1,
            highlightthickness=0,
            foreground=TEXT,
            background="#FBFCFE",
            insertbackground=TEXT,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=8,
        )
        self.url_text.pack(fill=X)
        self.url_text.bind("<<Modified>>", self._on_url_modified)

        link_actions = ttk.Frame(link_card, style="Card.TFrame")
        link_actions.pack(fill=X, pady=(8, 0))
        self.analyze_button = ttk.Button(link_actions, text="解析链接", style="Secondary.TButton", command=self._analyze_link)
        self.analyze_button.pack(side=LEFT)
        self.analysis_label = ttk.Label(link_actions, text="尚未解析", style="Muted.TLabel", wraplength=680)
        self.analysis_label.pack(side=LEFT, padx=(10, 0))

        options_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        options_card.pack(fill=X, pady=(0, 10))
        ttk.Label(options_card, text="下载选项", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        options_card.columnconfigure(1, weight=1)
        options_card.columnconfigure(3, weight=1)

        ttk.Label(options_card, text="类型", style="Body.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        type_box = ttk.Frame(options_card, style="Card.TFrame")
        type_box.grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(type_box, text="视频", value="video", variable=self.media_type_var, command=self._on_media_type_changed).pack(side=LEFT)
        ttk.Radiobutton(type_box, text="仅音频", value="audio", variable=self.media_type_var, command=self._on_media_type_changed).pack(side=LEFT, padx=(12, 0))

        ttk.Label(options_card, text="画质", style="Body.TLabel").grid(row=1, column=2, sticky="e", padx=(22, 8))
        self.quality_combo = ttk.Combobox(options_card, state="readonly", width=19)
        self.quality_combo.grid(row=1, column=3, sticky="ew")
        self.quality_combo["values"] = ("最佳画质（自动）", "优先 4K", "优先 1080p", "优先 720p", "优先 480p")
        self.quality_display_to_key = {
            "最佳画质（自动）": "best",
            "优先 4K": "2160",
            "优先 1080p": "1080",
            "优先 720p": "720",
            "优先 480p": "480",
        }
        self.quality_key_to_display = {value: key for key, value in self.quality_display_to_key.items()}
        self.quality_combo.set(self.quality_key_to_display.get(self.quality_var.get(), "最佳画质（自动）"))

        self.format_label = ttk.Label(options_card, text="容器", style="Body.TLabel")
        self.format_label.grid(row=1, column=4, sticky="e", padx=(22, 8))
        self.format_combo = ttk.Combobox(options_card, state="readonly", width=17)
        self.format_combo.grid(row=1, column=5, sticky="ew")
        self.format_combo.bind("<<ComboboxSelected>>", self._capture_format_selection)

        ttk.Label(options_card, text="保存到", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0), padx=(0, 8))
        self.output_entry = ttk.Entry(options_card, textvariable=self.output_var)
        self.output_entry.grid(row=2, column=1, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(options_card, text="浏览…", style="Secondary.TButton", command=self._choose_output).grid(row=2, column=5, sticky="e", pady=(10, 0), padx=(10, 0))

        advanced_toggle = ttk.Checkbutton(
            options_card,
            text="高级选项",
            variable=self.advanced_open,
            command=self._toggle_advanced,
        )
        advanced_toggle.grid(row=3, column=0, columnspan=6, sticky="w", pady=(9, 0))
        self.advanced_frame = ttk.Frame(options_card, style="Card.TFrame")
        self.advanced_frame.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        self.advanced_frame.columnconfigure(5, weight=1)

        ttk.Checkbutton(self.advanced_frame, text="下载播放列表", variable=self.playlist_var).grid(row=0, column=0, sticky="w")
        self.subtitle_check = ttk.Checkbutton(self.advanced_frame, text="下载中英字幕", variable=self.subtitles_var)
        self.subtitle_check.grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Checkbutton(self.advanced_frame, text="嵌入封面和信息", variable=self.metadata_var).grid(row=0, column=2, sticky="w", padx=(18, 0))
        login_row = ttk.Frame(self.advanced_frame, style="Card.TFrame")
        login_row.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(login_row, text="登录信息", style="Body.TLabel").pack(side=LEFT, padx=(0, 10))
        self.cookie_combo = ttk.Combobox(
            login_row,
            state="readonly",
            width=16,
            values=("不使用", "Chrome", "Edge", "Firefox", "Cookie 文件"),
        )
        self.cookie_combo.pack(side=LEFT)
        self.cookie_combo.bind("<<ComboboxSelected>>", self._on_cookie_source_changed)
        ttk.Button(login_row, text="登录帮助", style="Link.TButton", command=self._show_cookie_help).pack(side=LEFT, padx=(10, 0))
        cookie_display = {"none": "不使用", "chrome": "Chrome", "edge": "Edge", "firefox": "Firefox", "file": "Cookie 文件"}
        self.cookie_combo.set(cookie_display.get(self.cookie_browser_var.get(), "不使用"))
        self.cookie_file_frame = ttk.Frame(self.advanced_frame, style="Card.TFrame")
        self.cookie_file_frame.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        self.cookie_file_entry = ttk.Entry(self.cookie_file_frame, textvariable=self.cookie_file_var)
        self.cookie_file_entry.pack(side=LEFT, fill=X, expand=True)
        self.cookie_file_button = ttk.Button(self.cookie_file_frame, text="选择 cookies.txt…", command=self._choose_cookie_file)
        self.cookie_file_button.pack(side=LEFT, padx=(10, 0))
        ttk.Label(self.advanced_frame, textvariable=self.cookie_hint_var, style="Muted.TLabel", wraplength=740).grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self._on_cookie_source_changed()

        self.advanced_frame.grid_remove()

        progress_card = ttk.Frame(outer, style="Card.TFrame", padding=14)
        progress_card.pack(fill=BOTH, expand=True, pady=(0, 10))
        status_row = ttk.Frame(progress_card, style="Card.TFrame")
        status_row.pack(fill=X)
        ttk.Label(status_row, textvariable=self.status_var, style="Status.TLabel").pack(side=LEFT)
        ttk.Label(status_row, textvariable=self.progress_text_var, style="Success.TLabel").pack(side=RIGHT)
        ttk.Label(progress_card, textvariable=self.detail_var, style="Muted.TLabel", wraplength=820).pack(fill=X, anchor="w", pady=(4, 10))
        self.progress = ttk.Progressbar(progress_card, mode="determinate", maximum=100)
        self.progress.pack(fill=X)
        metrics = ttk.Frame(progress_card, style="Card.TFrame")
        metrics.pack(fill=X, pady=(7, 0))
        ttk.Label(metrics, textvariable=self.speed_var, style="Muted.TLabel").pack(side=LEFT)
        ttk.Label(metrics, textvariable=self.eta_var, style="Muted.TLabel").pack(side=LEFT, padx=(18, 0))
        ttk.Button(metrics, text="复制日志", style="Link.TButton", command=self._copy_log).pack(side=RIGHT)
        ttk.Button(metrics, text="查看详细日志", style="Link.TButton", command=self._show_log_dialog).pack(side=RIGHT, padx=(0, 8))

        actions = ttk.Frame(outer, style="App.TFrame")
        actions.pack(fill=X)
        self.download_button = ttk.Button(actions, text="开始下载", style="Accent.TButton", command=self._start_download)
        self.download_button.pack(side=LEFT)
        self.cancel_button = ttk.Button(actions, text="取消", style="Danger.TButton", command=self._cancel_download, state="disabled")
        self.cancel_button.pack(side=LEFT, padx=(8, 0))
        self.open_file_button = ttk.Button(actions, text="打开文件", style="Secondary.TButton", command=self._open_last_file, state="disabled")
        self.open_file_button.pack(side=RIGHT)
        self.open_folder_button = ttk.Button(actions, text="打开文件夹", style="Secondary.TButton", command=self._open_output_folder)
        self.open_folder_button.pack(side=RIGHT, padx=(0, 8))

        ttk.Label(outer, textvariable=self.tool_status_var, style="Tool.TLabel").pack(fill=X, pady=(5, 0))

    def _make_logo(self, parent: ttk.Frame):
        from tkinter import Canvas

        canvas = Canvas(parent, width=52, height=52, bg=BG, highlightthickness=0)
        canvas.create_oval(2, 2, 50, 50, fill=ACCENT, outline="")
        canvas.create_polygon(21, 15, 39, 26, 21, 37, fill="#FFFFFF", outline="")
        return canvas

    def _load_settings(self) -> dict[str, object]:
        path = settings_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    def _save_settings(self) -> None:
        self._capture_format_selection()
        quality = self.quality_display_to_key.get(self.quality_combo.get(), "best")
        cookie = "file" if self.cookie_combo.get() == "Cookie 文件" else self._cookie_browser_key()
        values = {
            "output_dir": self.output_var.get().strip(),
            "media_type": self.media_type_var.get(),
            "quality": quality,
            "audio_format": self.audio_format_var.get(),
            "video_container": self.video_container_var.get(),
            "playlist": self.playlist_var.get(),
            "subtitles": self.subtitles_var.get(),
            "metadata": self.metadata_var.get(),
            "cookie_browser": cookie,
            "cookie_file": self.cookie_file_var.get().strip(),
        }
        path = settings_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _toggle_advanced(self) -> None:
        if self.advanced_open.get():
            self.advanced_frame.grid()
            self._fit_options_height()
        else:
            self.advanced_frame.grid_remove()

    def _fit_options_height(self) -> None:
        self.root.update_idletasks()
        height = min(self.root.winfo_reqheight(), max(690, self.root.winfo_screenheight() - 80))
        if height > self.root.winfo_height():
            width = max(820, self.root.winfo_width())
            self.root.geometry(f"{width}x{height}")

    def _on_cookie_source_changed(self, _event=None) -> None:
        source = self.cookie_combo.get()
        if source == "Cookie 文件":
            self.cookie_file_frame.grid()
            hint = "选择从已登录浏览器导出的 Netscape cookies.txt。会员画质取决于账号权限和视频源。"
        else:
            self.cookie_file_frame.grid_remove()
            if source in {"Chrome", "Edge"}:
                hint = "请先完全退出浏览器再读取；若仍报解密失败，请改用 Cookie 文件或已登录的 Firefox。"
            elif source == "Firefox":
                hint = "请先在 Firefox 中登录对应网站；登录账号需要具备所选画质的权限。"
            else:
                hint = "不使用登录信息时，Bilibili 可能只提供较低画质。大会员请导入 Cookie 文件或读取已登录浏览器。"
        self.cookie_hint_var.set(hint)
        self._invalidate_cookie_analysis()
        if self.advanced_open.get():
            self._fit_options_height()

    def _invalidate_cookie_analysis(self, *_args) -> None:
        if self.analysis_info is not None:
            self.analysis_info = None
            self.analysis_label.configure(text="登录信息已变化，请重新解析")

    def _choose_cookie_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root, title="选择浏览器导出的 cookies.txt",
            filetypes=(("Cookie 文本文件", "*.txt"), ("所有文件", "*.*")),
        )
        if not selected:
            return
        try:
            path = validate_cookie_file(selected)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.cookie_file_var.set(str(path))
        self._on_cookie_source_changed()
        self._save_settings()

    def _selected_cookie_file(self) -> Path | None:
        if self.cookie_combo.get() != "Cookie 文件":
            return None
        value = self.cookie_file_var.get().strip()
        if not value:
            raise ValueError("请先选择从已登录浏览器导出的 cookies.txt 文件。")
        return validate_cookie_file(value)

    def _show_cookie_help(self) -> None:
        messagebox.showinfo(
            "登录信息与会员画质",
            "Chrome / Edge 提示无法复制数据库：保存浏览器中的工作，完全退出浏览器后再试。\n\n"
            "提示 DPAPI 或解密失败：当前浏览器的加密方式可能不支持直接读取。可在 Firefox 登录后选择 Firefox，或使用 Cookie 文件。\n\n"
            "Cookie 文件用法：\n"
            "1. 在 Chrome 打开 Bilibili，确认已登录大会员账号。\n"
            "2. 使用 yt-dlp 官方 FAQ 列出的 Get cookies.txt LOCALLY 扩展，仅导出 bilibili.com 的 Netscape cookies.txt。\n"
            "3. 登录信息选择“Cookie 文件”，选中导出文件，再解析或下载。\n\n"
            "Cookie 文件相当于登录凭证，请只在本机使用，不要发给他人。软件只记住文件路径，任务使用临时副本并在结束后清理。\n\n"
            "官方说明：https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp",
            parent=self.root,
        )

    def _on_media_type_changed(self) -> None:
        if self.active_format_mode:
            self._capture_format_selection()
        audio = self.media_type_var.get() == "audio"
        self.quality_combo.configure(state="disabled" if audio else "readonly")
        self.subtitle_check.configure(state="disabled" if audio else "normal")
        if audio:
            self.format_label.configure(text="音频格式")
            self.format_combo.configure(values=("MP3", "M4A"), width=10)
            self.format_combo.set(self.audio_format_var.get().upper())
            self.active_format_mode = "audio"
        else:
            self.format_label.configure(text="视频容器")
            self.format_combo.configure(values=("MKV（画质优先）", "MP4（兼容优先）"), width=17)
            self.format_combo.set(
                "MP4（兼容优先）" if self.video_container_var.get() == "mp4" else "MKV（画质优先）"
            )
            self.active_format_mode = "video"

    def _capture_format_selection(self, _event=None) -> None:
        if self.active_format_mode == "audio":
            value = self.format_combo.get().lower()
            if value in {"mp3", "m4a"}:
                self.audio_format_var.set(value)
        elif self.active_format_mode == "video":
            self.video_container_var.set(
                "mp4" if self.format_combo.get().startswith("MP4") else "mkv"
            )

    def _on_url_modified(self, _event=None) -> None:
        if self.url_text.edit_modified():
            self.analysis_info = None
            self.analysis_label.configure(text="内容已变化，请重新解析")
            self.url_text.edit_modified(False)

    def _paste_urls(self) -> None:
        try:
            value = self.root.clipboard_get()
        except Exception:
            messagebox.showinfo(APP_NAME, "剪贴板中没有可粘贴的文字。", parent=self.root)
            return
        if self.url_text.get("1.0", END).strip():
            self.url_text.insert(END, "\n")
        self.url_text.insert(END, value.strip())

    def _clear_urls(self) -> None:
        self.url_text.delete("1.0", END)
        self.analysis_info = None
        self.analysis_label.configure(text="尚未解析")

    def _choose_output(self) -> None:
        initial = Path(self.output_var.get().strip() or default_download_dir())
        selected = filedialog.askdirectory(parent=self.root, initialdir=initial if initial.exists() else default_download_dir())
        if selected:
            self.output_var.set(selected)
            self._save_settings()

    def _refresh_tool_status(self) -> None:
        self.tools = detect_tools()
        yt_state = "✓" if self.tools.yt_dlp else "缺失"
        ffmpeg_state = "✓" if self.tools.ffmpeg_ready else "缺失"
        js_state = " / ".join(name.title() for name, _ in self.tools.js_runtimes) or "缺失"
        self.tool_status_var.set(f"工具状态：yt-dlp {yt_state}    FFmpeg/ffprobe {ffmpeg_state}    JavaScript {js_state}")
        if self.operation is None:
            idle_state = "normal" if self.tools.yt_dlp else "disabled"
            self.download_button.configure(state=idle_state)
            self.analyze_button.configure(state=idle_state)

    def _show_tool_dialog(self) -> None:
        self._refresh_tool_status()
        dialog = Toplevel(self.root)
        dialog.title("工具检测")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=22)
        frame.pack(fill=BOTH, expand=True, padx=12, pady=12)
        ttk.Label(frame, text="运行工具", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        values = [
            ("yt-dlp", self.tools.yt_dlp, "未找到", ""),
            ("FFmpeg", self.tools.ffmpeg, "未找到", ""),
            ("ffprobe", self.tools.ffprobe, "未找到", ""),
            ("Deno", self.tools.deno, "未找到（推荐 2.3+）", "Deno"),
            ("Node.js", self.tools.node, "未找到（需 22+）", "Node"),
        ]
        version_targets: list[tuple[ttk.Label, Path, str]] = []
        for row, (name, path, missing_message, prefix) in enumerate(values, start=1):
            ttk.Label(frame, text=name, style="Body.TLabel").grid(row=row, column=0, sticky="nw", padx=(0, 16), pady=5)
            message = f"已找到\n{path}\n正在读取版本…" if path else missing_message
            value_label = ttk.Label(frame, text=message, style="Muted.TLabel", wraplength=510)
            value_label.grid(row=row, column=1, sticky="w", pady=5)
            if path:
                version_targets.append((value_label, path, prefix))
        tip = "把 yt-dlp.exe、ffmpeg.exe、ffprobe.exe 与 deno.exe 放入应用旁的 tools 文件夹，也可以自动识别。"
        ttk.Label(frame, text=tip, style="Muted.TLabel", wraplength=560).grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 10))
        ttk.Button(frame, text="关闭", style="Secondary.TButton", command=dialog.destroy).grid(row=7, column=1, sticky="e")
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        dialog.grab_set()
        for label, path, prefix in version_targets:
            threading.Thread(
                target=self._tool_version_worker,
                args=(label, path, prefix),
                daemon=True,
            ).start()

    def _tool_version_worker(self, label: ttk.Label, path: Path, prefix: str) -> None:
        version = executable_version(path) or "版本读取失败"
        if prefix:
            version = f"{prefix} {version}"
        self.events.put(("tool_version", (label, path, version)))

    def _validate_common(self) -> tuple[list[str], Path] | None:
        urls = normalize_urls(self.url_text.get("1.0", END))
        if not urls:
            messagebox.showwarning(APP_NAME, "请先粘贴视频链接。", parent=self.root)
            self.url_text.focus_set()
            return None
        bad = invalid_urls(urls)
        if bad:
            messagebox.showwarning(APP_NAME, f"这不是完整的网址：\n{bad[0]}", parent=self.root)
            return None
        output_dir = Path(self.output_var.get().strip() or default_download_dir()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".ytdlp-gui-", dir=output_dir):
                pass
        except OSError:
            messagebox.showerror(APP_NAME, "保存目录无法写入，请换一个目录。", parent=self.root)
            return None
        return urls, output_dir

    def _analyze_link(self) -> None:
        if self.operation is not None:
            return
        validated = self._validate_common()
        if not validated or not self.tools.yt_dlp:
            return
        urls, _ = validated
        if len(urls) > 1:
            self.analysis_label.configure(text=f"已输入 {len(urls)} 个链接，将逐个下载")
            return
        if self.worker and self.worker.is_alive():
            return
        cookie = self._cookie_browser_key()
        try:
            cookie_file = self._selected_cookie_file()
            command = build_analyze_command(self.tools.yt_dlp, urls[0], cookie, self.tools.js_runtimes, cookie_file=cookie_file)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.cancel_event.clear()
        self.analysis_label.configure(text="正在解析…")
        self.status_var.set("正在解析链接")
        self.detail_var.set("正在读取标题和播放列表信息")
        self.analyze_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.tool_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.url_text.configure(state="disabled")
        self.operation = "analysis"
        self._set_cookie_controls_enabled(False)
        self.worker = threading.Thread(target=self._analyze_worker, args=(command,), daemon=True)
        self.worker.start()

    def _analyze_worker(self, command: list[str]) -> None:
        try:
            with prepared_cookie_command(command) as prepared:
                result = self._analyze_worker_with_command(prepared)
            self.events.put(result)
        except (OSError, ValueError) as exc:
            self.events.put(("analysis_error", str(exc)))

    def _analyze_worker_with_command(self, command: list[str]) -> tuple[str, object]:
        try:
            self.analysis_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_subprocess_kwargs(),
            )
            if self.cancel_event.is_set():
                self._terminate_process(self.analysis_process)
            stdout, stderr = self.analysis_process.communicate(timeout=90)
            return_code = self.analysis_process.returncode
            if self.cancel_event.is_set():
                return ("analysis_cancelled", None)
            if return_code != 0:
                return ("analysis_error", stderr or stdout)
            for line in stderr.splitlines():
                self.events.put(("process_line", redact_log_line(line)))
            data = json.loads(stdout)
            return ("analysis_done", data)
        except subprocess.TimeoutExpired:
            if self.analysis_process:
                self._terminate_process(self.analysis_process)
            return ("analysis_error", "解析超时，请检查网络后重试。")
        except (OSError, json.JSONDecodeError) as exc:
            return ("analysis_error", str(exc))
        finally:
            self.analysis_process = None

    def _start_download(self) -> None:
        if self.operation is not None:
            return
        validated = self._validate_common()
        if not validated:
            return
        if not self.tools.yt_dlp:
            messagebox.showerror(APP_NAME, "未找到 yt-dlp，请点击“检查工具”查看解决方法。", parent=self.root)
            return
        if not self.tools.ffmpeg_ready:
            messagebox.showerror(APP_NAME, "未同时找到 FFmpeg 和 ffprobe，无法可靠地合并视频或转换音频。请点击“检查工具”查看解决方法。", parent=self.root)
            return

        urls, output_dir = validated
        try:
            cookie_file = self._selected_cookie_file()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        if self.playlist_var.get():
            count = None
            if self.analysis_info:
                entries = self.analysis_info.get("entries")
                count = len(entries) if isinstance(entries, list) else None
            count_text = f"（约 {count} 项）" if count else ""
            if not messagebox.askyesno(APP_NAME, f"已开启播放列表下载{count_text}。\n确定要继续吗？", parent=self.root):
                return

        self._capture_format_selection()
        options = DownloadOptions(
            output_dir=output_dir,
            media_type=self.media_type_var.get(),
            quality=self.quality_display_to_key.get(self.quality_combo.get(), "best"),
            audio_format=self.audio_format_var.get(),
            video_container=self.video_container_var.get(),
            playlist=self.playlist_var.get(),
            subtitles=self.subtitles_var.get(),
            metadata=self.metadata_var.get(),
            cookie_browser=self._cookie_browser_key(),
            cookie_file=cookie_file,
        )
        try:
            command = build_download_command(
                self.tools.yt_dlp,
                urls,
                options,
                self.tools.ffmpeg_dir,
                self.tools.js_runtimes,
            )
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        self.operation = "download"
        self._save_settings()
        self._set_running_state(True)
        self.cancel_event.clear()
        self.log_lines.clear()
        self._replace_log("")
        self.downloaded_files.clear()
        self.open_file_button.configure(state="disabled")
        self.progress.configure(value=0)
        self.progress_text_var.set("0%")
        self.speed_var.set("速度 —")
        self.eta_var.set("剩余 —")
        self.status_var.set("正在准备下载")
        self.detail_var.set(f"共 {len(urls)} 个链接")
        self.download_started_at = time.monotonic()
        self._append_log(f"{APP_NAME} {APP_VERSION}")
        self._append_log(f"保存目录：{output_dir}")
        self._append_log("下载任务已启动。")
        self.worker = threading.Thread(target=self._download_worker, args=(command,), daemon=True)
        self.worker.start()

    def _download_worker(self, command: list[str]) -> None:
        try:
            with prepared_cookie_command(command) as prepared:
                result = self._download_worker_with_command(prepared)
            self.events.put(result)
        except (OSError, ValueError) as exc:
            self.events.put(("download_exception", str(exc)))

    def _download_worker_with_command(self, command: list[str]) -> tuple[str, object]:
        kwargs = hidden_subprocess_kwargs()
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
            )
            if self.cancel_event.is_set():
                self._terminate_process(self.process)
            assert self.process.stdout is not None
            for raw_line in self.process.stdout:
                if self.cancel_event.is_set():
                    break
                line = raw_line.rstrip("\r\n")
                self.events.put(("process_line", line))
            return_code = self.process.wait()
            if self.cancel_event.is_set():
                return ("download_cancelled", None)
            else:
                return ("download_finished", return_code)
        except OSError as exc:
            return ("download_exception", str(exc))
        finally:
            if self.process and self.process.poll() is None:
                self._terminate_process(self.process)
            self.process = None

    def _cancel_download(self) -> None:
        self.cancel_event.set()
        self.status_var.set("正在取消")
        self.detail_var.set("正在结束 yt-dlp 和 FFmpeg 进程…")
        if self.process:
            threading.Thread(
                target=self._terminate_process,
                args=(self.process,),
                daemon=True,
            ).start()
        elif self.analysis_process:
            threading.Thread(
                target=self._terminate_process,
                args=(self.analysis_process,),
                daemon=True,
            ).start()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                    **hidden_subprocess_kwargs(),
                )
                if result.returncode != 0 and process.poll() is None:
                    process.kill()
            else:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass

    def _handle_process_line(self, line: str) -> None:
        progress = parse_progress_line(line)
        if progress:
            if progress.percent is not None:
                self.progress.configure(value=progress.percent)
                self.progress_text_var.set(f"{progress.percent:.1f}%")
            self.speed_var.set(f"速度 {progress.speed or '—'}")
            self.eta_var.set(f"剩余 {progress.eta or '—'}")
            self.status_var.set("正在下载")
            if progress.title:
                self.detail_var.set(progress.title)
            return
        if line.startswith(TITLE_PREFIX):
            raw_title = line[len(TITLE_PREFIX) :].strip()
            try:
                title = json.loads(raw_title)
            except json.JSONDecodeError:
                title = raw_title
            if title:
                self.detail_var.set(str(title))
            return
        if line.startswith(FILE_PREFIX):
            raw_path = line[len(FILE_PREFIX) :].strip()
            try:
                path_text = json.loads(raw_path)
            except json.JSONDecodeError:
                path_text = raw_path
            if path_text:
                path = Path(str(path_text))
                self.downloaded_files.append(path)
                self.open_file_button.configure(state="normal" if path.exists() else "disabled")
            return
        if line.startswith(POSTPROCESS_PREFIX):
            self.status_var.set("正在合并或转换")
            return

        lowered = line.lower()
        if any(tag in lowered for tag in ("[merger]", "[extractaudio]", "[videoremuxer]", "[ffmpeg]")):
            self.status_var.set("正在合并或转换")
        self._append_log(redact_log_line(line))

    def _drain_events(self) -> None:
        processed = 0
        try:
            while processed < 200:
                event, payload = self.events.get_nowait()
                processed += 1
                if self.closing and event != "close_ready":
                    continue
                if event == "process_line":
                    self._handle_process_line(str(payload))
                elif event == "download_finished":
                    self._finish_download(int(payload))
                elif event == "download_cancelled":
                    self._finish_cancelled()
                elif event == "download_exception":
                    self._finish_exception(str(payload))
                elif event == "analysis_done":
                    self._finish_analysis(payload)
                elif event == "analysis_error":
                    self._finish_analysis_error(str(payload))
                elif event == "analysis_cancelled":
                    self._finish_analysis_cancelled()
                elif event == "tool_version":
                    label, path, version = payload
                    try:
                        if label.winfo_exists():
                            label.configure(text=f"已找到\n{path}\n{version}")
                    except TclError:
                        pass
                elif event == "close_ready":
                    self._finalize_close()
                    return
        except queue.Empty:
            pass
        self.root.after(1 if not self.events.empty() else 100, self._drain_events)

    def _finish_download(self, return_code: int) -> None:
        self.operation = None
        self._set_running_state(False)
        elapsed = max(0, int(time.monotonic() - self.download_started_at))
        if return_code == 0:
            self.progress.configure(value=100)
            self.progress_text_var.set("100%")
            self.status_var.set("下载完成")
            file_count = len(self.downloaded_files)
            count_text = f"，生成 {file_count} 个文件" if file_count else ""
            self.detail_var.set(f"用时 {elapsed // 60}分{elapsed % 60}秒{count_text}")
            self._append_log("任务已完成。")
            if self.downloaded_files:
                self.open_file_button.configure(state="normal")
        else:
            text = "\n".join(self.log_lines)
            summary = friendly_error(text)
            self.status_var.set("下载失败")
            self.detail_var.set(summary)
            self.progress_text_var.set("失败")
            self._append_log(f"任务退出，代码：{return_code}")

    def _finish_cancelled(self) -> None:
        self.operation = None
        self._set_running_state(False)
        self.status_var.set("已取消")
        self.detail_var.set("任务已结束；未完成的临时文件可能保留，便于下次续传")
        self.progress_text_var.set("已取消")
        self._append_log("用户取消了任务。")

    def _finish_exception(self, message: str) -> None:
        self.operation = None
        self._set_running_state(False)
        self.status_var.set("无法启动下载")
        self.detail_var.set(message)
        self.progress_text_var.set("失败")
        self._append_log(redact_log_line(message))

    def _finish_analysis(self, payload: object) -> None:
        self.operation = None
        self._set_cookie_controls_enabled(True)
        self.analyze_button.configure(state="normal")
        self.download_button.configure(state="normal" if self.tools.yt_dlp else "disabled")
        self.tool_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.url_text.configure(state="normal")
        self.status_var.set("解析完成")
        self.detail_var.set("链接有效，可以开始下载")
        if not isinstance(payload, dict):
            self.analysis_label.configure(text="已解析")
            return
        self.analysis_info = payload
        title = str(payload.get("title") or payload.get("id") or "已识别内容")
        entries = payload.get("entries")
        if isinstance(entries, list):
            self.analysis_label.configure(text=f"播放列表：{title}（{len(entries)} 项）")
        else:
            duration = payload.get("duration_string")
            suffix = f" · {duration}" if duration else ""
            formats = payload.get("formats") or []
            heights = sorted({int(item["height"]) for item in formats
                              if isinstance(item, dict) and isinstance(item.get("height"), (int, float)) and item["height"] > 0})
            if heights:
                suffix += " · 可用画质：" + " / ".join(f"{height}p" for height in heights)
                self.detail_var.set(f"当前登录方式可读取的最高分辨率：{heights[-1]}p；以视频实际提供的格式为准")
            self.analysis_label.configure(text=f"{title}{suffix}")

    def _finish_analysis_error(self, message: str) -> None:
        self.operation = None
        self._set_cookie_controls_enabled(True)
        self.analyze_button.configure(state="normal")
        self.download_button.configure(state="normal" if self.tools.yt_dlp else "disabled")
        self.tool_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.url_text.configure(state="normal")
        summary = friendly_error(message)
        self.analysis_label.configure(text=summary)
        self.status_var.set("解析失败")
        self.detail_var.set(summary)
        self._append_log(redact_log_line(message))

    def _finish_analysis_cancelled(self) -> None:
        self.operation = None
        self._set_cookie_controls_enabled(True)
        self.analyze_button.configure(state="normal")
        self.download_button.configure(state="normal" if self.tools.yt_dlp else "disabled")
        self.tool_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.url_text.configure(state="normal")
        self.status_var.set("已取消解析")
        self.detail_var.set("可以修改链接或重新解析")

    def _set_running_state(self, running: bool) -> None:
        self._set_cookie_controls_enabled(not running)
        download_idle_state = "normal" if self.tools.yt_dlp else "disabled"
        self.download_button.configure(state="disabled" if running else download_idle_state)
        self.analyze_button.configure(state="disabled" if running else download_idle_state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.tool_button.configure(state="disabled" if running else "normal")
        self.url_text.configure(state="disabled" if running else "normal")

    def _cookie_browser_key(self) -> str:
        return {"不使用": "none", "Chrome": "chrome", "Edge": "edge", "Firefox": "firefox"}.get(self.cookie_combo.get(), "none")

    def _set_cookie_controls_enabled(self, enabled: bool) -> None:
        self.cookie_combo.configure(state="readonly" if enabled else "disabled")
        self.cookie_file_entry.configure(state="normal" if enabled else "disabled")
        self.cookie_file_button.configure(state="normal" if enabled else "disabled")

    def _append_log(self, line: str) -> None:
        if not line:
            return
        line = redact_log_line(line)
        self.log_lines.append(line)
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            self.log_text.insert(END, line + "\n")
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 2500:
                self.log_text.delete("1.0", "300.0")
            self.log_text.see(END)
            self.log_text.configure(state="disabled")

    def _replace_log(self, text: str) -> None:
        if self.log_text and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", END)
            if text:
                self.log_text.insert(END, text)
            self.log_text.configure(state="disabled")

    def _show_log_dialog(self) -> None:
        if self.log_dialog and self.log_dialog.winfo_exists():
            self.log_dialog.deiconify()
            self.log_dialog.lift()
            return
        dialog = Toplevel(self.root)
        self.log_dialog = dialog
        dialog.title("详细日志")
        dialog.geometry("760x430")
        dialog.minsize(580, 320)
        dialog.transient(self.root)
        dialog.configure(bg=BG)
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=14)
        frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
        head = ttk.Frame(frame, style="Card.TFrame")
        head.pack(fill=X, pady=(0, 8))
        ttk.Label(head, text="yt-dlp 输出", style="CardTitle.TLabel").pack(side=LEFT)
        ttk.Button(head, text="复制日志", style="Secondary.TButton", command=self._copy_log).pack(side=RIGHT)
        self.log_text = Text(
            frame,
            wrap="word",
            state="normal",
            relief="solid",
            bd=1,
            highlightthickness=0,
            foreground="#45516B",
            background="#F8FAFD",
            font=("Cascadia Mono", 9),
            padx=9,
            pady=7,
        )
        content = "\n".join(self.log_lines) or "暂无日志。"
        self.log_text.insert(END, content)
        self.log_text.configure(state="disabled")
        self.log_text.pack(fill=BOTH, expand=True)

        def close_dialog() -> None:
            dialog.destroy()
            self.log_dialog = None
            self.log_text = None

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

    def _copy_log(self) -> None:
        content = "\n".join(self.log_lines)
        if not content:
            messagebox.showinfo(APP_NAME, "目前没有日志可复制。", parent=self.root)
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.status_var.set("日志已复制")
        except TclError:
            messagebox.showerror(APP_NAME, "剪贴板暂时被占用，请稍后重试。", parent=self.root)

    def _open_output_folder(self) -> None:
        path = Path(self.output_var.get().strip() or default_download_dir())
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"无法打开文件夹：{exc}", parent=self.root)

    def _open_last_file(self) -> None:
        for path in reversed(self.downloaded_files):
            if path.exists():
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                except OSError as exc:
                    messagebox.showerror(APP_NAME, f"无法打开文件：{exc}", parent=self.root)
                return
        messagebox.showinfo(APP_NAME, "没有找到已完成的文件。", parent=self.root)

    def _on_close(self) -> None:
        if self.closing:
            return
        busy = self.worker is not None and self.worker.is_alive()
        if busy:
            if not messagebox.askyesno(APP_NAME, "任务仍在进行。要取消并退出吗？", parent=self.root):
                return
            self.closing = True
            self.cancel_event.set()
            self.status_var.set("正在安全退出")
            self.detail_var.set("正在结束后台任务…")
            self.download_button.configure(state="disabled")
            self.analyze_button.configure(state="disabled")
            self.cancel_button.configure(state="disabled")
            processes = [process for process in (self.process, self.analysis_process) if process]
            threading.Thread(
                target=self._close_worker,
                args=(processes, self.worker),
                daemon=True,
            ).start()
            return
        self._finalize_close()

    def _close_worker(
        self,
        processes: list[subprocess.Popen[str]],
        worker: threading.Thread | None,
    ) -> None:
        handled: set[int] = set()
        deadline = time.monotonic() + 12
        while True:
            current = [process for process in (self.process, self.analysis_process) if process]
            for process in [*processes, *current]:
                if process.pid not in handled:
                    handled.add(process.pid)
                    self._terminate_process(process)
            if not worker or not worker.is_alive() or time.monotonic() >= deadline:
                break
            worker.join(timeout=0.1)
        self.events.put(("close_ready", None))

    def _finalize_close(self) -> None:
        self._save_settings()
        self.root.destroy()


def main() -> None:
    enable_high_dpi()
    root = Tk()
    YTDLPApp(root)
    if "--smoke-test" in sys.argv:
        root.withdraw()
        root.update_idletasks()
        smoke_result = os.environ.get(SMOKE_RESULT_ENV)
        if smoke_result:
            Path(smoke_result).write_text("ok", encoding="ascii")
        root.after(350, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
