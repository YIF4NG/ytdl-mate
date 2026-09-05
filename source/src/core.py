from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


APP_NAME = "YT下载助手"
PROGRESS_PREFIX = "__YTDLP_PROGRESS__"
POSTPROCESS_PREFIX = "__YTDLP_POSTPROCESS__"
TITLE_PREFIX = "__YTDLP_TITLE__"
FILE_PREFIX = "__YTDLP_FILE__"


@dataclass(frozen=True)
class DownloadOptions:
    output_dir: Path
    media_type: str = "video"
    quality: str = "best"
    audio_format: str = "mp3"
    video_container: str = "mkv"
    playlist: bool = False
    subtitles: bool = False
    metadata: bool = True
    cookie_browser: str = "none"
    cookie_file: Path | None = None


@dataclass(frozen=True)
class ProgressUpdate:
    percent: float | None
    speed: str
    eta: str
    title: str


@dataclass(frozen=True)
class ToolPaths:
    yt_dlp: Path | None
    ffmpeg: Path | None
    ffprobe: Path | None
    deno: Path | None
    node: Path | None

    @property
    def ffmpeg_dir(self) -> Path | None:
        if self.ffmpeg:
            return self.ffmpeg.parent
        if self.ffprobe:
            return self.ffprobe.parent
        return None

    @property
    def ffmpeg_ready(self) -> bool:
        if not self.ffmpeg or not self.ffprobe:
            return False
        return os.path.normcase(str(self.ffmpeg.parent)) == os.path.normcase(
            str(self.ffprobe.parent)
        )

    @property
    def js_runtime(self) -> tuple[str, Path] | None:
        if self.deno:
            return ("deno", self.deno)
        if self.node:
            return ("node", self.node)
        return None

    @property
    def js_runtimes(self) -> tuple[tuple[str, Path], ...]:
        runtimes: list[tuple[str, Path]] = []
        if self.deno:
            runtimes.append(("deno", self.deno))
        if self.node:
            runtimes.append(("node", self.node))
        return tuple(runtimes)


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _candidate_directories() -> list[Path]:
    app_dir = app_directory()
    tools_dir = app_dir / "tools"
    candidates = [tools_dir, tools_dir / "ffmpeg" / "bin"]
    if tools_dir.is_dir():
        try:
            candidates.extend(
                child / "bin" for child in tools_dir.iterdir() if (child / "bin").is_dir()
            )
        except OSError:
            pass
    candidates.append(app_dir)

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        profile_path = Path(user_profile)
        candidates.append(
            profile_path / "Documents" / "Codex" / "tools" / "ffmpeg" / "bin"
        )
        candidates.append(profile_path / ".deno" / "bin")
        candidates.append(
            profile_path
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
        )

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "nodejs")

    # Preserve order while removing duplicate paths.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_executable(name: str, directories: Iterable[Path] | None = None) -> Path | None:
    executable_name = name if name.lower().endswith(".exe") else f"{name}.exe"
    for directory in directories or _candidate_directories():
        candidate = directory / executable_name
        if candidate.is_file():
            return candidate.resolve()

    located = shutil.which(name) or shutil.which(executable_name)
    return Path(located).resolve() if located else None


def find_ffmpeg_suite(
    directories: Iterable[Path] | None = None,
) -> tuple[Path | None, Path | None]:
    search_directories = list(directories or _candidate_directories())
    for directory in search_directories:
        ffmpeg = directory / "ffmpeg.exe"
        ffprobe = directory / "ffprobe.exe"
        if ffmpeg.is_file() and ffprobe.is_file():
            return ffmpeg.resolve(), ffprobe.resolve()

    ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    ffprobe_path = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if ffmpeg_path and ffprobe_path:
        ffmpeg = Path(ffmpeg_path).resolve()
        ffprobe = Path(ffprobe_path).resolve()
        if os.path.normcase(str(ffmpeg.parent)) == os.path.normcase(str(ffprobe.parent)):
            return ffmpeg, ffprobe

    return (
        find_executable("ffmpeg", search_directories),
        find_executable("ffprobe", search_directories),
    )


def detect_tools() -> ToolPaths:
    directories = _candidate_directories()
    ffmpeg, ffprobe = find_ffmpeg_suite(directories)
    return ToolPaths(
        yt_dlp=find_executable("yt-dlp", directories),
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        deno=find_executable("deno", directories),
        node=find_executable("node", directories),
    )


def normalize_urls(raw_text: str) -> list[str]:
    urls: list[str] = []
    for raw_line in raw_text.replace("\r", "\n").split("\n"):
        line = raw_line.strip().strip('"').strip("'")
        if not line:
            continue
        # A line can contain several pasted URLs separated by whitespace.
        for value in line.split():
            cleaned = value.strip().strip('"').strip("'")
            if cleaned and cleaned not in urls:
                urls.append(cleaned)
    return urls


