import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from tkinter import TclError, Tk
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import app as app_module  # noqa: E402
from core import ToolPaths  # noqa: E402


class AppCookieTests(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.directory = Path(self.resources.enter_context(tempfile.TemporaryDirectory()))
        self.settings_path = self.directory / "settings.json"
        self.cookie_file = self.directory / "cookies.txt"
        self.cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            "#HttpOnly_.example.test\tTRUE\t/\tTRUE\t0\tSESSDATA\tfake-local-test-session\n",
            encoding="utf-8",
        )
        tool_directory = self.directory / "tools"
        tools = ToolPaths(
            tool_directory / "yt-dlp.exe", tool_directory / "ffmpeg.exe",
            tool_directory / "ffprobe.exe", None, None,
        )
        self.resources.enter_context(patch.object(app_module, "settings_file", return_value=self.settings_path))
        self.resources.enter_context(patch.object(app_module, "default_download_dir", return_value=self.directory))
        self.resources.enter_context(patch.object(app_module, "detect_tools", return_value=tools))
        self.showerror = self.resources.enter_context(patch.object(app_module.messagebox, "showerror"))
        self.resources.enter_context(patch.object(app_module.messagebox, "showwarning"))
        self.resources.enter_context(patch.object(app_module.messagebox, "showinfo"))
        try:
            self.root = Tk()
        except TclError as exc:
            self.skipTest(f"Tk is unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.ui = app_module.YTDLPApp(self.root)
        self.ui.url_text.insert("1.0", "https://example.test/video")
        self.ui.url_text.edit_modified(False)

    def close_root(self):
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()

    def select_source(self, source):
        self.ui.cookie_combo.set(source)
        self.ui._on_cookie_source_changed()

    def reset_operation(self):
        self.ui.operation = None
        self.ui.worker = None
        self.ui.url_text.configure(state="normal")
        self.ui._set_running_state(False)

    def test_file_mode_rejects_missing_selection_before_starting_either_operation(self):
        self.select_source("Cookie 文件")
        with patch.object(app_module.threading, "Thread") as thread:
            for cookie_path in ("", str(self.directory / "missing.txt")):
                for action in (self.ui._analyze_link, self.ui._start_download):
                    with self.subTest(cookie_path=cookie_path, action=action.__name__):
                        self.ui.cookie_file_var.set(cookie_path)
                        self.showerror.reset_mock()
                        action()
                        self.showerror.assert_called_once()
                        self.assertIsNone(self.ui.operation)
                        thread.assert_not_called()
        self.ui.cookie_file_var.set(str(self.cookie_file))
        self.assertEqual(self.ui._selected_cookie_file(), self.cookie_file.resolve())

    def test_source_switching_applies_same_cookie_arguments_to_analysis_and_download(self):
        for source in ("Cookie 文件", "Chrome", "不使用"):
            for action in (self.ui._analyze_link, self.ui._start_download):
                with self.subTest(source=source, action=action.__name__):
                    self.reset_operation()
                    self.select_source(source)
                    # A remembered missing file must not interfere with browser mode.
                    self.ui.cookie_file_var.set(str(self.cookie_file if source == "Cookie 文件" else self.directory / "missing.txt"))
                    with patch.object(app_module.threading, "Thread") as thread:
                        action()
                        thread.assert_called_once()
                        thread.return_value.start.assert_called_once()
                        command = thread.call_args.kwargs["args"][0]
                    if source == "Cookie 文件":
                        self.assertEqual(command[command.index("--cookies") + 1], str(self.cookie_file.resolve()))
                        self.assertNotIn("--cookies-from-browser", command)
                    elif source == "Chrome":
                        self.assertEqual(command[command.index("--cookies-from-browser") + 1], "chrome")
                        self.assertNotIn("--cookies", command)
                    else:
                        self.assertNotIn("--cookies", command)
                        self.assertNotIn("--cookies-from-browser", command)
                    self.assertNotIn("fake-local-test-session", " ".join(command))
        self.assertNotIn("fake-local-test-session", self.settings_path.read_text(encoding="utf-8"))
        self.showerror.assert_not_called()

    def test_editing_cookie_path_or_source_invalidates_previous_analysis(self):
        self.select_source("Cookie 文件")
        self.ui.cookie_file_var.set(str(self.cookie_file))
        self.ui._finish_analysis({"title": "Old login", "formats": [{"height": 2160}]})
        self.ui.cookie_file_var.set(str(self.directory / "another-cookies.txt"))
        self.assertIsNone(self.ui.analysis_info)
        self.assertIn("重新解析", self.ui.analysis_label.cget("text"))
        self.ui._finish_analysis({"title": "Old login", "formats": [{"height": 2160}]})
        self.select_source("Chrome")
        self.assertIsNone(self.ui.analysis_info)
        self.assertIn("重新解析", self.ui.analysis_label.cget("text"))

    def test_workers_clean_temporary_cookies_before_every_terminal_event(self):
        original = self.cookie_file.read_bytes()
        command = ["fake-yt-dlp.exe", "--cookies", str(self.cookie_file), "--", "https://example.test/video"]
        for operation in ("analysis", "download"):
            outcomes = ["success", "failed", "cancelled", "launch_error"]
            if operation == "analysis":
                outcomes.extend(("timeout", "invalid_json"))
            for outcome in outcomes:
                with self.subTest(operation=operation, outcome=outcome):
                    self.ui.cancel_event.clear()
                    if outcome == "cancelled":
                        self.ui.cancel_event.set()
                    temporary_paths = []
                    events = []
                    process = Mock()
                    process.returncode = 1 if outcome == "failed" else 0
                    process.stdout = io.StringIO("[download] synthetic progress\n")
                    process.wait.return_value = process.returncode
                    process.poll.return_value = process.returncode
                    stdout = "not json" if outcome == "invalid_json" else json.dumps({"title": "Synthetic video"})
                    stderr = "WARNING: synthetic browser warning\nSESSDATA=fake-worker-secret"
                    process.communicate.return_value = (stdout, stderr)
                    if outcome == "timeout":
                        process.communicate.side_effect = subprocess.TimeoutExpired("fake-yt-dlp", 90)

                    def launch(prepared, **kwargs):
                        temporary_file = Path(prepared[prepared.index("--cookies") + 1])
                        temporary_paths.append(temporary_file)
                        self.assertNotEqual(temporary_file, self.cookie_file)
                        self.assertEqual(temporary_file.read_bytes(), original)
                        temporary_file.write_text("simulated yt-dlp cookie-jar update", encoding="utf-8")
                        if outcome == "launch_error":
                            raise OSError("synthetic executable launch failure")
                        return process

                    def record_event(event):
                        if event[0] != "process_line":
                            self.assertTrue(temporary_paths)
                            for temporary_file in temporary_paths:
                                self.assertFalse(temporary_file.exists())
                                self.assertFalse(temporary_file.parent.exists())
                            self.assertEqual(self.cookie_file.read_bytes(), original)
                            self.assertIsNone(self.ui.analysis_process)
                            self.assertIsNone(self.ui.process)
                        events.append(event)

                    with (
                        patch.object(app_module.subprocess, "Popen", side_effect=launch) as popen,
                        patch.object(self.ui, "_terminate_process") as terminate,
                        patch.object(self.ui.events, "put", side_effect=record_event),
                    ):
                        worker = self.ui._analyze_worker if operation == "analysis" else self.ui._download_worker
                        worker(command)
                        popen.assert_called_once()
                        if outcome in {"cancelled", "timeout"}:
                            terminate.assert_called_once_with(process)
                    terminal_events = [event for event in events if event[0] != "process_line"]
                    if operation == "analysis":
                        expected = "analysis_done" if outcome == "success" else "analysis_cancelled" if outcome == "cancelled" else "analysis_error"
                    else:
                        expected = "download_cancelled" if outcome == "cancelled" else "download_exception" if outcome == "launch_error" else "download_finished"
                    self.assertEqual(len(terminal_events), 1)
                    self.assertEqual(terminal_events[0][0], expected)
                    if operation == "download" and outcome in {"success", "failed"}:
                        self.assertEqual(terminal_events[0][1], 1 if outcome == "failed" else 0)
                    if operation == "analysis" and outcome == "success":
                        warnings = "\n".join(str(payload) for event, payload in events if event == "process_line")
                        self.assertIn("synthetic browser warning", warnings)
                        self.assertNotIn("fake-worker-secret", warnings)

    def test_analysis_displays_sorted_unique_available_heights_and_highest_resolution(self):
        self.ui._finish_analysis({
            "title": "Synthetic video", "duration_string": "01:23",
            "formats": [{"height": 2160}, {"height": 720}, {"height": None},
                        {"height": 1080}, {"height": 1080}, {"height": 0}, {"height": "unknown"}],
        })
        self.assertEqual(
            self.ui.analysis_label.cget("text"),
            "Synthetic video · 01:23 · 可用画质：720p / 1080p / 2160p",
        )
        self.assertIn("最高分辨率：2160p", self.ui.detail_var.get())


if __name__ == "__main__":
    unittest.main()
