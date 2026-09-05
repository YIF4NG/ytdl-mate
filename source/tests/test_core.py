import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core import (  # noqa: E402
    FILE_PREFIX,
    PROGRESS_PREFIX,
    DownloadOptions,
    ToolPaths,
    build_analyze_command,
    build_download_command,
    friendly_error,
    find_ffmpeg_suite,
    invalid_urls,
    normalize_urls,
    parse_progress_line,
    prepared_cookie_command,
    redact_log_line,
    validate_cookie_file,
)


class CoreTests(unittest.TestCase):
    def make_cookie_file(self, directory, content=None):
        cookie_file = Path(directory) / "cookies.txt"
        if content is None:
            content = "# Netscape HTTP Cookie File\n#HttpOnly_.example.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tfake-test-session\n"
        cookie_file.write_text(content, encoding="utf-8")
        return cookie_file

    def test_normalize_urls_deduplicates_and_strips_quotes(self):
        raw = '"https://example.com/a"\nhttps://example.com/b https://example.com/a'
        self.assertEqual(
            normalize_urls(raw),
            ["https://example.com/a", "https://example.com/b"],
        )

    def test_invalid_urls(self):
        self.assertEqual(invalid_urls(["https://ok.test", "not-a-url"]), ["not-a-url"])

    def test_build_video_command_is_safe_for_single_video(self):
        options = DownloadOptions(output_dir=Path("C:/下载"), quality="1080")
        command = build_download_command(
            Path("C:/tools/yt-dlp.exe"),
            ["https://example.com/watch?v=1"],
            options,
            Path("C:/tools"),
        )
        self.assertIn("--no-playlist", command)
        self.assertIn("--ffmpeg-location", command)
        self.assertIn("bv*+ba/b", command)
        self.assertIn("-t", command)
        self.assertIn("mkv", command)
        self.assertIn("res:1080", command)
        self.assertTrue(any(value.startswith("after_move:") for value in command))

    def test_build_audio_command_with_browser_login(self):
        options = DownloadOptions(
            output_dir=Path("C:/downloads"),
            media_type="audio",
            audio_format="m4a",
            cookie_browser="edge",
            playlist=True,
        )
        command = build_download_command(
            Path("yt-dlp.exe"),
            ["https://example.com/1"],
            options,
        )
        self.assertIn("--yes-playlist", command)
        self.assertEqual(command[command.index("--audio-format") + 1], "m4a")
        self.assertIn("ba[ext=m4a]", command[command.index("-f") + 1])
        self.assertEqual(command[command.index("--cookies-from-browser") + 1], "edge")

    def test_cookie_file_takes_priority_for_analysis_and_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = self.make_cookie_file(temp_dir)
            options = DownloadOptions(
                output_dir=Path(temp_dir), cookie_browser="chrome", cookie_file=cookie_file
            )
            commands = [
                build_download_command(Path("yt-dlp.exe"), ["https://example.test/1"], options),
                build_analyze_command(Path("yt-dlp.exe"), "https://example.test/1", "chrome", None, cookie_file),
            ]
            for command in commands:
                with self.subTest(command=command):
                    self.assertNotIn("--cookies-from-browser", command)
                    self.assertEqual(command[command.index("--cookies") + 1], str(cookie_file.resolve()))
                    self.assertNotIn("fake-test-session", " ".join(command))

    def test_analyze_keeps_existing_positional_runtime_argument(self):
        command = build_analyze_command(
            Path("yt-dlp.exe"), "https://example.test/1", "chrome", [("deno", Path("deno.exe"))]
        )
        self.assertEqual(command[command.index("--cookies-from-browser") + 1], "chrome")
        self.assertIn("deno:deno.exe", command)
        self.assertNotIn("--cookies", command)
        self.assertNotIn("--no-warnings", command)

    def test_cookie_file_is_validated_before_analysis_and_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = self.make_cookie_file(temp_dir, "{}")
            with self.assertRaisesRegex(ValueError, "格式不正确"):
                build_analyze_command(Path("yt-dlp.exe"), "https://example.test/1", cookie_file=cookie_file)
            with self.assertRaisesRegex(ValueError, "格式不正确"):
                build_download_command(
                    Path("yt-dlp.exe"), ["https://example.test/1"],
                    DownloadOptions(output_dir=Path(temp_dir), cookie_file=cookie_file),
                )

    def test_cookie_file_validates_session_future_and_http_only_without_changes(self):
        contents = [
            "# Netscape HTTP Cookie File\n#HttpOnly_.example.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tfake-session\n",
            "# HTTP Cookie File\nexample.test\tFALSE\t/\tFALSE\t\tSESSDATA\tfake-session\n",
            f"# Netscape HTTP Cookie File\n.example.test\tTRUE\t/\tTRUE\t{int(time.time()) + 86400}\tSESSDATA\tfake-session\n",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            for content in contents:
                with self.subTest(content=content):
                    cookie_file = self.make_cookie_file(temp_dir, content)
                    original = cookie_file.read_bytes()
                    self.assertEqual(validate_cookie_file(cookie_file), cookie_file.resolve())
                    self.assertEqual(cookie_file.read_bytes(), original)

    def test_cookie_file_rejects_missing_directory_empty_and_bad_formats(self):
        header = "# Netscape HTTP Cookie File\n"
        invalid_contents = [
            ("", "为空"),
            ("  \n", "为空"),
            (header + "# comment\n\n", "没有 Cookie"),
            ('[{"name":"SESSDATA","value":"fake-test-secret"}]', "格式不正确"),
            (header + ".example.test TRUE / TRUE 0 SESSDATA fake-test-secret\n", "7 列"),
            (header + ".example.test\tTRUE\t/\tTRUE\tinvalid\tSESSDATA\tfake-test-secret\n", "格式不正确"),
            (header + ".example.test\tFALSE\t/\tTRUE\t0\tSESSDATA\tfake-test-secret\n", "格式不正确"),
            (header + ".example.test\tTRUE\t/\tTRUE\t1\tSESSDATA\tfake-test-secret\n", "全部过期"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "不存在"):
                validate_cookie_file(Path(temp_dir) / "missing.txt")
            with self.assertRaisesRegex(ValueError, "文件夹"):
                validate_cookie_file(Path(temp_dir))
            for content, expected in invalid_contents:
                with self.subTest(expected=expected, content=content):
                    cookie_file = self.make_cookie_file(temp_dir, content)
                    original = cookie_file.read_bytes()
                    with self.assertRaisesRegex(ValueError, expected) as raised:
                        validate_cookie_file(cookie_file)
                    self.assertNotIn("fake-test-secret", str(raised.exception))
                    self.assertEqual(cookie_file.read_bytes(), original)

    def test_cookie_file_allows_expired_cookie_when_another_is_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = self.make_cookie_file(
                temp_dir,
                "# Netscape HTTP Cookie File\n"
                ".example.test\tTRUE\t/\tTRUE\t1\told\texpired-test-value\n"
                ".example.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tfake-test-session\n",
            )
            self.assertEqual(validate_cookie_file(cookie_file), cookie_file.resolve())

    def test_prepared_cookie_command_uses_temporary_copy_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = self.make_cookie_file(temp_dir)
            original = cookie_file.read_bytes()
            command = ["yt-dlp.exe", "--cookies", str(cookie_file), "--", "https://example.test/1"]
            with prepared_cookie_command(command) as prepared:
                temporary_file = Path(prepared[2])
                self.assertNotEqual(temporary_file, cookie_file)
                self.assertEqual(temporary_file.read_bytes(), original)
                self.assertEqual(command[2], str(cookie_file))
                temporary_file.write_text("simulate yt-dlp rewriting the cookie jar", encoding="utf-8")
            self.assertFalse(temporary_file.exists())
            self.assertFalse(temporary_file.parent.exists())
            self.assertEqual(cookie_file.read_bytes(), original)

    def test_prepared_cookie_command_cleans_up_after_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = self.make_cookie_file(temp_dir)
            original = cookie_file.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                with prepared_cookie_command(["yt-dlp.exe", "--cookies", str(cookie_file)]) as prepared:
                    temporary_file = Path(prepared[2])
                    raise RuntimeError("simulated failure")
            self.assertFalse(temporary_file.parent.exists())
            self.assertEqual(cookie_file.read_bytes(), original)

    def test_prepared_cookie_command_without_file_keeps_command(self):
        command = ["yt-dlp.exe", "--cookies-from-browser", "chrome"]
        with prepared_cookie_command(command) as prepared:
            self.assertIs(prepared, command)

    def test_mp4_mode_uses_compatibility_preset(self):
        options = DownloadOptions(
            output_dir=Path("C:/downloads"),
            quality="2160",
            video_container="mp4",
        )
        command = build_download_command(
            Path("yt-dlp.exe"),
            ["https://example.com/1"],
            options,
        )
        self.assertEqual(command[command.index("-t") + 1], "mp4")
        self.assertIn("--format-sort-reset", command)
        self.assertIn("res:2160,vcodec:h264,acodec:aac", command)

    def test_parse_progress_line(self):
        payload = {
            "_percent_str": " 42.7%",
            "_speed_str": "3.2MiB/s",
            "_eta_str": "00:18",
        }
        line = f"{PROGRESS_PREFIX}{json.dumps(payload)}"
        update = parse_progress_line(line)
        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update.percent, 42.7)
        self.assertEqual(update.speed, "3.2MiB/s")
        self.assertEqual(update.eta, "00:18")
        self.assertEqual(update.title, "")

    def test_parse_non_progress_line(self):
        self.assertIsNone(parse_progress_line(f"{FILE_PREFIX}C:/video.mp4"))

    def test_ffmpeg_suite_must_share_a_directory(self):
        same = ToolPaths(None, Path("C:/tools/ffmpeg.exe"), Path("C:/tools/ffprobe.exe"), None, None)
        split = ToolPaths(None, Path("C:/one/ffmpeg.exe"), Path("C:/two/ffprobe.exe"), None, None)
        self.assertTrue(same.ffmpeg_ready)
        self.assertFalse(split.ffmpeg_ready)

    def test_ffmpeg_suite_prefers_a_complete_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            incomplete = root / "a" / "bin"
            complete = root / "b" / "bin"
            incomplete.mkdir(parents=True)
            complete.mkdir(parents=True)
            (incomplete / "ffmpeg.exe").touch()
            (complete / "ffmpeg.exe").touch()
            (complete / "ffprobe.exe").touch()
            ffmpeg, ffprobe = find_ffmpeg_suite([incomplete, complete])
            self.assertEqual(ffmpeg, (complete / "ffmpeg.exe").resolve())
            self.assertEqual(ffprobe, (complete / "ffprobe.exe").resolve())

    def test_friendly_error(self):
        self.assertIn("登录", friendly_error("ERROR: Sign in to confirm your age"))
        self.assertIn("磁盘空间", friendly_error("No space left on device"))
        self.assertIn("Deno", friendly_error("No supported JavaScript runtime could be found"))

    def test_friendly_browser_errors_distinguish_decryption_lock_and_missing_profile(self):
        for error in ("ERROR: Failed to decrypt with DPAPI", "app-bound cookie encryption is not supported"):
            with self.subTest(error=error):
                message = friendly_error(error)
                self.assertIn("无法解密", message)
                self.assertIn("cookies.txt", message)
                self.assertNotIn("不使用", message)
        for error in ("Could not copy Chrome cookie database", "cookie database is locked", "Cookie database Permission denied"):
            with self.subTest(error=error):
                message = friendly_error(error)
                self.assertIn("被占用", message)
                self.assertIn("完全退出", message)
                self.assertNotIn("不使用", message)
        for error in ("Could not find Chrome cookies database", "Firefox profile directory not found"):
            with self.subTest(error=error):
                self.assertIn("找不到", friendly_error(error))

    def test_friendly_error_identifies_http_412_before_generic_network_error(self):
        message = friendly_error("ERROR: Unable to download JSON metadata: HTTP Error 412: Precondition Failed")
        self.assertIn("HTTP 412", message)
        self.assertIn("浏览器", message)
        self.assertIn("Cookies 文件", message)
        self.assertIn("稍后重试", message)

    def test_redact_log_line(self):
        redacted = redact_log_line(
            "Cookie: first-secret\nERROR: failed\nAuthorization: Bearer second-secret"
        )
        self.assertNotIn("first-secret", redacted)
        self.assertNotIn("second-secret", redacted)
        self.assertIn("ERROR: failed", redacted)

    def test_redact_log_line_hides_url_queries_and_profile(self):
        profile = os.environ.get("USERPROFILE", "C:/Users/Example")
        raw = f"Failed https://example.test/video?token=topsecret&signature=abc at {profile}\\Downloads"
        redacted = redact_log_line(raw)
        self.assertNotIn("topsecret", redacted)
        self.assertNotIn("signature=abc", redacted)
        if os.environ.get("USERPROFILE"):
            self.assertIn("%USERPROFILE%", redacted)

    def test_redact_log_line_hides_known_cookie_fields_and_netscape_rows(self):
        for raw in (
            "SESSDATA=fake-test-secret; resolution=1080",
            '"bili_jct": "fake-test-secret", "resolution": 1080',
            "DedeUserID__ckMd5='fake-test-secret' resolution=1080",
            "refresh_token: fake-test-secret resolution=1080",
            ".example.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tfake-test-secret",
        ):
            with self.subTest(raw=raw):
                redacted = redact_log_line(raw)
                self.assertNotIn("fake-test-secret", redacted)
                self.assertIn("已隐藏", redacted)
                if "resolution" in raw:
                    self.assertIn("1080", redacted)

    def test_redact_log_line_preserves_cookie_diagnostics(self):
        for raw in (
            "ERROR: Could not copy Chrome cookie database",
            "ERROR: Failed to decrypt with DPAPI",
            "cookie_file=C:/cookies.txt; cookie_browser=chrome",
            "Using --cookies-from-browser chrome; Extracted 52 cookies from Chrome",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(redact_log_line(raw), raw)


if __name__ == "__main__":
    unittest.main()
