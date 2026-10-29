"""테마 저장·왕복 전환이 사용 중인 작업을 보존하는지 검증한다."""
import json
import os
import tempfile
import unittest
from unittest import mock

import settings


class UiPreferencesTest(unittest.TestCase):
    def test_missing_and_invalid_preferences_default_to_light(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ui-preferences.json")
            with mock.patch.object(settings, "UI_PREFERENCES_PATH", path, create=True):
                self.assertEqual(settings.load_ui_preferences(), {"appearance_mode": "light"})
                for text in ('{broken', '[]', '{"appearance_mode":"unexpected"}'):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    self.assertEqual(settings.load_ui_preferences(), {"appearance_mode": "light"})

    def test_roundtrip_and_backup_without_touching_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ui-preferences.json")
            config = os.path.join(tmp, "config.txt")
            with open(config, "w", encoding="utf-8") as f:
                f.write("dart_api_key = keep\nkicpa_path = keep.xlsx\n")
            with mock.patch.object(settings, "UI_PREFERENCES_PATH", path, create=True), \
                 mock.patch.object(settings, "CONFIG_PATH", config):
                settings.save_ui_preferences("dark")
                self.assertEqual(settings.load_ui_preferences(), {"appearance_mode": "dark"})
                settings.save_ui_preferences("light")
                self.assertEqual(settings.load_ui_preferences(), {"appearance_mode": "light"})
                backups = [p for p in os.listdir(tmp) if p.startswith("backup_")]
                self.assertTrue(backups)
                with open(os.path.join(tmp, backups[0]), encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["appearance_mode"], "dark")
                with open(config, encoding="utf-8") as f:
                    self.assertEqual(f.read(), "dart_api_key = keep\nkicpa_path = keep.xlsx\n")


class ThemeSwitchTest(unittest.TestCase):
    def setUp(self):
        import app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pref = os.path.join(self.tmp.name, "ui-preferences.json")
        self.patches = [mock.patch.object(settings, "UI_PREFERENCES_PATH", self.pref, create=True),
                        mock.patch.object(app.PeerApp, "_startup", return_value=None),
                        mock.patch.object(settings, "load_config", return_value={k: "" for k in settings.KEYS})]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.a = app.PeerApp()
        self.addCleanup(self.a.destroy)
        self.a.update()

    def test_dark_light_roundtrip_preserves_work_and_native_colors(self):
        import tkinter.ttk as ttk
        a = self.a
        cp = a.candidate_panel
        from tests.test_gui_flow import KIND
        a.kind_rows = KIND
        cp.kw_var.set("피팅")
        cp.name_var.set("검증 대상")
        cp.search()
        cp.rows_state["014620"]["sel"].set(True)
        cp._on_select("014620")
        cp.rows_state["023160"]["reason"].set("확인 중")
        cp.find_var.set("태광")
        cp._on_find_typed()
        before_rows = cp.tree.get_children()
        a.show_summary()
        active_tab = a.tabs.get()
        for dark, expected_bg in ((True, "#1B283C"), (False, "#FFFFFF")):
            a.dark_mode_var.set(dark)
            a._toggle_dark_mode()
            a.update()
            self.assertEqual(cp.selected_codes(), ["014620"])
            self.assertEqual(cp.name_var.get(), "검증 대상")
            self.assertEqual(cp.rows_state["023160"]["reason"].get(), "확인 중")
            self.assertEqual(cp.tree.get_children(), before_rows)
            self.assertIn("found", cp.tree.item("023160", "tags"))
            self.assertEqual(a.tabs.get(), active_tab)
            self.assertEqual(cp.match_box.cget("background").upper(), expected_bg)
            self.assertEqual(ttk.Style().lookup("Cand.Treeview", "background").upper(), expected_bg)
        self.assertEqual(settings.load_ui_preferences()["appearance_mode"], "light")

    def test_saved_dark_mode_restored_on_start(self):
        settings.save_ui_preferences("dark")
        import app
        b = app.PeerApp()
        try:
            b.update()
            self.assertTrue(b.dark_mode_var.get())
            self.assertEqual(b.candidate_panel.match_box.cget("background").upper(), "#1B283C")
        finally:
            b.destroy()

    def test_load_completion_and_failure_cancel_progress_timer(self):
        from load_status import LoadStatus
        sp = self.a.summary_panel
        for finish in (sp._after_load, sp._load_failed):
            before = set(self.a.tk.call('after', 'info'))
            sp._load_status = LoadStatus(1, log=lambda _: None)
            sp._loading = True
            sp._poll_loading_status()
            scheduled = set(self.a.tk.call('after', 'info')) - before
            self.assertTrue(scheduled)
            finish()
            remaining = set(self.a.tk.call('after', 'info'))
            self.assertFalse(scheduled & remaining)

    def test_disabled_primary_buttons_and_headers_have_readable_contrast(self):
        import ui_theme
        import tkinter.ttk as ttk
        def luminance(value):
            rgb = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
            return sum((c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4)*w
                       for c, w in zip(rgb, (.2126, .7152, .0722)))
        def contrast(a, b):
            lo, hi = sorted((luminance(a), luminance(b)))
            return (hi+.05)/(lo+.05)
        button = self.a.summary_panel.report_btn
        for dark in (False, True):
            self.a.dark_mode_var.set(dark)
            self.a._toggle_dark_mode()
            foreground = ui_theme.color(button.cget('text_color_disabled'))
            background = ui_theme.color(button.cget('fg_color'))
            self.assertGreaterEqual(contrast(foreground, background), 4.5)
            style = ttk.Style()
            self.assertGreaterEqual(contrast(style.lookup('Sum.Treeview.Heading','foreground'),
                                             style.lookup('Sum.Treeview.Heading','background')), 4.5)
        button.configure(state='normal')
        self.assertEqual(button.cget('fg_color'), ui_theme.ACCENT)

    def test_dark_native_editors_and_open_debt_window(self):
        import tkinter as tk
        import tkinter.ttk as ttk
        a = self.a
        a.peers_loaded = [{"code": "014620", "name": "성광벤드", "liab_items": [
            {"name": "단기차입금", "amount": 1000000, "default": True}]}]
        a.summary_panel.open_debt_detail("014620")
        a.dark_mode_var.set(True)
        a._toggle_dark_mode()
        a.update()
        self.assertEqual(ttk.Style().lookup("TCombobox", "fieldbackground").upper(), "#1B283C")
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        labels = [w for w in descendants(a) if isinstance(w, tk.Label) and w.cget("text") == "단기차입금"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0].cget("fg").upper(), "#E5EDF8")

    def test_sidebar_and_advanced_conditions_leave_table_usable(self):
        a = self.a
        cp = a.candidate_panel
        a.geometry("1100x600")
        a.update()
        self.assertLess(cp.sidebar.winfo_rootx(), cp.results.winfo_rootx())
        self.assertGreater(cp.tree.winfo_height(), 200)
        self.assertFalse(cp.advanced_frame.winfo_ismapped())
        cp.neg_var.set("테스트 제외어")
        cp._toggle_advanced()
        a.update()
        self.assertTrue(cp.advanced_frame.winfo_ismapped())
        cp._toggle_advanced()
        self.assertEqual(cp.neg_var.get(), "테스트 제외어")
        self.assertGreater(cp.tree.winfo_height(), 200)