def invalid_urls(urls: Iterable[str]) -> list[str]:
    return [url for url in urls if not re.match(r"^https?://", url, re.IGNORECASE)]


def validate_cookie_file(path: Path | str) -> Path:
    """Validate a local Netscape/Mozilla cookie export without changing or logging it."""
    cookie_file = Path(path).expanduser()
    if not cookie_file.exists():
        raise ValueError("Cookies 文件不存在，请重新选择导出的 cookies.txt。")
    if not cookie_file.is_file():
        raise ValueError("请选择 Cookies 文件，不能选择文件夹。")
    try:
        text = cookie_file.read_text(encoding="utf-8")
    except UnicodeError:
        raise ValueError("Cookies 文件编码不正确，请重新导出 UTF-8 的 Netscape cookies.txt。") from None
    except OSError:
        raise ValueError("无法读取 Cookies 文件，请检查文件权限或重新导出。") from None
    if not text.strip():
        raise ValueError("Cookies 文件为空，请登录网站后重新导出。")
    lines = text.splitlines()
    # These are the Netscape and Mozilla headers accepted by yt-dlp's cookie jar.
    if not re.match(r"^#(?: Netscape)? HTTP Cookie File", lines[0]):
        raise ValueError(
            "Cookies 文件格式不正确：需要 Netscape/Mozilla cookies.txt，"
            "首行应为 # Netscape HTTP Cookie File 或 # HTTP Cookie File；不能使用 JSON 或浏览器数据库。"
        )

    cookie_count = 0
    usable_count = 0
    now = time.time()
    for line_number, line in enumerate(lines[1:], start=2):
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif not line.strip() or line.lstrip().startswith(("#", "$")):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError(f"Cookies 文件第 {line_number} 行格式不正确：每条 Cookie 必须用制表符分隔为 7 列。")
        domain, include_subdomains, cookie_path, secure, expires, name, value = fields
        if (
            not domain
            or any(character.isspace() for character in domain)
            or include_subdomains not in {"TRUE", "FALSE"}
            or (include_subdomains == "TRUE") != domain.startswith(".")
            or not cookie_path.startswith("/")
            or secure not in {"TRUE", "FALSE"}
            or (not name and not value)
            or (expires and not expires.isascii())
            or (expires and not expires.isdigit())
        ):
            raise ValueError(f"Cookies 文件第 {line_number} 行格式不正确，请重新导出 Netscape cookies.txt。")
        try:
            expiry = int(expires or "0")
        except ValueError:
            raise ValueError(f"Cookies 文件第 {line_number} 行有效期格式不正确，请重新导出。") from None
        cookie_count += 1
        # Browser exports commonly represent session cookies with 0 or an empty expiry.
        if expiry == 0 or expiry > now:
            usable_count += 1
    if not cookie_count:
        raise ValueError("Cookies 文件中没有 Cookie，请先在浏览器登录目标网站，再导出该网站的 cookies.txt。")
    if not usable_count:
        raise ValueError("Cookies 文件中的 Cookie 已全部过期，请重新登录目标网站后导出。")
    return cookie_file.resolve()


def _cookie_arguments(cookie_browser: str, cookie_file: Path | None) -> list[str]:
    if cookie_file is not None:
        return ["--cookies", str(validate_cookie_file(cookie_file))]
    if cookie_browser and cookie_browser != "none":
        return ["--cookies-from-browser", cookie_browser]
    return []


@contextmanager
def prepared_cookie_command(command: list[str]) -> Iterator[list[str]]:
    """Give yt-dlp a disposable cookie jar so it cannot rewrite the user's export."""
    if "--cookies" not in command:
        yield command
        return
    cookie_index = command.index("--cookies") + 1
    if cookie_index >= len(command):
        raise ValueError("下载命令缺少 Cookies 文件路径。")
    source_file = validate_cookie_file(command[cookie_index])
    with tempfile.TemporaryDirectory(prefix="yt-dlp-cookies-") as temporary_dir:
        temporary_file = Path(temporary_dir) / "cookies.txt"
        try:
            shutil.copyfile(source_file, temporary_file)
        except OSError:
            raise ValueError("无法准备临时 Cookies 文件，请检查文件权限和临时目录空间。") from None
        prepared = command.copy()
        prepared[cookie_index] = str(temporary_file)
        yield prepared


