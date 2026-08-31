import unittest
from unittest import mock


class GuiSmokeTest(unittest.TestCase):
    def test_app_builds_and_destroys(self):
        import market_data as md
        with mock.patch.object(md, "load_kind_list", return_value=[]), \
             mock.patch("dart_inputs.check_key", return_value=(True, "정상")), \
             mock.patch.object(md, "krx_login", return_value=False):
            import app
            a = app.PeerApp()
            a.update()
            self.assertTrue(a.candidate_panel.frame.winfo_exists())
            self.assertTrue(a.summary_panel.frame.winfo_exists())
            a.destroy()
