import unittest

from load_status import LoadStatus


class LoadStatusTest(unittest.TestCase):
    def test_current_stage_and_elapsed_time_identify_slow_peer(self):
        now = [0.0]
        logs = []
        status = LoadStatus(2, log=logs.append, clock=lambda: now[0])
        def fetch():
            now[0] = 12.0
            text = status.text()
            self.assertIn('삼성전자', text)
            self.assertIn('재무상태표', text)
            self.assertIn('12.0초', text)
            self.assertIn('0/2', text)
            return {'ok': True}
        self.assertEqual(status.run('005930', '삼성전자', '재무상태표', fetch), {'ok': True})
        status.complete('005930')
        self.assertIn('1/2', status.text())
        self.assertNotIn('재무상태표', status.text())
        self.assertIn('12.00초', logs[0])

    def test_instrumentation_keeps_network_exception_and_records_timing(self):
        logs = []
        status = LoadStatus(1, log=logs.append)
        def fail():
            raise TimeoutError('test')
        with self.assertRaises(TimeoutError):
            status.run('005930', '삼성전자', '주가', fail)
        self.assertTrue(logs)