def build_download_command(
    yt_dlp: Path,
    urls: list[str],
    options: DownloadOptions,
    ffmpeg_dir: Path | None = None,
    js_runtimes: Iterable[tuple[str, Path]] | None = None,
) -> list[str]:
    command = [
        str(yt_dlp),
        "--ignore-config",
        "--newline",
        "--progress",
        "--color",
        "no_color",
        "--encoding",
        "utf-8",
        "--windows-filenames",
        "--trim-filenames",
        "180",
        "--continue",
        "--no-overwrites",
        "--progress-template",
        f"download:{PROGRESS_PREFIX}%(progress)j",
        "--progress-template",
        f"postprocess:{POSTPROCESS_PREFIX}%(progress)j",
        "--progress-delta",
        "0.25",
        "--print",
        f"before_dl:{TITLE_PREFIX}%(title)j",
        "--print",
        f"after_move:{FILE_PREFIX}%(filepath)j",
        "--no-simulate",
        "-P",
        str(options.output_dir),
        "-o",
        "%(title).180B [%(id)s].%(ext)s",
    ]

    if ffmpeg_dir:
        command.extend(["--ffmpeg-location", str(ffmpeg_dir)])

    for runtime_name, runtime_path in js_runtimes or ():
        command.extend(["--js-runtimes", f"{runtime_name}:{runtime_path}"])

    if options.playlist:
        command.append("--yes-playlist")
    else:
        command.append("--no-playlist")

    command.extend(_cookie_arguments(options.cookie_browser, options.cookie_file))

    if options.media_type == "audio":
        audio_format = options.audio_format if options.audio_format in {"mp3", "m4a"} else "mp3"
        if audio_format == "mp3":
            command.extend(["-t", "mp3", "--audio-quality", "0"])
        else:
            command.extend(
                [
                    "-f",
                    "ba[ext=m4a]/ba[acodec^=mp4a]/ba[ext=aac]/ba[acodec^=aac]/ba/b",
                    "-x",
                    "--audio-format",
                    "m4a",
                    "--audio-quality",
                    "0",
                ]
            )
    else:
        command.extend(["-f", "bv*+ba/b"])
        if options.video_container == "mp4":
            command.extend(["-t", "mp4", "--format-sort-reset"])
            if options.quality == "best":
                command.extend(["-S", "res,vcodec:h264,acodec:aac"])
            else:
                height = options.quality if options.quality in {"2160", "1080", "720", "480"} else "1080"
                command.extend(["-S", f"res:{height},vcodec:h264,acodec:aac"])
        else:
            command.extend(["-t", "mkv"])
            if options.quality != "best":
                height = options.quality if options.quality in {"2160", "1080", "720", "480"} else "1080"
                command.extend(["-S", f"res:{height}"])

    if options.subtitles and options.media_type == "video":
        command.extend(
            [
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                "zh.*,en.*",
                "--convert-subs",
                "srt",
                "--embed-subs",
            ]
        )

    if options.metadata:
        command.extend(["--embed-metadata", "--embed-thumbnail"])

    command.append("--")
    command.extend(urls)
    return command


def build_analyze_command(
    yt_dlp: Path,
    url: str,
    cookie_browser: str = "none",
    js_runtimes: Iterable[tuple[str, Path]] | None = None,
    cookie_file: Path | None = None,
) -> list[str]:
    command = [
        str(yt_dlp),
        "--ignore-config",
        "--dump-single-json",
        "--flat-playlist",
        "--color",
        "no_color",
        "--encoding",
        "utf-8",
    ]
    command.extend(_cookie_arguments(cookie_browser, cookie_file))
    for runtime_name, runtime_path in js_runtimes or ():
        command.extend(["--js-runtimes", f"{runtime_name}:{runtime_path}"])
    command.extend(["--", url])
    return command


def parse_progress_line(line: str) -> ProgressUpdate | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None

    payload = line[len(PROGRESS_PREFIX) :].rstrip("\r\n")
    try:
        progress = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(progress, dict):
        return None

    percent_text = str(progress.get("_percent_str") or "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", percent_text)
    percent = float(match.group(1)) if match else None
    if percent is None:
        downloaded = progress.get("downloaded_bytes")
        total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
        if isinstance(downloaded, (int, float)) and isinstance(total, (int, float)) and total:
            percent = downloaded / total * 100
    if percent is not None:
        percent = max(0.0, min(100.0, percent))
    speed = str(progress.get("_speed_str") or "").strip()
    eta = str(progress.get("_eta_str") or "").strip()
    return ProgressUpdate(percent=percent, speed=speed, eta=eta, title="")


def friendly_error(log_text: str) -> str:
    lowered = log_text.lower()
    if "dpapi" in lowered or "app-bound" in lowered or "app bound" in lowered:
        return (
            "无法解密浏览器登录信息（DPAPI / 应用绑定加密）。"
            "请从已登录目标网站的浏览器导出 Netscape cookies.txt，并在“导入 Cookies 文件”中选择；"
            "也可使用已登录同一账号的 Firefox。关闭 Chrome 通常无法解决解密失败。"
        )
    if (
        ("could not copy" in lowered and "cookie" in lowered)
        or ("cookie" in lowered and any(value in lowered for value in ("database is locked", "permission denied", "access is denied", "being used by another process")))
    ):
        return (
            "浏览器 Cookie 数据库被占用或无法读取。请保存浏览器中的工作后完全退出所选浏览器"
            "（包括后台进程），再重试；也可导入已登录账号的 Netscape cookies.txt，以保留会员画质权限。"
        )
    if (
        ("could not find" in lowered and any(value in lowered for value in ("cookies database", "cookie database", "profile directory")))
        or ("profile" in lowered and any(value in lowered for value in ("not found", "does not exist", "no such file", "could not find")))
    ):
        return "找不到所选浏览器的用户配置或 Cookie 数据库。请确认该浏览器已安装且当前用户已登录目标网站，或导入该账号的 Netscape cookies.txt。"
    if "unsupported url" in lowered:
        return "暂不支持这个链接，请确认链接完整或换用视频页面地址。"
    if "private video" in lowered or "login required" in lowered or "sign in" in lowered:
        return "这个内容需要登录。请选择已登录账号的浏览器，或导入该账号的 Netscape cookies.txt 后重试。"
    if "javascript runtime" in lowered and ("not found" in lowered or "no supported" in lowered):
        return "缺少可用的 JavaScript 运行时。安装 Deno 2.3+ 后重试，YouTube 支持会更完整。"
    if "not available in your country" in lowered or "geo-restricted" in lowered:
        return "这个内容存在地区限制，当前网络无法访问。"
    if "disk full" in lowered or "no space left" in lowered:
        return "磁盘空间不足，请清理空间或更换保存目录。"
    if "permission denied" in lowered or "access is denied" in lowered:
        return "没有权限写入保存目录，请换一个目录后重试。"
    if "ffmpeg" in lowered and ("not found" in lowered or "not installed" in lowered):
        return "没有找到 FFmpeg，无法完成音视频合并或音频转换。"
    if "http error 412" in lowered or "412: precondition failed" in lowered:
        return (
            "网站拒绝了请求（HTTP 412），可能触发了风控。请先在浏览器确认视频能正常播放，"
            "重新导出并选择该网站的 Cookies 文件，然后稍后重试。"
        )
    if "unable to download" in lowered or "network" in lowered or "timed out" in lowered:
        return "网络连接失败或超时，请检查网络后重试。"
    if "requested format is not available" in lowered:
        return "该视频没有所选画质，请改用“最佳画质（自动）”后重试。"
    return "下载没有完成。可以展开详细日志查看原因，或复制日志进行排查。"


def redact_log_line(line: str) -> str:
    # yt-dlp normally does not print browser cookie values, but keep copied logs safe
    # if a future tool version includes sensitive request headers.
    line = re.sub(
        r"(\b(?:set-cookie|cookie|proxy-authorization|authorization)\b)(\s*[:=]\s*)[^\r\n]*",
        r"\1\2[已隐藏]",
        line,
        flags=re.IGNORECASE,
    )
    # Match only known authentication fields; words such as cookie_file and
    # cookies-from-browser are ordinary diagnostic details and must stay readable.
    sensitive_fields = r"SESSDATA|bili_jct|DedeUserID(?:__ckMd5)?|access_token|refresh_token|access_key|csrf_token"
    line = re.sub(
        rf"(\b(?:{sensitive_fields})\b[\"']?\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s;,}}\]\r\n]+)",
        r"\1[已隐藏]",
        line,
        flags=re.IGNORECASE,
    )
    # A copied Netscape row has the sensitive field name in the sixth column.
    line = re.sub(
        rf"(\t(?:{sensitive_fields})\t)[^\r\n]*",
        r"\1[已隐藏]",
        line,
        flags=re.IGNORECASE,
    )

    def redact_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return "[网址已隐藏]" + trailing
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        query = "参数已隐藏" if parsed.query else ""
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, "")) + trailing

    line = re.sub(r"(?i)https?://[^\s<>\"']+", redact_url, line)
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        line = re.sub(re.escape(user_profile), "%USERPROFILE%", line, flags=re.IGNORECASE)
    return line


def hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def executable_version(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        result = subprocess.run(
            [str(path), "-version" if path.name.lower().startswith("ffmpeg") else "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = (result.stdout or result.stderr).splitlines()
    return first_line[0].strip() if first_line else None
